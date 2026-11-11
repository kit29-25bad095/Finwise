import uuid
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple, NamedTuple


class RowQualityStatus:
    VALID = "VALID"
    WARNING = "WARNING"
    INVALID = "INVALID"
    DUPLICATE = "DUPLICATE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class RowErrorDetail(NamedTuple):
    row_index: int
    error_level: str  # ERROR, WARNING, DUPLICATE
    field_name: Optional[str]
    raw_value: Optional[str]
    error_code: str
    message: str
    raw_record: Dict[str, Any]


class ParsedRowResult(NamedTuple):
    status: str  # VALID, WARNING, INVALID, DUPLICATE, NEEDS_REVIEW
    entity: Optional[Any]  # The Canonical Model instance (e.g. CanonicalOrder)
    errors: List[RowErrorDetail]


class BaseAdapter(ABC):
    """
    Abstract adapter for vendor financial CSV transformations into canonical models.
    """
    source_type: str

    @abstractmethod
    def validate_headers(self, headers: List[str]) -> Tuple[bool, List[str]]:
        """
        Validates whether required headers are present.
        Returns (is_valid, list_of_missing_headers).
        """
        pass

    @abstractmethod
    def parse_row(
        self,
        row_dict: Dict[str, Any],
        row_index: int,
        tenant_id: uuid.UUID,
        batch_id: uuid.UUID
    ) -> ParsedRowResult:
        """
        Normalizes a single CSV row dictionary into a canonical model instance.
        """
        pass
