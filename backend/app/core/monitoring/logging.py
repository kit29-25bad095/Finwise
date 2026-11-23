import re
import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class SensitiveDataRedactor:
    """
    Scrubs sensitive customer PII, cryptographic credentials, bank account numbers,
    and confidential financial statements from log streams and error reports.
    """

    # 1. API Keys and Tokens
    API_KEY_REGEX = re.compile(r"AIza[0-9A-Za-z-_]{20,45}", re.IGNORECASE)
    BEARER_TOKEN_REGEX = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.]{20,}")

    # 2. Key-Value Credential Pairs (password, secret_key, api_key, etc.)
    CREDENTIAL_REGEX = re.compile(
        r"(?i)(password|secret_key|secret|token|api_key|client_secret|postgres_password|redis_password)\s*[:=]\s*['\"]?[^\s,'\"}]+['\"]?"
    )

    # 3. Bank Account Numbers (9 to 18 digits)
    BANK_ACCOUNT_LABEL_REGEX = re.compile(
        r"(?i)(account[_\s]?no|account[_\s]?number|acc[_\s]?no|bank[_\s]?account|beneficiary[_\s]?account)\s*[:=]?\s*['\"]?\d{9,18}['\"]?"
    )
    STANDALONE_BANK_ACC_REGEX = re.compile(r"\b\d{11,18}\b")

    # 4. Customer PII (Email & Indian 10-digit Mobile Numbers)
    EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
    PHONE_REGEX = re.compile(r"(?:(?:\+91|91|0)[\-\s]?)?[6-9]\d{9}\b")

    # 5. Raw Financial CSV/TSV Document Dumps
    CSV_DUMP_REGEX = re.compile(
        r"(?:Shopify,Order|order_id,line_item|Narration,Chq/Ref|HDFC,Statement|Razorpay,Payment).*?(?:\n.*?){2,}",
        re.DOTALL | re.IGNORECASE
    )

    @classmethod
    def redact(cls, text: Any) -> str:
        if not isinstance(text, str):
            text = str(text)

        # 1. Redact CSV file dumps first
        text = cls.CSV_DUMP_REGEX.sub("[REDACTED_CONFIDENTIAL_CSV_DATA]", text)

        # 2. Redact API keys and bearer tokens
        text = cls.API_KEY_REGEX.sub("[REDACTED_API_KEY]", text)
        text = cls.BEARER_TOKEN_REGEX.sub(r"\1[REDACTED_BEARER_TOKEN]", text)

        # 3. Redact key-value credentials
        text = cls.CREDENTIAL_REGEX.sub(r"\1=[REDACTED_SECRET]", text)

        # 4. Redact bank account numbers
        text = cls.BANK_ACCOUNT_LABEL_REGEX.sub(r"\1=[REDACTED_BANK_ACCOUNT]", text)

        # 5. Redact PII (Email and Phone)
        text = cls.EMAIL_REGEX.sub("[REDACTED_EMAIL]", text)
        text = cls.PHONE_REGEX.sub("[REDACTED_PHONE]", text)

        return text


class StructuredJsonFormatter(logging.Formatter):
    """
    Outputs structured JSON log records compatible with ELK, Datadog, CloudWatch,
    and OpenTelemetry collectors, enforcing automatic PII/secret scrubbing.
    """

    def __init__(self, service_name: str = "finora-backend", environment: str = "production"):
        super().__init__()
        self.service_name = service_name
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        # Extract base record message
        raw_message = record.getMessage()
        safe_message = SensitiveDataRedactor.redact(raw_message)

        log_payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": safe_message,
            "service": self.service_name,
            "environment": self.environment,
            "caller": f"{record.module}:{record.funcName}:{record.lineno}",
        }

        # Include request correlation ID if available
        if hasattr(record, "correlation_id") and record.correlation_id:
            log_payload["correlation_id"] = str(record.correlation_id)

        # Include tenant ID if available
        if hasattr(record, "tenant_id") and record.tenant_id:
            log_payload["tenant_id"] = str(record.tenant_id)

        # Include additional structured extra fields
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            safe_extra = {
                k: SensitiveDataRedactor.redact(v) if isinstance(v, str) else v
                for k, v in record.extra_data.items()
            }
            log_payload["data"] = safe_extra

        # Format and redact exception tracebacks
        if record.exc_info:
            raw_trace = "".join(traceback.format_exception(*record.exc_info))
            safe_trace = SensitiveDataRedactor.redact(raw_trace)
            log_payload["exception"] = safe_trace

        return json.dumps(log_payload)


def configure_structured_logging(level: int = logging.INFO, environment: str = "production"):
    """Configures the root and application loggers to emit structured JSON logs."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to prevent duplicate outputs
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(StructuredJsonFormatter(environment=environment))
    root_logger.addHandler(console_handler)

    # Quieten excessively verbose third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("passlib").setLevel(logging.WARNING)
