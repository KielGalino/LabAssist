"""Tests for the optional Jira Cloud integration (core/jira.py) - HTTP is mocked."""
import io
import json

import pytest

from core import config, db, jira
from core.tools import execute_tool


class InlineThread:
    """Runs the 'background' Jira call immediately so the test can check the result."""

    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


@pytest.fixture
def jira_on(monkeypatch):
    monkeypatch.setattr(config, "JIRA_BASE_URL", "https://csis-lab.atlassian.net")
    monkeypatch.setattr(config, "JIRA_EMAIL", "lab.admin@example.com")
    monkeypatch.setattr(config, "JIRA_API_TOKEN", "test-token")
    monkeypatch.setattr(config, "JIRA_PROJECT_KEY", "LAB")
    monkeypatch.setattr(config, "JIRA_SYNC", "urgent")
    monkeypatch.setattr(jira.threading, "Thread", InlineThread)
    sent = []

    def fake_urlopen(req, timeout=10):
        sent.append({"url": req.full_url, "body": json.loads(req.data), "auth": req.headers["Authorization"]})
        return io.BytesIO(json.dumps({"key": f"LAB-{len(sent)}"}).encode())
    monkeypatch.setattr(jira.urllib.request, "urlopen", fake_urlopen)
    return sent


def test_critical_ticket_creates_jira_issue(jira_on, student):
    res = execute_tool("create_ticket", {"category": "Hardware", "description": "smoke from PC-20",
                                         "unit": "PC-20", "priority": "critical"}, student)
    assert len(jira_on) == 1
    body = jira_on[0]["body"]["fields"]
    assert jira_on[0]["url"].endswith("/rest/api/3/issue") and body["project"]["key"] == "LAB"
    assert body["summary"].startswith(f"[{res['data']['ticket_no']}]")
    assert db.get_ticket(res["data"]["ticket_no"])["external_ref"] == "LAB-1"


def test_unlock_request_is_synced_but_low_priority_ticket_is_not(jira_on, student):
    execute_tool("request_station_unlock", {"unit": "PC-12", "issue": "locked"}, student)
    execute_tool("create_ticket", {"category": "Hardware", "description": "scratch", "unit": "PC-01",
                                   "priority": "low"}, student)
    assert len(jira_on) == 1  # only the unlock request (urgent mode)


def test_jira_off_when_not_configured(student, monkeypatch):
    called = []
    monkeypatch.setattr(jira.urllib.request, "urlopen", lambda *a, **k: called.append(1))
    execute_tool("create_ticket", {"category": "Hardware", "description": "x", "unit": "PC-01",
                                   "priority": "critical"}, student)
    assert called == [] and not jira.enabled()


def test_jira_failure_never_breaks_ticketing(jira_on, student, monkeypatch):
    def boom(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(jira.urllib.request, "urlopen", boom)
    res = execute_tool("create_ticket", {"category": "Hardware", "description": "smoke", "unit": "PC-20",
                                         "priority": "critical"}, student)
    assert res["ok"]
    assert any(e["tool"] == "jira_create_issue" and not e["success"] for e in db.list_action_logs())
