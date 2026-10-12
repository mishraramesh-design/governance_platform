"""Deterministic, non-LLM detectors: secrets, India PII, logging-leak, static-code heuristics.
Masking: raw sensitive values are never stored/returned - only masked fragments + keyed hashes."""
import os
import re
import hmac
import hashlib

MASK_KEY = os.environ.get("MASKING_KEY", "ivv-governance-platform-mask-key-2026").encode()

SECRET_PATTERNS = [
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("openai_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z\-_]{35}")),
    ("slack_token", re.compile(r"xox[baprs]-[0-9A-Za-z\-]{10,}")),
    ("private_key_block", re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----")),
    ("generic_secret_assignment", re.compile(r"(?:api[_-]?key|secret|password|passwd)\s*[:=]\s*[\"']([A-Za-z0-9_\-/+]{10,})[\"']", re.IGNORECASE)),
    ("sensitive_assignment_unquoted", re.compile(
        r"(?im)^[\s\-]*[A-Za-z0-9_.]*(?:password|passwd|secret|token|api[_-]?key|apikey|jwt|credential|access[_-]?key|private[_-]?key|db[_-]?pass)[A-Za-z0-9_.]*\s*[:=]\s*(?P<val>[^\s#\"'\n]{6,})")),
]

SECRET_PLACEHOLDERS = {"changeme", "change_me", "your_password", "your_secret", "yoursecret",
                       "example", "placeholder", "none", "null", "true", "false", "secret",
                       "password", "token", "xxxxxx", "redacted", "dummy"}


def _unquoted_secret_value(raw_val: str):
    """Resolve the real hardcoded value from an unquoted assignment, or None to skip."""
    v = (raw_val or "").strip().strip(",;")
    if v.startswith("${") or v.startswith("$("):
        if ":-" in v:  # env ref WITH a hardcoded default: ${VAR:-default}
            v = v.split(":-", 1)[1].rstrip("}").strip()
        else:
            return None  # pure env reference, not a hardcoded secret
    if v.startswith(("process.env", "import.meta", "os.environ", "<", "{{")):
        return None
    if len(v) < 6 or v.lower() in SECRET_PLACEHOLDERS:
        return None
    return v

PII_PATTERNS = [
    ("aadhaar", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")),
    ("pan", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    ("gstin", re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z0-9]\b")),
    ("mobile_in", re.compile(r"\b[6-9]\d{9}\b")),
    ("card_number", re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b")),
    ("upi_id", re.compile(r"\b[\w.\-]{2,}@(?:paytm|ybl|upi|ibl|axl|oksbi)\b")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
]

LOGGING_LEAK_PATTERN = re.compile(
    r"(log(?:ger)?\.\w+|print)\s*\([^)]{0,200}(password|passwd|token|secret|aadhaar|pan_no|card_number|otp|cvv)[^)]{0,200}\)",
    re.IGNORECASE,
)


def mask_value(value: str) -> str:
    v = (value or "").strip()
    if len(v) <= 4:
        return "*" * len(v)
    return f"{v[:2]}{'*' * (len(v) - 4)}{v[-2:]}"


def keyed_hash(value: str) -> str:
    return hmac.new(MASK_KEY, (value or "").encode(), hashlib.sha256).hexdigest()[:16]


def scan_secrets(text: str):
    findings = []
    seen = set()
    for label, pattern in SECRET_PATTERNS:
        for m in pattern.finditer(text or ""):
            if label == "sensitive_assignment_unquoted":
                val = _unquoted_secret_value(m.group("val"))
                if not val:
                    continue
                raw = val
            else:
                raw = m.group(0)
            if raw in seen:
                continue
            seen.add(raw)
            findings.append({"type": f"secret:{label}", "masked": mask_value(raw), "hash": keyed_hash(raw), "severity": "critical"})
    return findings


def scan_pii(text: str):
    findings = []
    seen = set()
    for label, pattern in PII_PATTERNS:
        for m in pattern.finditer(text or ""):
            raw = m.group(0)
            if raw in seen:
                continue
            seen.add(raw)
            sev = "high" if label in ("aadhaar", "pan", "card_number", "gstin") else "medium"
            findings.append({"type": f"pii:{label}", "masked": mask_value(raw), "hash": keyed_hash(raw), "severity": sev})
    return findings


def scan_logging_leak(text: str):
    findings = []
    for m in LOGGING_LEAK_PATTERN.finditer(text or ""):
        raw = m.group(0)
        findings.append({"type": "logging_leak", "masked": mask_value(raw)[:48] + "...", "hash": keyed_hash(raw), "severity": "high"})
    return findings


def static_code_issues(text: str):
    issues = []
    t = text or ""
    if re.search(r"TODO|FIXME", t):
        issues.append({"type": "todo_fixme_marker", "severity": "low"})
    if re.search(r"except\s*:\s*\n?\s*pass", t):
        issues.append({"type": "bare_except_swallows_errors", "severity": "medium"})
    if len(t.split("\n")) > 40:
        issues.append({"type": "long_function_heuristic", "severity": "low"})
    if re.search(r"eval\(|exec\(", t):
        issues.append({"type": "dangerous_dynamic_execution", "severity": "high"})
    return issues
