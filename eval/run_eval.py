"""Evaluation on eval/test_cases.json.

  python eval/run_eval.py          retrieval only (no API calls)
  python eval/run_eval.py --full   full agent run, writes eval/results.md
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
EVAL_DIR = ROOT / "eval"


def make_user(db, case) -> dict:
    """User for a test case (role + session id)."""
    from core import auth
    if case["user_id"] == "ADMIN":
        return dict(auth.ADMIN_USER)
    return auth.identify(case["user_id"].lower(), f"eval{case['id']:04d}")[0]


def load_cases():
    return json.loads((EVAL_DIR / "test_cases.json").read_text(encoding="utf-8"))


def md_table(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c).replace("|", "/") for c in r) + " |" for r in rows]
    return "\n".join(out)


# Retrieval mode
def run_retrieval(cases):
    from core import config
    from core.guardrails import detect_injection
    from core.rag import get_retriever

    retriever = get_retriever()
    rows, hit1, hit4, n_ret, correct_other, n_other = [], 0, 0, 0, 0, 0
    for c in cases:
        q = c["query"]
        if c["type"] == "injection":
            ok = detect_injection(q) is not None
            n_other += 1
            correct_other += ok
            rows.append([c["id"], c["type"], q[:55], "-", "blocked" if ok else "NOT blocked", "-",
                         "PASS" if ok else "FAIL"])
            continue
        results, relevant = retriever.search(q, config.TOP_K)
        top_ids = [r["sop_id"] for r in results]
        best = results[0] if results else {}
        if c["expected_sop"]:
            n_ret += 1
            h1 = relevant and top_ids[0] in c["expected_sop"]
            h4 = relevant and any(s in c["expected_sop"] for s in top_ids)
            hit1 += h1
            hit4 += h4
            mark = "PASS" if h1 else ("top-4 only" if h4 else "FAIL")
            rows.append([c["id"], c["type"], q[:55], "/".join(c["expected_sop"]), top_ids[0],
                         f"v={best['vector']:.2f} bm25={best['bm25']:.1f}", mark])
        else:  # off-topic: should be marked NOT relevant
            n_other += 1
            ok = not relevant
            correct_other += ok
            rows.append([c["id"], c["type"], q[:55], "(none)", "not relevant" if ok else top_ids[0],
                         f"v={best['vector']:.2f} bm25={best['bm25']:.1f}", "PASS" if ok else "FAIL"])

    summary = (f"Retrieval hit@1: {hit1}/{n_ret} = {hit1 / n_ret:.0%}\n"
               f"Retrieval hit@4: {hit4}/{n_ret} = {hit4 / n_ret:.0%}\n"
               f"Off-topic / injection handled: {correct_other}/{n_other}\n"
               f"Thresholds: VECTOR_MIN_SCORE={config.VECTOR_MIN_SCORE}, "
               f"BM25_MIN_SCORE={config.BM25_MIN_SCORE} | index: {retriever.status()}")
    table = md_table(["#", "Type", "Query", "Expected", "Top-1", "Best scores", "Result"], rows)
    print(table, "\n\n" + summary)
    (EVAL_DIR / "retrieval_results.md").write_text(
        f"# LabAssist - Retrieval Evaluation\n\n{table}\n\n```\n{summary}\n```\n", encoding="utf-8")
    print(f"\nWrote {EVAL_DIR / 'retrieval_results.md'}")


# Full agent mode
def run_full(cases):
    # temporary database
    tmp = tempfile.mkdtemp(prefix="labassist_eval_")
    os.environ["LABASSIST_DB"] = str(Path(tmp) / "eval.db")
    os.environ["RATE_LIMIT_PER_MIN"] = "1000"  # evaluation is not a flood
    for name in ("JIRA_BASE_URL", "DISCORD_WEBHOOK_URL", "AUTOMATION_WEBHOOK_URL"):
        os.environ[name] = ""  # test tickets never go to Jira / Discord / webhooks
    from core import agent, config, db
    from core.rag import tokenize

    db.init_db()
    rows, passed, latencies, models = [], 0, [], set()
    deflected = non_blocked = 0
    citing = valid_citations = 0   # replies that cite an SOP / whose citations were retrieved
    grounded_scores = []           # English answers: share of words found in the retrieved SOPs
    for c in cases:
        user = make_user(db, c)
        conv = db.create_conversation(user["user_id"], user["role"])
        t0 = time.perf_counter()
        res = agent.handle_message(user, conv, c["query"])
        latencies.append((time.perf_counter() - t0) * 1000)
        models.add(res.model)

        tools = [a["tool"] for a in res.actions]
        ok_res = res.resolution == c["expected_resolution"]
        ok_tool = c["expected_tool"] is None or c["expected_tool"] in tools
        cited = {r["sop_id"] for r in res.sources} if res.relevant else set()
        ok_src = not c["expected_sop"] or bool(cited & set(c["expected_sop"]))
        ok = ok_res and ok_tool and ok_src
        passed += ok
        if res.resolution != "blocked":
            non_blocked += 1
            deflected += res.resolution in ("answered", "action")

        # RAG quality
        # citation accuracy: cited SOPs must be in the retrieved context
        cited_in_reply = set(re.findall(r"SOP-\d+", res.reply))
        retrieved = {r["sop_id"] for r in res.sources}
        referenced = set(re.findall(r"SOP-\d+", " ".join(r["text"] for r in res.sources)))
        if cited_in_reply:
            citing += 1
            valid_citations += cited_in_reply <= (retrieved | referenced)
        # groundedness: share of answer words found in the SOPs (English only)
        if res.resolution == "answered" and c["lang"] == "English" and res.relevant:
            context = set(tokenize(" ".join(r["text"] for r in res.sources)))
            words = [w for w in tokenize(res.reply) if w.isalpha() and len(w) > 3]
            if words:
                grounded_scores.append(sum(w in context for w in words) / len(words))
        rows.append([c["id"], c["type"], c["lang"], c["query"][:50],
                     f"{c['expected_resolution']} -> {res.resolution}", ", ".join(tools) or "-",
                     ", ".join(sorted(cited)) or "-", f"{res.latency_ms}", res.model,
                     "PASS" if ok else "FAIL"])
        print(f"[{c['id']:2}] {'PASS' if ok else 'FAIL'} {res.resolution:9} {res.latency_ms:6} ms  {c['query'][:60]}")
        if config.llm_enabled():
            time.sleep(1)  # free-tier rate limit

    accuracy = passed / len(cases)
    avg_ms = sum(latencies) / len(latencies)
    p95_ms = sorted(latencies)[min(len(latencies) - 1, int(len(latencies) * 0.95))]
    deflection = deflected / non_blocked if non_blocked else 0
    grounded = sum(grounded_scores) / len(grounded_scores) if grounded_scores else 0
    summary = (f"- **Accuracy:** {passed}/{len(cases)} = **{accuracy:.0%}** "
               f"(resolution + tool + source all correct)\n"
               f"- **Citation accuracy:** {valid_citations}/{citing} replies cite only SOPs found in the "
               f"retrieved context ({(valid_citations / citing if citing else 0):.0%}); "
               f"invented sources: {citing - valid_citations}\n"
               f"- **Groundedness (faithfulness proxy):** {grounded:.0%} of the content words in English "
               f"answers appear in the retrieved SOP text ({len(grounded_scores)} answers)\n"
               f"- **Average latency:** {avg_ms:.0f} ms (p95 {p95_ms:.0f} ms)\n"
               f"- **Deflection rate:** {deflection:.0%} of non-blocked requests solved without a "
               f"ticket/escalation\n"
               f"- **Model(s) used:** {', '.join(sorted(models))}\n"
               f"- **Date:** {time.strftime('%Y-%m-%d %H:%M')}")
    table = md_table(["#", "Type", "Lang", "Query", "Expected -> Actual", "Tools", "Sources",
                      "ms", "Model", "Pass"], rows)
    (EVAL_DIR / "results.md").write_text(
        f"# LabAssist - Evaluation Results (full agent)\n\n{summary}\n\n{table}\n", encoding="utf-8")
    print("\n" + summary.replace("**", ""))
    print(f"\nWrote {EVAL_DIR / 'results.md'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate LabAssist")
    parser.add_argument("--full", action="store_true", help="run the full agent (uses the LLM if configured)")
    args = parser.parse_args()
    cases = load_cases()
    run_full(cases) if args.full else run_retrieval(cases)
