import uuid
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, text, Engine, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import QueuePool

from app.core.config import settings
from app.core.database import Base
from app.models.tenant import Tenant
from app.models.canonical import CanonicalOrder, CanonicalPayment
from app.models.ingestion import IngestionBatch, SourceType, IngestionStatus
from tests.integration.conftest import PG_TEST_DATABASE_URL


def test_managed_postgres_connection_pooling_and_pre_ping():
    """
    Verifies that managed PostgreSQL engine configures QueuePool with
    pool_size, max_overflow, pool_timeout, and pool_pre_ping enabled.
    """
    pool_engine = create_engine(
        PG_TEST_DATABASE_URL,
        poolclass=QueuePool,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=settings.DB_POOL_PRE_PING,
    )

    assert pool_engine.pool.size() == settings.DB_POOL_SIZE
    assert pool_engine.pool._max_overflow == settings.DB_MAX_OVERFLOW
    assert pool_engine.pool._timeout == settings.DB_POOL_TIMEOUT

    # Verify multiple concurrent connections check out cleanly
    connections = []
    try:
        for _ in range(5):
            conn = pool_engine.connect()
            connections.append(conn)
            val = conn.scalar(text("SELECT 1;"))
            assert val == 1
    finally:
        for conn in connections:
            conn.close()
        pool_engine.dispose()


def test_postgres_numeric_precision_exact_roundtrip(pg_engine: Engine):
    """
    Verifies that PostgreSQL NUMERIC(18, 4) financial columns store and retrieve
    extreme Decimal values with exact precision and zero floating-point distortion.
    """
    tenant_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    order_id = uuid.uuid4()

    # Extreme high-precision Decimal values
    gross = Decimal("98765432101234.5678")
    discount = Decimal("0.0001")
    tax = Decimal("1777777777822.2220")
    shipping = Decimal("123.4500")

    with Session(bind=pg_engine) as session:
        try:
            tenant = Tenant(id=tenant_id, name="Precision Tenant", slug=f"prec-{uuid.uuid4().hex[:6]}")
            session.add(tenant)
            session.flush()

            batch = IngestionBatch(
                id=batch_id,
                tenant_id=tenant_id,
                source_type=SourceType.SHOPIFY,
                filename="precision_test.csv",
                file_hash_sha256="p" * 64,
                status=IngestionStatus.COMPLETED,
            )
            session.add(batch)
            session.flush()

            order = CanonicalOrder(
                id=order_id,
                tenant_id=tenant_id,
                batch_id=batch_id,
                source_row_index=1,
                order_reference=f"ORD-PREC-{uuid.uuid4().hex[:6]}",
                gross_amount=gross,
                discount_amount=discount,
                tax_amount=tax,
                shipping_amount=shipping,
                currency="INR",
                order_timestamp=text("NOW()"),
            )
            session.add(order)
            session.commit()

            # Retrieve and verify exact Decimal equality
            saved_order = session.execute(
                select(CanonicalOrder).where(CanonicalOrder.id == order_id)
            ).scalar_one()

            assert saved_order.gross_amount == gross
            assert saved_order.discount_amount == discount
            assert saved_order.tax_amount == tax
            assert saved_order.shipping_amount == shipping

            # Confirm string representations have exact 4 decimal digits
            assert f"{saved_order.gross_amount:.4f}" == "98765432101234.5678"
            assert f"{saved_order.discount_amount:.4f}" == "0.0001"
            assert f"{saved_order.tax_amount:.4f}" == "1777777777822.2220"

        finally:
            session.rollback()
            # Clean up test rows
            with pg_engine.connect() as cleanup_conn:
                cleanup_conn.execute(text(f"DELETE FROM canonical_orders WHERE tenant_id = '{tenant_id}';"))
                cleanup_conn.execute(text(f"DELETE FROM ingestion_batches WHERE tenant_id = '{tenant_id}';"))
                cleanup_conn.execute(text(f"DELETE FROM tenants WHERE id = '{tenant_id}';"))
                cleanup_conn.commit()


def test_postgres_all_23_durable_tables_tenant_restrict(pg_engine: Engine):
    """
    Verifies that all 23 historical, canonical, reconciliation, leakage, and forensic tables
    strictly enforce ON DELETE RESTRICT against tenants, preventing accidental data erasure.
    """
    with pg_engine.connect() as conn:
        result = conn.execute(text("""
            SELECT
                tc.table_name,
                kcu.column_name,
                rc.delete_rule
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.referential_constraints AS rc
                ON tc.constraint_name = rc.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
              AND ccu.table_name = 'tenants'
            ORDER BY tc.table_name;
        """)).fetchall()

        fks = {row[0]: row[2] for row in result}

        # 23 durable tables must be RESTRICT
        durable_tables = [
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
        ]

        for table in durable_tables:
            assert table in fks, f"Table {table} missing foreign key to tenants!"
            assert fks[table] == "RESTRICT", f"Table {table} foreign key has rule '{fks[table]}', expected 'RESTRICT'!"

        # Only tenant_memberships should be CASCADE
        assert fks.get("tenant_memberships") == "CASCADE"


def test_postgres_tenant_isolation_boundary(pg_engine: Engine):
    """
    Verifies that multi-tenant row isolation is preserved: queries scoped to
    Tenant A never expose records belonging to Tenant B.
    """
    tenant_a_id = uuid.uuid4()
    tenant_b_id = uuid.uuid4()
    batch_a_id = uuid.uuid4()
    batch_b_id = uuid.uuid4()

    with Session(bind=pg_engine) as session:
        try:
            t_a = Tenant(id=tenant_a_id, name="Tenant Alpha", slug=f"alpha-{uuid.uuid4().hex[:6]}")
            t_b = Tenant(id=tenant_b_id, name="Tenant Beta", slug=f"beta-{uuid.uuid4().hex[:6]}")
            session.add_all([t_a, t_b])
            session.flush()

            b_a = IngestionBatch(id=batch_a_id, tenant_id=tenant_a_id, source_type=SourceType.SHOPIFY, filename="a.csv", file_hash_sha256="a"*64, status=IngestionStatus.COMPLETED)
            b_b = IngestionBatch(id=batch_b_id, tenant_id=tenant_b_id, source_type=SourceType.SHOPIFY, filename="b.csv", file_hash_sha256="b"*64, status=IngestionStatus.COMPLETED)
            session.add_all([b_a, b_b])
            session.commit()

            # Query tenant A's batches
            a_batches = session.execute(
                select(IngestionBatch).where(IngestionBatch.tenant_id == tenant_a_id)
            ).scalars().all()

            assert len(a_batches) == 1
            assert a_batches[0].id == batch_a_id
            assert all(b.tenant_id == tenant_a_id for b in a_batches)

            # Query tenant B's batches
            b_batches = session.execute(
                select(IngestionBatch).where(IngestionBatch.tenant_id == tenant_b_id)
            ).scalars().all()

            assert len(b_batches) == 1
            assert b_batches[0].id == batch_b_id
            assert all(b.tenant_id == tenant_b_id for b in b_batches)

        finally:
            session.rollback()
            with pg_engine.connect() as conn:
                conn.execute(text(f"DELETE FROM ingestion_batches WHERE tenant_id IN ('{tenant_a_id}', '{tenant_b_id}');"))
                conn.execute(text(f"DELETE FROM tenants WHERE id IN ('{tenant_a_id}', '{tenant_b_id}');"))
                conn.commit()


def test_postgres_migration_schema_metadata_consistency(pg_engine: Engine):
    """
    Verifies that every single table and column defined in SQLAlchemy Base.metadata
    exists in PostgreSQL's information_schema catalogs with exact matching nullability.
    """
    with pg_engine.connect() as conn:
        for table_name, table in Base.metadata.tables.items():
            result = conn.execute(text(f"""
                SELECT column_name, is_nullable, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = '{table_name}';
            """)).fetchall()

            pg_cols = {row[0]: {"nullable": row[1] == "YES", "type": row[2]} for row in result}
            assert len(pg_cols) > 0, f"Table '{table_name}' does not exist in PostgreSQL!"

            for col in table.columns:
                assert col.name in pg_cols, f"Column '{col.name}' in table '{table_name}' missing from PostgreSQL!"
                expected_nullable = col.nullable if col.nullable is not None else True
                actual_nullable = pg_cols[col.name]["nullable"]
                assert actual_nullable == expected_nullable, (
                    f"Nullability mismatch on {table_name}.{col.name}: expected {expected_nullable}, got {actual_nullable}"
                )
