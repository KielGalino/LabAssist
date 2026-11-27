"""Tests for api.py - REST endpoints, authentication and the no-password rule."""
import json

import pytest
from fastapi.testclient import TestClient

from api import app
from core import db

STUDENT = {"role": "student", "client_id": "aaaa1111"}
ADMIN = {"X-PIN": "1234"}


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_chat_needs_no_sign_in(client):
    r = client.post("/api/chat", json={**STUDENT, "message": "my monitor has no signal"})
    assert r.status_code == 200 and "SOP-03" in r.json()["sources"]
    assert r.json()["client_id"] == "aaaa1111"
    # no client_id: the server creates one and returns it
    fresh = client.post("/api/chat", json={"message": "my monitor has no signal"}).json()
    assert fresh["client_id"] and fresh["client_id"] != "aaaa1111"
    # only student / teacher can be chosen (admin needs the PIN)
    assert client.post("/api/chat", json={"role": "admin", "message": "hi"}).status_code == 422
    assert client.post("/api/chat", json={"client_id": "<bad>", "message": "hi"}).status_code == 400


def test_cannot_continue_someone_elses_conversation(client):
    conv = client.post("/api/chat", json={**STUDENT, "message": "black screen"}).json()["conversation_id"]
    other = {"role": "student", "client_id": "bbbb2222"}
    r = client.post("/api/chat", json={**other, "message": "hi", "conversation_id": conv})
    assert r.status_code == 403


def test_full_unlock_workflow_over_api(client):
    r = client.post("/api/chat", json={**STUDENT, "message": "I waited 15 minutes and PC-12 is still locked"})
    ticket_no = r.json()["actions"][0]["data"]["ticket_no"]
    assert all("secret" not in a for a in r.json()["actions"])
    # without the admin PIN nobody can approve
    assert client.post(f"/api/tickets/{ticket_no}/actions", json={"action": "unlock"}).status_code == 401
    ok = client.post(f"/api/tickets/{ticket_no}/actions", json={"action": "unlock"}, headers=ADMIN)
    assert ok.status_code == 200 and db.get_station("PC-12")["status"] == "active"
    status = client.get(f"/api/tickets/{ticket_no}").json()
    assert status["status"] == "resolved"


def test_password_reset_is_not_available_over_api(client):
    client.post("/api/chat", json={**STUDENT, "message": "I waited 15 minutes and PC-12 is still locked"})
    r = client.post("/api/tickets/TKT-0001/actions", json={"action": "reset"}, headers=ADMIN)
    assert r.status_code == 422  # "reset" is not an allowed action in the API


def test_staff_endpoints_need_sign_in(client):
    assert client.get("/api/stations").status_code == 401
    assert client.get("/api/stations", headers={"X-PIN": "0000"}).status_code == 401
    stations = client.get("/api/stations", headers=ADMIN).json()
    assert len(stations) == 42 and all("password_hash" not in s for s in stations)
    assert client.get("/api/metrics").status_code == 401
    assert "kpis" in client.get("/api/metrics", headers=ADMIN).json()


def test_ticket_lookup_shows_only_public_fields(client):
    client.post("/api/chat", json={**STUDENT, "message": "I waited 15 minutes and PC-12 is still locked"})
    t = client.get("/api/tickets/TKT-0001").json()
    assert t["status"] == "pending_approval"
    assert "requester" not in t and "description" not in t
    assert client.get("/api/tickets/TKT-9999").status_code == 404


def test_incoming_webhook_requires_secret(client):
    client.post("/api/chat", json={**STUDENT, "message": "I waited 15 minutes and PC-12 is still locked"})
    body = {"ticket_no": "TKT-0001", "status": "in_progress"}
    assert client.post("/api/webhooks/ticket-status", json=body,
                       headers={"X-Webhook-Secret": "wrong"}).status_code == 401
    ok = client.post("/api/webhooks/ticket-status", json=body, headers={"X-Webhook-Secret": "test-secret"})
    assert ok.status_code == 200 and db.get_ticket("TKT-0001")["status"] == "in_progress"


def test_kb_search(client):
    r = client.post("/api/kb/search", json={"query": "paano mag-print"}).json()
    assert r["relevant"] and r["results"][0]["sop_id"] == "SOP-09"


def test_chat_stream_sends_tokens_then_result(client):
    with client.stream("POST", "/api/chat/stream",
                       json={**STUDENT, "message": "I waited 15 minutes and PC-12 is still locked"}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert "event: token" in body and "event: done" in body
    done = json.loads(body.split("event: done\ndata: ")[1].split("\n\n")[0])
    assert done["resolution"] == "ticket" and done["intent"] == "station_access"
    assert all("secret" not in a for a in done["actions"])


def test_chat_stream_rejects_invalid_client_id(client):
    r = client.post("/api/chat/stream", json={"client_id": "!!", "role": "student",
                                               "message": "hi"})
    assert r.status_code == 400


def test_widget_and_embed_script_are_served(client):
    assert "CSIS ICT Laboratory Helpdesk" in client.get("/widget").text
    assert "iframe" in client.get("/static/embed.js").text
    assert client.get("/assets/csis-logo.png").status_code == 200
    portal = client.get("/portal").text
    assert "ICT Laboratory Portal" in portal and "/static/embed.js" in portal
