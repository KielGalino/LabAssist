"""Tests for core/auth.py: roles, admin PIN, lockout, rate limit."""
from core import auth, config, db


def test_identify_needs_only_a_role():
    user, _ = auth.identify("student", "3f9a2c1b")
    assert user == {"user_id": "STUDENT-3f9a2c1b", "full_name": "Student", "role": "student",
                    "section": None}
    assert auth.identify("teacher", "3f9a2c1b")[0]["role"] == "teacher"


def test_identify_rejects_other_roles_and_bad_ids():
    assert auth.identify("admin", "3f9a2c1b")[0] is None      # admin needs the PIN, never a choice
    assert auth.identify("student", "<script>")[0] is None
    assert auth.identify("student", "")[0] is None


def test_new_client_ids_are_random():
    assert auth.new_client_id() != auth.new_client_id()


def test_no_account_tables_exist():
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "users" not in tables and "students" not in tables


def test_admin_pin():
    assert auth.verify_admin_pin("9999")[0] is False
    assert auth.verify_admin_pin("")[0] is False
    assert auth.verify_admin_pin(config.ADMIN_PIN)[0] is True


def test_lockout_after_five_wrong_pins_is_per_client():
    for _ in range(auth.MAX_PIN_FAILURES):
        assert auth.verify_admin_pin("0000", client="pc-a")[0] is False
    ok, reason = auth.verify_admin_pin(config.ADMIN_PIN, client="pc-a")
    assert ok is False and "Too many" in reason
    assert auth.lockout_remaining("pc-a") > 0
    assert auth.verify_admin_pin(config.ADMIN_PIN, client="pc-b")[0] is True


def test_wrong_pins_are_audit_logged_without_the_pin():
    auth.verify_admin_pin("0000")
    logs = db.list_action_logs()
    assert logs[0]["tool"] == "auth_failed" and "0000" not in logs[0]["arguments"]


def test_rate_limit(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 3)
    assert all(auth.allow_message("u1") for _ in range(3))
    assert auth.allow_message("u1") is False
    assert auth.allow_message("u2") is True
