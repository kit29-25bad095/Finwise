import uuid
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from sqlalchemy.orm import Session

from app.models.leakage import DetectorType, LeakageExceptionType, ExceptionSeverity


@dataclass
class EvidenceItemDraft:
    evidence_type: str
    entity_type: str
    entity_id: uuid.UUID
    source_batch_id: Optional[uuid.UUID] = None
    source_row_index: Optional[int] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LeakageFinding:
    detector_type: DetectorType
    exception_type: LeakageExceptionType
    severity: ExceptionSeverity
    severity_reason: str
    source_entity_type: str
    source_entity_id: uuid.UUID
    source_reference: str
    order_reference: Optional[str]
    gateway_name: str
    expected_amount: Decimal
    actual_amount: Decimal
    leakage_amount: Decimal
    recoverable_amount: Decimal
    currency: str
    calculation_breakdown: Dict[str, Any]
    explanation: str
    evidence_items: List[EvidenceItemDraft] = field(default_factory=list)
    contract_id: Optional[uuid.UUID] = None
    contract_version: Optional[int] = None
    detector_version: str = "1.0.0"
    rule_version: str = "FINORA-DETECTORS-V3"


class BaseLeakageDetector(ABC):
    """
    Abstract Base Class for Deterministic Revenue Leakage Detectors.
    Every detector runs within a tenant boundary, uses pure Decimal arithmetic,
    and returns strongly-typed, verifiable LeakageFinding objects with evidence.
    """

    @abstractmethod
    def detect(
        self,
        db: Session,
        tenant_id: uuid.UUID,
        parameters: Optional[Dict[str, Any]] = None
    ) -> List[LeakageFinding]:
        """
        Executes detector logic against canonical financial entities and contracts.
        """
        pass
