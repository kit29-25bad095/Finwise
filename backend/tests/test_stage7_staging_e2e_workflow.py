import io
import uuid
from decimal import Decimal
from datetime import datetime, date, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import SessionLocal, get_db_session
from app.core.security import create_access_token, get_password_hash
from app.core.rbac import Role
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.models.canonical import (
    CanonicalOrder,
    CanonicalPayment,
    CanonicalSettlement,
    CanonicalBankTransaction,
)
from app.models.reconciliation import (
    FeeContract,
    FeeScheduleTier,
    ReconciliationRun,
    ReconciliationMatch,
    ReconciliationStatus,
    MatchType,
    MatchClassification,
)
from app.models.ingestion import IngestionBatch, IngestionStatus
from app.models.leakage import (
    LeakageDetectionRun,
    LeakageException,
    LeakageExceptionType,
    ExceptionStatus,
)
from app.models.forensic import (
    ForensicInvestigation,
    InvestigationStatus,
    InvestigationConclusion,
    InvestigationConfidence,
)
from app.models.audit import AuditLog
from app.services.ingestion.ingestion_service import IngestionService
from app.services.reconciliation.reconciliation_service import ReconciliationService
from app.services.leakage.detection_engine import DetectionEngine
from app.services.forensics.investigation_service import ForensicInvestigationService
from app.services.forensics.llm_adapter import MockLLMAdapter

client = TestClient(app)


@pytest.fixture
def staging_environment():
    """Sets up an isolated, synthetic merchant enterprise in staging."""
    db: Session = SessionLocal()
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()

    # 1. Staging Enterprise Tenant
    tenant = Tenant(
        id=tenant_id,
        name="Staging D2C Apparel Private Limited",
        slug=f"staging-d2c-{tenant_id.hex[:8]}",
        default_currency="INR",
        settlement_cutoff_time="23:00",
        fee_overcharge_tolerance=Decimal("0.0500"),
        max_knapsack_bound=5,
        is_active=True,
    )
    db.add(tenant)

    # 2. Finance Manager User
    user = User(
        id=user_id,
        email=f"finance.manager.{tenant_id.hex[:6]}@staging.finora.internal",
        hashed_password=get_password_hash("StagingPass#2026"),
        full_name="Priya Sharma (Staging Manager)",
        is_active=True,
        is_superuser=False,
    )
    db.add(user)

    membership = TenantMembership(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        role=Role.FINANCE_MANAGER,
        is_default=True,
    )
    db.add(membership)
    db.commit()

    # 3. Contractual MDR Fee Contract (Razorpay: 2.0% MDR + 18% GST)
    contract = FeeContract(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Razorpay Standard Staging Contract",
        start_date=date(2026, 1, 1),
        end_date=date(2027, 12, 31),
        gst_rate=Decimal("0.180000"),
        is_active=True,
    )
    db.add(contract)
    db.commit()

    tier = FeeScheduleTier(
        id=uuid.uuid4(),
        contract_id=contract.id,
        tenant_id=tenant_id,
        instrument_type="UPI",
        percentage_rate=Decimal("0.020000"),
        fixed_fee_per_txn=Decimal("0.0000"),
    )
    db.add(tier)
    db.commit()

    token = create_access_token(
        subject=str(user_id),
        tenant_id=str(tenant_id),
        role=Role.FINANCE_MANAGER,
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-ID": str(tenant_id),
    }

    yield {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "headers": headers,
        "token": token,
    }

    db.close()


# ==============================================================================
# Complete End-to-End Staging Pipeline Test
# ==============================================================================

def test_complete_staging_e2e_reconciliation_pipeline(staging_environment):
    """
    Executes the full 7-stage financial pipeline in staging using pure synthetic data:
    1. CSV Upload (Shopify, Razorpay, HDFC)
    2. Canonical Normalization
    3. Multi-Pass Reconciliation (Pass 1 & Pass 2)
    4. Revenue Leakage Detection (Contractual MDR Overcharge)
    5. AI Forensic Investigation (Root Cause & Claim Draft)
    6. Human Review Decision (Resolution)
    7. Complete Audit Trail Verification
    """
    tenant_id = staging_environment["tenant_id"]
    user_id = staging_environment["user_id"]
    headers = staging_environment["headers"]
    db: Session = SessionLocal()

    try:
        # ----------------------------------------------------------------------
        # STAGE 1: Synthetic CSV Document Upload
        # ----------------------------------------------------------------------
        shopify_csv = (
            "Name,Total,Created at,Financial Status\n"
            "#SHOP-STG-9001,4999.00,2026-11-10T10:00:00Z,paid\n"
        ).encode("utf-8")

        # Two payments: pay_9001 (normal) and pay_9002 (overcharged: fee 350 vs exp 236)
        razorpay_csv = (
            "payment_id,order_id,amount,fee,tax,payment_method,created_at,status\n"
            "pay_STG_9001,SHOP-STG-9001,4999.00,100.00,18.00,UPI,2026-11-10T10:05:00Z,captured\n"
            "pay_STG_9002,,10000.00,350.00,63.00,UPI,2026-11-10T11:00:00Z,captured\n"
        ).encode("utf-8")

        # HDFC Bank Credit matching net payout of pay_9001 (4999 - 118 = 4881)
        hdfc_csv = (
            "Date,Narration,Deposit,Chq/Ref No,Value Dt\n"
            "12/11/2026,CMS/RZP/NODAL/HDFCR5202611129001,4881.00,HDFCR5202611129001,12/11/2026\n"
        ).encode("utf-8")

        # Upload Shopify CSV
        resp_shop = client.post(
            "/api/v1/ingestion/upload",
            data={"source_type": "SHOPIFY"},
            files={"file": ("shopify_orders.csv", io.BytesIO(shopify_csv), "text/csv")},
            headers=headers,
        )
        assert resp_shop.status_code == 201
        batch_shop_id = uuid.UUID(resp_shop.json()["id"])

        # Upload Razorpay CSV
        resp_rzp = client.post(
            "/api/v1/ingestion/upload",
            data={"source_type": "RAZORPAY"},
            files={"file": ("razorpay_payments.csv", io.BytesIO(razorpay_csv), "text/csv")},
            headers=headers,
        )
        assert resp_rzp.status_code == 201
        batch_rzp_id = uuid.UUID(resp_rzp.json()["id"])

        # Upload HDFC CSV
        resp_hdfc = client.post(
            "/api/v1/ingestion/upload",
            data={"source_type": "HDFC"},
            files={"file": ("hdfc_statement.csv", io.BytesIO(hdfc_csv), "text/csv")},
            headers=headers,
        )
        assert resp_hdfc.status_code == 201
        batch_hdfc_id = uuid.UUID(resp_hdfc.json()["id"])

        # ----------------------------------------------------------------------
        # STAGE 2: Canonical Normalization
        # ----------------------------------------------------------------------
        b_shop = db.get(IngestionBatch, batch_shop_id)
        assert b_shop.status in (IngestionStatus.COMPLETED, IngestionStatus.COMPLETED_WITH_WARNINGS)

        b_rzp = db.get(IngestionBatch, batch_rzp_id)
        assert b_rzp.status in (IngestionStatus.COMPLETED, IngestionStatus.COMPLETED_WITH_WARNINGS)

        b_hdfc = db.get(IngestionBatch, batch_hdfc_id)
        assert b_hdfc.status in (IngestionStatus.COMPLETED, IngestionStatus.COMPLETED_WITH_WARNINGS)

        # Verify Canonical Records
        order = db.execute(select(CanonicalOrder).where(CanonicalOrder.tenant_id == tenant_id)).scalar_one_or_none()
        assert order is not None
        assert "SHOP-STG-9001" in order.order_reference
        assert order.gross_amount == Decimal("4999.0000")

        payments = db.execute(select(CanonicalPayment).where(CanonicalPayment.tenant_id == tenant_id)).scalars().all()
        assert len(payments) == 2

        bank_tx = db.execute(select(CanonicalBankTransaction).where(CanonicalBankTransaction.tenant_id == tenant_id)).scalar_one_or_none()
        assert bank_tx is not None
        assert bank_tx.credit_amount == Decimal("4881.0000")

        # Synthesize settlement for pay_9001 to test 3-way matching
        settlement = CanonicalSettlement(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            batch_id=batch_rzp_id,
            source_row_index=1,
            gateway_name="RAZORPAY",
            settlement_reference="setl_STG_9001",
            utr_number="HDFCR5202611129001",
            gross_amount=Decimal("4999.0000"),
            total_fee=Decimal("100.0000"),
            total_tax=Decimal("18.0000"),
            net_settlement_amount=Decimal("4881.0000"),
            unallocated_balance=Decimal("4881.0000"),
            settled_at=datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc),
            status="settled",
        )
        db.add(settlement)
        db.commit()

        # ----------------------------------------------------------------------
        # STAGE 3: Three-Way Multi-Pass Reconciliation
        # ----------------------------------------------------------------------
        run_record = ReconciliationService.create_run(db, tenant_id=tenant_id, user_id=user_id, parameters={})
        completed_run = ReconciliationService.execute_run(db, run_record.id)
        assert completed_run.status in (ReconciliationStatus.COMPLETED.value, ReconciliationStatus.COMPLETED_WITH_EXCEPTIONS.value)
        assert completed_run.matched_orders_count >= 1

        # Verify Pass 1 Exact Reference Match
        p1_match = db.execute(
            select(ReconciliationMatch).where(
                and_(
                    ReconciliationMatch.run_id == completed_run.id,
                    ReconciliationMatch.classification == MatchClassification.EXACT_MATCH.value,
                    ReconciliationMatch.pass_number == 1,
                )
            )
        ).scalar_one_or_none()
        assert p1_match is not None
        assert p1_match.allocated_amount == Decimal("4999.0000")

        # ----------------------------------------------------------------------
        # STAGE 4: Revenue Leakage Detection (MDR Fee Overcharge)
        # ----------------------------------------------------------------------
        leakage_run = DetectionEngine.create_run(db, tenant_id=tenant_id, user_id=user_id, parameters={})
        completed_l_run = DetectionEngine.execute_run(db, leakage_run.id)
        assert completed_l_run.exceptions_count >= 1

        overcharge_exc = db.execute(
            select(LeakageException).where(
                and_(
                    LeakageException.tenant_id == tenant_id,
                    LeakageException.exception_type == LeakageExceptionType.FEE_OVERCHARGE.value,
                )
            )
        ).scalar_one_or_none()
        assert overcharge_exc is not None
        # Expected fee: 2% of 10,000 = 200 + 18% GST (36) = 236. Reported: 350 + 63 = 413. Overcharge: 177.00
        assert overcharge_exc.leakage_amount > Decimal("100.0000")
        assert overcharge_exc.status == ExceptionStatus.OPEN.value

        # ----------------------------------------------------------------------
        # STAGE 5: AI Forensic Root Cause Investigation
        # ----------------------------------------------------------------------
        mock_adapter = MockLLMAdapter()

        inv = ForensicInvestigationService.create_investigation(
            db=db,
            tenant_id=tenant_id,
            exception_id=overcharge_exc.id,
            user_id=user_id,
        )
        completed_inv = ForensicInvestigationService.execute_investigation(
            db=db,
            investigation_id=inv.id,
            adapter=mock_adapter,
        )
        assert completed_inv.status == InvestigationStatus.COMPLETED.value
        assert completed_inv.conclusion in (
            InvestigationConclusion.SUPPORTED.value,
            InvestigationConclusion.PARTIALLY_SUPPORTED.value,
            InvestigationConclusion.INCONCLUSIVE.value,
        )
        assert completed_inv.summary is not None

        # ----------------------------------------------------------------------
        # STAGE 6: Human Review Decision
        # ----------------------------------------------------------------------
        review = DetectionEngine.review_exception(
            db=db,
            exception_id=overcharge_exc.id,
            tenant_id=tenant_id,
            reviewer_id=user_id,
            action="CONFIRM",
            notes="Auditor confirmed 1.5% MDR overcharge based on AI forensic evidence.",
        )
        assert review is not None

        db.refresh(overcharge_exc)
        assert overcharge_exc.status == ExceptionStatus.CONFIRMED.value

        # ----------------------------------------------------------------------
        # STAGE 7: Audit Trail Provenance
        # ----------------------------------------------------------------------
        logs = db.execute(
            select(AuditLog).where(AuditLog.tenant_id == tenant_id).order_by(AuditLog.performed_at)
        ).scalars().all()

        action_names = [l.action for l in logs]
        assert "INGESTION_BATCH_PROCESSED" in action_names
        assert "RECONCILIATION_RUN_COMPLETED" in action_names
        assert "LEAKAGE_DETECTION_RUN_COMPLETED" in action_names
        assert "LEAKAGE_EXCEPTION_REVIEWED" in action_names

    finally:
        db.close()


# ==============================================================================
# Dashboard Routes & Monitoring Health Verification
# ==============================================================================

def test_staging_dashboard_and_health_probes(staging_environment):
    """Verifies that all monitoring probes and system endpoints respond cleanly in staging."""
    headers = staging_environment["headers"]

    # 1. Health Liveness & Readiness Probes
    resp_live = client.get("/health/live")
    assert resp_live.status_code == 200
    assert resp_live.json()["status"] == "ALIVE"

    resp_ready = client.get("/health/ready")
    assert resp_ready.status_code == 200
    assert resp_ready.json()["status"] == "READY"

    # 2. Prometheus Exposition
    resp_prom = client.get("/metrics")
    assert resp_prom.status_code == 200
    assert "finora_http_requests_total" in resp_prom.text

    # 3. JSON Telemetry & Alerts
    resp_telemetry = client.get("/api/v1/monitoring/metrics")
    assert resp_telemetry.status_code == 200
    assert "api" in resp_telemetry.json()

    # 4. Core Authenticated Ingestion Routes
    resp_batches = client.get("/api/v1/ingestion/batches", headers=headers)
    assert resp_batches.status_code == 200

    resp_runs = client.get("/api/v1/reconciliation/runs", headers=headers)
    assert resp_runs.status_code == 200
