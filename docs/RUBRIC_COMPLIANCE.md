# LabAssist - Capstone Specification Compliance

How LabAssist meets the *AI-Powered Enterprise Helpdesk & Workflow Automation System (AI-HAS)*
specification: the grading rubric, the technical stack, the team-role deliverables and the
8-week roadmap - with the evidence to show during the defense.

## 1. Grading rubric

### Core AI & RAG Architecture (25%)

| Requirement | Implementation | Evidence |
|---|---|---|
| Vector database of SOPs | ChromaDB, local embeddings, cosine, 16 SOPs / 61 sections, re-index on change | `core/rag.py`, Knowledge Base page |
| Hybrid search | 0.5 vector + 0.5 BM25 with Taglish expansion | Knowledge Base > Test retrieval |
| Accuracy of vector search | Retrieval hit@1 **23/23 (100%)**, off-topic correctly rejected | `eval/retrieval_results.md` |
| Dynamic prompt construction | Role, detected language, retrieved SOPs, role-specific tools | `docs/PROMPTS.md`, `agent.build_system_prompt()` |
| Hallucination reduction | Relevance gate, answer only from SOPs, invented units rejected, offline fallback shows SOP text | `core/rag.py`, `core/tools.py` |
| Context citation | `Source: SOP-XX` on every answer; Sources expander with scores; API returns `sources` | Helpdesk, `/api/chat` |
| Faithfulness / relevance evaluation | Citation accuracy **21/21, 0 invented sources**; groundedness **83%** | `eval/results.md` |
| Intent classification | 12 intents per request, stored, charted, returned by the API | `docs/PROMPTS.md`, dashboard |

### Software Engineering & Automation (20%)

| Requirement | Implementation | Evidence |
|---|---|---|
| Clean architecture | UI (`views/`), REST API (`api.py`), widget + sample portal (`static/`), shared services (`core/`) | `docs/ARCHITECTURE.md` |
| API design | FastAPI, 11 endpoints incl. streaming, typed models, OpenAPI docs | `docs/API.md`, `/docs` |
| LLM function calling | 5 tools in OpenAI format (role-filtered), streamed tool calls, model fallback | `core/tools.py`, `core/agent.py` |
| Automated webhooks | Outgoing JSON events (n8n / Make), Discord alerts, incoming status webhook with secret | `core/notify.py`, `api.py` |
| Jira ticket creation | Direct Jira Cloud REST API v3 integration (free plan), Jira key stored on the ticket | `core/jira.py`, `tests/test_jira.py` |
| Password reset / access workflow | Unlock requests, admin approval, station password reset (dashboard only) | `core/workflow.py` |
| Human escalation | `escalate_to_admin`, Pending Requests queue (human in the loop) | Admin Dashboard |

### Governance, Security & Guardrails (15%)

| Requirement | Implementation | Evidence |
|---|---|---|
| PII scrubbing | Masked before the LLM, before saving, and in every streamed piece of the reply | `core/guardrails.py`, `tests/test_streaming.py` |
| Prompt injection prevention | English + Taglish, l33t / spacing / zero-width normalised; output guard stops prompt leaks mid-stream; SOP uploads scanned | `tests/test_guardrails.py`, `tests/test_streaming.py` |
| RBAC | Enforced in Python on every tool; role-filtered tool lists; no sign-in for the helpdesk (the school has no portal / LMS), so the teacher role gets no extra power; admin PIN with lockout | `core/auth.py`, `core/tools.py`, `tests/test_no_student_password.py` |
| System resilience | Model fallback, streaming fallback, offline rules, BM25-only fallback, rate limit, never crashes | `tests/test_llm_flow.py`, `eval/stress_results.md` |

### Evaluation & Testing (15%)

| Requirement | Evidence |
|---|---|
| Automated tests | 154 pytest tests (guardrails, auth, tools, no-student-password, retrieval, agent, intent, streaming, LLM flow, Jira, REST API) |
| RAG accuracy | `eval/retrieval_results.md` (hit@1 100%), `eval/results.md` (25/25 end-to-end with Gemini) |
| Latency | Average 1.4 s, p95 2.4 s end-to-end (`eval/results.md`); live p95 and daily trend chart |
| Ticket deflection rate | 79% (`eval/results.md`); live KPI and daily trend chart |
| Stress testing | 40 concurrent users x 10 messages: 0 errors, ~83 msg/s, p50 93 ms; rate limiter verified (`eval/stress_results.md`) |
| CI | `.github/workflows/ci.yml` runs tests, retrieval eval and stress test |

### Technical Documentation (15%)

| Requirement | Where |
|---|---|
| Architecture diagrams | `docs/ARCHITECTURE.md` (component, sequence, state, ER) |
| API specs | `docs/API.md` + live OpenAPI at `/docs` |
| User manuals | `docs/USER_MANUAL.md` |
| Setup instructions | `README.md` (Windows, Docker, troubleshooting) |
| Prompt taxonomy | `docs/PROMPTS.md` |

### Final Presentation & Live Defense (10%)

Demo script and edge cases: `README.md` section 4.

## 2. Team-role deliverables (spec section 4)

| Role | Deliverable | Status |
|---|---|---|
| AI / RAG Engineer | Indexing, embeddings, prompt optimisation, guardrails, faithfulness/relevance evaluation | Done (`core/rag.py`, `docs/PROMPTS.md`, `eval/`) |
| Backend & Automation | REST API, schema, Jira integration, function-calling handlers | Done (`api.py`, `core/db.py`, `core/jira.py`, `core/tools.py`) |
| Frontend & UI/UX | Chatbot widget, human-in-the-loop dashboard, **real response streaming**, analytics (deflection, latency) | Done (`static/`, `views/`) |
| DevOps, QA & Docs | CI, Docker, load testing, synthetic test suite, documentation | Done (`.github/`, `Dockerfile` tested, `eval/stress_test.py`, `docs/`) |

## 3. Roadmap deliverables (spec section 5)

| Weeks | Deliverable | Status |
|---|---|---|
| 1-2 | Architecture, DB schema, GitHub/Docker setup, prompt taxonomy | Done (local git repository; push to GitHub to run CI) |
| 3-4 | SOP indexing, hybrid search, REST API with grounded citation | Done |
| 5-6 | Function calling (password reset, Jira ticket creation), chat UI, admin dashboard | Done |
| 7 | PII redaction, injection guardrails, evaluation audit, dockerized build | Done (Docker build and run tested) |
| 8 | Documentation, presentation deck, live defense | Docs done; the deck is prepared separately |

## 4. Deviations from the recommended stack (and why)

| Recommended | Used | Reason |
|---|---|---|
| OpenAI gpt-4o-mini | Gemini free tier via the OpenAI-compatible API (same `openai` client) | Must be free; switching needs only `LLM_BASE_URL` / `LLM_MODELS` |
| LangChain / LlamaIndex | Plain Python orchestration | Fewer dependencies; every step can be explained line by line |
| ServiceNow | Jira Cloud (free plan) + generic automation webhook | ServiceNow has no free tier; the webhook works with any tool |
| "VPN troubleshooting" example | Teacher Wi-Fi (SOP-07) and network SOP-06 | The lab has no VPN; the equivalent lab scenarios are covered |
| "Password resets" for users | Station password resets + unlock workflow | Students have no accounts in this lab (access model) |
