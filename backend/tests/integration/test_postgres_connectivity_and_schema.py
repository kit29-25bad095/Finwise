import uuid
from decimal import Decimal
import pytest
from sqlalchemy import text, Engine
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.tenant import Tenant
from app.models.forensic import ForensicClaimDraft


def test_postgres_17_connectivity(pg_engine: Engine):
    """B1: Verify connection to PostgreSQL 17 server."""
    with pg_engine.connect() as conn:
        ver = conn.scalar(text("SELECT version();"))
        assert "PostgreSQL 17" in ver, f"Expected PostgreSQL 17, got: {ver}"


def test_postgres_active_database_and_role(pg_engine: Engine):
    """B1: Verify active database is strictly finora_test and user is finora_staging."""
    with pg_engine.connect() as conn:
        active_db = conn.scalar(text("SELECT current_database();"))
        active_user = conn.scalar(text("SELECT current_user;"))
        assert active_db == "finora_test", f"Safety violation: Connected to {active_db}"
        assert active_user == "finora_staging", f"Unexpected role: {active_user}"


def test_postgres_transaction_isolation_and_rollback(pg_engine: Engine):
    """B1: Verify transaction handling and rollback on finora_test."""
    test_slug = f"tx-test-{uuid.uuid4().hex[:8]}"

    # Insert inside transaction and rollback
    with pg_engine.connect() as conn:
        tx = conn.begin()
        conn.execute(
            text("INSERT INTO tenants (id, name, slug, default_currency, is_active, created_at, updated_at) "
                 "VALUES (:id, :name, :slug, 'INR', true, NOW(), NOW())"),
            {"id": uuid.uuid4(), "name": "Tx Test Tenant", "slug": test_slug}
        )
        tx.rollback()

    # Verify tenant was NOT persisted
    with pg_engine.connect() as conn:
        count = conn.scalar(
            text("SELECT count(*) FROM tenants WHERE slug = :slug"),
            {"slug": test_slug}
        )
        assert count == 0, "Rolled back transaction leaked into finora_test!"


def test_alembic_current_head_is_008(pg_session: Session):
    """B2: Verify Alembic migration head is 008_forensic_investigation_leases_and_outbox."""
    rev = pg_session.execute(text("SELECT version_num FROM alembic_version;")).scalar()
    assert rev == "008_forensic_investigation_leases_and_outbox", (
        f"Alembic head mismatch: expected 008_forensic_investigation_leases_and_outbox, found {rev}"
    )


def test_alembic_version_column_capacity_postgresql(pg_session: Session):
    """B2: Verify alembic_version.version_num VARCHAR capacity is >= 128 in PostgreSQL."""
    length = pg_session.execute(text(
        "SELECT character_maximum_length FROM information_schema.columns "
        "WHERE table_name = 'alembic_version' AND column_name = 'version_num';"
    )).scalar()
    assert length is not None and length >= 128, (
        f"Alembic version column capacity insufficient: expected >= 128, found {length}"
    )


def test_all_27_application_tables_exist(pg_session: Session):
    """B2: Verify all 27 expected application tables exist in finora_test public schema."""
    expected_tables = {
        "alembic_version",
        "audit_logs",
        "canonical_bank_transactions",
        "canonical_orders",
        "canonical_payments",
        "canonical_refunds",
        "canonical_settlements",
        "fee_contracts",
        "fee_schedule_tiers",
        "forensic_claim_drafts",
        "forensic_dispatch_outbox",
        "forensic_investigations",
        "ingestion_batches",
        "leakage_detection_runs",
        "leakage_exception_evidence",
        "leakage_exception_reviews",
        "leakage_exceptions",
        "leakage_run_evidence",
        "leakage_run_exceptions",
        "reconciliation_allocations",
        "reconciliation_matches",
        "reconciliation_run_deltas",
        "reconciliation_runs",
        "source_row_errors",
        "tenant_memberships",
        "tenants",
        "users",
    }
    rows = pg_session.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public';"
    )).fetchall()
    actual_tables = {r[0] for r in rows}

    missing = expected_tables - actual_tables
    assert not missing, f"Missing expected PostgreSQL tables in finora_test: {missing}"
    assert len(actual_tables) == 27, f"Expected 27 tables, found {len(actual_tables)}: {actual_tables}"


def test_numeric_18_4_precision_on_financial_columns(pg_session: Session):
    """B2: Verify NUMERIC(18, 4) financial precision on key financial columns in PostgreSQL."""
    query = text("""
        SELECT table_name, column_name, numeric_precision, numeric_scale
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND column_name IN ('dispute_amount', 'leakage_amount', 'actual_amount', 'expected_amount', 'recoverable_amount')
        ORDER BY table_name, column_name;
    """)
    results = pg_session.execute(query).fetchall()
    assert len(results) > 0, "No financial NUMERIC columns found in information_schema!"

    for row in results:
        table_name, col_name, prec, scale = row
        assert prec == 18, f"Column {table_name}.{col_name} has precision {prec}, expected 18"
        assert scale == 4, f"Column {table_name}.{col_name} has scale {scale}, expected 4"


def test_check_constraints_enforced_in_postgresql(pg_session: Session):
    """B2: Verify check constraint chk_positive_dispute_amount is enforced by PostgreSQL engine."""
    # Attempt to insert a negative dispute amount directly via raw SQL
    t_id = uuid.uuid4()
    exc_id = uuid.uuid4()
    inv_id = uuid.uuid4()
    run_id = uuid.uuid4()
    draft_id = uuid.uuid4()

    # Create dummy tenant to satisfy foreign key
    pg_session.execute(
        text("INSERT INTO tenants (id, name, slug, default_currency, is_active, created_at, updated_at) "
             "VALUES (:id, 'Negative Test Tenant', :slug, 'INR', true, NOW(), NOW())"),
        {"id": t_id, "slug": f"neg-{uuid.uuid4().hex[:8]}"}
    )

    with pytest.raises(IntegrityError) as exc_info:
        pg_session.execute(
            text("""
                INSERT INTO forensic_claim_drafts (
                    id, tenant_id, exception_id, investigation_id, detection_run_id,
                    draft_number, status, dispute_amount, currency, target_entity,
                    target_reference, claim_summary, supporting_facts, evidence_references,
                    human_review_status, disclaimer, created_at, updated_at
                ) VALUES (
                    :id, :t_id, :exc_id, :inv_id, :run_id,
                    1, 'DRAFT', -50.0000, 'INR', 'RAZORPAY',
                    'ref_123', 'summary', '[]'::json, '[]'::json,
                    'PENDING_HUMAN_REVIEW', 'disclaimer', NOW(), NOW()
                )
            """),
            {"id": draft_id, "t_id": t_id, "exc_id": exc_id, "inv_id": inv_id, "run_id": run_id}
        )
    assert "chk_positive_dispute_amount" in str(exc_info.value).lower() or "check constraint" in str(exc_info.value).lower()
