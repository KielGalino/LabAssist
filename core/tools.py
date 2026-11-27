"""Tools the LLM can call. Role checks happen here, not in the prompt."""
import re
import secrets
import string

from core import db, jira
from core.notify import emit_event, notify_admin

CATEGORIES = ["Hardware", "Network", "Station Access", "Software Request", "Printing",
              "Lab Reservation", "Server", "Other"]
PRIORITIES = ["low", "medium", "high", "critical"]
# roles are self-chosen, so only the admin can unlock or reset


def normalize_unit(unit: str) -> str:
    """'pc 7' / 'PC7' / 'pc-07' -> 'PC-07';  'mps2' -> 'MPS-2'; others upper-cased."""
    u = re.sub(r"[\s_]+", "-", (unit or "").strip().upper())
    m = re.fullmatch(r"PC-?(\d{1,2})", u)
    if m:
        return f"PC-{int(m.group(1)):02d}"
    m = re.fullmatch(r"MPS-?(\d)", u)
    return f"MPS-{m.group(1)}" if m else (u or "N/A")


# Tool definitions (OpenAI format)
def _fn(name, description, properties, required):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required}}}


UNIT_PROP = {"type": "string", "description": "Thin client unit, e.g. PC-12"}

REQUEST_UNLOCK = _fn(
    "request_station_unlock",
    "File an unlock request for a thin client station that is locked or will not log in, "
    "AFTER the user says the SOP-01 steps did not work. Needs the unit number - ask if missing. "
    "The lab administrator approves it; no password is ever given to the user.",
    {"unit": UNIT_PROP, "issue": {"type": "string", "description": "What the user sees / tried"}},
    ["unit", "issue"])
UNLOCK = _fn(
    "unlock_station",
    "Mark a locked station as active again. Lab Administrator only.",
    {"unit": UNIT_PROP}, ["unit"])
CREATE_TICKET = _fn(
    "create_ticket",
    "Create a helpdesk ticket ONLY when the user says the SOP steps did not work, equipment is "
    "physically damaged, there is a safety risk, or the user asks for a software request or lab "
    "reservation. Needs the unit number (ask if missing). Use the SOP-14 priority table.",
    {"category": {"type": "string", "enum": CATEGORIES},
     "description": {"type": "string", "description": "Short summary of the problem"},
     "unit": {"type": "string", "description": "e.g. PC-12, MPS-2, LAB-PRINTER-01, or N/A"},
     "priority": {"type": "string", "enum": PRIORITIES}},
    ["category", "description", "unit", "priority"])
ESCALATE = _fn(
    "escalate_to_admin",
    "Escalate to the lab administrator for safety or security incidents, problems a ticket "
    "cannot cover, or when the user asks for a human.",
    {"reason": {"type": "string"}, "summary": {"type": "string"},
     "priority": {"type": "string", "enum": PRIORITIES}},
    ["reason", "summary", "priority"])
CHECK_STATUS = _fn(
    "check_ticket_status",
    "Check the status of a helpdesk ticket by its number (TKT-0001 format).",
    {"ticket_no": {"type": "string", "description": "e.g. TKT-0003"}}, ["ticket_no"])


def tool_schemas_for(role: str) -> list:
    """Tools offered to the LLM for a role (never the password reset)."""
    tools = [REQUEST_UNLOCK, CREATE_TICKET, ESCALATE, CHECK_STATUS]
    if role == "admin":
        tools.append(UNLOCK)
    return tools


def _result(tool, ok, status, message, data=None, secret=None) -> dict:
    """Tool result. 'secret' is only shown on the Admin Dashboard."""
    return {"tool": tool, "ok": ok, "status": status, "message": message,
            "data": data or {}, "secret": secret or {}}


def llm_view(result: dict) -> dict:
    """Tool result without the secret (for the LLM and the logs)."""
    return {k: v for k, v in result.items() if k != "secret"}


# Station tools
def request_station_unlock(user: dict, unit: str, issue: str = "") -> dict:
    tool = "request_station_unlock"
    unit = normalize_unit(unit)
    station = db.get_station(unit)
    if not station:
        return _result(tool, False, "not_found",
                       f"'{unit}' is not a lab station. Ask for the unit number (PC-01 to PC-42).")
    if station["status"] == "needs_repair":
        return _result(tool, False, "needs_repair",
                       f"{unit} is already marked for repair, so it cannot be unlocked. "
                       "Please use another unit; the repair is already logged.",
                       data={"unit": unit, "station_status": "needs_repair"})

    # one open request per station
    existing = db.open_station_request(unit)
    if existing:
        # teacher report -> raise to high
        if user["role"] == "teacher" and existing["priority"] in ("low", "medium"):
            db.set_ticket_priority(existing["ticket_no"], "high")
            existing = db.get_ticket(existing["ticket_no"])
        return _result(tool, True, "duplicate",
                       f"An unlock request for {unit} is already waiting ({existing['ticket_no']}, "
                       f"status {existing['status']}). No new request was filed.",
                       data={"ticket_no": existing["ticket_no"], "unit": unit,
                             "category": "Station Access", "priority": existing["priority"],
                             "status": existing["status"], "duplicate": True})

    description = f"Unlock request for {unit}: {(issue or 'station locked / cannot log in').strip()[:400]}"
    # teacher request -> high priority
    priority = "high" if user["role"] == "teacher" else "medium"
    ticket_no = db.create_ticket(user["user_id"], "Station Access", unit, description, priority,
                                 status="pending_approval", requester_section=user.get("section"))
    notified = notify_admin("Station unlock request", db.get_ticket(ticket_no))
    jira.sync_ticket(db.get_ticket(ticket_no))  # optional Jira issue (if configured)
    emit_event("unlock.requested", {"ticket_no": ticket_no, "unit": unit,
                                    "requester": user["user_id"], "section": user.get("section")})
    return _result(
        tool, True, "success",
        f"Unlock request {ticket_no} filed for {unit}. It is pending approval by the lab "
        "administrator. " + ("You can log the station in once it is unlocked."
                             if user["role"] == "teacher" else
                             "The teacher will log the station in once it is unlocked. "
                             "No password is given to the student."),
        data={"ticket_no": ticket_no, "unit": unit, "category": "Station Access",
              "priority": priority, "status": "pending_approval", "admin_notified": notified},
    )


def unlock_station(user: dict, unit: str) -> dict:
    tool = "unlock_station"
    if user["role"] != "admin":
        return _result(tool, False, "denied",
                       "Only the lab administrator can unlock stations. "
                       "I can file an unlock request instead.")
    unit = normalize_unit(unit)
    station = db.get_station(unit)
    if not station:
        return _result(tool, False, "not_found", f"'{unit}' is not a lab station.")
    if station["status"] == "needs_repair":
        return _result(tool, False, "needs_repair",
                       f"{unit} is marked for repair and cannot be unlocked until it is fixed.")
    db.set_station_status(unit, "active")
    resolved = db.resolve_station_requests(unit)
    emit_event("station.unlocked", {"unit": unit, "by": user["user_id"], "resolved_tickets": resolved})
    return _result(tool, True, "success", f"{unit} is now active.",
                   data={"unit": unit, "station_status": "active", "resolved_tickets": resolved})


def _new_station_password() -> str:
    """10 random characters without look-alikes (0/O, 1/l/I)."""
    alphabet = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")
    return "".join(secrets.choice(alphabet) for _ in range(10))


def reset_station_password(user: dict, unit: str) -> dict:
    tool = "reset_station_password"
    if user["role"] != "admin":
        return _result(tool, False, "denied",
                       "Only the lab administrator can reset station passwords.")
    unit = normalize_unit(unit)
    if not db.get_station(unit):
        return _result(tool, False, "not_found", f"'{unit}' is not a lab station.")
    password = _new_station_password()
    db.set_station_password(unit, db.sha256(password))  # only the hash is stored
    resolved = db.resolve_station_requests(unit)
    emit_event("station.password_reset", {"unit": unit, "by": user["user_id"]})  # no password in the event
    return _result(tool, True, "success",
                   f"Password for {unit} was reset and the station is active.",
                   data={"unit": unit, "station_status": "active", "resolved_tickets": resolved},
                   secret={"station_password": password})


# Ticket tools
def create_ticket(user: dict, category: str, description: str, unit: str = "N/A",
                  priority: str = "medium", status: str = "open") -> dict:
    tool = "create_ticket"
    category = category if category in CATEGORIES else "Other"
    priority = (priority or "medium").lower()
    priority = priority if priority in PRIORITIES else "medium"
    description = (description or "").strip()[:1000] or "(no description)"
    unit = normalize_unit(unit)[:40]
    # the unit must exist
    if re.fullmatch(r"PC-\d+", unit) and not db.get_station(unit):
        return _result(tool, False, "not_found",
                       f"'{unit}' is not a lab station. Ask the user for the unit number (PC-01 to PC-42).")
    if re.fullmatch(r"MPS-\d+", unit) and unit not in ("MPS-1", "MPS-2", "MPS-3"):
        return _result(tool, False, "not_found", f"'{unit}' is not a lab server (MPS-1 to MPS-3).")

    ticket_no = db.create_ticket(user["user_id"], category, unit, description, priority, status,
                                 requester_section=user.get("section"))
    ticket = db.get_ticket(ticket_no)
    notified = False
    if priority in ("high", "critical") or status == "escalated":
        notified = notify_admin("Escalation" if status == "escalated" else "New urgent ticket", ticket)
    jira.sync_ticket(ticket)  # optional Jira issue (if configured)
    emit_event("ticket.escalated" if status == "escalated" else "ticket.created",
               {k: ticket[k] for k in ("ticket_no", "requester", "requester_section", "category",
                                       "unit", "priority", "status", "description")})
    return _result(
        tool, True, "success",
        f"Ticket {ticket_no} created ({priority} priority, {category}).",
        data={"ticket_no": ticket_no, "category": category, "unit": unit,
              "priority": priority, "status": status, "admin_notified": notified},
    )


def escalate_to_admin(user: dict, reason: str, summary: str, priority: str = "high") -> dict:
    # category from keywords
    text = f"{reason} {summary}".lower()
    category = ("Station Access" if any(w in text for w in ("locked", "login", "password", "station"))
                else "Server" if any(w in text for w in ("server", "mps"))
                else "Hardware" if any(w in text for w in ("smoke", "spark", "fire", "usok", "damage"))
                else "Other")
    res = create_ticket(user, category, f"[ESCALATED] {reason}: {summary}", "N/A",
                        priority, status="escalated")
    res["tool"] = "escalate_to_admin"
    res["message"] = (f"Escalated to the lab administrator as {res['data']['ticket_no']}. "
                      "The administrator will follow up.")
    return res


def check_ticket_status(user: dict, ticket_no: str) -> dict:
    tool = "check_ticket_status"
    ticket = db.get_ticket(ticket_no or "")
    if not ticket:
        return _result(tool, False, "not_found", f"Ticket {ticket_no} was not found.")
    # works like a tracking number: public fields only
    return _result(
        tool, True, "success",
        f"{ticket['ticket_no']} is '{ticket['status']}' (priority {ticket['priority']}).",
        data={k: ticket[k] for k in ("ticket_no", "category", "unit", "priority",
                                     "status", "created_at", "updated_at")},
    )


TOOL_FUNCTIONS = {
    "request_station_unlock": request_station_unlock,
    "unlock_station": unlock_station,
    "reset_station_password": reset_station_password,
    "create_ticket": create_ticket,
    "escalate_to_admin": escalate_to_admin,
    "check_ticket_status": check_ticket_status,
}
ALLOWED_ARGS = {
    "request_station_unlock": {"unit", "issue"},
    "unlock_station": {"unit"},
    "reset_station_password": {"unit"},
    "create_ticket": {"category", "description", "unit", "priority"},
    "escalate_to_admin": {"reason", "summary", "priority"},
    "check_ticket_status": {"ticket_no"},
}


def execute_tool(name: str, args: dict, user: dict) -> dict:
    """Run a tool and write it to the audit log."""
    func = TOOL_FUNCTIONS.get(name)
    if not func:
        result = _result(name, False, "error", f"Unknown tool '{name}'.")
    else:
        clean = {k: str(v) for k, v in (args or {}).items() if k in ALLOWED_ARGS[name]}
        try:
            result = func(user, **clean)
        except TypeError as e:  # missing required arguments
            result = _result(name, False, "error", f"Missing or invalid arguments: {e}")
        except Exception as e:  # noqa: BLE001 - never crash the chat
            result = _result(name, False, "error", f"Tool failed: {type(e).__name__}")
    # audit log (no secrets)
    db.log_action(user["user_id"], name, args or {}, llm_view(result), result["ok"])
    return result
