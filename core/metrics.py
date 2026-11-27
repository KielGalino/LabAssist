"""KPIs and model stats for the dashboard and API."""
from core import db


def _one(sql: str, params: tuple = ()) -> float:
    return db.query(sql, params)[0]["n"] or 0


def kpis() -> dict:
    handled = _one("SELECT COUNT(*) AS n FROM messages WHERE role='assistant' "
                   "AND resolution NOT IN ('blocked')")
    deflected = _one("SELECT COUNT(*) AS n FROM messages WHERE role='assistant' "
                     "AND resolution IN ('answered','action')")
    latencies = [r["latency_ms"] for r in db.query(
        "SELECT latency_ms FROM messages WHERE role='assistant' AND latency_ms IS NOT NULL "
        "ORDER BY latency_ms")]
    p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else 0
    llm_answers = _one("SELECT COUNT(*) AS n FROM messages WHERE role='assistant' "
                       "AND model NOT IN ('offline-rules','guardrail','policy-rule','rate-limit')")
    offline = _one("SELECT COUNT(*) AS n FROM messages WHERE role='assistant' AND model='offline-rules'")
    # MTTR in minutes (resolved tickets)
    mttr = _one("SELECT AVG((julianday(updated_at) - julianday(created_at)) * 24 * 60) AS n "
                "FROM tickets WHERE status='resolved'")
    return {
        "conversations": int(_one("SELECT COUNT(DISTINCT conversation_id) AS n FROM messages")),
        "requests": int(_one("SELECT COUNT(*) AS n FROM messages WHERE role='user'")),
        "deflection_rate": round(deflected / handled * 100, 1) if handled else 0.0,
        "avg_latency_ms": int(_one("SELECT AVG(latency_ms) AS n FROM messages WHERE role='assistant'")),
        "p95_latency_ms": int(p95),
        "pending_approvals": int(_one("SELECT COUNT(*) AS n FROM tickets WHERE status='pending_approval'")),
        "open_tickets": int(_one("SELECT COUNT(*) AS n FROM tickets "
                                 "WHERE status NOT IN ('resolved','rejected')")),
        "escalations": int(_one("SELECT COUNT(*) AS n FROM tickets WHERE description LIKE '[ESCALATED]%'")),
        "blocked": int(_one("SELECT COUNT(*) AS n FROM messages WHERE role='assistant' "
                            "AND resolution='blocked'")),
        "mttr_minutes": round(mttr, 1),
        "llm_answers": int(llm_answers),
        "offline_fallbacks": int(offline),
        "prompt_tokens": int(_one("SELECT SUM(prompt_tokens) AS n FROM messages")),
        "completion_tokens": int(_one("SELECT SUM(completion_tokens) AS n FROM messages")),
    }


def daily_trends() -> list[dict]:
    """Per day: requests, average / maximum response time, deflection rate (%)."""
    return db.query(
        "SELECT date(created_at) AS day, COUNT(*) AS requests, "
        "CAST(AVG(latency_ms) AS INTEGER) AS avg_latency_ms, MAX(latency_ms) AS max_latency_ms, "
        "ROUND(100.0 * SUM(resolution IN ('answered','action')) / "
        "      MAX(SUM(resolution != 'blocked'), 1), 1) AS deflection_rate "
        "FROM messages WHERE role='assistant' GROUP BY day ORDER BY day")


def by_intent() -> list[dict]:
    """How many requests of each intent (what users wanted)."""
    return db.query("SELECT COALESCE(intent, 'unknown') AS intent, COUNT(*) AS requests FROM messages "
                    "WHERE role='assistant' GROUP BY intent ORDER BY requests DESC")


def by_model() -> list[dict]:
    """Requests, average latency and tokens per model (observability)."""
    return db.query(
        "SELECT model, COUNT(*) AS requests, CAST(AVG(latency_ms) AS INTEGER) AS avg_latency_ms, "
        "SUM(prompt_tokens + completion_tokens) AS tokens FROM messages "
        "WHERE role='assistant' GROUP BY model ORDER BY requests DESC")
