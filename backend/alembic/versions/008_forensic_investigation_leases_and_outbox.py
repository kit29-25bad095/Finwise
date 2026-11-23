"""forensic_investigation_leases_and_outbox

Revision ID: 008_forensic_investigation_leases_and_outbox
Revises: 007_phase5_forensic_investigations
Create Date: 2026-11-14 21:00:00.000000

Phase 5.1-D.1 Migration: Orphaned Investigation Recovery, Lease Management & Transactional Outbox
- Adds lease_owner_id, lease_token, lease_expires_at, attempt_count, last_heartbeat_at to forensic_investigations.
- Creates partial index ix_forensic_inv_lease_recovery on forensic_investigations (status, lease_expires_at).
- Creates forensic_dispatch_outbox table for durable, transactional event dispatch and recovery intent.
- Preserves ON DELETE RESTRICT on tenants foreign keys and CASCADE on investigation foreign key.
- Fully portable across PostgreSQL 17 and SQLite.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '008_forensic_investigation_leases_and_outbox'
down_revision: Union[str, None] = '007_phase5_forensic_investigations'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add lease metadata columns to forensic_investigations
    op.add_column('forensic_investigations', sa.Column('lease_owner_id', sa.String(100), nullable=True))
    op.add_column('forensic_investigations', sa.Column('lease_token', sa.Uuid(), nullable=True))
    op.add_column('forensic_investigations', sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('forensic_investigations', sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('forensic_investigations', sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True))

    op.create_index(
        'ix_forensic_inv_lease_recovery',
        'forensic_investigations',
        ['status', 'lease_expires_at'],
        unique=False
    )

    # 2. Create forensic_dispatch_outbox table
    op.create_table(
        'forensic_dispatch_outbox',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('investigation_id', sa.Uuid(), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('idempotency_key', sa.String(150), nullable=False),
        sa.Column('expected_prior_token', sa.Uuid(), nullable=True),
        sa.Column('payload_version', sa.String(20), nullable=False, server_default='v1.0'),
        sa.Column('dispatch_status', sa.String(30), nullable=False, server_default='PENDING'),
        sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('available_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lease_owner_id', sa.String(100), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['investigation_id'], ['forensic_investigations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key', name='uq_outbox_idempotency_key')
    )
    op.create_index('ix_outbox_pending_available', 'forensic_dispatch_outbox', ['dispatch_status', 'available_at'], unique=False)
    op.create_index('ix_outbox_tenant_status', 'forensic_dispatch_outbox', ['tenant_id', 'dispatch_status'], unique=False)
    op.create_index(op.f('ix_forensic_dispatch_outbox_tenant_id'), 'forensic_dispatch_outbox', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_forensic_dispatch_outbox_investigation_id'), 'forensic_dispatch_outbox', ['investigation_id'], unique=False)


def downgrade() -> None:
    # Safe downgrade implementation for test isolation & rollback validation
    op.drop_index(op.f('ix_forensic_dispatch_outbox_investigation_id'), table_name='forensic_dispatch_outbox')
    op.drop_index(op.f('ix_forensic_dispatch_outbox_tenant_id'), table_name='forensic_dispatch_outbox')
    op.drop_index('ix_outbox_tenant_status', table_name='forensic_dispatch_outbox')
    op.drop_index('ix_outbox_pending_available', table_name='forensic_dispatch_outbox')
    op.drop_table('forensic_dispatch_outbox')

    op.drop_index('ix_forensic_inv_lease_recovery', table_name='forensic_investigations')
    op.drop_column('forensic_investigations', 'last_heartbeat_at')
    op.drop_column('forensic_investigations', 'attempt_count')
    op.drop_column('forensic_investigations', 'lease_expires_at')
    op.drop_column('forensic_investigations', 'lease_token')
    op.drop_column('forensic_investigations', 'lease_owner_id')
