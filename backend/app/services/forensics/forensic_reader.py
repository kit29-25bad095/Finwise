import uuid
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, desc

from app.models.leakage import (
    LeakageException,
    LeakageRunException,
    LeakageExceptionEvidence,
    LeakageRunEvidence,
    LeakageDetectionRun,
    LeakageExceptionReview,
)
from app.models.canonical import (
    CanonicalOrder,
    CanonicalPayment,
    CanonicalSettlement,
    CanonicalRefund,
    CanonicalBankTransaction,
)
from app.models.reconciliation import FeeContract, FeeScheduleTier
from app.services.forensics.exceptions import ResourceNotFoundError, TenantMismatchError


class LeakageForensicReader:
    """
    Dedicated read-only data access layer for Phase 5 AI Forensic Investigation.
    Enforces strict tenant isolation and prevents any mutation of financial or exception state.
    """

    @staticmethod
    def get_exception(
        db: Session,
        tenant_id: uuid.UUID,
        exception_id: uuid.UUID
    ) -> LeakageException:
        """
        Retrieves a leakage exception strictly scoped to the requesting tenant.
        """
        stmt = select(LeakageException).where(
            and_(
                LeakageException.id == exception_id,
                LeakageException.tenant_id == tenant_id
            )
        )
        exc = db.execute(stmt).scalar_one_or_none()
        if not exc:
            # Check if exception exists under a different tenant to avoid leaking details
            # but raise clean ResourceNotFoundError
            raise ResourceNotFoundError(f"Leakage exception {exception_id} not found.")
        return exc

    @staticmethod
    def get_detection_run(
        db: Session,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID
    ) -> LeakageDetectionRun:
        """
        Retrieves a detection run strictly scoped to the requesting tenant.
        """
        stmt = select(LeakageDetectionRun).where(
            and_(
                LeakageDetectionRun.id == run_id,
                LeakageDetectionRun.tenant_id == tenant_id
            )
        )
        run = db.execute(stmt).scalar_one_or_none()
        if not run:
            raise ResourceNotFoundError(f"Detection run {run_id} not found.")
        return run

    @staticmethod
    def get_run_snapshot(
        db: Session,
        tenant_id: uuid.UUID,
        exception_id: uuid.UUID,
        detection_run_id: uuid.UUID
    ) -> Optional[LeakageRunException]:
        """
        Retrieves the immutable point-in-time snapshot of an exception for a specific run.
        """
        stmt = select(LeakageRunException).where(
            and_(
                LeakageRunException.exception_id == exception_id,
                LeakageRunException.detection_run_id == detection_run_id,
                LeakageRunException.tenant_id == tenant_id
            )
        )
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def get_evidence_for_run(
        db: Session,
        tenant_id: uuid.UUID,
        exception_id: uuid.UUID,
        detection_run_id: uuid.UUID
    ) -> List[LeakageExceptionEvidence]:
        """
        Retrieves all evidence associated with an exception evaluated during a specific run.
        Uses the LeakageRunEvidence junction table with fallback to direct exception evidence.
        """
        # First attempt: join via LeakageRunEvidence junction table
        junction_stmt = (
            select(LeakageExceptionEvidence)
            .join(
                LeakageRunEvidence,
                LeakageRunEvidence.evidence_id == LeakageExceptionEvidence.id
            )
            .where(
                and_(
                    LeakageExceptionEvidence.exception_id == exception_id,
                    LeakageExceptionEvidence.tenant_id == tenant_id,
                    LeakageRunEvidence.detection_run_id == detection_run_id,
                    LeakageRunEvidence.tenant_id == tenant_id
                )
            )
            .order_by(LeakageExceptionEvidence.created_at)
        )
        evidence_items = list(db.execute(junction_stmt).scalars().all())

        if evidence_items:
            return evidence_items

        # Fallback: direct exception evidence items scoped to the exception and tenant
        fallback_stmt = (
            select(LeakageExceptionEvidence)
            .where(
                and_(
                    LeakageExceptionEvidence.exception_id == exception_id,
                    LeakageExceptionEvidence.tenant_id == tenant_id
                )
            )
            .order_by(LeakageExceptionEvidence.created_at)
        )
        return list(db.execute(fallback_stmt).scalars().all())

    @staticmethod
    def get_reviewer_history(
        db: Session,
        tenant_id: uuid.UUID,
        exception_id: uuid.UUID
    ) -> List[LeakageExceptionReview]:
        """
        Retrieves immutable audit trail of human lifecycle reviews for an exception.
        """
        stmt = (
            select(LeakageExceptionReview)
            .where(
                and_(
                    LeakageExceptionReview.exception_id == exception_id,
                    LeakageExceptionReview.tenant_id == tenant_id
                )
            )
            .order_by(desc(LeakageExceptionReview.created_at))
        )
        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def get_canonical_record(
        db: Session,
        tenant_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID
    ) -> Optional[Any]:
        """
        Reads a related canonical entity when explicitly referenced in evidence.
        Supported entities: canonical_orders, canonical_payments, canonical_settlements,
        canonical_refunds, canonical_bank_transactions.
        """
        mapping = {
            "canonical_orders": CanonicalOrder,
            "canonical_payments": CanonicalPayment,
            "canonical_settlements": CanonicalSettlement,
            "canonical_refunds": CanonicalRefund,
            "canonical_bank_transactions": CanonicalBankTransaction,
        }
        model = mapping.get(entity_type.lower())
        if not model:
            return None

        stmt = select(model).where(
            and_(
                model.id == entity_id,
                model.tenant_id == tenant_id
            )
        )
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def get_fee_contract(
        db: Session,
        tenant_id: uuid.UUID,
        contract_id: uuid.UUID
    ) -> Optional[FeeContract]:
        """
        Reads fee contract metadata for contractual fee overcharge explanations.
        """
        stmt = select(FeeContract).where(
            and_(
                FeeContract.id == contract_id,
                FeeContract.tenant_id == tenant_id
            )
        )
        return db.execute(stmt).scalar_one_or_none()
