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

LOG_CALL_PATTERN = re.compile(r"(?:log(?:ger)?\.\w+|console\.\w+|print)\s*\((?P<args>[^)]{0,400})\)", re.IGNORECASE)
LOG_SENSITIVE_RE = re.compile(r"\b(password|passwd|pwd|secret|token|api[_-]?key|apikey|jwt|aadhaar|pan_no|card_number|cardnumber|otp|cvv|ssn|credential|private[_-]?key)\b", re.IGNORECASE)
STRING_LITERAL_RE = re.compile(r"'[^']*'|\"[^\"]*\"|`[^`]*`")
FORMAT_PLACEHOLDER_RE = re.compile(r"%[sdrf]|\{\}|\$\{[^}]+\}|\{[A-Za-z0-9_]+\}")

# Context hints: a 10-digit number near these words is an id/amount, not a mobile.
MOBILE_SKIP_CONTEXT = re.compile(r"\b(id|ids|timestamp|epoch|order|orderid|txn|transaction|count|qty|quantity|amount|price|total|port|seq|sequence|millis|nanos|invoice|ref|reference)\b", re.IGNORECASE)
MOBILE_KEEP_CONTEXT = re.compile(r"\b(mobile|phone|contact|whatsapp|otp|sms|cell|msisdn|tel)\b", re.IGNORECASE)
PAN_FOURTH = set("PCHFATBLJG")

# --- checksum / structural validators ---
_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]
_GSTIN_CODE = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def verhoeff_valid(num: str) -> bool:
    if not num.isdigit():
        return False
    c = 0
    for i, item in enumerate(reversed(num)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(item)]]
    return c == 0


def luhn_valid(num: str) -> bool:
    if not num.isdigit():
        return False
    total, alt = 0, False
    for ch in reversed(num):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def aadhaar_valid(raw: str) -> bool:
    digits = re.sub(r"\s", "", raw)
    return len(digits) == 12 and digits[0] in "23456789" and verhoeff_valid(digits)


def card_valid(raw: str) -> bool:
    digits = re.sub(r"[ -]", "", raw)
    return 13 <= len(digits) <= 19 and luhn_valid(digits)


def pan_valid(raw: str) -> bool:
    return len(raw) == 10 and raw[3] in PAN_FOURTH


def gstin_valid(raw: str) -> bool:
    g = raw.upper()
    if len(g) != 15 or not g[:2].isdigit():
        return False
    if not (1 <= int(g[:2]) <= 38):
        return False
    factor, total = 1, 0
    for ch in g[:14]:
        if ch not in _GSTIN_CODE:
            return False
        v = _GSTIN_CODE.index(ch) * factor
        total += v // 36 + v % 36
        factor = 2 if factor == 1 else 1
    check = (36 - (total % 36)) % 36
    return _GSTIN_CODE[check] == g[14]


def _line_of(text: str, start: int, end: int) -> str:
    ls = text.rfind("\n", 0, start) + 1
    le = text.find("\n", end)
    return text[ls:(le if le != -1 else len(text))]


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
    text = text or ""
    validators = {"aadhaar": aadhaar_valid, "pan": pan_valid, "gstin": gstin_valid, "card_number": card_valid}
    for label, pattern in PII_PATTERNS:
        for m in pattern.finditer(text):
            raw = m.group(0)
            validate = validators.get(label)
            if validate and not validate(raw):
                continue
            if label == "mobile_in":
                line = _line_of(text, m.start(), m.end())
                ctx = re.sub(r"([a-z])([A-Z])", r"\1 \2", re.sub(r"[_\W]+", " ", line))
                if MOBILE_SKIP_CONTEXT.search(ctx) and not MOBILE_KEEP_CONTEXT.search(ctx):
                    continue
            if raw in seen:
                continue
            seen.add(raw)
            sev = "high" if label in ("aadhaar", "pan", "card_number", "gstin") else "medium"
            findings.append({"type": f"pii:{label}", "masked": mask_value(raw), "hash": keyed_hash(raw), "severity": sev})
    return findings


def scan_logging_leak(text: str):
    findings = []
    for m in LOG_CALL_PATTERN.finditer(text or ""):
        args = m.group("args")
        # A sensitive keyword only inside a plain string literal with NO variable is not a leak.
        has_keyword = bool(LOG_SENSITIVE_RE.search(args))
        has_detected_value = bool(scan_secrets(args)) or bool(scan_pii(args))
        outside_strings = STRING_LITERAL_RE.sub("", args)
        has_variable = bool(re.search(r"[A-Za-z_][A-Za-z0-9_.]*", outside_strings))
        has_format = bool(FORMAT_PLACEHOLDER_RE.search(args))
        is_leak = has_detected_value or (has_keyword and (has_variable or has_format))
        if not is_leak:
            continue
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
