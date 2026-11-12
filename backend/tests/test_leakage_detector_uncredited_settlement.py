import uuid
from decimal import Decimal
from datetime import datetime, date, timezone, timedelta
import pytest
from sqlalchemy.orm import Session

from app.models.ingestion import IngestionBatch, IngestionStatus
from app.models.canonical import CanonicalSettlement, CanonicalBankTransaction
from app.models.leakage import DetectorType, LeakageExceptionType, ExceptionSeverity
from app.services.leakage.uncredited_settlement_detector import UncreditedSettlementDetector


def seed_batch(db_session: Session, tenant_id: uuid.UUID) -> IngestionBatch:
    batch = IngestionBatch(
        tenant_id=tenant_id,
        source_type="RAZORPAY",
        filename="settlements.csv",
        file_hash_sha256="dummyhash_uncredited",
        file_size_bytes=1024,
        total_rows=10,
        valid_rows=10,
        status=IngestionStatus.COMPLETED
    )
    db_session.add(batch)
    db_session.flush()
    return batch


def test_uncredited_settlement_detector_complete_statement_missing_credit(db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    # Settlement 7 days ago
    settle_date = date(2026, 11, 2)
    settlement = CanonicalSettlement(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        settlement_reference="SETL-UNCRED-001",
        utr_number="HDFC00192847291",
        gross_amount=Decimal("51000.0000"),
        total_fee=Decimal("1000.0000"),
        total_tax=Decimal("180.0000"),
        net_settlement_amount=Decimal("49820.0000"),
        unallocated_balance=Decimal("49820.0000"),
        status="settled",
        settled_at=datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc),
    )

    # Bank statement exists covering through Nov 10 (well past clearing window Nov 3)
    bank_tx = CanonicalBankTransaction(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        bank_name="HDFC",
        bank_reference="REF_UNRELATED",
        raw_narration="OTHER CUSTOMER CREDIT",
        transaction_date=date(2026, 11, 10),
        credit_amount=Decimal("5000.0000"),
        unallocated_balance=Decimal("5000.0000")
    )
    db_session.add_all([settlement, bank_tx])
    db_session.commit()

    detector = UncreditedSettlementDetector()
    findings = detector.detect(
        db_session,
        tenant_id,
        parameters={"as_of_date": date(2026, 11, 10), "bank_clearing_window_days": 1}
    )

    assert len(findings) == 1
    f = findings[0]
    assert f.detector_type == DetectorType.UNCREDITED_SETTLEMENT
    assert f.exception_type == LeakageExceptionType.UNCREDITED_SETTLEMENT
    assert f.leakage_amount == Decimal("49820.0000")
    assert f.recoverable_amount == Decimal("49820.0000")
    assert f.source_reference == "SETL-UNCRED-001"
    assert f.severity in (ExceptionSeverity.CRITICAL, ExceptionSeverity.HIGH)
    assert len(f.evidence_items) == 1
    assert f.evidence_items[0].evidence_type == "SETTLEMENT_BATCH"


def test_uncredited_settlement_detector_statement_gap_defense(db_session: Session, seeded_entities: dict):
    """
    If uploaded bank statements do NOT cover the settlement clearing date,
    financial recovery claim must be suppressed (evidence pending statement gap).
    """
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    # Settlement on Nov 8 with expected clearing Nov 9
    settle_date = date(2026, 11, 8)
    settlement = CanonicalSettlement(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=2,
        gateway_name="RAZORPAY",
        settlement_reference="SETL-GAP-002",
        utr_number="HDFC00998877665",
        gross_amount=Decimal("30000.0000"),
        net_settlement_amount=Decimal("29400.0000"),
        unallocated_balance=Decimal("29400.0000"),
        status="settled",
        settled_at=datetime(2026, 11, 8, 14, 0, tzinfo=timezone.utc),
    )

    # Bank statement ONLY uploaded up to Nov 5!
    bank_tx = CanonicalBankTransaction(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        bank_name="HDFC",
        bank_reference="REF_OLD",
        raw_narration="OLD CREDIT",
        transaction_date=date(2026, 11, 5),
        credit_amount=Decimal("1000.0000"),
        unallocated_balance=Decimal("1000.0000")
    )
    db_session.add_all([settlement, bank_tx])
    db_session.commit()

    detector = UncreditedSettlementDetector()
    findings = detector.detect(
        db_session,
        tenant_id,
        parameters={"as_of_date": date(2026, 11, 11), "bank_clearing_window_days": 1}
    )

    assert len(findings) == 1
    f = findings[0]
    # Recoverable amount MUST be 0.0000 because evidence is pending statement upload!
    assert f.recoverable_amount == Decimal("0.0000")
    assert f.severity == ExceptionSeverity.LOW
    assert "statement upload" in f.severity_reason.lower()


def test_uncredited_settlement_detector_amount_mismatch(db_session: Session, seeded_entities: dict):
    tenant_id = seeded_entities["tenant_a"].id
    batch = seed_batch(db_session, tenant_id)

    # Settlement reported net ₹50,000 with UTR 'UTR_MATCH_123'
    settlement = CanonicalSettlement(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=3,
        gateway_name="RAZORPAY",
        settlement_reference="SETL-MISMATCH-003",
        utr_number="UTR_MATCH_123",
        gross_amount=Decimal("51000.0000"),
        net_settlement_amount=Decimal("50000.0000"),
        unallocated_balance=Decimal("50000.0000"),
        status="settled",
        settled_at=datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc),
    )

    # Bank credit with same UTR credited only ₹48,000!
    bank_tx = CanonicalBankTransaction(
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=2,
        bank_name="HDFC",
        bank_reference="REF_MISMATCH",
        extracted_utr="UTR_MATCH_123",
        raw_narration="RTGS UTR_MATCH_123 SHORT CREDIT",
        transaction_date=date(2026, 11, 3),
        credit_amount=Decimal("48000.0000"),
        unallocated_balance=Decimal("48000.0000")
    )
    db_session.add_all([settlement, bank_tx])
    db_session.commit()

    detector = UncreditedSettlementDetector()
    findings = detector.detect(
        db_session,
        tenant_id,
        parameters={"as_of_date": date(2026, 11, 10), "bank_clearing_window_days": 1}
    )

    assert len(findings) == 1
    f = findings[0]
    assert f.exception_type == LeakageExceptionType.SETTLEMENT_AMOUNT_MISMATCH
    assert len(f.evidence_items) == 2  # Both settlement and mismatched bank transaction
