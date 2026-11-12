"""phase5_forensic_investigations

Revision ID: 007_phase5_forensic_investigations
Revises: 006_tenant_financial_history_retention
Create Date: 2026-11-12 18:00:00.000000

Phase 5 Migration: AI Forensic Investigator & Root Cause Analysis
- Creates forensic_investigations for immutable investigation snapshots, evidence bundle
  fingerprints, structured root-cause analysis hypotheses, and model provenance.
- Creates forensic_claim_drafts for human-reviewable dispute claim drafts grounded in
  deterministic financial amounts and verified investigation facts.
- Enforces ON DELETE RESTRICT on all tenant foreign keys.
- Enforces fail-closed downgrade behavior to prevent data loss of immutable audit history.
- Fully portable across SQLite and PostgreSQL.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '007_phase5_forensic_investigations'
down_revision: Union[str, None] = '006_tenant_financial_history_retention'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128);"))

    # 1. Create forensic_investigations table
    op.create_table(
        'forensic_investigations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('exception_id', sa.Uuid(), nullable=False),
        sa.Column('detection_run_id', sa.Uuid(), nullable=False),
        sa.Column('idempotency_key', sa.String(100), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='PENDING'),
        sa.Column('conclusion', sa.String(50), nullable=False, server_default='INCONCLUSIVE'),
        sa.Column('confidence', sa.String(20), nullable=False, server_default='LOW'),
        sa.Column('summary', sa.Text(), nullable=False, server_default=''),
        sa.Column('evidence_bundle_fingerprint', sa.String(64), nullable=False),
        sa.Column('evidence_bundle_snapshot', sa.JSON(), nullable=False),
        sa.Column('investigation_result', sa.JSON(), nullable=True),
        sa.Column('model_provider', sa.String(50), nullable=False, server_default='mock'),
        sa.Column('model_name', sa.String(100), nullable=False, server_default='mock-forensic-v1'),
        sa.Column('prompt_version', sa.String(50), nullable=False, server_default='v1.0'),
        sa.Column('schema_version', sa.String(50), nullable=False, server_default='v1.0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['exception_id'], ['leakage_exceptions.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['detection_run_id'], ['leakage_detection_runs.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_forensic_inv_tenant_exc', 'forensic_investigations', ['tenant_id', 'exception_id'])
    op.create_index('ix_forensic_inv_tenant_run', 'forensic_investigations', ['tenant_id', 'detection_run_id'])
    op.create_index('ix_forensic_inv_idempotency', 'forensic_investigations', ['tenant_id', 'idempotency_key'])
    op.create_index(op.f('ix_forensic_investigations_tenant_id'), 'forensic_investigations', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_forensic_investigations_exception_id'), 'forensic_investigations', ['exception_id'], unique=False)
    op.create_index(op.f('ix_forensic_investigations_detection_run_id'), 'forensic_investigations', ['detection_run_id'], unique=False)
    op.create_index(op.f('ix_forensic_investigations_evidence_bundle_fingerprint'), 'forensic_investigations', ['evidence_bundle_fingerprint'], unique=False)

    # 2. Create forensic_claim_drafts table
    op.create_table(
        'forensic_claim_drafts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('exception_id', sa.Uuid(), nullable=False),
        sa.Column('investigation_id', sa.Uuid(), nullable=False),
        sa.Column('detection_run_id', sa.Uuid(), nullable=False),
        sa.Column('draft_number', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(50), nullable=False, server_default='DRAFT'),
        sa.Column('dispute_amount', sa.Numeric(18, 4), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='INR'),
        sa.Column('target_entity', sa.String(50), nullable=False),
        sa.Column('target_reference', sa.String(100), nullable=False),
        sa.Column('claim_summary', sa.Text(), nullable=False),
        sa.Column('supporting_facts', sa.JSON(), nullable=False),
        sa.Column('evidence_references', sa.JSON(), nullable=False),
        sa.Column('unresolved_questions', sa.JSON(), nullable=True),
        sa.Column('required_attachments', sa.JSON(), nullable=True),
        sa.Column('human_review_status', sa.String(50), nullable=False, server_default='PENDING_HUMAN_REVIEW'),
        sa.Column('disclaimer', sa.Text(), nullable=False),
        sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['exception_id'], ['leakage_exceptions.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['investigation_id'], ['forensic_investigations.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['detection_run_id'], ['leakage_detection_runs.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('dispute_amount >= 0', name='chk_positive_dispute_amount')
    )
    op.create_index('ix_claim_draft_tenant_exc', 'forensic_claim_drafts', ['tenant_id', 'exception_id'])
    op.create_index('ix_claim_draft_tenant_inv', 'forensic_claim_drafts', ['tenant_id', 'investigation_id'])
    op.create_index(op.f('ix_forensic_claim_drafts_tenant_id'), 'forensic_claim_drafts', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_forensic_claim_drafts_exception_id'), 'forensic_claim_drafts', ['exception_id'], unique=False)
    op.create_index(op.f('ix_forensic_claim_drafts_investigation_id'), 'forensic_claim_drafts', ['investigation_id'], unique=False)


def downgrade() -> None:
    raise RuntimeError(
        "Downgrading migration 007_phase5_forensic_investigations is strictly prohibited "
        "to prevent irreversible data loss of immutable forensic investigations and claim drafts."
    )
