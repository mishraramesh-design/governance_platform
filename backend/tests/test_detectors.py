"""Unit tests for the hardened deterministic detectors (checksum/structural
validation + context-aware logging-leak detection)."""
import detectors as D


def _types(findings):
    return {f["type"] for f in findings}


# ---------- Aadhaar / Verhoeff ----------
def test_aadhaar_valid_verhoeff_detected():
    assert "pii:aadhaar" in _types(D.scan_pii('aadhaar = "234567890124"'))


def test_aadhaar_invalid_verhoeff_not_detected():
    # correct length & first digit but Verhoeff checksum fails
    assert D.verhoeff_valid("234567890123") is False
    assert "pii:aadhaar" not in _types(D.scan_pii('aadhaar = "234567890123"'))


def test_order_id_not_flagged_as_aadhaar():
    assert D.scan_pii("order_id = 123456789012") == []


# ---------- Card / Luhn ----------
def test_card_valid_luhn_detected():
    assert "pii:card_number" in _types(D.scan_pii('card = "4111 1111 1111 1111"'))


def test_card_invalid_luhn_not_detected():
    assert D.luhn_valid("1111111111111111") is False
    assert "pii:card_number" not in _types(D.scan_pii("card = 1111 1111 1111 1111"))


def test_repeated_ones_no_card_no_aadhaar():
    findings = D.scan_pii("x = 1111 1111 1111 1111")
    assert findings == []


# ---------- PAN ----------
def test_pan_valid_fourth_char():
    assert "pii:pan" in _types(D.scan_pii('pan = "AAAPL1234C"'))


def test_pan_invalid_fourth_char_rejected():
    # 4th char 'D' not in [PCHFATBLJG]
    assert D.pan_valid("ABCDE1234F") is False
    assert "pii:pan" not in _types(D.scan_pii('pan = "ABCDE1234F"'))


# ---------- GSTIN ----------
def test_gstin_valid():
    assert "pii:gstin" in _types(D.scan_pii('gstin = "22AAAPL1234C1ZO"'))


def test_gstin_bad_state_code_rejected():
    assert D.gstin_valid("99AAAPL1234C1ZO") is False


# ---------- Mobile ----------
def test_mobile_detected_with_phone_context():
    assert "pii:mobile_in" in _types(D.scan_pii('mobile = "9876543210"'))


def test_mobile_ignored_in_id_context():
    assert "pii:mobile_in" not in _types(D.scan_pii("order_id = 9876543210"))
    assert "pii:mobile_in" not in _types(D.scan_pii("timestamp = 9876543210"))


def test_mobile_ignored_when_part_of_longer_run():
    assert "pii:mobile_in" not in _types(D.scan_pii("x = 98765432100000"))


# ---------- Logging leak ----------
def test_logging_leak_plain_string_no_variable_not_flagged():
    assert D.scan_logging_leak('logger.debug("password reset for user")') == []


def test_logging_leak_with_variable_flagged():
    assert len(D.scan_logging_leak('logger.info("login user=%s password=%s", u, pw)')) == 1
    assert len(D.scan_logging_leak('logger.debug("issued token=%s", token)')) == 1
    assert len(D.scan_logging_leak('print("card_number", card_number)')) == 1


def test_logging_non_sensitive_not_flagged():
    assert D.scan_logging_leak('logger.info("processing order %s", order_id)') == []
    assert D.scan_logging_leak('logger.error("db connection failed")') == []
