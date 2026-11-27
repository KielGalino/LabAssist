"""Knowledge Base page (admin PIN): view, upload and delete SOPs, rebuild, test search."""
import re

import pandas as pd
import streamlit as st

from core import config, rag
from core.guardrails import detect_instruction_override
from core.ui import header, require_admin_pin, section

header("Knowledge Base", "Standard Operating Procedures used by LabAssist")

if not require_admin_pin():
    st.stop()

retriever = rag.refresh_if_changed()
if retriever.vector_ok:
    st.caption(f"Search index: {retriever.status()}")
else:
    st.warning(f"Index: {retriever.status()} - {retriever.vector_error}")

# SOP list
files = rag.kb_files()
rows = []
for f in files:
    chunks = rag.chunk_sop(f)
    rows.append({"SOP": chunks[0]["sop_id"], "Title": chunks[0]["title"], "File": f.name,
                 "Chunks": len(chunks), "Size (KB)": round(f.stat().st_size / 1024, 1)})
section(f"SOP documents ({len(files)} files, {sum(r['Chunks'] for r in rows)} chunks)")
st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

col_view, col_manage = st.columns([3, 2])

with col_view:
    section("View SOP")
    if files:
        chosen = st.selectbox("Choose a file", files, format_func=lambda p: p.name)
        with st.container(border=True, height=420):
            st.markdown(chosen.read_text(encoding="utf-8"))

with col_manage:
    section("Upload new SOP")
    st.caption("Markdown file starting with `# SOP-XX: Title`, then `**Applies to:**`, "
               "`**Common phrases:**` and `## ` sections.")
    up = st.file_uploader("SOP markdown (.md)", type=["md"])
    if up and st.button("Save and re-index", type="primary"):
        text = up.getvalue().decode("utf-8", errors="replace")
        # simple file names only
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", up.name)
        if not re.search(r"^#\s+SOP-\d+", text, re.MULTILINE):
            st.error("The file must contain a title line like `# SOP-17: Title`.")
        elif detect_instruction_override(text):
            # SOPs go into the prompt, so scan them
            st.error("The file contains instruction-like text that could manipulate the assistant "
                     "(prompt injection). It was not saved.")
        elif len(text) > 30_000:
            st.error("The file is too large for one SOP (maximum 30,000 characters).")
        else:
            (config.KB_DIR / name).write_text(text, encoding="utf-8")
            with st.spinner("Rebuilding index..."):
                rag.rebuild_index()
            st.success(f"Saved {name} and rebuilt the index.")
            st.rerun()

    section("Delete SOP")
    if files:
        to_delete = st.selectbox("File to delete", files, format_func=lambda p: p.name, key="del")
        confirm = st.checkbox(f"Yes, permanently delete {to_delete.name}")
        if st.button("Delete", disabled=not confirm):
            to_delete.unlink()
            with st.spinner("Rebuilding index..."):
                rag.rebuild_index()
            st.success(f"Deleted {to_delete.name}.")
            st.rerun()

    section("Rebuild index")
    st.caption("The index rebuilds automatically when files change (SHA-256 fingerprint). "
               "Use this to force a full rebuild.")
    if st.button("Rebuild now"):
        with st.spinner("Re-embedding all chunks..."):
            r = rag.rebuild_index()
        st.success(f"Done: {r.status()}")

# Test retrieval
section("Test retrieval")
q = st.text_input("Type a question (English or Taglish)", "walang internet sa PC-07")
k = st.slider("Top K", 1, 10, config.TOP_K)
if q:
    results, relevant = retriever.search(q, k)
    if relevant:
        st.success("Relevant: at least one score passed its threshold "
                   f"(vector >= {config.VECTOR_MIN_SCORE} or BM25 >= {config.BM25_MIN_SCORE}).")
    else:
        st.warning("Not relevant: both scores are below the thresholds, so LabAssist would decline.")
    st.caption("Keyword tokens after Taglish expansion: `" + " ".join(rag.tokenize(q)) + "`")
    st.dataframe(pd.DataFrame([{
        "rank": i, "chunk": r["chunk_id"], "section": r["section"],
        "hybrid": r["score"], "vector (cosine)": r["vector"],
        "BM25 raw": r["bm25"], "BM25 norm": r["bm25_norm"],
    } for i, r in enumerate(results, 1)]), width="stretch", hide_index=True)
    with st.expander("Top chunk text"):
        st.markdown(results[0]["text"] if results else "-")
