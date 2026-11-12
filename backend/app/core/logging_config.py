import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict


REDACTED_PATTERNS = [
    (re.compile(r"Bearer\s+[A-Za-z0-9\-_\.]+", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"(password|secret|key|api_key|token)\s*[:=]\s*['\"]?[^\s,'\"]+['\"]?", re.IGNORECASE), r"\1=[REDACTED]"),
    (re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"), "[REDACTED_CARD_NUMBER]"),
    (re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"), "[REDACTED_IFSC]"),
]


def redact_sensitive_data(message: str) -> str:
    """
    Scrubs JWT tokens, API keys, passwords, card numbers, and IFSC codes from log strings.
    """
    result = message
    for pattern, replacement in REDACTED_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


class JSONFormatter(logging.Formatter):
    """
    Structured JSON log formatter for production log aggregation (CloudWatch, Datadog, ELK).
    """

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive_data(record.getMessage()),
            "module": record.module,
            "line": record.lineno,
        }

        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj)


def configure_production_logging(log_level: int = logging.INFO) -> None:
    """
    Sets up structured JSON logging for the application.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)
