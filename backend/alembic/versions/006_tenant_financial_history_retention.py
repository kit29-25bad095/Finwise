"""tenant_financial_history_retention

Revision ID: 006_tenant_financial_history_retention
Revises: 005_phase4_evidence_and_lineage
Create Date: 2026-11-12 16:30:00.000000

Group A2.1 Migration: Financial History Retention & Tenant Deletion Protection
- Modifies foreign key constraints referencing tenants.id across all 20 historical,
  canonical, reconciliation, leakage detection, and audit tables.
- Changes ondelete from CASCADE to RESTRICT to enforce the financial invariant:
  'Physical tenant deletion must not erase historical financial records.'
- Fails closed on downgrade to prevent accidental reintroduction of cascading deletion.
- Fully compatible with SQLite (via batch_alter_table) and PostgreSQL.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '006_tenant_financial_history_retention'
down_revision: Union[str, None] = '005_phase4_evidence_and_lineage'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Complete inventory of 20 durable financial, reconciliation, audit, and provenance tables
TABLES_TO_PROTECT = [
    # Audit Logs
    "audit_logs",
    # Ingestion & Source Provenance
    "ingestion_batches",
    "source_row_errors",
    # Canonical Financial Records
    "canonical_orders",
    "canonical_payments",
    "canonical_settlements",
    "canonical_refunds",
    "canonical_bank_transactions",
    # Fee Contracts & Reconciliation
    "fee_contracts",
    "fee_schedule_tiers",
    "reconciliation_runs",
    "reconciliation_matches",
    "reconciliation_allocations",
    "reconciliation_run_deltas",
    # Leakage Detection Runs, Exceptions & Evidence Lineage
    "leakage_detection_runs",
    "leakage_exceptions",
    "leakage_exception_evidence",
    "leakage_exception_reviews",
    "leakage_run_exceptions",
    "leakage_run_evidence",
]


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    # Defensive guard: Widen alembic_version column to VARCHAR(128) on PostgreSQL
    # before Alembic updates alembic_version to this revision (38 characters).
    if dialect_name == "postgresql":
        bind.execute(sa.text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128);"))

    if dialect_name == "sqlite":
        naming_convention = {
            'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s',
        }
        for tbl in TABLES_TO_PROTECT:
            with op.batch_alter_table(tbl, naming_convention=naming_convention) as batch_op:
                batch_op.drop_constraint(f'fk_{tbl}_tenant_id_tenants', type_='foreignkey')
                batch_op.create_foreign_key(
                    f'fk_{tbl}_tenant_id_tenants',
                    'tenants',
                    ['tenant_id'],
                    ['id'],
                    ondelete='RESTRICT'
                )
    else:
        # PostgreSQL / generic SQL engines
        for tbl in TABLES_TO_PROTECT:
            # Query actual constraint name dynamically to ensure portability
            try:
                row = bind.execute(sa.text(
                    "SELECT tc.constraint_name "
                    "FROM information_schema.table_constraints tc "
                    "JOIN information_schema.key_column_usage kcu "
                    "  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
                    "WHERE tc.table_name = :tbl "
                    "  AND tc.constraint_type = 'FOREIGN KEY' "
                    "  AND kcu.column_name = 'tenant_id'"
                ), {"tbl": tbl}).fetchone()
                constraint_name = row[0] if row else f"{tbl}_tenant_id_fkey"
            except Exception:
                constraint_name = f"{tbl}_tenant_id_fkey"

            op.drop_constraint(constraint_name, tbl, type_='foreignkey')
            op.create_foreign_key(
                f"fk_{tbl}_tenant_id_tenants",
                tbl,
                'tenants',
                ['tenant_id'],
                ['id'],
                ondelete='RESTRICT'
            )


def downgrade() -> None:
    raise RuntimeError(
        "Destructive downgrade prohibited: Migration 006 enforces "
        "financial-history retention constraints (ON DELETE RESTRICT) on all "
        "tenant foreign keys. Reverting this migration would reintroduce cascading "
        "deletion of historical financial and audit records."
    )
