"""phase4_leakage_detection_models

Revision ID: 004_phase4_leakage
Revises: 003_phase3_reconciliation
Create Date: 2026-11-12 10:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '004_phase4_leakage'
down_revision: Union[str, None] = '003_phase3_reconciliation'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Leakage Detection Runs Table
    op.create_table(
        'leakage_detection_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('run_number', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='PENDING'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('triggered_by_user_id', sa.Uuid(), nullable=True),
        sa.Column('reconciliation_run_id', sa.Uuid(), nullable=True),
        sa.Column('parameters', sa.JSON(), nullable=True),
        sa.Column('total_captures_evaluated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_settlements_evaluated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_refunds_evaluated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('exceptions_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_leakage_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('total_potential_recovery', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['triggered_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reconciliation_run_id'], ['reconciliation_runs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'run_number', name='uq_tenant_leakage_run_number')
    )
    op.create_index('ix_leakage_run_tenant', 'leakage_detection_runs', ['tenant_id', 'run_number'])
    op.create_index('ix_leakage_run_status', 'leakage_detection_runs', ['tenant_id', 'status'])
    op.create_index(op.f('ix_leakage_detection_runs_tenant_id'), 'leakage_detection_runs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_leakage_detection_runs_reconciliation_run_id'), 'leakage_detection_runs', ['reconciliation_run_id'], unique=False)

    # 2. Leakage Exceptions Table
    op.create_table(
        'leakage_exceptions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('detection_run_id', sa.Uuid(), nullable=False),
        sa.Column('detector_type', sa.String(length=50), nullable=False),
        sa.Column('exception_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='OPEN'),
        sa.Column('severity', sa.String(length=20), nullable=False, server_default='MEDIUM'),
        sa.Column('severity_reason', sa.Text(), nullable=False),
        sa.Column('source_entity_type', sa.String(length=50), nullable=False),
        sa.Column('source_entity_id', sa.Uuid(), nullable=False),
        sa.Column('source_reference', sa.String(length=100), nullable=False),
        sa.Column('order_reference', sa.String(length=100), nullable=True),
        sa.Column('gateway_name', sa.String(length=50), nullable=False, server_default='RAZORPAY'),
        sa.Column('expected_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('actual_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('leakage_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('recoverable_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='INR'),
        sa.Column('calculation_breakdown', sa.JSON(), nullable=True),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('detector_version', sa.String(length=20), nullable=False, server_default='1.0.0'),
        sa.Column('rule_version', sa.String(length=50), nullable=False, server_default='FINORA-DETECTORS-V3'),
        sa.Column('contract_id', sa.Uuid(), nullable=True),
        sa.Column('contract_version', sa.Integer(), nullable=True),
        sa.Column('reviewed_by_user_id', sa.Uuid(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_action', sa.String(length=50), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('leakage_amount >= 0', name='chk_positive_leakage_amount'),
        sa.CheckConstraint('recoverable_amount >= 0', name='chk_positive_recoverable_amount'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['detection_run_id'], ['leakage_detection_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['contract_id'], ['fee_contracts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_leakage_exc_tenant_detector', 'leakage_exceptions', ['tenant_id', 'detector_type'])
    op.create_index('ix_leakage_exc_tenant_status', 'leakage_exceptions', ['tenant_id', 'status'])
    op.create_index('ix_leakage_exc_tenant_severity', 'leakage_exceptions', ['tenant_id', 'severity'])
    op.create_index('ix_leakage_exc_source', 'leakage_exceptions', ['tenant_id', 'source_entity_type', 'source_entity_id'])
    op.create_index(op.f('ix_leakage_exceptions_tenant_id'), 'leakage_exceptions', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_leakage_exceptions_detection_run_id'), 'leakage_exceptions', ['detection_run_id'], unique=False)
    op.create_index(op.f('ix_leakage_exceptions_source_entity_id'), 'leakage_exceptions', ['source_entity_id'], unique=False)

    # 3. Leakage Exception Evidence Table
    op.create_table(
        'leakage_exception_evidence',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('exception_id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('evidence_type', sa.String(length=50), nullable=False),
        sa.Column('entity_type', sa.String(length=50), nullable=False),
        sa.Column('entity_id', sa.Uuid(), nullable=False),
        sa.Column('source_batch_id', sa.Uuid(), nullable=True),
        sa.Column('source_row_index', sa.Integer(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['exception_id'], ['leakage_exceptions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_evidence_exception', 'leakage_exception_evidence', ['exception_id', 'evidence_type'])
    op.create_index('ix_evidence_entity', 'leakage_exception_evidence', ['tenant_id', 'entity_type', 'entity_id'])
    op.create_index(op.f('ix_leakage_exception_evidence_exception_id'), 'leakage_exception_evidence', ['exception_id'], unique=False)
    op.create_index(op.f('ix_leakage_exception_evidence_tenant_id'), 'leakage_exception_evidence', ['tenant_id'], unique=False)

    # 4. Leakage Exception Reviews Table
    op.create_table(
        'leakage_exception_reviews',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('exception_id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('reviewer_id', sa.Uuid(), nullable=True),
        sa.Column('from_status', sa.String(length=50), nullable=False),
        sa.Column('to_status', sa.String(length=50), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['exception_id'], ['leakage_exceptions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reviewer_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_review_exception', 'leakage_exception_reviews', ['exception_id'])
    op.create_index('ix_review_tenant', 'leakage_exception_reviews', ['tenant_id'])
    op.create_index(op.f('ix_leakage_exception_reviews_exception_id'), 'leakage_exception_reviews', ['exception_id'], unique=False)
    op.create_index(op.f('ix_leakage_exception_reviews_tenant_id'), 'leakage_exception_reviews', ['tenant_id'], unique=False)

    # Relax uq_tenant_gateway_refund_id to support multi-record lifecycle retry records and duplicate reference detection
    try:
        op.drop_constraint('uq_tenant_gateway_refund_id', 'canonical_refunds', type_='unique')
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.create_unique_constraint('uq_tenant_gateway_refund_id', 'canonical_refunds', ['tenant_id', 'gateway_refund_id'])
    except Exception:
        pass
    op.drop_table('leakage_exception_reviews')
    op.drop_table('leakage_exception_evidence')
    op.drop_table('leakage_exceptions')
    op.drop_table('leakage_detection_runs')
