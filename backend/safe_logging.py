"""JSON allow-list logging with deterministic sensitive-text redaction."""
import json
import logging
from datetime import datetime, timezone

from detectors import mask_sensitive_text


class SafeRedactionFilter(logging.Filter):
    """Render then redact before formatting; discard unreviewed exception payloads."""
    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:
            message = "[unrenderable log message]"
        record.msg = mask_sensitive_text(str(message))[0][:4000]
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


class AllowListJsonFormatter(logging.Formatter):
    """Emit only timestamp, severity, logger name and already-redacted message."""
    def format(self, record):
        return json.dumps({
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname[:16],
            "logger": record.name[:160],
            "message": record.msg if isinstance(record.msg, str) else "[non-text log message]",
        }, ensure_ascii=False, separators=(",", ":"))


def configure_safe_logging():
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler()], force=True)
    loggers = [logging.getLogger()]
    loggers.extend(logger for logger in logging.Logger.manager.loggerDict.values()
                   if isinstance(logger, logging.Logger))
    for logger in loggers:
        for handler in logger.handlers:
            if not any(isinstance(item, SafeRedactionFilter) for item in handler.filters):
                handler.addFilter(SafeRedactionFilter())
            handler.setFormatter(AllowListJsonFormatter())


def run_log_canary_test():
    """Self-check the redaction boundary using a synthetic credential canary."""
    import io
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SafeRedactionFilter())
    handler.setFormatter(AllowListJsonFormatter())
    logger = logging.getLogger("governance.log-canary")
    logger.propagate = False
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    canary = "ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    logger.info("token=%s", canary)
    output = stream.getvalue()
    logger.handlers.clear()
    return {"status": "passed" if canary not in output else "failed",
            "canary_absent": canary not in output,
            "output_sha256": __import__("hashlib").sha256(output.encode()).hexdigest(),
            "raw_output_retained": False}
