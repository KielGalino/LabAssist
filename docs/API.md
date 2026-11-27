# LabAssist - REST API Specification

Base URL: `http://localhost:8000` (start with `run_api.bat` or
`.venv\Scripts\python.exe -m uvicorn api:app --port 8000`).

Interactive documentation (OpenAPI / Swagger UI): **http://localhost:8000/docs**.
The machine-readable spec is at `/openapi.json`.

## Authentication

| Caller | How |
|---|---|
| Student / teacher | No sign-in. Send `role` (`student` or `teacher`) and `client_id` (random id of the browser session) in the chat body. Without a `client_id` the server creates one and returns it; send it with the next messages. |
| Lab Administrator | Header `X-PIN: <ADMIN_PIN>` |
| External system | Header `X-Webhook-Secret: <WEBHOOK_SECRET>` (incoming webhook only) |

Five wrong admin PINs lock that client for five minutes (HTTP 401 with "Too many wrong PINs").
Chat messages are limited to 12 per user per minute and 1,000 characters.

**Station password resets are not available through the API.** A new password is shown only
once on the Admin Dashboard and never appears in any HTTP response.

## Endpoints

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/api/health` | anyone | Service status, LLM mode, search index |
| POST | `/api/chat` | anyone (no sign-in) | Send a message, get the complete answer |
| POST | `/api/chat/stream` | anyone (no sign-in) | Same, but the answer is streamed (Server-Sent Events) |
| GET | `/api/tickets/{ticket_no}` | anyone with the number | Ticket status (public fields only) |
| GET | `/api/tickets?status=pending_approval` | admin | List tickets |
| POST | `/api/tickets/{ticket_no}/actions` | admin | `unlock`, `resolve` or `reject` a request |
| GET | `/api/stations` | admin | 42 stations with status (no password hashes) |
| GET | `/api/metrics` | admin | KPIs and LLM observability |
| POST | `/api/kb/search` | anyone | Hybrid retrieval test |
| POST | `/api/webhooks/ticket-status` | external system | Update a ticket status |
| GET | `/widget` | anyone | Embeddable chat widget page |
| GET | `/static/embed.js` | anyone | One-line embed script for other websites |

## Streaming (`/api/chat/stream`)

Same request body as `/api/chat`. The response is `text/event-stream`:

```
event: token
data: {"text": "1. Do not type any password and do not try to guess it.\n"}

event: token
data: {"text": "2. Raise your hand and ask your teacher to log the station in.\n"}

event: done
data: {"conversation_id": 3, "reply": "...", "resolution": "answered", "intent": "station_access", ...}
```

Each `token` piece has already passed the output guard (PII masked, secrets scrubbed, prompt
leaks stopped). The `done` event has the same fields as the `/api/chat` response.

## Chat widget

Add one line to any web page:

```html
<script src="http://<labassist-server>:8000/static/embed.js"></script>
```

A "Lab Helpdesk" button appears in the bottom-right corner and opens the widget (`/widget`).
Users choose Student or Teacher (no sign-in), then chat; answers stream live. The widget uses
`/api/chat/stream`, so every guardrail, rate limit and ticket rule applies.
A full example page is `GET /portal` (sample CSIS ICT Laboratory portal with the widget embedded).
A demo page is at `http://localhost:8000/static/embed-demo.html`.

## Examples (PowerShell)

Chat as a student:

```powershell
$body = @{ role = "student"; client_id = "demo1234"; message = "I waited 15 minutes and PC-12 is still locked" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/chat -ContentType "application/json" -Body $body
```

Response (shortened):

```json
{
  "conversation_id": 1,
  "reply": "Unlock request TKT-0001 has been filed for PC-12 (priority: medium, status: Pending approval). ...",
  "resolution": "ticket",
  "category": "Station Access",
  "sources": ["SOP-01", "SOP-02"],
  "actions": [{"tool": "request_station_unlock", "ok": true, "status": "success",
               "data": {"ticket_no": "TKT-0001", "unit": "PC-12", "status": "pending_approval"}}],
  "pii_masked": [],
  "latency_ms": 2100,
  "model": "gemini-3.5-flash-lite"
}
```

Approve the request as the Lab Administrator:

```powershell
$h = @{ "X-PIN" = "1234" }
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/tickets/TKT-0001/actions -Headers $h -ContentType "application/json" -Body '{"action":"unlock"}'
```

Check the status (anyone with the ticket number):

```powershell
Invoke-RestMethod "http://localhost:8000/api/tickets/TKT-0001"
```

Incoming webhook from an automation tool:

```powershell
$h = @{ "X-Webhook-Secret" = "<WEBHOOK_SECRET from .env>" }
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/webhooks/ticket-status -Headers $h -ContentType "application/json" -Body '{"ticket_no":"TKT-0002","status":"in_progress"}'
```

## Error codes

| Code | Meaning |
|---|---|
| 401 | Unknown student / wrong PIN / locked out / bad webhook secret |
| 403 | Signed in but not allowed (e.g. teacher calling an admin action, student reading another student's ticket) |
| 404 | Ticket not found |
| 400 | Action not possible (e.g. unlocking a station marked for repair) |
| 422 | Invalid body (e.g. action "reset", message longer than 1,000 characters) |
| 503 | Incoming webhooks disabled (no WEBHOOK_SECRET) |

## Outgoing automation webhook

When `AUTOMATION_WEBHOOK_URL` is set, LabAssist POSTs JSON like this (no passwords, ever):

```json
{
  "event": "unlock.requested",
  "source": "labassist",
  "timestamp": "2026-11-23T20:46:24",
  "data": {"ticket_no": "TKT-0001", "unit": "PC-12", "requester": "STUDENT-demo1234", "section": null}
}
```

Events: `ticket.created`, `ticket.escalated`, `unlock.requested`, `station.unlocked`,
`station.password_reset`, `ticket.status_changed`. In n8n, use a **Webhook** trigger node with this
URL, then e.g. a **Jira** node to create an issue for critical tickets.

## Direct Jira Cloud integration (optional)

Set `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` and `JIRA_PROJECT_KEY` in `.env` (free Jira
plan). New tickets are then created as Jira issues through Jira's REST API v3
(`POST /rest/api/3/issue`), and the Jira key (e.g. `LAB-12`) is saved in the ticket's
`external_ref` column (visible in the Admin Dashboard ticket table). `JIRA_SYNC=urgent` (default)
syncs only high/critical tickets, escalations and unlock requests; `JIRA_SYNC=all` syncs every
ticket. To send Jira status changes back, create a Jira Automation rule "When issue transitioned ->
Send web request" to `/api/webhooks/ticket-status` with the `X-Webhook-Secret` header.
Jira errors are logged in the audit log and never stop the helpdesk.
