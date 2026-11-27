"""Shared test setup: a temporary database per test, no API key."""
import os
import sys
import tempfile
from pathlib import Path

# set before importing core
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = "https://generativelanguage.googleapis.com/v1beta/openai/"
os.environ["DISCORD_WEBHOOK_URL"] = ""
os.environ["ADMIN_PIN"] = "1234"
os.environ["LABASSIST_CHROMA_DIR"] = tempfile.mkdtemp(prefix="labassist_chroma_")
os.environ["RATE_LIMIT_PER_MIN"] = "1000"  # the rate-limit test lowers it on purpose
os.environ["WEBHOOK_SECRET"] = "test-secret"
os.environ["AUTOMATION_WEBHOOK_URL"] = ""
for _name in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY"):
    os.environ[_name] = ""  # tests never create real Jira issues

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from core import auth, db  # noqa: E402


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Fresh database (42 stations) and fresh limits for every test."""
    monkeypatch.setenv("LABASSIST_DB", str(tmp_path / "test.db"))
    db.init_db()
    auth.reset_limits()
    yield


def make_student(client_id="aaaa1111") -> dict:
    """A student: role + session id."""
    return auth.identify("student", client_id)[0]


@pytest.fixture
def student():
    return make_student()


@pytest.fixture
def other_student():
    return make_student("bbbb2222")


@pytest.fixture
def teacher():
    return auth.identify("teacher", "cccc3333")[0]


@pytest.fixture
def admin():
    return dict(auth.ADMIN_USER)
