import re
import uuid
from typing import Dict, Any, List, Optional, Tuple
from app.models.leakage import LeakageExceptionEvidence
from app.services.leakage.evidence_hasher import generate_evidence_fingerprint


class EvidenceValidator:
    """
    Validates cryptographic evidence integrity, prevents cross-tenant leakage,
    and performs PII minimization before bundle assembly.
    """

    # PII Regex Patterns
    EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
    PHONE_PATTERN = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
    ACCOUNT_PATTERN = re.compile(r"\b\d{9,18}\b")

    @classmethod
    def verify_evidence_fingerprint(
        cls,
        evidence: LeakageExceptionEvidence,
        expected_tenant_id: uuid.UUID,
        expected_exception_id: uuid.UUID
    ) -> Tuple[str, Optional[str]]:
        """
        Cryptographically verifies an evidence item's SHA-256 fingerprint and tenancy.
        Returns (status, failure_reason) where status is 'VERIFIED', 'TAMPERED', or 'UNVERIFIED'.
        """
        # 1. Tenancy Guard
        if evidence.tenant_id != expected_tenant_id:
            return "TAMPERED", f"Evidence tenant_id {evidence.tenant_id} does not match expected {expected_tenant_id}"

        # 2. Exception Association Guard
        if evidence.exception_id != expected_exception_id:
            return "TAMPERED", f"Evidence exception_id {evidence.exception_id} does not match expected {expected_exception_id}"

        # 3. Cryptographic Fingerprint Verification
        try:
            computed_fingerprint = generate_evidence_fingerprint(
                evidence_type=evidence.evidence_type,
                entity_type=evidence.entity_type,
                entity_id=evidence.entity_id,
                details=evidence.details or {}
            )
            if computed_fingerprint != evidence.fingerprint_sha256:
                return (
                    "TAMPERED",
                    f"Cryptographic fingerprint mismatch. Stored: {evidence.fingerprint_sha256}, Computed: {computed_fingerprint}"
                )
        except Exception as e:
            return "UNVERIFIED", f"Failed to compute canonical fingerprint: {str(e)}"

        return "VERIFIED", None

    @classmethod
    def redact_pii(cls, val: Any) -> Any:
        """
        Recursively minimizes PII:
        - Replaces email addresses with [REDACTED_EMAIL]
        - Replaces phone numbers with [REDACTED_PHONE]
        - Masks bank account numbers to last 4 digits (e.g. *******1234)
        - Removes password, token, api_key, authorization headers
        """
        if isinstance(val, dict):
            redacted_dict: Dict[str, Any] = {}
            for k, v in val.items():
                k_lower = str(k).lower()
                # Security / Secret Stripping
                if any(secret_term in k_lower for secret_term in ("password", "secret", "token", "authorization", "api_key", "bearer")):
                    redacted_dict[k] = "[REDACTED_SECRET]"
                    continue
                # Specific PII field handling
                if any(email_term in k_lower for email_term in ("email", "mail")):
                    redacted_dict[k] = "[REDACTED_EMAIL]"
                    continue
                if any(phone_term in k_lower for phone_term in ("phone", "mobile", "contact_no")):
                    redacted_dict[k] = "[REDACTED_PHONE]"
                    continue
                if any(name_term in k_lower for name_term in ("customer_name", "user_name", "cardholder_name")):
                    redacted_dict[k] = "[REDACTED_NAME]"
                    continue
                if any(acc_term in k_lower for acc_term in ("account_number", "bank_account", "account_no", "acc_no")):
                    if isinstance(v, str) and len(v) >= 4:
                        redacted_dict[k] = f"*******{v[-4:]}"
                    else:
                        redacted_dict[k] = "[REDACTED_ACCOUNT]"
                    continue

                redacted_dict[k] = cls.redact_pii(v)
            return redacted_dict

        if isinstance(val, list):
            return [cls.redact_pii(item) for item in val]

        if isinstance(val, str):
            # Mask emails
            cleaned = cls.EMAIL_PATTERN.sub("[REDACTED_EMAIL]", val)
            # Mask phones
            cleaned = cls.PHONE_PATTERN.sub("[REDACTED_PHONE]", cleaned)
            return cleaned

        return val
