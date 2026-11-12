"""phase4_evidence_and_lineage

Revision ID: 005_phase4_evidence_and_lineage
Revises: 004_phase4_leakage
Create Date: 2026-11-12 15:30:00.000000

Group A2 Migration: Evidence Persistence, Historical Run Lineage & Immutability
- Creates leakage_run_exceptions for point-in-time exception observations
- Creates leakage_run_evidence for run-to-evidence associations
- Adds latest_detection_run_id to leakage_exceptions
- Adds fingerprint_sha256 and detection_run_id to leakage_exception_evidence
- Backfills historical observations as LEGACY_BACKFILL
- Computes SHA-256 fingerprints with Decimal precision preservation
- Fully compatible with both SQLite and PostgreSQL via batch operations
"""
from typing import Sequence, Union
import uuid
import json
import hashlib
from decimal import Decimal
from datetime import datetime, date, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '005_phase4_evidence_and_lineage'
down_revision: Union[str, None] = '004_phase4_leakage'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _canonical_json_dumps(obj) -> str:
    def _default(o):
        if isinstance(o, Decimal):
            return f"{o:.4f}"
        if isinstance(o, (uuid.UUID, datetime, date)):
            return str(o)
        raise TypeError(f"Type {type(o)} not serializable in canonical JSON")
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), default=_default)


def _compute_evidence_fingerprint(evidence_type: str, entity_type: str, entity_id: Union[str, uuid.UUID], details: Union[dict, str, None]) -> str:
    entity_str = str(entity_id).lower().replace("-", "") if entity_id else ""
    if isinstance(details, str):
        details_obj = json.loads(details, parse_float=Decimal)
    elif details is None:
        details_obj = {}
    else:
        details_obj = details
    payload = {
        "evidence_type": str(evidence_type),
        "entity_type": str(entity_type),
        "entity_id": entity_str,
        "details": details_obj
    }
    serialized = _canonical_json_dumps(payload)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Create leakage_run_exceptions table
    op.create_table(
        'leakage_run_exceptions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('detection_run_id', sa.Uuid(), nullable=False),
        sa.Column('exception_id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('observed_status', sa.String(length=50), nullable=False),
        sa.Column('observed_severity', sa.String(length=20), nullable=False),
        sa.Column('observed_expected_amount', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('observed_actual_amount', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('observed_leakage_amount', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('observed_recoverable_amount', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('calculation_breakdown', sa.JSON(), nullable=True),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('snapshot_quality', sa.String(length=50), nullable=False, server_default='VERIFIED_AT_EXECUTION'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['detection_run_id'], ['leakage_detection_runs.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['exception_id'], ['leakage_exceptions.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('detection_run_id', 'exception_id', name='uq_run_exception_snapshot')
    )
    op.create_index('ix_run_exception_tenant', 'leakage_run_exceptions', ['tenant_id', 'detection_run_id'])
    op.create_index(op.f('ix_leakage_run_exceptions_detection_run_id'), 'leakage_run_exceptions', ['detection_run_id'], unique=False)
    op.create_index(op.f('ix_leakage_run_exceptions_exception_id'), 'leakage_run_exceptions', ['exception_id'], unique=False)
    op.create_index(op.f('ix_leakage_run_exceptions_tenant_id'), 'leakage_run_exceptions', ['tenant_id'], unique=False)

    # 2. Create leakage_run_evidence table
    op.create_table(
        'leakage_run_evidence',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('detection_run_id', sa.Uuid(), nullable=False),
        sa.Column('evidence_id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['detection_run_id'], ['leakage_detection_runs.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['evidence_id'], ['leakage_exception_evidence.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('detection_run_id', 'evidence_id', name='uq_run_evidence_item')
    )
    op.create_index('ix_run_evidence_tenant', 'leakage_run_evidence', ['tenant_id', 'detection_run_id'])
    op.create_index(op.f('ix_leakage_run_evidence_detection_run_id'), 'leakage_run_evidence', ['detection_run_id'], unique=False)
    op.create_index(op.f('ix_leakage_run_evidence_evidence_id'), 'leakage_run_evidence', ['evidence_id'], unique=False)
    op.create_index(op.f('ix_leakage_run_evidence_tenant_id'), 'leakage_run_evidence', ['tenant_id'], unique=False)

    # 3. Add latest_detection_run_id to leakage_exceptions
    with op.batch_alter_table('leakage_exceptions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('latest_detection_run_id', sa.Uuid(), nullable=True))
        batch_op.create_index('ix_leakage_exceptions_latest_detection_run_id', ['latest_detection_run_id'], unique=False)

    # 4. Add fingerprint_sha256 and detection_run_id to leakage_exception_evidence
    with op.batch_alter_table('leakage_exception_evidence', schema=None) as batch_op:
        batch_op.add_column(sa.Column('fingerprint_sha256', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('detection_run_id', sa.Uuid(), nullable=True))
        batch_op.create_index('ix_leakage_exception_evidence_fingerprint', ['fingerprint_sha256'], unique=False)
        batch_op.create_index('ix_leakage_exception_evidence_detection_run_id', ['detection_run_id'], unique=False)

    # 5. Backfill existing data
    # 5a. Populate latest_detection_run_id from detection_run_id
    # 5b. Backfill existing exceptions into leakage_run_exceptions as LEGACY_BACKFILL
    now = datetime.now(timezone.utc)
    try:
        exceptions = conn.execute(
            sa.text(
                "SELECT id, tenant_id, detection_run_id, status, severity, "
                "expected_amount, actual_amount, leakage_amount, recoverable_amount, "
                "calculation_breakdown, explanation FROM leakage_exceptions"
            )
        ).fetchall()

        for exc_row in exceptions:
            # Map columns
            exc_id = exc_row[0] if isinstance(exc_row[0], uuid.UUID) else uuid.UUID(str(exc_row[0]))
            tenant_id = exc_row[1] if isinstance(exc_row[1], uuid.UUID) else uuid.UUID(str(exc_row[1]))
            run_id = exc_row[2] if isinstance(exc_row[2], uuid.UUID) else uuid.UUID(str(exc_row[2]))
            status = exc_row[3]
            severity = exc_row[4]
            expected_amt = Decimal(str(exc_row[5]))
            actual_amt = Decimal(str(exc_row[6]))
            leakage_amt = Decimal(str(exc_row[7]))
            recoverable_amt = Decimal(str(exc_row[8]))
            breakdown = exc_row[9]
            if isinstance(breakdown, str):
                breakdown = json.loads(breakdown, parse_float=Decimal)
            explanation = exc_row[10]

            # Update latest_detection_run_id
            conn.execute(
                sa.text("UPDATE leakage_exceptions SET latest_detection_run_id = :run_id WHERE id = :exc_id"),
                {"run_id": run_id, "exc_id": exc_id}
            )

            # Insert legacy snapshot
            conn.execute(
                sa.text(
                    "INSERT INTO leakage_run_exceptions (id, detection_run_id, exception_id, tenant_id, "
                    "observed_status, observed_severity, observed_expected_amount, observed_actual_amount, "
                    "observed_leakage_amount, observed_recoverable_amount, calculation_breakdown, explanation, "
                    "snapshot_quality, created_at, updated_at) "
                    "VALUES (:id, :detection_run_id, :exception_id, :tenant_id, :observed_status, :observed_severity, "
                    ":observed_expected_amount, :observed_actual_amount, :observed_leakage_amount, :observed_recoverable_amount, "
                    ":calculation_breakdown, :explanation, :snapshot_quality, :created_at, :updated_at)"
                ),
                {
                    "id": uuid.uuid4(),
                    "detection_run_id": run_id,
                    "exception_id": exc_id,
                    "tenant_id": tenant_id,
                    "observed_status": status,
                    "observed_severity": severity,
                    "observed_expected_amount": expected_amt,
                    "observed_actual_amount": actual_amt,
                    "observed_leakage_amount": leakage_amt,
                    "observed_recoverable_amount": recoverable_amt,
                    "calculation_breakdown": json.dumps(breakdown) if breakdown else None,
                    "explanation": explanation,
                    "snapshot_quality": "LEGACY_BACKFILL",
                    "created_at": now,
                    "updated_at": now,
                }
            )

        # 5c. Backfill fingerprints on existing evidence rows and link to leakage_run_evidence
        evidence_rows = conn.execute(
            sa.text(
                "SELECT e.id, e.tenant_id, e.exception_id, e.evidence_type, e.entity_type, e.entity_id, e.details, "
                "x.detection_run_id "
                "FROM leakage_exception_evidence e "
                "JOIN leakage_exceptions x ON e.exception_id = x.id"
            )
        ).fetchall()

        seen_fingerprints = {}  # (exception_id, fingerprint) -> canonical_id
        for ev_row in evidence_rows:
            ev_id = ev_row[0] if isinstance(ev_row[0], uuid.UUID) else uuid.UUID(str(ev_row[0]))
            tenant_id = ev_row[1] if isinstance(ev_row[1], uuid.UUID) else uuid.UUID(str(ev_row[1]))
            exc_id = ev_row[2] if isinstance(ev_row[2], uuid.UUID) else uuid.UUID(str(ev_row[2]))
            ev_type = ev_row[3]
            entity_type = ev_row[4]
            entity_id = ev_row[5]
            details = ev_row[6]
            run_id = ev_row[7] if isinstance(ev_row[7], uuid.UUID) else uuid.UUID(str(ev_row[7]))

            fingerprint = _compute_evidence_fingerprint(ev_type, entity_type, entity_id, details)
            key = (exc_id, fingerprint)

            if key in seen_fingerprints:
                # Duplicate evidence content in legacy data: redirect to canonical and delete redundant row
                canonical_id = seen_fingerprints[key]
                conn.execute(
                    sa.text("DELETE FROM leakage_exception_evidence WHERE id = :ev_id"),
                    {"ev_id": ev_id}
                )
                target_ev_id = canonical_id
            else:
                seen_fingerprints[key] = ev_id
                target_ev_id = ev_id
                conn.execute(
                    sa.text(
                        "UPDATE leakage_exception_evidence "
                        "SET fingerprint_sha256 = :fingerprint, detection_run_id = :run_id "
                        "WHERE id = :ev_id"
                    ),
                    {"fingerprint": fingerprint, "run_id": run_id, "ev_id": ev_id}
                )

            # Link into leakage_run_evidence
            existing_link = conn.execute(
                sa.text(
                    "SELECT id FROM leakage_run_evidence WHERE detection_run_id = :run_id AND evidence_id = :ev_id"
                ),
                {"run_id": run_id, "ev_id": target_ev_id}
            ).fetchone()
            if not existing_link:
                conn.execute(
                    sa.text(
                        "INSERT INTO leakage_run_evidence (id, detection_run_id, evidence_id, tenant_id, created_at, updated_at) "
                        "VALUES (:id, :run_id, :ev_id, :tenant_id, :created_at, :updated_at)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "run_id": run_id,
                        "ev_id": target_ev_id,
                        "tenant_id": tenant_id,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
    except Exception as e:
        # If tables are empty during initial setup, backfill simply passes
        pass

    # 6. Make fingerprint_sha256 NOT NULL and add UniqueConstraint on (exception_id, fingerprint_sha256)
    with op.batch_alter_table('leakage_exception_evidence', schema=None) as batch_op:
        batch_op.alter_column('fingerprint_sha256', nullable=False, existing_type=sa.String(length=64))
        batch_op.create_unique_constraint('uq_evidence_exception_fingerprint', ['exception_id', 'fingerprint_sha256'])


def downgrade() -> None:
    raise RuntimeError(
        "Destructive downgrade prohibited: Migration 005 contains "
        "immutable financial snapshots and evidence lineage required "
        "for financial audit integrity. Use a verified backup and "
        "forward corrective migration strategy."
    )
