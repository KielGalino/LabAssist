"""REST API (FastAPI), docs at /docs. Uses the same core/ services as the app.

Chat needs no sign-in; admin endpoints need the X-PIN header.
Password resets are not available here (Admin Dashboard only).
"""
import hmac
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core import agent, auth, config, db, metrics, rag, workflow

@asynccontextmanager
async def lifespan(_app):
    db.init_db()  # create tables / seed data on startup
    yield


app = FastAPI(
    title="LabAssist API",
    version="1.0",
    description="REST API of the CSIS ICT Laboratory Helpdesk (first-level IT support).",
    lifespan=lifespan,
)

# widget files and logo
ROOT = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")


@app.get("/widget", include_in_schema=False)
def widget():
    """Chat widget page (embedded with static/embed.js)."""
    return FileResponse(ROOT / "static" / "widget.html")


@app.get("/portal", include_in_schema=False)
def portal():
    """Sample portal page with the widget."""
    return FileResponse(ROOT / "static" / "portal.html")


# Request / response models
class ChatRequest(BaseModel):
    message: str = Field(..., max_length=config.MAX_MESSAGE_CHARS, examples=["PC-12 is still locked"])
    role: Literal["student", "teacher"] = "student"
    client_id: Optional[str] = Field(None, examples=["3f9a2c1b"],
                                     description="Random id of the browser session (keep it for the next messages)")
    conversation_id: Optional[int] = None


class ChatResponse(BaseModel):
    conversation_id: int
    client_id: str
    reply: str
    resolution: str
    category: str
    sources: list[str]
    actions: list[dict]
    pii_masked: list[str]
    latency_ms: int
    model: str
    intent: str


class ActionRequest(BaseModel):
    action: Literal["unlock", "resolve", "reject"]


class SearchRequest(BaseModel):
    query: str = Field(..., max_length=500, examples=["walang internet sa PC-07"])
    top_k: int = Field(config.TOP_K, ge=1, le=10)


class TicketStatusWebhook(BaseModel):
    ticket_no: str = Field(..., examples=["TKT-0001"])
    status: Literal["open", "pending_approval", "escalated", "in_progress", "resolved", "rejected"]
    note: Optional[str] = Field(None, max_length=300)


# Authentication helpers
def require_admin(request: Request, x_pin: Optional[str] = Header(None)):
    """Admin only: X-PIN must match ADMIN_PIN."""
    if not x_pin:
        raise HTTPException(401, "Lab Administrator PIN required (header X-PIN).")
    client = "api:" + (request.client.host if request.client else "unknown")
    ok, reason = auth.verify_admin_pin(x_pin, client)
    if not ok:
        raise HTTPException(401, reason)
    return dict(auth.ADMIN_USER)


def public_ticket(t: dict) -> dict:
    return {k: t[k] for k in ("ticket_no", "category", "unit", "priority", "status",
                              "created_at", "updated_at")}


# Endpoints
@app.get("/api/health", tags=["System"])
def health():
    """Service status."""
    r = rag.get_retriever()
    return {"status": "ok", "llm": "online" if config.llm_enabled() else "offline",
            "models": config.LLM_MODELS, "search_index": r.status()}


@app.post("/api/chat", response_model=ChatResponse, tags=["Helpdesk"])
def chat(req: ChatRequest):
    """Send a message and get the full answer."""
    user, conv_id = _chat_identity(req)
    res = agent.handle_message(user, conv_id, req.message)
    return _chat_response(user, conv_id, res)


@app.post("/api/chat/stream", tags=["Helpdesk"])
def chat_stream(req: ChatRequest):
    """Same as /api/chat, but streamed (Server-Sent Events)."""
    user, conv_id = _chat_identity(req)
    stream = agent.stream_message(user, conv_id, req.message)

    def events():
        try:
            for piece in stream:
                yield f"event: token\ndata: {json.dumps({'text': piece})}\n\n"
            yield f"event: done\ndata: {_chat_response(user, conv_id, stream.result).model_dump_json()}\n\n"
        except Exception as e:  # noqa: BLE001 - never leave the widget hanging
            yield f"event: error\ndata: {json.dumps({'error': type(e).__name__})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


def _chat_identity(req: ChatRequest):
    """Get the user and their conversation (only their own)."""
    rag.refresh_if_changed()  # pick up SOPs uploaded on the Knowledge Base page
    user, reason = auth.identify(req.role, req.client_id or auth.new_client_id())
    if not user:
        raise HTTPException(400, reason)
    conv_id = req.conversation_id
    if conv_id:
        conv = db.get_conversation(conv_id)
        if not conv or conv["user_id"] != user["user_id"]:  # no reading other people's chats
            raise HTTPException(403, "This conversation belongs to another user.")
    else:
        conv_id = db.create_conversation(user["user_id"], user["role"])
    return user, conv_id


def _chat_response(user: dict, conv_id: int, res) -> ChatResponse:
    return ChatResponse(
        conversation_id=conv_id, client_id=user["user_id"].split("-", 1)[1], reply=res.reply, resolution=res.resolution, category=res.category,
        sources=sorted({s["sop_id"] for s in res.sources}) if res.relevant else [],
        # tool results without secrets
        actions=[{k: v for k, v in a.items() if k != "secret"} for a in res.actions],
        pii_masked=res.pii_types, latency_ms=res.latency_ms, model=res.model, intent=res.intent)


@app.get("/api/tickets/{ticket_no}", tags=["Tickets"])
def get_ticket(ticket_no: str):
    """Ticket status by number (public fields only)."""
    ticket = db.get_ticket(ticket_no)
    if not ticket:
        raise HTTPException(404, "Ticket not found.")
    return public_ticket(ticket)


@app.get("/api/tickets", tags=["Tickets"])
def list_tickets(status: Optional[str] = None, admin=Depends(require_admin)):
    """All tickets (admin), optionally by status."""
    tickets = db.list_tickets([status] if status else None)
    return [public_ticket(t) | {"requester": t["requester"], "description": t["description"]}
            for t in tickets]


@app.post("/api/tickets/{ticket_no}/actions", tags=["Tickets"])
def ticket_action(ticket_no: str, req: ActionRequest, admin=Depends(require_admin)):
    """Unlock, resolve or reject a request (admin). No password reset here."""
    result = workflow.apply_action(ticket_no, req.action, admin)
    if not result["ok"]:
        raise HTTPException(400, result["message"])
    return {"ok": True, "message": result["message"]}


@app.get("/api/stations", tags=["Stations"])
def stations(admin=Depends(require_admin)):
    """All stations with their status (admin)."""
    return db.list_stations()


@app.get("/api/metrics", tags=["Observability"])
def get_metrics(admin=Depends(require_admin)):
    """KPIs and model stats (admin)."""
    return {"kpis": metrics.kpis(), "by_model": metrics.by_model(), "by_intent": metrics.by_intent(),
            "daily_trends": metrics.daily_trends()}


@app.post("/api/kb/search", tags=["Knowledge base"])
def kb_search(req: SearchRequest):
    """Test the hybrid search."""
    results, relevant = rag.get_retriever().search(req.query, req.top_k)
    return {"relevant": relevant, "results": [
        {k: r[k] for k in ("sop_id", "section", "score", "vector", "bm25")} for r in results]}


@app.post("/api/webhooks/ticket-status", tags=["Webhooks"])
def ticket_status_webhook(body: TicketStatusWebhook, x_webhook_secret: Optional[str] = Header(None)):
    """Incoming webhook: an external tool updates a ticket status."""
    if not config.WEBHOOK_SECRET:
        raise HTTPException(503, "Incoming webhooks are disabled (WEBHOOK_SECRET is not set).")
    if not hmac.compare_digest(x_webhook_secret or "", config.WEBHOOK_SECRET):
        raise HTTPException(401, "Invalid webhook secret.")
    ticket = db.get_ticket(body.ticket_no)
    if not ticket:
        raise HTTPException(404, "Ticket not found.")
    workflow.set_ticket_status(ticket, body.status, {"user_id": "webhook"}, "webhook_status_update")
    return {"ok": True, "ticket_no": ticket["ticket_no"], "status": body.status}
