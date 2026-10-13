"""Evaluation harness for the deterministic detectors: labelled golden sets and
seeded canaries used to measure precision, recall and F1 per rule-pack.

Item-level classification: for each golden item we know whether it SHOULD trip the
detector (expected_positive). We run the real detector and compare.
"""
from detectors import scan_secrets, scan_pii, scan_logging_leak, static_code_issues

# Each golden set: list of (text, expected_positive). Fake-but-valid-format values.
GOLDEN_SETS = {
    "secrets": [
        ('AWS_ACCESS_KEY = "AKIAABCDEFGHIJKLMNOP"', True),
        ('OPENAI_KEY = "sk-proj-THISISADEMOFAKEKEYFORSEEDDATAONLY1234567890"', True),
        ('password = "S3cr3tP@ssw0rd123"', True),
        ('google = "AIzaSyA1234567890abcdefghijklmnopqrstuv"', True),
        ('def add(a, b):\n    return a + b', False),
        ('timeout_seconds = 30  # not a secret', False),
        ('log.info("user logged in")', False),
        ('api_endpoint = "https://api.example.com/v1"', False),
    ],
    "india_pii": [
        ('aadhaar = "234567890124"', True),
        ('pan = "AAAPL1234C"', True),
        ('mobile = "9876543210"', True),
        ('card = "4111 1111 1111 1111"', True),
        ('order_id = "ORD-10045"', False),
        ('quantity = 123456789012', False),
        ('note = "call the customer back"', False),
        ('pincode = "560001"', False),
    ],
    "logging_leak": [
        ('logger.info("login user=%s password=%s", u, pw)', True),
        ('logger.debug("issued token=%s", token)', True),
        ('print("card_number", card_number)', True),
        ('logger.info("processing order %s", order_id)', False),
        ('logger.error("db connection failed")', False),
        ('print("done")', False),
    ],
    "static_code": [
        ('try:\n    risky()\nexcept:\n    pass', True),
        ('# TODO: fix this later\nx = 1', True),
        ('eval(user_input)', True),
        ('def clean(a):\n    return a.strip()', False),
        ('if x > 0:\n    return x', False),
    ],
}

# Canaries: known-positive injected flaws used to measure recall only.
CANARIES = {
    "secrets": ['SECRET_TOKEN = "xoxb-123456789012-abcdefghijklmnop"', 'aws_secret = "AKIAZZZZZZZZZZZZZZZZ"'],
    "india_pii": ['gstin = "22AAAPL1234C1ZO"', 'phone = "+91 9123456780"'],
    "logging_leak": ['logger.warning("otp=%s", otp)'],
    "static_code": ['exec(payload)'],
}

_DETECTORS = {
    "secrets": lambda t: scan_secrets(t),
    "india_pii": lambda t: scan_pii(t),
    "logging_leak": lambda t: scan_logging_leak(t),
    "static_code": lambda t: static_code_issues(t),
}

DETECTOR_KEYS = list(_DETECTORS.keys())


def _tripped(detector_key, text) -> bool:
    return len(_DETECTORS[detector_key](text)) > 0


def run_eval(detector_key: str) -> dict:
    """Run the golden set + canaries; return precision/recall/f1 and confusion counts."""
    golden = GOLDEN_SETS.get(detector_key, [])
    tp = fp = tn = fn = 0
    for text, expected in golden:
        got = _tripped(detector_key, text)
        if expected and got:
            tp += 1
        elif expected and not got:
            fn += 1
        elif not expected and got:
            fp += 1
        else:
            tn += 1
    # canaries contribute to recall (all expected positive)
    canary_total = len(CANARIES.get(detector_key, []))
    canary_hit = sum(1 for t in CANARIES.get(detector_key, []) if _tripped(detector_key, t))
    tp += canary_hit
    fn += (canary_total - canary_hit)

    precision = round(tp / (tp + fp), 3) if (tp + fp) else 1.0
    recall = round(tp / (tp + fn), 3) if (tp + fn) else 1.0
    f1 = round(2 * precision * recall / (precision + recall), 3) if (precision + recall) else 0.0
    return {
        "detector": detector_key, "precision": precision, "recall": recall, "f1": f1,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "golden_size": len(golden), "canary_total": canary_total, "canary_recall": round(canary_hit / canary_total, 3) if canary_total else 1.0,
    }
