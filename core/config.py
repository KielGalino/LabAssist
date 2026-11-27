"""Settings, read from .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

# project folder
BASE_DIR = Path(__file__).resolve().parent.parent

# load .env (existing env vars win, e.g. in tests)
load_dotenv(BASE_DIR / ".env")


def _float(name: str, default: float) -> float:
    """Read a float from the environment, falling back to a default."""
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


# LLM (OpenAI-compatible endpoint)
# Gemini, Groq or Ollama: change LLM_BASE_URL
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv(
    "LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
).strip()
# fallback list, tried in order
LLM_MODELS = [
    m.strip()
    for m in os.getenv(
        "LLM_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.8-flash"
    ).split(",")
    if m.strip()
]
LLM_TIMEOUT = _float("LLM_TIMEOUT", 30)  # seconds per model attempt
MAX_TOOL_ROUNDS = 4  # max times the LLM may call tools for one message
# stream answers while they are written
LLM_STREAM = os.getenv("LLM_STREAM", "true").strip().lower() not in ("0", "false", "no")
HISTORY_MESSAGES = 6  # how many previous chat messages the LLM sees


def llm_enabled() -> bool:
    """True if we can try the LLM. A local Ollama server needs no real key."""
    is_local = "localhost" in LLM_BASE_URL or "127.0.0.1" in LLM_BASE_URL
    return bool(LLM_API_KEY) or is_local


# Admin and notifications
# only the admin pages need a PIN
ADMIN_PIN = os.getenv("ADMIN_PIN", "1234").strip() or "1234"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
# outgoing webhook for n8n / Make
AUTOMATION_WEBHOOK_URL = os.getenv("AUTOMATION_WEBHOOK_URL", "").strip()
# secret for the incoming webhook
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

# optional Jira Cloud (all four needed)
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").strip()          # https://<site>.atlassian.net
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "").strip()                # Atlassian account email
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "").strip()        # id.atlassian.com > API tokens
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "").strip()    # e.g. LAB
JIRA_ISSUE_TYPE = os.getenv("JIRA_ISSUE_TYPE", "Task").strip() or "Task"
JIRA_SYNC = os.getenv("JIRA_SYNC", "urgent").strip().lower()    # urgent | all

# Abuse protection
RATE_LIMIT_PER_MIN = int(_float("RATE_LIMIT_PER_MIN", 12))  # chat messages per user per minute
MAX_MESSAGE_CHARS = 1000  # longer messages are cut

# Storage paths
# functions so tests can use temp folders
KB_DIR = Path(os.getenv("LABASSIST_KB_DIR", BASE_DIR / "kb"))
DATA_DIR = BASE_DIR / "data"


def db_path() -> Path:
    return Path(os.getenv("LABASSIST_DB", DATA_DIR / "labassist.db"))


def chroma_dir() -> Path:
    return Path(os.getenv("LABASSIST_CHROMA_DIR", DATA_DIR / "chroma"))


# Retrieval tuning
TOP_K = 4  # number of SOP chunks given to the LLM
VECTOR_WEIGHT = 0.5  # hybrid score = 0.5 * vector + 0.5 * BM25
BM25_WEIGHT = 0.5
# relevant if either score reaches its threshold
# (tuned with eval/run_eval.py)
VECTOR_MIN_SCORE = _float("VECTOR_MIN_SCORE", 0.35)
BM25_MIN_SCORE = _float("BM25_MIN_SCORE", 5.5)
