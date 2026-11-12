import uuid
import pytest
from decimal import Decimal
from datetime import datetime, timezone, date
from fastapi.testclient import TestClient

from app.models.tenant import Tenant
from app.models.ingestion import IngestionBatch, IngestionStatus
from app.models.canonical import (
    CanonicalOrder,
    CanonicalPayment,
    CanonicalSettlement,
    CanonicalBankTransaction,
)
from app.models.reconciliation import (
    ReconciliationRun,
    ReconciliationMatch,
    FeeContract,
    FeeScheduleTier,
    ReconciliationStatus,
    MatchClassification,
    MatchType,
    ReviewStatus,
)
from app.models.audit import AuditLog


def seed_ingestion_batch(db_session, tenant_id: uuid.UUID) -> IngestionBatch:
    batch = IngestionBatch(
        tenant_id=tenant_id,
        source_type="SHOPIFY",
        filename="dash_test.csv",
        file_hash_sha256="dummy_dash_hash_" + str(uuid.uuid4())[:8],
        file_size_bytes=1000,
        status=IngestionStatus.COMPLETED
    )
    db_session.add(batch)
    db_session.commit()
    return batch


def test_dashboard_overview_endpoint(client: TestClient, db_session, seeded_entities):
    tenant_id = seeded_entities["tenant_a"].id
    headers = seeded_entities["headers_a_admin"]
    batch = seed_ingestion_batch(db_session, tenant_id)

    # Add canonical order
    order = CanonicalOrder(
        tenant_id=tenant_id,
        batch_id=batch.id,
        order_reference="ORD-DASH-001",
        order_number="1001",
        gross_amount=Decimal("15000.0000"),
        order_timestamp=datetime.now(timezone.utc),
        source_row_index=1,
    )
    # Add canonical payment
    payment = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        gateway_payment_id="pay_dash_001",
        captured_amount=Decimal("15000.0000"),
        reported_fee=Decimal("280.0000"),
        reported_tax=Decimal("50.4000"),
        unallocated_balance=Decimal("0.0000"),
        payment_method="credit_card",
        captured_at=datetime.now(timezone.utc),
        source_row_index=1,
    )
    # Add canonical settlement
    settlement = CanonicalSettlement(
        tenant_id=tenant_id,
        batch_id=batch.id,
        settlement_reference="SETL-DASH-001",
        utr_number="UTR-DASH-001",
        gross_amount=Decimal("15000.0000"),
        net_settlement_amount=Decimal("14670.0000"),
        unallocated_balance=Decimal("0.0000"),
        settled_at=datetime.now(timezone.utc),
        source_row_index=1,
    )
    # Add bank credit
    bank_tx = CanonicalBankTransaction(
        tenant_id=tenant_id,
        batch_id=batch.id,
        bank_reference="BANK-DASH-001",
        credit_amount=Decimal("14670.0000"),
        unallocated_balance=Decimal("0.0000"),
        transaction_date=date.today(),
        extracted_utr="UTR-DASH-001",
        raw_narration="CMS/NODAL RTGS SETTLEMENT",
        source_row_index=1,
    )
    db_session.add_all([order, payment, settlement, bank_tx])
    db_session.commit()

    res = client.get("/api/v1/dashboard/overview", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert data["total_orders_count"] >= 1
    assert Decimal(data["total_orders_amount"]) >= Decimal("15000.0000")
    assert Decimal(data["total_captured_amount"]) >= Decimal("15000.0000")
    assert Decimal(data["total_settled_amount"]) >= Decimal("14670.0000")
    assert Decimal(data["total_bank_credited_amount"]) >= Decimal("14670.0000")
    assert "flow" in data
    assert data["flow"]["shopify_orders"]["total_count"] >= 1
    assert "leakage_by_category" in data
    assert "leakage_by_severity" in data


def test_dashboard_leakage_findings_and_review_queue(client: TestClient, db_session, seeded_entities):
    tenant_id = seeded_entities["tenant_a"].id
    headers = seeded_entities["headers_a_admin"]
    batch = seed_ingestion_batch(db_session, tenant_id)

    # Create unallocated payment (missing settlement)
    p_unalloc = CanonicalPayment(
        tenant_id=tenant_id,
        batch_id=batch.id,
        gateway_payment_id="pay_missing_setl_099",
        captured_amount=Decimal("5000.0000"),
        reported_fee=Decimal("84.7500"),
        reported_tax=Decimal("15.2500"),
        unallocated_balance=Decimal("5000.0000"),
        payment_method="upi",
        captured_at=datetime.now(timezone.utc),
        source_row_index=99,
    )
    # Create fee contract
    contract = FeeContract(
        tenant_id=tenant_id,
        gateway_name="RAZORPAY",
        contract_name="Standard Tariff",
        version=1,
        is_active=True,
        start_date=date(2026, 1, 1),
        gst_rate=Decimal("0.180000"),
    )
    db_session.add_all([p_unalloc, contract])
    db_session.commit()

    # Create a reconciliation run and match with fee overcharge
    run = ReconciliationRun(
        tenant_id=tenant_id,
        run_number=99,
        status=ReconciliationStatus.COMPLETED.value,
        total_orders_evaluated=1,
        total_payments_evaluated=1,
        total_settlements_evaluated=0,
        total_bank_transactions_evaluated=0,
        total_order_amount=Decimal("5000.0000"),
        total_captured_amount=Decimal("5000.0000"),
        total_settled_amount=Decimal("0.0000"),
        total_matched_bank_amount=Decimal("0.0000"),
        total_discrepancy_amount=Decimal("5000.0000"),
        total_fee_drift_amount=Decimal("25.0000"),
    )
    db_session.add(run)
    db_session.flush()

    match_exc = ReconciliationMatch(
        tenant_id=tenant_id,
        run_id=run.id,
        match_type=MatchType.ORDER_TO_PAYMENT.value,
        classification=MatchClassification.PARTIAL_MATCH.value,
        pass_number=1,
        confidence_score=Decimal("0.9500"),
        source_amount=Decimal("5000.0000"),
        target_amount=Decimal("4900.0000"),
        allocated_amount=Decimal("4900.0000"),
        discrepancy_amount=Decimal("100.0000"),
        expected_fee=Decimal("75.0000"),
        expected_tax=Decimal("13.5000"),
        fee_discrepancy=Decimal("11.5000"),
        explanation="Partial allocation with ₹11.50 fee overcharge",
        review_status=ReviewStatus.PENDING_REVIEW.value,
    )
    db_session.add(match_exc)
    db_session.commit()

    # Test leakage findings
    res_lkg = client.get("/api/v1/dashboard/leakage-findings", headers=headers)
    assert res_lkg.status_code == 200
    lkg_data = res_lkg.json()
    assert lkg_data["total_findings"] >= 1
    categories = [f["category"] for f in lkg_data["findings"]]
    assert "MISSING_SETTLEMENT" in categories or "FEE_OVERCHARGE" in categories

    # Test review queue
    res_rq = client.get("/api/v1/dashboard/review-queue", headers=headers)
    assert res_rq.status_code == 200
    rq_data = res_rq.json()
    assert rq_data["total_pending"] >= 1
    assert rq_data["items"][0]["review_status"] == "PENDING_REVIEW"


def test_dashboard_fee_analytics_and_ai_investigations(client: TestClient, db_session, seeded_entities):
    headers = seeded_entities["headers_a_admin"]

    # Fee analytics
    res_fee = client.get("/api/v1/dashboard/fee-analytics", headers=headers)
    assert res_fee.status_code == 200
    fee_data = res_fee.json()
    assert "gst_rate" in fee_data
    assert "tiers" in fee_data
    assert len(fee_data["tiers"]) > 0

    # AI investigations
    res_ai = client.get("/api/v1/dashboard/ai-investigations", headers=headers)
    assert res_ai.status_code == 200
    ai_data = res_ai.json()
    assert ai_data["provider"] == "GOOGLE_GEMINI"
    assert ai_data["status"] in ("PENDING_CONFIGURATION", "ACTIVE")
    assert "Gemini" in ai_data["message"]


def test_dashboard_audit_logs_and_tenant_isolation(client: TestClient, db_session, seeded_entities):
    tenant_a_id = seeded_entities["tenant_a"].id
    headers_a = seeded_entities["headers_a_admin"]
    headers_b = seeded_entities["headers_b_admin"]

    # Create an audit log for tenant A
    audit = AuditLog(
        tenant_id=tenant_a_id,
        action="TEST_DASHBOARD_AUDIT",
        target_entity_type="reconciliation_run",
        user_rationale="Quarterly audit review",
        ip_address="127.0.0.1"
    )
    db_session.add(audit)
    db_session.commit()

    res_audit = client.get("/api/v1/dashboard/audit-logs", headers=headers_a)
    assert res_audit.status_code == 200
    audit_data = res_audit.json()
    assert audit_data["total_logs"] >= 1
    actions = [l["action"] for l in audit_data["logs"]]
    assert "TEST_DASHBOARD_AUDIT" in actions

    # Tenant B should NOT see Tenant A's audit log
    res_b_audit = client.get("/api/v1/dashboard/audit-logs", headers=headers_b)
    assert res_b_audit.status_code == 200
    b_audit_data = res_b_audit.json()
    assert b_audit_data["total_logs"] == 0

    # Tenant B overview should be isolated
    res_b_overview = client.get("/api/v1/dashboard/overview", headers=headers_b)
    assert res_b_overview.status_code == 200
    b_data = res_b_overview.json()
    assert b_data["total_orders_count"] == 0
    assert Decimal(b_data["total_orders_amount"]) == Decimal("0.0000")
