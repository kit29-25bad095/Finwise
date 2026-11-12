class ForensicError(Exception):
    """Base exception for all Phase 5 AI Forensic Investigation errors."""
    pass


class EvidenceIntegrityError(ForensicError):
    """Raised when evidence tampering, fingerprint mismatch, or missing evidence association is detected."""
    pass


class TenantMismatchError(ForensicError):
    """Raised when cross-tenant access to exceptions, runs, or evidence is attempted."""
    pass


class LLMProviderError(ForensicError):
    """Raised when the LLM provider fails, times out, rate limits, or returns malformed output."""
    pass


class InvalidInvestigationStateError(ForensicError):
    """Raised when an operation is invalid for the current investigation state."""
    pass


class ResourceNotFoundError(ForensicError):
    """Raised when a requested exception, run, or evidence record cannot be found."""
    pass
