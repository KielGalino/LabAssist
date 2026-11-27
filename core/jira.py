"""Optional Jira Cloud sync: creates issues for urgent tickets (JIRA_* in .env)."""
import base64
import json
import threading
import urllib.error
import urllib.request

from core import config, db

PRIORITY_MAP = {"critical": "Highest", "high": "High", "medium": "Medium", "low": "Low"}


def enabled() -> bool:
    return all([config.JIRA_BASE_URL, config.JIRA_EMAIL, config.JIRA_API_TOKEN, config.JIRA_PROJECT_KEY])


def should_sync(ticket: dict) -> bool:
    if config.JIRA_SYNC == "all":
        return True
    return (ticket["priority"] in ("high", "critical") or ticket["status"] in ("escalated", "pending_approval"))


def issue_payload(ticket: dict) -> dict:
    """Issue fields for a ticket."""
    lines = [f"LabAssist ticket {ticket['ticket_no']}",
             f"Requester: {ticket['requester']} {ticket.get('requester_section') or ''}".strip(),
             f"Category: {ticket['category']} | Unit: {ticket['unit']} | Priority: {ticket['priority']}",
             f"Status: {ticket['status']}", "", ticket["description"]]
    return {"fields": {
        "project": {"key": config.JIRA_PROJECT_KEY},
        "issuetype": {"name": config.JIRA_ISSUE_TYPE},
        "summary": f"[{ticket['ticket_no']}] {ticket['category']} - {ticket['unit']}: "
                   f"{ticket['description'][:120]}",
        "labels": ["labassist", ticket["category"].lower().replace(" ", "-")],
        "description": {"type": "doc", "version": 1, "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line}]} if line else
            {"type": "paragraph", "content": []} for line in lines]},
    }}


def _create_issue(ticket: dict) -> None:
    try:
        token = base64.b64encode(f"{config.JIRA_EMAIL}:{config.JIRA_API_TOKEN}".encode()).decode()
        req = urllib.request.Request(
            config.JIRA_BASE_URL.rstrip("/") + "/rest/api/3/issue",
            data=json.dumps(issue_payload(ticket)).encode(), method="POST",
            headers={"Authorization": f"Basic {token}", "Content-Type": "application/json",
                     "Accept": "application/json", "User-Agent": "LabAssist/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            key = json.loads(resp.read().decode()).get("key")
        if key:
            db.set_external_ref(ticket["ticket_no"], key)
            db.log_action("jira", "jira_create_issue", {"ticket_no": ticket["ticket_no"]},
                          {"status": "success", "jira_key": key}, True)
    except Exception as e:  # noqa: BLE001 - never break the helpdesk
        # keep the HTTP code for the audit log
        reason = f"HTTP {e.code}" if isinstance(e, urllib.error.HTTPError) else type(e).__name__
        db.log_action("jira", "jira_create_issue", {"ticket_no": ticket["ticket_no"]},
                      {"status": "error", "message": reason}, False)


def sync_ticket(ticket: dict, background: bool = True) -> bool:
    """Create the Jira issue in the background if Jira is set up."""
    if not enabled() or not should_sync(ticket):
        return False
    if background:
        threading.Thread(target=_create_issue, args=(ticket,), daemon=True).start()
    else:
        _create_issue(ticket)
    return True
