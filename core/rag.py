"""Loads the SOPs, splits them into chunks and runs hybrid search (ChromaDB + BM25)."""
import hashlib
import re
import threading
from pathlib import Path

from rank_bm25 import BM25Okapi

from core import config

COLLECTION = "labassist_kb"

# Text processing for BM25
# Taglish -> English words
TAGLISH = {
    "ayaw": "not working", "gumagana": "working", "walang": "no", "wala": "no",
    "sira": "broken damaged", "nasira": "broken damaged",
    "nakalimutan": "forgot", "limot": "forgot", "mabagal": "slow", "bagal": "slow",
    "tunog": "sound audio", "itim": "black", "nawala": "lost missing",
    "naka-lock": "locked", "nalock": "locked", "na-lock": "locked",
    "usok": "smoke", "umuusok": "smoke", "kislap": "sparks", "apoy": "fire",
    "mag-print": "print", "magprint": "print", "printer": "printer",
    "pumasok": "login", "makapasok": "login", "maka-login": "login",
    "nag-hang": "frozen hang", "nagha-hang": "frozen hang", "hang": "frozen",
    "naputol": "disconnected", "disconnect": "disconnected",
    "save": "save", "nawawala": "lost missing", "file": "file files",
    "mouse": "mouse", "keyboard": "keyboard", "headset": "headset audio",
    "projector": "projector", "screen": "screen display",
    "i-reserve": "reserve reservation", "magreserve": "reserve reservation",
    "schedule": "schedule hours", "bukas": "open", "sarado": "closed",
    "mag-install": "install", "i-install": "install",
}

STOPWORDS = set("""
a an the is are was were be been am to of in on at for and or but with my me i you
your it this that these those do does did can could would should will how what why
when where who please po ang ng sa ko mo yung yong na naman ba ako ka kami namin
paano bakit ano saan si ni nang may mga lang din rin pa po ho kasi tapos ito iyan
""".split())


def tokenize(text: str) -> list[str]:
    """Lowercase, split into words, expand Taglish, drop stopwords."""
    words = re.findall(r"[a-z0-9@\-]+", text.lower())
    tokens = []
    for w in words:
        w = w.strip("-")
        if not w:
            continue
        tokens.append(w)
        if w in TAGLISH:  # keep the word, add the English one
            tokens.extend(TAGLISH[w].split())
        if "-" in w:  # "PC-12" also matches "pc" and "12"
            tokens.extend(p for p in w.split("-") if p)
    return [t for t in tokens if t not in STOPWORDS]


# Knowledge base loading and chunking
def kb_files() -> list[Path]:
    return sorted(config.KB_DIR.glob("*.md"))


def kb_fingerprint() -> str:
    """SHA-256 of every KB file name + content. Changes when any SOP changes."""
    h = hashlib.sha256()
    for f in kb_files():
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def chunk_sop(path: Path) -> list[dict]:
    """Split one SOP markdown file into chunks at each '## ' heading."""
    text = path.read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else path.stem
    id_match = re.match(r"(SOP-\d+)", title)
    sop_id = id_match.group(1) if id_match else path.stem.upper()

    parts = re.split(r"^(?=##\s)", text, flags=re.MULTILINE)
    header = parts[0].strip()  # "# SOP-XX: Title" + Applies to + Common phrases
    sections = parts[1:] or [""]

    chunks = []
    for i, body in enumerate(sections):
        section_name = body.splitlines()[0].lstrip("#").strip() if body else "Overview"
        chunks.append({
            "chunk_id": f"{sop_id}-{i}",
            "sop_id": sop_id,
            "title": title,
            "section": section_name,
            "file": path.name,
            "body": body.strip(),  # section only (shown in offline answers)
            # prefix the SOP header for context
            "text": f"{header}\n\n{body.strip()}".strip(),
        })
    return chunks


def load_chunks() -> list[dict]:
    chunks = []
    for f in kb_files():
        chunks.extend(chunk_sop(f))
    return chunks


# Hybrid retriever
class HybridRetriever:
    def __init__(self, force_rebuild: bool = False):
        self.fingerprint = kb_fingerprint()
        self.chunks = load_chunks()
        self.by_id = {c["chunk_id"]: c for c in self.chunks}
        # BM25 index (always works)
        self.bm25 = BM25Okapi([tokenize(c["text"]) for c in self.chunks]) if self.chunks else None
        # vector index (may fail -> BM25 only)
        self.collection = None
        self._vec_cache = {}  # cache: question -> scores
        self._embed_lock = threading.Lock()
        self.vector_ok = False
        self.vector_error = ""
        self.rebuilt = False
        try:
            self._init_chroma(force_rebuild)
            self.vector_ok = True
        except Exception as e:  # noqa: BLE001 - any failure -> BM25 only
            self.vector_error = f"{type(e).__name__}: {e}"[:300]

    def _init_chroma(self, force_rebuild: bool):
        import chromadb
        from chromadb.config import Settings
        from chromadb.utils import embedding_functions

        cdir = config.chroma_dir()
        cdir.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(cdir), settings=Settings(anonymized_telemetry=False))
        embed_fn = embedding_functions.DefaultEmbeddingFunction()  # free, local, CPU

        fp_file = cdir / "kb_fingerprint.txt"
        fingerprint = kb_fingerprint()
        old_fp = fp_file.read_text() if fp_file.exists() else ""

        collection = client.get_or_create_collection(
            COLLECTION, embedding_function=embed_fn, metadata={"hnsw:space": "cosine"}
        )
        needs_rebuild = (force_rebuild or old_fp != fingerprint
                         or collection.count() != len(self.chunks))
        if needs_rebuild:
            client.delete_collection(COLLECTION)
            collection = client.create_collection(
                COLLECTION, embedding_function=embed_fn, metadata={"hnsw:space": "cosine"}
            )
            if self.chunks:
                collection.add(
                    ids=[c["chunk_id"] for c in self.chunks],
                    documents=[c["text"] for c in self.chunks],
                    metadatas=[{"sop_id": c["sop_id"], "section": c["section"]} for c in self.chunks],
                )
            fp_file.write_text(fingerprint)
            self.rebuilt = True
        self.collection = collection

    # single searches
    def vector_scores(self, query: str) -> dict:
        """Cosine similarity per chunk (cached). Empty if Chroma is down."""
        if not self.vector_ok:  # Chroma down -> BM25 only
            return {}
        key = query.strip().lower()
        cached = self._vec_cache.get(key)
        if cached is not None:
            return cached
        # one embedding at a time (parallel calls slow each other down)
        with self._embed_lock:
            cached = self._vec_cache.get(key)
            if cached is not None:
                return cached
            scores = self._vector_scores_uncached(query)
            if scores:
                if len(self._vec_cache) >= 512:
                    self._vec_cache.pop(next(iter(self._vec_cache)))  # drop the oldest entry
                self._vec_cache[key] = scores
        return scores

    def _vector_scores_uncached(self, query: str) -> dict:
        if not (self.vector_ok and self.collection and self.chunks):
            return {}
        try:
            res = self.collection.query(query_texts=[query], n_results=len(self.chunks))
            # similarity = 1 - distance
            return {cid: max(0.0, 1 - dist)
                    for cid, dist in zip(res["ids"][0], res["distances"][0])}
        except Exception as e:  # noqa: BLE001
            self.vector_ok = False
            self.vector_error = f"query failed: {e}"[:300]
            return {}

    def bm25_scores(self, query: str) -> dict:
        """chunk_id -> raw BM25 score."""
        if not self.bm25:
            return {}
        scores = self.bm25.get_scores(tokenize(query))
        return {c["chunk_id"]: float(s) for c, s in zip(self.chunks, scores)}

    # hybrid search
    def search(self, query: str, k: int = config.TOP_K):
        """Return (top results, is_relevant)."""
        vec = self.vector_scores(query)
        bm = self.bm25_scores(query)
        max_bm = max(bm.values(), default=0) or 1.0
        use_vector = bool(vec)

        results = []
        for c in self.chunks:
            v = vec.get(c["chunk_id"], 0.0)
            b_raw = bm.get(c["chunk_id"], 0.0)
            b_norm = b_raw / max_bm
            if use_vector:
                score = config.VECTOR_WEIGHT * v + config.BM25_WEIGHT * b_norm
            else:
                score = b_norm  # BM25-only fallback
            results.append({**c, "vector": round(v, 4), "bm25": round(b_raw, 3),
                            "bm25_norm": round(b_norm, 4), "score": round(score, 4)})
        results.sort(key=lambda r: r["score"], reverse=True)
        top = results[:k]

        best_vec = max((r["vector"] for r in results), default=0)
        best_bm = max((r["bm25"] for r in results), default=0)
        # not relevant only if both scores are low
        relevant = bool(top) and (
            (use_vector and best_vec >= config.VECTOR_MIN_SCORE)
            or best_bm >= config.BM25_MIN_SCORE
        )
        return top, relevant

    def status(self) -> str:
        if self.vector_ok:
            return f"ChromaDB + BM25 hybrid ({len(self.chunks)} chunks)"
        return f"BM25 only - vector DB unavailable ({len(self.chunks)} chunks)"


# one retriever per process
_retriever = None
_lock = threading.Lock()


def get_retriever() -> HybridRetriever:
    global _retriever
    with _lock:
        if _retriever is None:
            _retriever = HybridRetriever()
        return _retriever


def rebuild_index() -> HybridRetriever:
    """Force a full rebuild (used after uploading / deleting an SOP)."""
    global _retriever
    with _lock:
        _retriever = HybridRetriever(force_rebuild=True)
        return _retriever


def refresh_if_changed() -> HybridRetriever:
    """Reload if KB files changed on disk since the retriever was built."""
    r = get_retriever()
    if r.fingerprint != kb_fingerprint():
        global _retriever
        with _lock:
            _retriever = HybridRetriever()  # Chroma rebuilds itself via fingerprint
        return _retriever
    return r
