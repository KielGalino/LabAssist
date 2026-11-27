"""SQLite database: tables, seed data and queries."""
import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from core import config

SCHEMA_VERSION = 5  # bump when tables change

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    unit                 TEXT PRIMARY KEY,    -- PC-01 .. PC-42
    server               TEXT NOT NULL,       -- MPS-1 / MPS-2 / MPS-3
    status               TEXT NOT NULL DEFAULT 'active'
                         CHECK (status IN ('active','locked','needs_repair')),
    password_hash        TEXT NOT NULL,       -- sha256 only, never the plain password
    last_password_change TEXT
);
CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,                 -- session id (STUDENT-xxxx / TEACHER-xxxx) or ADMIN
    role       TEXT NOT NULL,
    started_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    role            TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content         TEXT NOT NULL,            -- already PII-redacted
    category        TEXT,
    sources         TEXT,                     -- JSON list of SOP ids
    resolution      TEXT,                     -- answered|action|ticket|escalated|no_answer|blocked
    latency_ms      INTEGER,
    model           TEXT,
    prompt_tokens     INTEGER DEFAULT 0,      -- LLM usage (observability)
    completion_tokens INTEGER DEFAULT 0,
    intent          TEXT,                     -- classified intent (agent.classify_intent)
    created_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tickets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_no         TEXT UNIQUE,            -- TKT-0001
    requester         TEXT NOT NULL,          -- session id (STUDENT-xxxx / TEACHER-xxxx) or ADMIN
    requester_section TEXT,
    category          TEXT NOT NULL,
    unit              TEXT,
    description       TEXT NOT NULL,
    priority          TEXT NOT NULL CHECK (priority IN ('low','medium','high','critical')),
    status            TEXT NOT NULL DEFAULT 'open' CHECK (status IN
                      ('open','pending_approval','escalated','in_progress','resolved','rejected')),
    external_ref      TEXT,                   -- e.g. Jira issue key (LAB-12) when synced
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS action_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT,
    tool       TEXT NOT NULL,
    arguments  TEXT,                          -- JSON (secrets never included)
    result     TEXT,                          -- JSON (secrets never included)
    success    INTEGER,
    created_at TEXT NOT NULL
);
"""

SECTIONS = ["ICT-11A", "ICT-11B", "ICT-12A"]
DEMO_STATION_STATUS = {"PC-12": "locked", "PC-31": "needs_repair"}

TICKET_STATUSES = ["open", "pending_approval", "escalated", "in_progress", "resolved", "rejected"]
STATION_STATUSES = ["active", "locked", "needs_repair"]
# labels for pills and replies
STATUS_LABELS = {"open": "Open", "pending_approval": "Pending approval", "escalated": "Escalated",
                 "in_progress": "In progress", "resolved": "Resolved", "rejected": "Rejected",
                 "active": "Active", "locked": "Locked", "needs_repair": "Needs repair"}


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def server_for(unit: str) -> str:
    """PC-01..14 -> MPS-1, PC-15..28 -> MPS-2, PC-29..42 -> MPS-3."""
    n = int(unit.split("-")[1])
    return f"MPS-{(n - 1) // 14 + 1}"


@contextmanager
def get_conn():
    """Open the database; commits on success and always closes."""
    path = config.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row  # rows behave like dicts
    # WAL: readers and a writer at the same time
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create tables and seed data (old schema versions are rebuilt)."""
    with get_conn() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            for table in ("lab_accounts", "users", "students", "stations", "conversations",
                          "messages", "tickets", "action_logs"):
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.executescript(SCHEMA)
        for n in range(1, 43):
            unit = f"PC-{n:02d}"
            # random password per station, only the hash is kept
            conn.execute(
                "INSERT OR IGNORE INTO stations (unit, server, status, password_hash, "
                "last_password_change) VALUES (?,?,?,?,?)",
                (unit, server_for(unit), DEMO_STATION_STATUS.get(unit, "active"),
                 sha256(secrets.token_urlsafe(12)), now()),
            )


# Stations
def get_station(unit: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM stations WHERE unit = ?",
                           (unit.strip().upper(),)).fetchone()
    return dict(row) if row else None


def list_stations() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT unit, server, status, last_password_change "
                            "FROM stations ORDER BY unit").fetchall()
    return [dict(r) for r in rows]


def set_station_status(unit: str, status: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE stations SET status = ? WHERE unit = ?", (status, unit))


def set_station_password(unit: str, password_hash: str) -> None:
    """Store a new password HASH and mark the station active."""
    with get_conn() as conn:
        conn.execute("UPDATE stations SET password_hash = ?, status = 'active', "
                     "last_password_change = ? WHERE unit = ?", (password_hash, now(), unit))


# Conversations and messages
def create_conversation(user_id: str, role: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (user_id, role, started_at) VALUES (?,?,?)",
            (user_id, role, now()),
        )
        return cur.lastrowid


def get_conversation(conversation_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    return dict(row) if row else None


def add_message(conversation_id, role, content, category=None, sources=None,
                resolution=None, latency_ms=None, model=None,
                prompt_tokens=0, completion_tokens=0, intent=None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, category, sources, "
            "resolution, latency_ms, model, prompt_tokens, completion_tokens, intent, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (conversation_id, role, content, category, json.dumps(sources or []),
             resolution, latency_ms, model, prompt_tokens, completion_tokens, intent, now()),
        )


def get_history(conversation_id: int, limit: int) -> list[dict]:
    """Last `limit` messages of a conversation, oldest first (for the LLM)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


# Tickets
def create_ticket(requester, category, unit, description, priority, status="open",
                  requester_section=None) -> str:
    """Insert a ticket and return its number, e.g. TKT-0007."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO tickets (requester, requester_section, category, unit, description, "
            "priority, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (requester, requester_section, category, unit, description, priority, status,
             now(), now()),
        )
        ticket_no = f"TKT-{cur.lastrowid:04d}"  # numbering follows the row id
        conn.execute("UPDATE tickets SET ticket_no = ? WHERE id = ?", (ticket_no, cur.lastrowid))
    return ticket_no


def get_ticket(ticket_no: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tickets WHERE ticket_no = ?", (ticket_no.strip().upper(),)
        ).fetchone()
    return dict(row) if row else None


def list_tickets(statuses=None) -> list[dict]:
    """All tickets (newest first), optionally only those with the given statuses."""
    sql, params = "SELECT * FROM tickets", ()
    if statuses:
        sql += f" WHERE status IN ({','.join('?' * len(statuses))})"
        params = tuple(statuses)
    with get_conn() as conn:
        rows = conn.execute(sql + " ORDER BY id DESC", params).fetchall()
    return [dict(r) for r in rows]


def set_external_ref(ticket_no: str, ref: str) -> None:
    """Remember the matching issue in an external system (e.g. Jira key LAB-12)."""
    with get_conn() as conn:
        conn.execute("UPDATE tickets SET external_ref = ? WHERE ticket_no = ?", (ref, ticket_no))


def update_ticket_status(ticket_no: str, status: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE tickets SET status = ?, updated_at = ? WHERE ticket_no = ?",
            (status, now(), ticket_no),
        )


def set_ticket_priority(ticket_no: str, priority: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE tickets SET priority = ?, updated_at = ? WHERE ticket_no = ?",
                     (priority, now(), ticket_no))


def open_station_request(unit: str):
    """The newest unlock request for a unit that is still waiting, if any."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tickets WHERE unit = ? AND category = 'Station Access' "
            "AND status IN ('open','pending_approval','in_progress','escalated') "
            "ORDER BY id DESC LIMIT 1", (unit,)).fetchone()
    return dict(row) if row else None


def tickets_for_requester(requester: str, limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM tickets WHERE requester = ? ORDER BY id DESC LIMIT ?",
                            (requester, limit)).fetchall()
    return [dict(r) for r in rows]


def resolve_station_requests(unit: str) -> list[str]:
    """Mark the open Station Access requests of a unit as resolved."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ticket_no FROM tickets WHERE unit = ? AND category = 'Station Access' "
            "AND status IN ('open','pending_approval','in_progress','escalated')", (unit,)
        ).fetchall()
        numbers = [r["ticket_no"] for r in rows]
        for no in numbers:
            conn.execute("UPDATE tickets SET status = 'resolved', updated_at = ? "
                         "WHERE ticket_no = ?", (now(), no))
    return numbers


# Audit log
def log_action(user_id, tool, arguments: dict, result: dict, success: bool) -> None:
    """Write one action to the audit trail (callers must pass safe data only)."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO action_logs (user_id, tool, arguments, result, success, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, tool, json.dumps(arguments), json.dumps(result), int(success), now()),
        )


def list_action_logs(limit: int = 200) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM action_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# Dashboard queries
def query(sql: str, params: tuple = ()) -> list[dict]:
    """Small helper for read-only dashboard queries."""
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
