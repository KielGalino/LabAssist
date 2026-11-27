"""Safety checks: prompt injection, PII masking, prompt leaks, secret scrubbing."""
import re

from core import config

# 1. Prompt injection
# attempts to override the instructions
OVERRIDE_PATTERNS = [
    # English
    r"ignore\s+(all\s+|any\s+|the\s+|your\s+)?(previous|prior|above|earlier|system)\s+(instructions?|rules?|prompts?)",
    r"disregard\s+(all\s+|the\s+|your\s+)?(previous|prior|above)?\s*(instructions?|rules?)",
    r"forget\s+(all\s+|your\s+|the\s+)?(previous\s+)?(instructions?|rules?)",
    r"(reveal|show|print|display|leak|give me|repeat|output)\s+(me\s+)?(your|the)\s+"
    r"(system\s+|hidden\s+|initial\s+)?(prompt|instructions?)",
    r"system\s+prompt",
    r"\b(you are|you're) now\b",
    r"\bact\s+as\s+(an?\s+|the\s+)?(admin|administrator|root|developer|system|teacher)",
    r"\bpretend\s+(to\s+be|you\s+are)\s+(an?\s+|the\s+)?(admin|administrator|developer|teacher)",
    r"\bi\s+am\s+(the\s+|an?\s+)?(admin|administrator|lab administrator)\b",
    r"\bjail\s*break",
    r"\b(developer|god|sudo|dan)\s+mode\b",
]
# requests for credentials or admin actions
CREDENTIAL_PATTERNS = [
    r"(admin|administrator|router|mikrotik|omada|switch|wi-?fi|server|root)\s+password",
    r"password\s+(of|for|ng)\s+(the\s+)?(admin|router|mikrotik|wi-?fi|server|omada)",
    r"bypass\s+(the\s+)?(web\s+|content\s+|internet\s+)?(filter|firewall|block|security)",
    r"(unblock|disable)\s+(the\s+)?(web\s+|content\s+)?filter",
    r"reset\s+(all|every|lahat\s+ng)\s+(the\s+)?(accounts?|passwords?|users?|stations?)",
    r"unlock\s+(all|every|lahat\s+ng)\s+(the\s+)?(stations?|pcs?|computers?)",
    r"(dump|export|list)\s+(all\s+)?(the\s+)?(user|account|password|hash)(e?s)?\s*(table|database|hashes)?",
    r"\b(api|secret)\s*key\b",
    r"admin\s*pin",
    r"(drop|delete|truncate)\s+table",
]
OVERRIDE_PATTERNS += [
    # Filipino / Taglish
    r"kalimutan\s+(mo\s+)?(na\s+)?(ang|yung|lahat\s+ng)\s+(instructions?|rules?|utos|patakaran)",
    r"(huwag|wag)\s+(mo\s+|mong\s+)?(nang\s+)?(sundin|pansinin)\s+(ang|yung)\s+"
    r"(instructions?|rules?|utos|patakaran)",
    r"(ipakita|sabihin|ibigay)\s+(mo\s+)?(sa\s+akin\s+)?(ang|yung)\s+(system\s+prompt|instructions?|utos\s+mo)",
    r"(magpanggap|kunwari)\s+(ka\s+)?(na\s+)?(ikaw\s+)?(ay\s+)?(admin|administrator|teacher)",
]
INJECTION_PATTERNS = OVERRIDE_PATTERNS + CREDENTIAL_PATTERNS
_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]
_OVERRIDE_RE = [re.compile(p, re.IGNORECASE) for p in OVERRIDE_PATTERNS]

# l33t-speak / disguised characters -> plain letters
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_ZERO_WIDTH = re.compile("[​-‏⁠﻿]")

BLOCKED_REPLY = (
    "Sorry, I can't help with that request. I'm LabAssist, the CSIS ICT Lab helpdesk, "
    "and I can only help with lab IT issues (thin clients, network, printing and similar). "
    "Passwords, filters and system settings are handled only by the Lab Administrator.\n\n"
    "Pasensya na, hindi ko po magagawa iyan. Lab IT concerns lang po ang matutulungan ko."
)


def _variants(text: str) -> list[str]:
    """The message itself plus normalised versions that undo common disguises."""
    plain = _ZERO_WIDTH.sub("", text).lower()
    deleet = plain.translate(_LEET)
    spaced = re.sub(r"[^a-z0-9]+", " ", deleet)  # "ignore_previous-instructions" -> words
    # "i g n o r e" -> "ignore"
    joined = re.sub(r"\b(?:[a-z] ){2,}[a-z]\b", lambda m: m.group().replace(" ", ""), spaced)
    return [text, plain, deleet, spaced, joined]


def _match(text: str, patterns):
    for variant in _variants(text):
        for rx in patterns:
            if rx.search(variant):
                return rx.pattern
    return None


def detect_injection(text: str):
    """Return the matched pattern if the message looks like an attack."""
    return _match(text, _INJECTION_RE)


def detect_instruction_override(text: str):
    """Check uploaded SOPs (only instruction overrides count)."""
    return _match(text, _OVERRIDE_RE)


# phrases only in our system prompt; a reply with one is blocked
_PROMPT_MARKERS = ["ACCESS MODEL", "WORKFLOW (troubleshoot first)", "LAB PROCEDURES (retrieved",
                   "You are LabAssist, the first-level", "Language: decide ONLY"]


def leaks_system_prompt(reply: str) -> bool:
    return any(marker.lower() in reply.lower() for marker in _PROMPT_MARKERS)


# 2. PII redaction (student IDs are kept)
# words after "password is" that are not a password
_NOT_PASSWORDS = (
    r"not|wrong|incorrect|invalid|expired|locked|blocked|correct|already|still|"
    r"forgotten|ayaw|mali|hindi|di|na|the|a|an|reset|changed|working|ok|okay"
)
PII_PATTERNS = [
    # (type, regex, replacement)
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    # PH mobile numbers
    ("phone", re.compile(r"(?<!\d)(?:\+63|0)\s?9\d{2}[\s-]?\d{3}[\s-]?\d{4}(?!\d)"), "[PHONE]"),
    # card numbers (13-16 digits)
    ("card", re.compile(r"(?<![\d-])(?:\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{1,4}|\d{13,16})(?![\d-])"), "[CARD]"),
    # typed passwords
    ("password", re.compile(
        r"(?i)(\b(?:password|passwd|pwd|pass)\b(?:\s+ko)?\s*(?:is|:|=|ay)\s*)"
        rf"(?!(?:{_NOT_PASSWORDS})\b)(\S+)"
    ), r"\1[PASSWORD]"),
]


def redact_pii(text: str):
    """Mask PII. Returns (clean_text, list_of_pii_types_found)."""
    found = []
    for pii_type, rx, repl in PII_PATTERNS:
        text, count = rx.subn(repl, text)
        if count:
            found.append(pii_type)
    return text, found


# 3. Remove the admin PIN / API key from replies
def scrub_secrets(reply: str) -> str:
    if config.LLM_API_KEY and len(config.LLM_API_KEY) > 6:
        reply = reply.replace(config.LLM_API_KEY, "[REDACTED]")
    for pin in (config.ADMIN_PIN,):
        if pin:
            # stand-alone only (keeps TKT-1234)
            reply = re.sub(rf"(?<![\w@-]){re.escape(pin)}(?![\w])", "[REDACTED]", reply)
    return reply
