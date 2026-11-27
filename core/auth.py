"""Who is chatting (no sign-in), admin PIN with lockout, and the rate limit."""
import hmac
import re
import secrets
import threading
import time
from collections import defaultdict, deque

from core import config, db

ROLES = ("student", "teacher")
CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9-]{6,64}$")
MAX_PIN_FAILURES = 5
LOCKOUT_SECONDS = 300

# admin user for the dashboard and API
ADMIN_USER = {"user_id": "ADMIN", "full_name": "Lab Administrator", "role": "admin", "section": None}

_lock = threading.Lock()
_failures = defaultdict(list)     # client key -> timestamps of recent wrong PINs
_locked_until = {}                # client key -> unix time when the lockout ends
_messages = defaultdict(deque)    # user_id -> timestamps of recent chat messages


# Students and teachers (no sign-in)
def new_client_id() -> str:
    """Random id for one browser session (not linked to a person)."""
    return secrets.token_hex(4)


def identify(role: str, client_id: str):
    """Build the user from the chosen role and session id."""
    if role not in ROLES:
        return None, "Choose Student or Teacher."
    client_id = (client_id or "").strip()
    if not CLIENT_ID_RE.match(client_id):
        return None, "Invalid session. Reload the page."
    return {"user_id": f"{role.upper()}-{client_id[:16]}", "full_name": role.capitalize(),
            "role": role, "section": None}, ""


# Admin PIN with lockout
def lockout_remaining(client: str = "local") -> int:
    """Seconds left on a lockout (0 = not locked)."""
    with _lock:
        return max(0, int(_locked_until.get(client, 0) - time.time()))


def _record_failure(client: str) -> None:
    now = time.time()
    with _lock:
        recent = [t for t in _failures[client] if now - t < LOCKOUT_SECONDS] + [now]
        _failures[client] = recent
        if len(recent) >= MAX_PIN_FAILURES:
            _locked_until[client] = now + LOCKOUT_SECONDS
            _failures[client] = []
    db.log_action("ADMIN", "auth_failed", {"client": client[:24]}, {"status": "wrong_pin"}, False)


def verify_admin_pin(pin: str, client: str = "local"):
    """Check the admin PIN. Returns (ok, reason)."""
    if lockout_remaining(client):
        return False, f"Too many wrong PINs. Try again in {lockout_remaining(client) // 60 + 1} minute(s)."
    pin = (pin or "").strip()
    if pin and hmac.compare_digest(pin, config.ADMIN_PIN):
        with _lock:
            _failures.pop(client, None)
        db.log_action("ADMIN", "auth_success", {"role": "admin"}, {"status": "signed_in"}, True)
        return True, ""
    _record_failure(client)
    return False, "Incorrect admin PIN."


# Rate limit for chat messages
def allow_message(user_id: str) -> bool:
    """Sliding 60-second window per user."""
    now = time.time()
    with _lock:
        q = _messages[user_id]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= config.RATE_LIMIT_PER_MIN:
            return False
        q.append(now)
        return True


def reset_limits() -> None:
    """Used by tests."""
    with _lock:
        _failures.clear()
        _locked_until.clear()
        _messages.clear()
