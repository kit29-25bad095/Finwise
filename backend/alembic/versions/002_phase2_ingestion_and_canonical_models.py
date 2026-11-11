"""phase2_ingestion_and_canonical_models

Revision ID: 002_phase2_ingestion
Revises: 001_initial_phase1
Create Date: 2026-11-12 03:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '002_phase2_ingestion'
down_revision: Union[str, None] = '001_initial_phase1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Ingestion Batches Table
    op.create_table(
        'ingestion_batches',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=True),
        sa.Column('source_type', sa.String(length=50), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('file_hash_sha256', sa.String(length=64), nullable=False),
        sa.Column('file_size_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='UPLOADED'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('total_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('valid_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('invalid_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('duplicate_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('warning_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('processing_duration_ms', sa.Integer(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ingestion_tenant_status', 'ingestion_batches', ['tenant_id', 'status'])
    op.create_index('ix_ingestion_tenant_hash', 'ingestion_batches', ['tenant_id', 'file_hash_sha256'])

    # 2. Source Row Errors Table
    op.create_table(
        'source_row_errors',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('batch_id', sa.Uuid(), nullable=False),
        sa.Column('row_index', sa.Integer(), nullable=False),
        sa.Column('error_level', sa.String(length=20), nullable=False, server_default='ERROR'),
        sa.Column('field_name', sa.String(length=100), nullable=True),
        sa.Column('raw_value', sa.Text(), nullable=True),
        sa.Column('error_code', sa.String(length=50), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('raw_record', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['batch_id'], ['ingestion_batches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_row_error_tenant_batch', 'source_row_errors', ['tenant_id', 'batch_id'])

    # 3. Canonical Orders Table
    op.create_table(
        'canonical_orders',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('batch_id', sa.Uuid(), nullable=False),
        sa.Column('source_row_index', sa.Integer(), nullable=False),
        sa.Column('order_reference', sa.String(length=100), nullable=False),
        sa.Column('order_number', sa.String(length=100), nullable=True),
        sa.Column('customer_reference', sa.String(length=255), nullable=True),
        sa.Column('gross_amount', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('discount_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('tax_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('shipping_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='INR'),
        sa.Column('fulfillment_status', sa.String(length=50), nullable=True),
        sa.Column('financial_status', sa.String(length=50), nullable=True),
        sa.Column('order_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('payment_gateway_names', sa.String(length=255), nullable=True),
        sa.Column('payment_references', sa.Text(), nullable=True),
        sa.Column('raw_source_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['batch_id'], ['ingestion_batches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'order_reference', name='uq_tenant_order_reference')
    )
    op.create_index('ix_orders_tenant_ref', 'canonical_orders', ['tenant_id', 'order_reference'])
    op.create_index('ix_orders_tenant_date', 'canonical_orders', ['tenant_id', 'order_timestamp'])

    # 4. Canonical Payments Table
    op.create_table(
        'canonical_payments',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('batch_id', sa.Uuid(), nullable=False),
        sa.Column('source_row_index', sa.Integer(), nullable=False),
        sa.Column('gateway_name', sa.String(length=50), nullable=False, server_default='RAZORPAY'),
        sa.Column('gateway_payment_id', sa.String(length=100), nullable=False),
        sa.Column('gateway_order_id', sa.String(length=100), nullable=True),
        sa.Column('order_reference', sa.String(length=100), nullable=True),
        sa.Column('payment_method', sa.String(length=50), nullable=True),
        sa.Column('card_network', sa.String(length=50), nullable=True),
        sa.Column('card_type', sa.String(length=50), nullable=True),
        sa.Column('captured_amount', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('reported_fee', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('reported_tax', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='INR'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='captured'),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('unallocated_balance', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('raw_source_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['batch_id'], ['ingestion_batches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'gateway_payment_id', name='uq_tenant_gateway_payment_id')
    )
    op.create_index('ix_payments_tenant_payid', 'canonical_payments', ['tenant_id', 'gateway_payment_id'])
    op.create_index('ix_payments_tenant_captured_at', 'canonical_payments', ['tenant_id', 'captured_at'])

    # 5. Canonical Settlements Table
    op.create_table(
        'canonical_settlements',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('batch_id', sa.Uuid(), nullable=False),
        sa.Column('source_row_index', sa.Integer(), nullable=False),
        sa.Column('gateway_name', sa.String(length=50), nullable=False, server_default='RAZORPAY'),
        sa.Column('settlement_reference', sa.String(length=100), nullable=False),
        sa.Column('utr_number', sa.String(length=100), nullable=True),
        sa.Column('gross_amount', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('total_fee', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('total_tax', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('total_refunds', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('total_adjustments', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('net_settlement_amount', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('unallocated_balance', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='settled'),
        sa.Column('settled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('raw_source_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['batch_id'], ['ingestion_batches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'settlement_reference', name='uq_tenant_settlement_reference')
    )
    op.create_index('ix_settle_tenant_ref', 'canonical_settlements', ['tenant_id', 'settlement_reference'])
    op.create_index('ix_settle_tenant_utr', 'canonical_settlements', ['tenant_id', 'utr_number'])

    # 6. Canonical Refunds Table
    op.create_table(
        'canonical_refunds',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('batch_id', sa.Uuid(), nullable=False),
        sa.Column('source_row_index', sa.Integer(), nullable=False),
        sa.Column('gateway_refund_id', sa.String(length=100), nullable=False),
        sa.Column('gateway_payment_id', sa.String(length=100), nullable=True),
        sa.Column('order_reference', sa.String(length=100), nullable=True),
        sa.Column('refund_amount', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='INR'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='processed'),
        sa.Column('initiated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('raw_source_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['batch_id'], ['ingestion_batches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'gateway_refund_id', name='uq_tenant_gateway_refund_id')
    )
    op.create_index('ix_refunds_tenant_refid', 'canonical_refunds', ['tenant_id', 'gateway_refund_id'])

    # 7. Canonical Bank Transactions Table
    op.create_table(
        'canonical_bank_transactions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('batch_id', sa.Uuid(), nullable=False),
        sa.Column('source_row_index', sa.Integer(), nullable=False),
        sa.Column('bank_name', sa.String(length=50), nullable=False, server_default='HDFC'),
        sa.Column('bank_reference', sa.String(length=100), nullable=True),
        sa.Column('extracted_utr', sa.String(length=100), nullable=True),
        sa.Column('raw_narration', sa.Text(), nullable=False),
        sa.Column('transaction_date', sa.Date(), nullable=False),
        sa.Column('value_date', sa.Date(), nullable=True),
        sa.Column('credit_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('debit_amount', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0.0000'),
        sa.Column('running_balance', sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column('unallocated_balance', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('raw_source_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['batch_id'], ['ingestion_batches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_bank_tenant_date', 'canonical_bank_transactions', ['tenant_id', 'transaction_date'])
    op.create_index('ix_bank_tenant_utr', 'canonical_bank_transactions', ['tenant_id', 'extracted_utr'])
    op.create_index('ix_bank_tenant_ref', 'canonical_bank_transactions', ['tenant_id', 'bank_reference'])


def downgrade() -> None:
    op.drop_table('canonical_bank_transactions')
    op.drop_table('canonical_refunds')
    op.drop_table('canonical_settlements')
    op.drop_table('canonical_payments')
    op.drop_table('canonical_orders')
    op.drop_table('source_row_errors')
    op.drop_table('ingestion_batches')
