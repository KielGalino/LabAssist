"""Discord alerts and automation webhook events, sent in the background."""
import json
import threading
import urllib.request
from datetime import datetime

from core import config


def _post(url: str, payload: dict) -> None:
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "LabAssist/1.0"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:  # noqa: BLE001 - never break the helpdesk
        pass


def _send(url: str, payload: dict) -> bool:
    if not url:
        return False
    threading.Thread(target=_post, args=(url, payload), daemon=True).start()
    return True


def notify_admin(title: str, ticket: dict) -> bool:
    """Short Discord message. Returns True if a message was sent."""
    priority = str(ticket.get("priority", "")).upper()
    section = f" ({ticket['requester_section']})" if ticket.get("requester_section") else ""
    content = (
        f"**[{priority}] LabAssist - {title}**\n"
        f"Ticket: `{ticket.get('ticket_no')}` | Status: {ticket.get('status')} | "
        f"Category: {ticket.get('category')} | Unit: {ticket.get('unit') or '-'}\n"
        f"Requester: {ticket.get('requester')}{section}\n"
        f"> {str(ticket.get('description', ''))[:500]}"
    )
    return _send(config.DISCORD_WEBHOOK_URL, {"content": content})


def emit_event(event: str, data: dict) -> bool:
    """Automation webhook, e.g. emit_event("ticket.created", {...})."""
    payload = {"event": event, "source": "labassist",
               "timestamp": datetime.now().isoformat(timespec="seconds"), "data": data}
    return _send(config.AUTOMATION_WEBHOOK_URL, payload)
