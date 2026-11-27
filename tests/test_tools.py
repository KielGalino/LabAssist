"""Tests for core/tools.py - station tools, RBAC, ticket numbering, secrecy."""
import json

from core import db
from core.tools import execute_tool, llm_view, normalize_unit


def test_seeded_stations():
    stations = db.list_stations()
    assert len(stations) == 42
    assert db.get_station("PC-12")["status"] == "locked"
    assert db.get_station("PC-31")["status"] == "needs_repair"
    assert db.get_station("PC-14")["server"] == "MPS-1"
    assert db.get_station("PC-15")["server"] == "MPS-2"
    assert db.get_station("PC-29")["server"] == "MPS-3"


def test_normalize_unit():
    assert normalize_unit("pc 7") == "PC-07"
    assert normalize_unit("PC12") == "PC-12"
    assert normalize_unit("mps2") == "MPS-2"


def test_unlock_request_creates_pending_ticket(student):
    res = execute_tool("request_station_unlock", {"unit": "PC-12", "issue": "still locked"}, student)
    assert res["ok"] and res["data"]["ticket_no"] == "TKT-0001"
    ticket = db.get_ticket("TKT-0001")
    assert ticket["category"] == "Station Access"
    assert ticket["status"] == "pending_approval"
    assert ticket["requester"] == student["user_id"] and ticket["priority"] == "medium"
    assert res["secret"] == {}  # a request never returns a password


def test_unlock_request_for_needs_repair_station(student):
    res = execute_tool("request_station_unlock", {"unit": "PC-31", "issue": "locked"}, student)
    assert not res["ok"] and res["status"] == "needs_repair"
    assert db.list_tickets() == []


def test_unlock_request_unknown_unit(student):
    res = execute_tool("request_station_unlock", {"unit": "PC-99", "issue": "x"}, student)
    assert res["status"] == "not_found"


def test_teacher_unlock_request_is_high_priority(teacher):
    res = execute_tool("request_station_unlock", {"unit": "PC-12", "issue": "class waiting"}, teacher)
    assert res["ok"] and db.get_ticket(res["data"]["ticket_no"])["priority"] == "high"


def test_teacher_report_raises_existing_request_to_high(student, teacher):
    execute_tool("request_station_unlock", {"unit": "PC-12", "issue": "locked"}, student)
    res = execute_tool("request_station_unlock", {"unit": "PC-12", "issue": "class waiting"}, teacher)
    assert res["status"] == "duplicate" and res["data"]["priority"] == "high"
    assert len(db.list_tickets()) == 1


def test_teacher_cannot_unlock_directly(teacher):
    """Teachers cannot unlock; only the admin can."""
    res = execute_tool("unlock_station", {"unit": "PC-12"}, teacher)
    assert not res["ok"] and res["status"] == "denied"
    assert db.get_station("PC-12")["status"] == "locked"


def test_admin_unlock_resolves_request(student, admin):
    execute_tool("request_station_unlock", {"unit": "PC-12", "issue": "locked"}, student)
    res = execute_tool("unlock_station", {"unit": "PC-12"}, admin)
    assert res["ok"] and db.get_station("PC-12")["status"] == "active"
    assert db.get_ticket("TKT-0001")["status"] == "resolved"


def test_admin_can_unlock(admin):
    assert execute_tool("unlock_station", {"unit": "PC-12"}, admin)["ok"]


def test_cannot_unlock_needs_repair_station(admin):
    res = execute_tool("unlock_station", {"unit": "PC-31"}, admin)
    assert not res["ok"] and db.get_station("PC-31")["status"] == "needs_repair"


def test_admin_reset_stores_only_hash(admin):
    res = execute_tool("reset_station_password", {"unit": "PC-05"}, admin)
    pw = res["secret"]["station_password"]
    assert res["ok"] and len(pw) == 10
    station = db.get_station("PC-05")
    assert station["password_hash"] == db.sha256(pw) and pw not in json.dumps(station)
    assert pw not in json.dumps(llm_view(res))
    logs = json.dumps(db.list_action_logs())
    assert pw not in logs


def test_teacher_cannot_reset_password(teacher):
    res = execute_tool("reset_station_password", {"unit": "PC-05"}, teacher)
    assert not res["ok"] and res["status"] == "denied" and res["secret"] == {}


def test_ticket_numbering(student):
    t1 = execute_tool("create_ticket", {"category": "Hardware", "description": "mouse broken",
                                        "unit": "PC-05", "priority": "medium"}, student)
    t2 = execute_tool("create_ticket", {"category": "Printing", "description": "jam",
                                        "unit": "LAB-PRINTER-01", "priority": "high"}, student)
    assert t1["data"]["ticket_no"] == "TKT-0001"
    assert t2["data"]["ticket_no"] == "TKT-0002"


def test_invalid_category_and_priority_are_normalised(student):
    res = execute_tool("create_ticket", {"category": "Coffee", "description": "x",
                                         "unit": "pc-01", "priority": "urgent!!"}, student)
    assert res["data"]["category"] == "Other" and res["data"]["priority"] == "medium"
    assert res["data"]["unit"] == "PC-01"


def test_escalation_creates_escalated_ticket(student):
    res = execute_tool("escalate_to_admin", {"reason": "security", "summary": "someone tried "
                                             "to log in to stations", "priority": "high"}, student)
    assert res["ok"] and db.get_ticket(res["data"]["ticket_no"])["status"] == "escalated"


def test_ticket_number_works_like_a_tracking_number(student, other_student):
    t = execute_tool("create_ticket", {"category": "Hardware", "description": "secret detail",
                                       "unit": "PC-01", "priority": "low"}, other_student)
    res = execute_tool("check_ticket_status", {"ticket_no": t["data"]["ticket_no"]}, student)
    assert res["ok"] and res["data"]["status"] == "open"
    # only non-sensitive fields: no requester, no description
    assert "requester" not in res["data"] and "description" not in res["data"]


def test_every_tool_call_is_logged(student):
    execute_tool("check_ticket_status", {"ticket_no": "TKT-9999"}, student)
    execute_tool("unknown_tool", {}, student)
    tools_logged = [entry["tool"] for entry in db.list_action_logs()]
    assert "check_ticket_status" in tools_logged and "unknown_tool" in tools_logged


def test_duplicate_unlock_request_points_to_existing_ticket(student, other_student):
    first = execute_tool("request_station_unlock", {"unit": "PC-12", "issue": "locked"}, student)
    second = execute_tool("request_station_unlock", {"unit": "PC-12", "issue": "locked"}, other_student)
    assert second["status"] == "duplicate" and second["data"]["ticket_no"] == first["data"]["ticket_no"]
    assert len(db.list_tickets()) == 1


def test_invented_units_are_rejected(student):
    assert execute_tool("create_ticket", {"category": "Hardware", "description": "x", "unit": "PC-99",
                                          "priority": "low"}, student)["status"] == "not_found"
    assert execute_tool("create_ticket", {"category": "Server", "description": "x", "unit": "MPS-7",
                                          "priority": "low"}, student)["status"] == "not_found"
    assert db.list_tickets() == []
