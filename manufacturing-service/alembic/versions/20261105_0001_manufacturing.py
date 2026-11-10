"""Manufacturing schema: shop-floor route, sales orders, work orders with stage records, materials and history; audit log.

The audit log and the work-order history are append-only (trigger).

Revision ID: 0001
Revises: 
Create Date: 2026-11-05 09:45:24.823035+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

APPEND_ONLY = ("audit_log", "work_order_event")

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('audit_log',
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('actor_user_id', sa.String(length=100), nullable=False),
    sa.Column('actor_name', sa.String(length=200), nullable=False),
    sa.Column('module', sa.String(length=50), nullable=False),
    sa.Column('action', sa.String(length=80), nullable=False),
    sa.Column('entity_type', sa.String(length=80), nullable=True),
    sa.Column('entity_id', sa.String(length=100), nullable=True),
    sa.Column('entity_label', sa.String(length=200), nullable=True),
    sa.Column('result', sa.String(length=10), nullable=False),
    sa.Column('request_id', sa.String(length=100), nullable=True),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    op.create_index('ix_audit_log_actor_user_id', 'audit_log', ['actor_user_id'], unique=False)
    op.create_index('ix_audit_log_created_at', 'audit_log', ['created_at'], unique=False)
    op.create_index('ix_audit_log_entity', 'audit_log', ['entity_type', 'entity_id'], unique=False)
    op.create_index('ix_audit_log_module_action', 'audit_log', ['module', 'action'], unique=False)
    op.create_index('ix_audit_log_request_id', 'audit_log', ['request_id'], unique=False)
    op.create_table('sales_order',
    sa.Column('order_no', sa.String(length=40), nullable=False),
    sa.Column('customer_name', sa.String(length=200), nullable=False),
    sa.Column('rating_kva', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=False),
    sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("status IN ('draft', 'confirmed', 'in_design', 'in_production', 'testing', 'ready_to_dispatch', 'dispatched', 'on_hold')", name=op.f('ck_sales_order_status')),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_sales_order_quantity')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sales_order')),
    sa.UniqueConstraint('order_no', name=op.f('uq_sales_order_order_no'))
    )
    op.create_table('work_order_stage',
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('label', sa.String(length=80), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_order_stage')),
    sa.UniqueConstraint('code', name=op.f('uq_work_order_stage_code')),
    sa.UniqueConstraint('sequence', name=op.f('uq_work_order_stage_sequence'))
    )
    op.create_table('work_order',
    sa.Column('work_order_no', sa.String(length=40), nullable=False),
    sa.Column('sales_order_id', sa.UUID(), nullable=False),
    sa.Column('unit_index', sa.Integer(), nullable=False),
    sa.Column('unit_of', sa.Integer(), nullable=False),
    sa.Column('rating_kva', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('voltage_ratio', sa.String(length=40), nullable=False),
    sa.Column('vector_group', sa.String(length=20), nullable=False),
    sa.Column('cooling', sa.String(length=20), nullable=False),
    sa.Column('design_ref', sa.String(length=60), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('stage_id', sa.UUID(), nullable=False),
    sa.Column('priority', sa.String(length=6), nullable=False),
    sa.Column('work_centre', sa.String(length=80), nullable=False),
    sa.Column('planned_start', sa.Date(), nullable=False),
    sa.Column('planned_finish', sa.Date(), nullable=False),
    sa.Column('customer_due_date', sa.Date(), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('schedule_status', sa.String(length=10), nullable=False),
    sa.Column('variance_days', sa.Integer(), nullable=False),
    sa.Column('blocker_type', sa.String(length=12), nullable=True),
    sa.Column('blocker_description', sa.Text(), nullable=True),
    sa.Column('blocker_since', sa.Date(), nullable=True),
    sa.Column('next_action_label', sa.String(length=200), nullable=False),
    sa.Column('next_action_owner_id', sa.String(length=60), nullable=False),
    sa.Column('next_action_owner_name', sa.String(length=160), nullable=False),
    sa.Column('next_action_owner_role', sa.String(length=80), nullable=False),
    sa.Column('next_action_due', sa.Date(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("blocker_type IS NULL OR blocker_type IN ('material', 'quality', 'engineering', 'capacity')", name=op.f('ck_work_order_blocker_type')),
    sa.CheckConstraint("priority IN ('high', 'normal')", name=op.f('ck_work_order_priority')),
    sa.CheckConstraint("schedule_status IN ('on_track', 'at_risk', 'delayed')", name=op.f('ck_work_order_schedule_status')),
    sa.CheckConstraint("status IN ('not_started', 'in_progress', 'on_hold', 'completed')", name=op.f('ck_work_order_status')),
    sa.CheckConstraint('(blocker_type IS NULL) = (blocker_since IS NULL)', name=op.f('ck_work_order_blocker_complete')),
    sa.CheckConstraint('planned_finish >= planned_start', name=op.f('ck_work_order_dates')),
    sa.CheckConstraint('unit_index BETWEEN 1 AND unit_of', name=op.f('ck_work_order_unit')),
    sa.ForeignKeyConstraint(['sales_order_id'], ['sales_order.id'], name=op.f('fk_work_order_sales_order_id_sales_order'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['stage_id'], ['work_order_stage.id'], name=op.f('fk_work_order_stage_id_work_order_stage'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_order')),
    sa.UniqueConstraint('work_order_no', name=op.f('uq_work_order_work_order_no'))
    )
    op.create_index(op.f('ix_work_order_sales_order_id'), 'work_order', ['sales_order_id'], unique=False)
    op.create_index(op.f('ix_work_order_stage_id'), 'work_order', ['stage_id'], unique=False)
    op.create_index('ix_work_order_status_due', 'work_order', ['status', 'customer_due_date'], unique=False)
    op.create_table('work_order_event',
    sa.Column('work_order_id', sa.UUID(), nullable=False),
    sa.Column('summary', sa.String(length=500), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['work_order_id'], ['work_order.id'], name=op.f('fk_work_order_event_work_order_id_work_order'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_order_event'))
    )
    op.create_index(op.f('ix_work_order_event_work_order_id'), 'work_order_event', ['work_order_id'], unique=False)
    op.create_table('work_order_material',
    sa.Column('work_order_id', sa.UUID(), nullable=False),
    sa.Column('item', sa.String(length=200), nullable=False),
    sa.Column('required', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('expected_date', sa.Date(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.CheckConstraint("status IN ('issued', 'available', 'short', 'on_order')", name=op.f('ck_work_order_material_status')),
    sa.ForeignKeyConstraint(['work_order_id'], ['work_order.id'], name=op.f('fk_work_order_material_work_order_id_work_order'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_order_material'))
    )
    op.create_index(op.f('ix_work_order_material_work_order_id'), 'work_order_material', ['work_order_id'], unique=False)
    op.create_table('work_order_stage_record',
    sa.Column('work_order_id', sa.UUID(), nullable=False),
    sa.Column('stage_id', sa.UUID(), nullable=False),
    sa.Column('state', sa.String(length=8), nullable=False),
    sa.Column('started_at', sa.Date(), nullable=True),
    sa.Column('completed_at', sa.Date(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.CheckConstraint("state IN ('done', 'current', 'pending')", name=op.f('ck_work_order_stage_record_state')),
    sa.ForeignKeyConstraint(['stage_id'], ['work_order_stage.id'], name=op.f('fk_work_order_stage_record_stage_id_work_order_stage'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['work_order_id'], ['work_order.id'], name=op.f('fk_work_order_stage_record_work_order_id_work_order'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_order_stage_record')),
    sa.UniqueConstraint('work_order_id', 'stage_id', name='uq_work_order_stage_record')
    )
    op.execute(
        """
        CREATE FUNCTION manufacturing_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
        END;
        $$
        """
    )
    for table in APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_no_update_delete BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION manufacturing_append_only()")
        op.execute(f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION manufacturing_append_only()")


def downgrade() -> None:
    for table in APPEND_ONLY:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update_delete ON {table}")
    op.drop_table('work_order_stage_record')
    op.drop_index(op.f('ix_work_order_material_work_order_id'), table_name='work_order_material')
    op.drop_table('work_order_material')
    op.drop_index(op.f('ix_work_order_event_work_order_id'), table_name='work_order_event')
    op.drop_table('work_order_event')
    op.drop_index('ix_work_order_status_due', table_name='work_order')
    op.drop_index(op.f('ix_work_order_stage_id'), table_name='work_order')
    op.drop_index(op.f('ix_work_order_sales_order_id'), table_name='work_order')
    op.drop_table('work_order')
    op.drop_table('work_order_stage')
    op.drop_table('sales_order')
    op.drop_index('ix_audit_log_request_id', table_name='audit_log')
    op.drop_index('ix_audit_log_module_action', table_name='audit_log')
    op.drop_index('ix_audit_log_entity', table_name='audit_log')
    op.drop_index('ix_audit_log_created_at', table_name='audit_log')
    op.drop_index('ix_audit_log_actor_user_id', table_name='audit_log')
    op.drop_table('audit_log')
    op.execute("DROP FUNCTION IF EXISTS manufacturing_append_only()")
