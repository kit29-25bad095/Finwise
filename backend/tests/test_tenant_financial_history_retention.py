import uuid
import importlib.util
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone, date
import pytest
from sqlalchemy import text, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi.testclient import TestClient

from app.models.base import ImmutabilityViolationError
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.models.audit import AuditLog
from app.models.canonical import (
    CanonicalOrder,
    CanonicalPayment,
    CanonicalSettlement,
    CanonicalBankTransaction,
    CanonicalRefund,
)
from app.models.reconciliation import (
    FeeContract,
    ReconciliationRun,
    ReconciliationMatch,
    ReconciliationAllocation,
    ReconciliationRunDelta,
)
from app.models.ingestion import IngestionBatch, SourceRowError
from app.models.leakage import (
    LeakageDetectionRun,
    LeakageException,
    LeakageRunException,
    LeakageExceptionEvidence,
    LeakageRunEvidence,
    LeakageExceptionReview,
    SnapshotQuality,
)
from app.services.tenant_service import TenantService
from app.core.security import get_password_hash, create_access_token
from app.core.rbac import Role


def _load_migration_module(filename: str):
    migration_path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename[:-3], migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def populated_tenant_environment(db_session: Session):
    """
    Creates a tenant with a complete representative graph of historical records
    across audit, canonical ledgers, reconciliation, ingestion, and leakage detection.
    """
    tenant_id = uuid.uuid4()
    tenant = Tenant(
        id=tenant_id,
        name="Durable Financial Corp",
        slug=f"durable-corp-{uuid.uuid4().hex[:6]}",
        default_currency="INR",
        is_active=True,
    )
    db_session.add(tenant)
    db_session.flush()

    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=f"admin_{uuid.uuid4().hex[:6]}@durable.com",
        hashed_password=get_password_hash("Password123!"),
        full_name="Admin User",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    membership = TenantMembership(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        role=Role.ADMIN.value,
        is_default=True,
    )
    db_session.add(membership)

    audit = AuditLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        action="INITIAL_SEED",
        target_entity_type="tenant",
        target_entity_id=tenant_id,
        new_state={"seeded": True},
        user_rationale="Initial ledger setup",
    )
    db_session.add(audit)

    batch = IngestionBatch(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        source_type="RAZORPAY",
        filename="payments.csv",
        file_hash_sha256="dummy_hash",
        status="COMPLETED",
        total_rows=1,
        valid_rows=1,
        invalid_rows=0,
    )
    db_session.add(batch)
    db_session.flush()

    row_err = SourceRowError(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        batch_id=batch.id,
        row_index=1,
        raw_record={"test": "error"},
        message="Sample validation error",
        error_code="INVALID_ROW",
    )
    db_session.add(row_err)

    order = CanonicalOrder(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        order_number="ORD-1001",
        order_reference="ORD-REF-1001",
        gross_amount=Decimal("1500.0000"),
        currency="INR",
        fulfillment_status="FULFILLED",
        financial_status="PAID",
        order_timestamp=datetime.now(timezone.utc),
    )
    db_session.add(order)

    payment = CanonicalPayment(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        gateway_payment_id="pay_sample_123",
        order_reference="ORD-REF-1001",
        captured_amount=Decimal("1500.0000"),
        reported_fee=Decimal("35.4000"),
        reported_tax=Decimal("5.4000"),
        currency="INR",
        status="CAPTURED",
        unallocated_balance=Decimal("1500.0000"),
        captured_at=datetime.now(timezone.utc),
    )
    db_session.add(payment)

    settlement = CanonicalSettlement(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_name="RAZORPAY",
        settlement_reference="setl_sample_456",
        utr_number="UTR-SAMPLE-789",
        gross_amount=Decimal("1500.0000"),
        total_fee=Decimal("35.4000"),
        total_tax=Decimal("5.4000"),
        net_settlement_amount=Decimal("1464.6000"),
        unallocated_balance=Decimal("1464.6000"),
        status="SETTLED",
        settled_at=datetime.now(timezone.utc),
    )
    db_session.add(settlement)

    bank_txn = CanonicalBankTransaction(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        bank_name="HDFC",
        extracted_utr="UTR-SAMPLE-789",
        raw_narration="CMS/000123/UTR-SAMPLE-789/SETTLEMENT",
        credit_amount=Decimal("1464.6000"),
        unallocated_balance=Decimal("1464.6000"),
        transaction_date=datetime.now(timezone.utc),
        value_date=datetime.now(timezone.utc),
    )
    db_session.add(bank_txn)

    refund = CanonicalRefund(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        batch_id=batch.id,
        source_row_index=1,
        gateway_refund_id="rfnd_sample_999",
        gateway_payment_id="pay_sample_123",
        refund_amount=Decimal("100.0000"),
        currency="INR",
        status="PROCESSED",
        processed_at=datetime.now(timezone.utc),
    )
    db_session.add(refund)

    fee_contract = FeeContract(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Standard 2026",
        version=1,
        start_date=date(2026, 1, 1),
        is_active=True,
    )
    db_session.add(fee_contract)

    rec_run = ReconciliationRun(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        run_number=1,
        status="COMPLETED",
        total_orders_evaluated=1,
        total_payments_evaluated=1,
        total_settlements_evaluated=1,
        total_bank_transactions_evaluated=1,
    )
    db_session.add(rec_run)
    db_session.flush()

    rec_match = ReconciliationMatch(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        run_id=rec_run.id,
        pass_number=1,
        match_type="ORDER_TO_PAYMENT_EXACT",
        classification="EXACT_MATCH",
        confidence_score=Decimal("1.0000"),
        allocated_amount=Decimal("1500.0000"),
        explanation="Order ORD-1001 matched to Payment pay_sample_123",
    )
    db_session.add(rec_match)
    db_session.flush()

    rec_alloc = ReconciliationAllocation(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        run_id=rec_run.id,
        match_id=rec_match.id,
        source_entity_type="canonical_orders",
        source_entity_id=order.id,
        target_entity_type="canonical_payments",
        target_entity_id=payment.id,
        allocated_amount=Decimal("1500.0000"),
        status="ALLOCATED",
    )
    db_session.add(rec_alloc)

    det_run = LeakageDetectionRun(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        run_number=1,
        status="COMPLETED",
        total_captures_evaluated=1,
        exceptions_count=1,
        total_leakage_amount=Decimal("50.0000"),
        total_potential_recovery=Decimal("50.0000"),
    )
    db_session.add(det_run)
    db_session.flush()

    exc = LeakageException(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        detection_run_id=det_run.id,
        latest_detection_run_id=det_run.id,
        detector_type="FEE_OVERCHARGE",
        exception_type="FEE_OVERCHARGE",
        status="OPEN",
        severity="MEDIUM",
        severity_reason="Fee exceeds contractual tier",
        source_entity_type="canonical_payments",
        source_entity_id=payment.id,
        source_reference="pay_sample_123",
        expected_amount=Decimal("30.0000"),
        actual_amount=Decimal("35.4000"),
        leakage_amount=Decimal("5.4000"),
        recoverable_amount=Decimal("5.4000"),
        currency="INR",
        explanation="Contract fee 2.0% expected 30.00, charged 35.40",
    )
    db_session.add(exc)
    db_session.flush()

    run_exc = LeakageRunException(
        id=uuid.uuid4(),
        detection_run_id=det_run.id,
        exception_id=exc.id,
        tenant_id=tenant_id,
        observed_status="OPEN",
        observed_severity="MEDIUM",
        observed_expected_amount=Decimal("30.0000"),
        observed_actual_amount=Decimal("35.4000"),
        observed_leakage_amount=Decimal("5.4000"),
        observed_recoverable_amount=Decimal("5.4000"),
        explanation="Contract fee 2.0% expected 30.00, charged 35.40",
        snapshot_quality=SnapshotQuality.VERIFIED_AT_EXECUTION.value,
    )
    db_session.add(run_exc)

    ev = LeakageExceptionEvidence(
        id=uuid.uuid4(),
        exception_id=exc.id,
        tenant_id=tenant_id,
        detection_run_id=det_run.id,
        evidence_type="PAYMENT_CAPTURE",
        entity_type="canonical_payments",
        entity_id=payment.id,
        details={"fee": "35.4000"},
    )
    db_session.add(ev)
    db_session.flush()

    run_ev = LeakageRunEvidence(
        id=uuid.uuid4(),
        detection_run_id=det_run.id,
        evidence_id=ev.id,
        tenant_id=tenant_id,
    )
    db_session.add(run_ev)

    rev = LeakageExceptionReview(
        id=uuid.uuid4(),
        exception_id=exc.id,
        tenant_id=tenant_id,
        reviewer_id=user_id,
        from_status="OPEN",
        to_status="UNDER_REVIEW",
        action="FLAG_REVIEW",
        notes="Under verification with gateway",
    )
    db_session.add(rev)
    db_session.commit()

    return {
        "tenant_id": tenant_id,
        "tenant": tenant,
        "user_id": user_id,
        "user": user,
        "membership": membership,
        "payment_id": payment.id,
        "run_exc_id": run_exc.id,
        "det_run_id": det_run.id,
        "exc_id": exc.id,
    }


def test_raw_sql_tenant_deletion_blocked_by_database_foreign_key(
    db_session: Session, populated_tenant_environment
):
    """
    Test A: Raw SQL deletion of a tenant with historical records must be
    rejected by the database foreign key constraint (ON DELETE RESTRICT).
    """
    tenant_id = populated_tenant_environment["tenant_id"]

    # Attempt raw SQL DELETE (supporting both UUID hyphenated and hex SQLite representation)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.execute(
            text("DELETE FROM tenants WHERE id = :tid OR id = :tid_hex"),
            {"tid": str(tenant_id), "tid_hex": tenant_id.hex},
        )
        db_session.commit()

    db_session.rollback()

    # Verify foreign key constraint failure
    err_str = str(exc_info.value).lower()
    assert "foreign key" in err_str or "constraint" in err_str or "restrict" in err_str

    # Verify tenant remains intact
    surviving_tenant = db_session.get(Tenant, tenant_id)
    assert surviving_tenant is not None

    # Verify representative child records remain completely intact
    assert db_session.get(LeakageRunException, populated_tenant_environment["run_exc_id"]) is not None
    assert db_session.get(CanonicalPayment, populated_tenant_environment["payment_id"]) is not None
    assert db_session.get(LeakageException, populated_tenant_environment["exc_id"]) is not None


def test_orm_tenant_deletion_blocked_by_immutability_listener(
    db_session: Session, populated_tenant_environment
):
    """
    Test B: Attempting session.delete(tenant) must be blocked by the
    SQLAlchemy Tenant before_delete event listener raising ImmutabilityViolationError.
    """
    tenant_id = populated_tenant_environment["tenant_id"]
    tenant = db_session.get(Tenant, tenant_id)
    assert tenant is not None

    with pytest.raises(ImmutabilityViolationError) as exc_info:
        db_session.delete(tenant)
        db_session.flush()

    db_session.rollback()

    assert "strictly prohibited" in str(exc_info.value)
    assert "historical financial and audit records" in str(exc_info.value)

    # Verify tenant survives
    assert db_session.get(Tenant, tenant_id) is not None


def test_bulk_sql_tenant_deletion_blocked_by_database_foreign_key(
    db_session: Session, populated_tenant_environment
):
    """
    Test C: Bulk SQL deletion bypassing ORM instance listeners must still
    be rejected by the database foreign key constraint.
    """
    from sqlalchemy import delete

    tenant_id = populated_tenant_environment["tenant_id"]

    with pytest.raises(IntegrityError):
        # execute an update/delete bypassing ORM identity map
        db_session.execute(delete(Tenant).where(Tenant.id == tenant_id))
        db_session.commit()

    db_session.rollback()
    assert db_session.get(Tenant, tenant_id) is not None


def test_tenant_soft_deactivation_service_and_api(
    client: TestClient, db_session: Session, populated_tenant_environment
):
    """
    Test soft deactivation: TenantService.deactivate_tenant and DELETE /tenants/{id}
    must set is_active=False while preserving all historical records.
    """
    tenant_id = populated_tenant_environment["tenant_id"]
    user_id = populated_tenant_environment["user_id"]

    # 1. Test Service layer deactivation
    deactivated = TenantService.deactivate_tenant(
        session=db_session,
        tenant_id=tenant_id,
        performed_by_id=user_id,
        user_rationale="Voluntary company closure",
    )
    assert deactivated.is_active is False

    # Check Audit log generated
    audit = db_session.execute(
        select(AuditLog).where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.action == "TENANT_DEACTIVATED",
        )
    ).scalar_one_or_none()
    assert audit is not None
    assert audit.new_state == {"is_active": False}

    # Verify all financial records still exist
    assert db_session.get(CanonicalPayment, populated_tenant_environment["payment_id"]) is not None
    assert db_session.get(LeakageRunException, populated_tenant_environment["run_exc_id"]) is not None

    # Reactivate tenant for API testing
    deactivated.is_active = True
    db_session.commit()

    # 2. Test API DELETE /tenants/{tenant_id}
    token = create_access_token(subject=str(user_id), tenant_id=str(tenant_id), role=Role.ADMIN.value)
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": str(tenant_id)}

    response = client.delete(f"/api/v1/tenants/{tenant_id}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["is_active"] is False

    # Verify in DB
    refreshed = db_session.get(Tenant, tenant_id)
    assert refreshed.is_active is False


def test_inactive_tenant_rejected_from_authenticated_endpoints(
    client: TestClient, db_session: Session, populated_tenant_environment
):
    """
    Inactive tenants must be rejected from performing authenticated tenant operations.
    """
    tenant_id = populated_tenant_environment["tenant_id"]
    user_id = populated_tenant_environment["user_id"]

    # Deactivate tenant
    tenant = db_session.get(Tenant, tenant_id)
    tenant.is_active = False
    db_session.commit()

    # Attempt to access a protected endpoint
    token = create_access_token(subject=str(user_id), tenant_id=str(tenant_id), role=Role.ADMIN.value)
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": str(tenant_id)}

    response = client.get(f"/api/v1/tenants/{tenant_id}", headers=headers)
    assert response.status_code in (401, 403)


def test_database_schema_enforces_restrict_on_all_durable_tables(db_session: Session):
    """
    Inspect the active database engine schema directly via SQLite PRAGMA
    and verify that every single durable table has ON DELETE RESTRICT (or NO ACTION).
    """
    conn = db_session.connection()

    m006 = _load_migration_module("006_tenant_financial_history_retention.py")
    TABLES_TO_PROTECT = m006.TABLES_TO_PROTECT

    for tbl in TABLES_TO_PROTECT:
        rows = conn.execute(text(f"PRAGMA foreign_key_list('{tbl}')")).fetchall()
        tenant_fks = [r for r in rows if r[2] == "tenants" and r[3] == "tenant_id"]
        assert len(tenant_fks) > 0, f"Table {tbl} missing tenant_id foreign key!"
        for fk in tenant_fks:
            # PRAGMA foreign_key_list columns: (id, seq, table, from, to, on_update, on_delete, match)
            on_delete = fk[6].upper()
            assert on_delete in ("RESTRICT", "NO ACTION"), (
                f"Table {tbl} tenant foreign key has unsafe ondelete='{on_delete}'! Must be RESTRICT."
            )


def test_migration_005_downgrade_fails_closed():
    """
    Verify that Migration 005 downgrade fails closed with a clear RuntimeError
    prohibiting destructive financial data loss.
    """
    m005 = _load_migration_module("005_phase4_evidence_and_lineage.py")

    with pytest.raises(RuntimeError) as exc_info:
        m005.downgrade()

    assert "Destructive downgrade prohibited: Migration 005" in str(exc_info.value)
    assert "immutable financial snapshots and evidence lineage" in str(exc_info.value)


def test_migration_006_downgrade_fails_closed():
    """
    Verify that Migration 006 downgrade fails closed with a clear RuntimeError
    prohibiting reintroduction of cascading deletion.
    """
    m006 = _load_migration_module("006_tenant_financial_history_retention.py")

    with pytest.raises(RuntimeError) as exc_info:
        m006.downgrade()

    assert "Destructive downgrade prohibited: Migration 006" in str(exc_info.value)
    assert "financial-history retention constraints" in str(exc_info.value)


def test_migration_005_and_006_upgrade_and_data_preservation(tmp_path, monkeypatch):
    """
    Executes Migration 005 and 006 in an isolated disposable database:
    1. Upgrades through 005 and 006.
    2. Verifies constraints and verifies that attempted downgrade fails closed
       without dropping or corrupting data.
    """
    from alembic.config import Config
    from alembic import command
    from app.core.config import settings
    from sqlalchemy import create_engine

    db_file = tmp_path / "migration_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setattr(settings, "SYNC_DATABASE_URL", db_url)

    alembic_cfg = Config("alembic.ini")

    # Upgrade through 005 and 006
    command.upgrade(alembic_cfg, "006_tenant_financial_history_retention")

    eng = create_engine(db_url)
    with eng.connect() as conn:
        # Check that table leakage_run_exceptions exists
        rows = conn.execute(text("SELECT count(*) FROM leakage_run_exceptions")).fetchone()
        assert rows[0] == 0

        # Check FK on leakage_run_exceptions
        fk_rows = conn.execute(text("PRAGMA foreign_key_list('leakage_run_exceptions')")).fetchall()
        tenant_fk = [r for r in fk_rows if r[2] == "tenants"]
        assert tenant_fk[0][6].upper() in ("RESTRICT", "NO ACTION")
    eng.dispose()

    # Attempt downgrade - must fail closed
    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(alembic_cfg, "005_phase4_evidence_and_lineage")
    assert "Destructive downgrade prohibited: Migration 006" in str(exc_info.value)

    # Upgrade to head (007) and verify 007 downgrade fails closed as well
    command.upgrade(alembic_cfg, "head")
    with pytest.raises(RuntimeError) as exc_info7:
        command.downgrade(alembic_cfg, "006_tenant_financial_history_retention")
    assert "Downgrading migration 007" in str(exc_info7.value)

    # Verify that data/schema remains intact after failed downgrade attempt
    eng2 = create_engine(db_url)
    with eng2.connect() as conn:
        rows = conn.execute(text("SELECT count(*) FROM leakage_run_exceptions")).fetchone()
        assert rows[0] == 0
    eng2.dispose()
