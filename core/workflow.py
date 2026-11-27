"""Admin actions on tickets (unlock, reset, resolve, reject) for the dashboard and API."""
import re

from core import db
from core.notify import emit_event
from core.tools import execute_tool

ACTIONS = ("unlock", "reset", "resolve", "reject")


def is_station(unit: str) -> bool:
    return bool(re.fullmatch(r"PC-\d{2}", unit or ""))


def set_ticket_status(ticket: dict, status: str, actor: dict, action: str) -> None:
    """Update a ticket's status, audit-log it and emit an automation event."""
    db.update_ticket_status(ticket["ticket_no"], status)
    db.log_action(actor["user_id"], action, {"ticket_no": ticket["ticket_no"], "unit": ticket["unit"]},
                  {"status": status}, True)
    emit_event("ticket.status_changed", {"ticket_no": ticket["ticket_no"], "status": status,
                                         "by": actor["user_id"]})


def apply_action(ticket_no: str, action: str, actor: dict) -> dict:
    """Apply one action. 'secret' is only filled by reset (dashboard only)."""
    ticket = db.get_ticket(ticket_no)
    if not ticket:
        return {"ok": False, "message": f"{ticket_no} was not found.", "secret": {}}
    if actor["role"] != "admin":
        return {"ok": False, "message": "Only the Lab Administrator can approve requests.", "secret": {}}
    unit = ticket["unit"]

    if action in ("unlock", "reset") and not is_station(unit):
        return {"ok": False, "message": f"{unit} is not a station; use Mark resolved instead.", "secret": {}}
    if action == "unlock":
        res = execute_tool("unlock_station", {"unit": unit}, actor)
        if not res["ok"]:
            return {"ok": False, "message": res["message"], "secret": {}}
        set_ticket_status(ticket, "resolved", actor, "admin_approve_unlock")
        return {"ok": True, "message": f"{unit} unlocked. {ticket_no} marked Resolved.", "secret": {}}
    if action == "reset":
        res = execute_tool("reset_station_password", {"unit": unit}, actor)
        if not res["ok"]:
            return {"ok": False, "message": res["message"], "secret": {}}
        set_ticket_status(ticket, "resolved", actor, "admin_approve_reset")
        return {"ok": True, "message": f"Password for {unit} reset. {ticket_no} marked Resolved.",
                "secret": res["secret"]}
    if action == "resolve":
        set_ticket_status(ticket, "resolved", actor, "admin_mark_resolved")
        station = db.get_station(unit) if is_station(unit) else None
        if ticket["category"] == "Station Access" and station and station["status"] == "locked":
            db.set_station_status(unit, "active")
        return {"ok": True, "message": f"{ticket_no} marked Resolved.", "secret": {}}
    if action == "reject":
        set_ticket_status(ticket, "rejected", actor, "admin_reject")
        return {"ok": True, "message": f"{ticket_no} rejected.", "secret": {}}
    return {"ok": False, "message": f"Unknown action '{action}'.", "secret": {}}
