"""phase3_reconciliation_and_fee_models

Revision ID: 003_phase3_reconciliation
Revises: 002_phase2_ingestion
Create Date: 2026-11-12 04:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '003_phase3_reconciliation'
down_revision: Union[str, None] = '002_phase2_ingestion'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Fee Contracts Table
    op.create_table(
        'fee_contracts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('gateway_name', sa.String(length=50), nullable=False, server_default='RAZORPAY'),
        sa.Column('contract_name', sa.String(length=100), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('gst_rate', sa.Numeric(precision=8, scale=6), nullable=False, server_default='0.180000'),
        sa.Column('chargeback_dispute_fee', sa.Numeric(precision=18, scale=4), nullable=False, server_default='500.0000'),
        sa.Column('rolling_reserve_percentage', sa.Numeric(precision=8, scale=6), nullable=False, server_default='0.000000'),
        sa.Column('rolling_reserve_hold_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('retain_mdr_on_refund', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('instant_refund_flat_fee', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('instant_refund_percentage_fee', sa.Numeric(precision=8, scale=6), nullable=False, server_default='0.000000'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_fee_contracts_tenant', 'fee_contracts', ['tenant_id', 'gateway_name', 'is_active'])

    # 2. Fee Schedule Tiers Table
    op.create_table(
        'fee_schedule_tiers',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('contract_id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('instrument_type', sa.String(length=50), nullable=False),
        sa.Column('percentage_rate', sa.Numeric(precision=8, scale=6), nullable=False, server_default='0.020000'),
        sa.Column('fixed_fee_per_txn', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('min_fee_cap', sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column('max_fee_cap', sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['contract_id'], ['fee_contracts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_fee_schedule_tiers_contract_inst', 'fee_schedule_tiers', ['contract_id', 'instrument_type'])

    # 3. Reconciliation Runs Table
    op.create_table(
        'reconciliation_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('run_number', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='PENDING'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('triggered_by_user_id', sa.Uuid(), nullable=True),
        sa.Column('parameters', sa.JSON(), nullable=True),
        sa.Column('total_orders_evaluated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_payments_evaluated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_settlements_evaluated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_bank_transactions_evaluated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('matched_orders_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('matched_payments_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('matched_settlements_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('matched_bank_txs_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unmatched_orders_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unmatched_payments_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unmatched_settlements_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unmatched_bank_txs_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ambiguous_matches_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unresolved_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_order_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('total_captured_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('total_settled_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('total_matched_bank_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('total_discrepancy_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('total_fee_drift_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['triggered_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'run_number', name='uq_tenant_recon_run_number')
    )
    op.create_index('ix_recon_runs_tenant', 'reconciliation_runs', ['tenant_id', 'run_number'])

    # 4. Reconciliation Matches Table
    op.create_table(
        'reconciliation_matches',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('run_id', sa.Uuid(), nullable=False),
        sa.Column('match_type', sa.String(length=50), nullable=False),
        sa.Column('classification', sa.String(length=50), nullable=False),
        sa.Column('pass_number', sa.Integer(), nullable=False),
        sa.Column('confidence_score', sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column('order_id', sa.Uuid(), nullable=True),
        sa.Column('payment_id', sa.Uuid(), nullable=True),
        sa.Column('settlement_id', sa.Uuid(), nullable=True),
        sa.Column('bank_transaction_id', sa.Uuid(), nullable=True),
        sa.Column('source_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('target_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('allocated_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('discrepancy_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('expected_fee', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('expected_tax', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('fee_discrepancy', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('evidence_metadata', sa.JSON(), nullable=True),
        sa.Column('review_status', sa.String(length=50), nullable=False, server_default='NOT_REQUIRED'),
        sa.Column('reviewed_by_user_id', sa.Uuid(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_action', sa.String(length=50), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['run_id'], ['reconciliation_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['order_id'], ['canonical_orders.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['payment_id'], ['canonical_payments.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['settlement_id'], ['canonical_settlements.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['bank_transaction_id'], ['canonical_bank_transactions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_recon_matches_tenant_run', 'reconciliation_matches', ['tenant_id', 'run_id'])
    op.create_index('ix_recon_matches_classification', 'reconciliation_matches', ['tenant_id', 'classification'])

    # 5. Reconciliation Allocations Table
    op.create_table(
        'reconciliation_allocations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('run_id', sa.Uuid(), nullable=False),
        sa.Column('match_id', sa.Uuid(), nullable=False),
        sa.Column('source_entity_type', sa.String(length=50), nullable=False),
        sa.Column('source_entity_id', sa.Uuid(), nullable=False),
        sa.Column('target_entity_type', sa.String(length=50), nullable=False),
        sa.Column('target_entity_id', sa.Uuid(), nullable=False),
        sa.Column('allocated_amount', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='ACTIVE'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['run_id'], ['reconciliation_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['match_id'], ['reconciliation_matches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('allocated_amount > 0', name='chk_positive_allocated_amount')
    )
    op.create_index('ix_recon_alloc_tenant_run', 'reconciliation_allocations', ['tenant_id', 'run_id'])
    op.create_index('ix_recon_alloc_source', 'reconciliation_allocations', ['tenant_id', 'source_entity_type', 'source_entity_id'])
    op.create_index('ix_recon_alloc_target', 'reconciliation_allocations', ['tenant_id', 'target_entity_type', 'target_entity_id'])

    # 6. Reconciliation Run Deltas Table
    op.create_table(
        'reconciliation_run_deltas',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('current_run_id', sa.Uuid(), nullable=False),
        sa.Column('previous_run_id', sa.Uuid(), nullable=False),
        sa.Column('delta_type', sa.String(length=50), nullable=False),
        sa.Column('match_id', sa.Uuid(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['current_run_id'], ['reconciliation_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['previous_run_id'], ['reconciliation_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['match_id'], ['reconciliation_matches.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_recon_run_deltas_tenant', 'reconciliation_run_deltas', ['tenant_id', 'current_run_id', 'previous_run_id'])


def downgrade() -> None:
    op.drop_table('reconciliation_run_deltas')
    op.drop_table('reconciliation_allocations')
    op.drop_table('reconciliation_matches')
    op.drop_table('reconciliation_runs')
    op.drop_table('fee_schedule_tiers')
    op.drop_table('fee_contracts')
