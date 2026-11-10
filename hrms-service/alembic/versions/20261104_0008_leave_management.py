"""Module 6: leave management, permission and overtime requests.

Adds tables only. No Module 1-5 table is changed. Reuses hrms_append_only()
(0007) and hrms_reject_code_change() (0003).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-04 03:54:25.563030+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

APPEND_ONLY = ("leave_ledger_entry", "request_event", "leave_routing_event", "leave_workflow_history")

# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('leave_approval_workflow',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('scope', sa.String(length=12), nullable=False),
    sa.Column('department_ids', postgresql.ARRAY(sa.UUID()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('first_approver', sa.String(length=20), nullable=False),
    sa.Column('fallback_approver', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
    sa.Column('escalation', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('notifications', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("first_approver IN ('reporting_manager', 'department_head')", name=op.f('ck_leave_approval_workflow_first_approver')),
    sa.CheckConstraint("scope IN ('company', 'departments')", name=op.f('ck_leave_approval_workflow_scope')),
    sa.CheckConstraint("status IN ('draft', 'active', 'inactive')", name=op.f('ck_leave_approval_workflow_status')),
    sa.CheckConstraint('effective_to IS NULL OR effective_to >= effective_from', name=op.f('ck_leave_approval_workflow_dates')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_leave_approval_workflow'))
    )
    op.create_table('leave_type',
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('paid', sa.Boolean(), nullable=False),
    sa.Column('allow_half_day', sa.Boolean(), nullable=False),
    sa.Column('balance_tracked', sa.Boolean(), nullable=False),
    sa.Column('attachment_after_days', sa.Integer(), nullable=True),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("code ~ '^[A-Za-z0-9_-]{1,20}$'", name=op.f('ck_leave_type_code_format')),
    sa.CheckConstraint('attachment_after_days IS NULL OR attachment_after_days >= 0', name=op.f('ck_leave_type_attachment_days')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_leave_type')),
    sa.UniqueConstraint('code', name=op.f('uq_leave_type_code'))
    )
    op.create_table('notification_outbox',
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('message', sa.String(length=1000), nullable=False),
    sa.Column('link', sa.String(length=300), nullable=True),
    sa.Column('employee_ids', postgresql.ARRAY(sa.UUID()), nullable=False),
    sa.Column('user_ids', postgresql.ARRAY(sa.String(length=100)), nullable=False),
    sa.Column('role_codes', postgresql.ARRAY(sa.String(length=100)), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.String(length=500), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'delivered', 'failed')", name=op.f('ck_notification_outbox_status')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notification_outbox'))
    )
    op.create_index('ix_notification_outbox_status', 'notification_outbox', ['status', 'next_attempt_at'], unique=False)
    op.create_table('request_event',
    sa.Column('request_kind', sa.String(length=10), nullable=False),
    sa.Column('request_id', sa.UUID(), nullable=False),
    sa.Column('action', sa.String(length=10), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.CheckConstraint("action IN ('submitted', 'approved', 'rejected', 'cancelled', 'updated', 'commented')", name=op.f('ck_request_event_action')),
    sa.CheckConstraint("request_kind IN ('leave', 'permission', 'overtime')", name=op.f('ck_request_event_request_kind')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_request_event'))
    )
    op.create_index('ix_request_event_request', 'request_event', ['request_kind', 'request_id', 'created_at'], unique=False)
    op.create_table('holiday',
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('type', sa.String(length=10), nullable=False),
    sa.Column('work_location_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("type IN ('national', 'festival', 'company')", name=op.f('ck_holiday_type')),
    sa.ForeignKeyConstraint(['work_location_id'], ['work_location.id'], name=op.f('fk_holiday_work_location_id_work_location'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_holiday'))
    )
    op.create_index('uq_holiday_company_date', 'holiday', ['date'], unique=True, postgresql_where=sa.text('work_location_id IS NULL'))
    op.create_index('uq_holiday_location_date', 'holiday', ['date', 'work_location_id'], unique=True, postgresql_where=sa.text('work_location_id IS NOT NULL'))
    op.create_table('leave_policy',
    sa.Column('leave_type_id', sa.UUID(), nullable=False),
    sa.Column('accrual_method', sa.String(length=10), nullable=False),
    sa.Column('accrual_days', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('carry_forward_allowed', sa.Boolean(), nullable=False),
    sa.Column('carry_forward_max_days', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('employment_type_ids', postgresql.ARRAY(sa.UUID()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('department_ids', postgresql.ARRAY(sa.UUID()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('allow_half_day', sa.Boolean(), nullable=True),
    sa.Column('attachment_after_days', sa.Integer(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("accrual_method <> 'none' OR accrual_days = 0", name=op.f('ck_leave_policy_none_has_no_days')),
    sa.CheckConstraint("accrual_method IN ('annual', 'monthly', 'none')", name=op.f('ck_leave_policy_accrual_method')),
    sa.CheckConstraint('accrual_days >= 0', name=op.f('ck_leave_policy_accrual_days')),
    sa.CheckConstraint('carry_forward_max_days IS NULL OR carry_forward_max_days >= 0', name=op.f('ck_leave_policy_carry_forward_max')),
    sa.CheckConstraint('effective_to IS NULL OR effective_to >= effective_from', name=op.f('ck_leave_policy_dates')),
    sa.ForeignKeyConstraint(['leave_type_id'], ['leave_type.id'], name=op.f('fk_leave_policy_leave_type_id_leave_type'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_leave_policy'))
    )
    op.create_index(op.f('ix_leave_policy_leave_type_id'), 'leave_policy', ['leave_type_id'], unique=False)
    op.create_table('leave_workflow_history',
    sa.Column('workflow_id', sa.UUID(), nullable=False),
    sa.Column('workflow_version', sa.Integer(), nullable=False),
    sa.Column('action', sa.String(length=12), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['workflow_id'], ['leave_approval_workflow.id'], name=op.f('fk_leave_workflow_history_workflow_id_leave_approval_workflow'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_leave_workflow_history'))
    )
    op.create_index(op.f('ix_leave_workflow_history_workflow_id'), 'leave_workflow_history', ['workflow_id'], unique=False)
    op.create_table('leave_request',
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('leave_type_id', sa.UUID(), nullable=False),
    sa.Column('from_date', sa.Date(), nullable=False),
    sa.Column('to_date', sa.Date(), nullable=False),
    sa.Column('portion', sa.String(length=12), nullable=False),
    sa.Column('days', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('days_by_year', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('charged_dates', postgresql.ARRAY(sa.Date()), nullable=False),
    sa.Column('reason', sa.String(length=500), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('workflow_id', sa.UUID(), nullable=True),
    sa.Column('workflow_snapshot', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
    sa.Column('approver_kind', sa.String(length=20), nullable=True),
    sa.Column('approver_employee_id', sa.UUID(), nullable=True),
    sa.Column('approver_ref', sa.String(length=100), nullable=True),
    sa.Column('approver_name', sa.String(length=200), nullable=True),
    sa.Column('recipient_kind', sa.String(length=10), nullable=True),
    sa.Column('recipient_ref', sa.String(length=100), nullable=True),
    sa.Column('recipient_name', sa.String(length=200), nullable=True),
    sa.Column('escalation_due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reminder_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reminder_sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('escalated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('stage', sa.String(length=12), nullable=False),
    sa.Column('reviewed_by_name', sa.String(length=200), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_comment', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("portion = 'full' OR from_date = to_date", name=op.f('ck_leave_request_half_day_single')),
    sa.CheckConstraint("portion IN ('full', 'first_half', 'second_half')", name=op.f('ck_leave_request_portion')),
    sa.CheckConstraint("stage IN ('first_level', 'escalated', 'completed', 'withdrawn')", name=op.f('ck_leave_request_stage')),
    sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'cancelled')", name=op.f('ck_leave_request_status')),
    sa.CheckConstraint('days > 0', name=op.f('ck_leave_request_days_positive')),
    sa.CheckConstraint('to_date >= from_date', name=op.f('ck_leave_request_dates')),
    sa.ForeignKeyConstraint(['approver_employee_id'], ['employee.id'], name=op.f('fk_leave_request_approver_employee_id_employee'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], name=op.f('fk_leave_request_employee_id_employee'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['leave_type_id'], ['leave_type.id'], name=op.f('fk_leave_request_leave_type_id_leave_type'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['workflow_id'], ['leave_approval_workflow.id'], name=op.f('fk_leave_request_workflow_id_leave_approval_workflow'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_leave_request'))
    )
    op.create_index('ix_leave_request_employee_dates', 'leave_request', ['employee_id', 'from_date', 'to_date'], unique=False)
    op.create_index('ix_leave_request_status_created', 'leave_request', ['status', 'created_at'], unique=False)
    op.create_table('overtime_request',
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('minutes', sa.Integer(), nullable=False),
    sa.Column('reason', sa.String(length=300), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('workflow_id', sa.UUID(), nullable=True),
    sa.Column('workflow_version', sa.Integer(), nullable=True),
    sa.Column('steps', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('current_step', sa.Integer(), nullable=True),
    sa.Column('step_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('escalated', sa.Boolean(), nullable=False),
    sa.Column('reviewed_by_name', sa.String(length=200), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_comment', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'cancelled')", name=op.f('ck_overtime_request_status')),
    sa.CheckConstraint('minutes BETWEEN 1 AND 960', name=op.f('ck_overtime_request_minutes')),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], name=op.f('fk_overtime_request_employee_id_employee'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflow.id'], name=op.f('fk_overtime_request_workflow_id_workflow'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_overtime_request'))
    )
    op.create_index('ix_overtime_request_employee_date', 'overtime_request', ['employee_id', 'date'], unique=False)
    op.create_table('permission_request',
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('from_time', sa.String(length=5), nullable=False),
    sa.Column('to_time', sa.String(length=5), nullable=False),
    sa.Column('minutes', sa.Integer(), nullable=False),
    sa.Column('reason', sa.String(length=300), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('reviewed_by_name', sa.String(length=200), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_comment', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'cancelled')", name=op.f('ck_permission_request_status')),
    sa.CheckConstraint('to_time > from_time AND minutes > 0', name=op.f('ck_permission_request_times')),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], name=op.f('fk_permission_request_employee_id_employee'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_permission_request'))
    )
    op.create_index('ix_permission_request_employee_date', 'permission_request', ['employee_id', 'date'], unique=False)
    op.create_table('leave_ledger_entry',
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('leave_type_id', sa.UUID(), nullable=False),
    sa.Column('leave_year', sa.Integer(), nullable=False),
    sa.Column('entry_type', sa.String(length=15), nullable=False),
    sa.Column('days', sa.Numeric(precision=7, scale=2), nullable=False),
    sa.Column('leave_request_id', sa.UUID(), nullable=True),
    sa.Column('leave_policy_id', sa.UUID(), nullable=True),
    sa.Column('reason', sa.String(length=500), nullable=True),
    sa.Column('period_key', sa.String(length=120), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.CheckConstraint("entry_type IN ('allocation', 'accrual', 'carry_forward', 'lapse', 'usage', 'usage_reversal', 'adjustment')", name=op.f('ck_leave_ledger_entry_entry_type')),
    sa.CheckConstraint("entry_type NOT IN ('adjustment', 'allocation') OR reason IS NOT NULL OR period_key IS NOT NULL", name=op.f('ck_leave_ledger_entry_manual_needs_reason')),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], name=op.f('fk_leave_ledger_entry_employee_id_employee'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['leave_policy_id'], ['leave_policy.id'], name=op.f('fk_leave_ledger_entry_leave_policy_id_leave_policy'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['leave_request_id'], ['leave_request.id'], name=op.f('fk_leave_ledger_entry_leave_request_id_leave_request'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['leave_type_id'], ['leave_type.id'], name=op.f('fk_leave_ledger_entry_leave_type_id_leave_type'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_leave_ledger_entry'))
    )
    op.create_index('ix_leave_ledger_employee_year', 'leave_ledger_entry', ['employee_id', 'leave_type_id', 'leave_year'], unique=False)
    op.create_index('uq_leave_ledger_period', 'leave_ledger_entry', ['employee_id', 'leave_type_id', 'period_key'], unique=True, postgresql_where=sa.text('period_key IS NOT NULL'))
    op.create_table('leave_request_attachment',
    sa.Column('leave_request_id', sa.UUID(), nullable=False),
    sa.Column('file_name', sa.String(length=200), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('storage_key', sa.String(length=32), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['leave_request_id'], ['leave_request.id'], name=op.f('fk_leave_request_attachment_leave_request_id_leave_request'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_leave_request_attachment')),
    sa.UniqueConstraint('storage_key', name=op.f('uq_leave_request_attachment_storage_key'))
    )
    op.create_index(op.f('ix_leave_request_attachment_leave_request_id'), 'leave_request_attachment', ['leave_request_id'], unique=False)
    op.create_table('leave_routing_event',
    sa.Column('leave_request_id', sa.UUID(), nullable=False),
    sa.Column('action', sa.String(length=15), nullable=False),
    sa.Column('detail', sa.String(length=500), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.CheckConstraint("action IN ('assigned', 'reminder_sent', 'escalated')", name=op.f('ck_leave_routing_event_action')),
    sa.ForeignKeyConstraint(['leave_request_id'], ['leave_request.id'], name=op.f('fk_leave_routing_event_leave_request_id_leave_request'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_leave_routing_event'))
    )
    op.create_index(op.f('ix_leave_routing_event_leave_request_id'), 'leave_routing_event', ['leave_request_id'], unique=False)
    for table in APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_no_update_delete BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION hrms_append_only()")
        op.execute(f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION hrms_append_only()")
    op.execute(
        "CREATE TRIGGER leave_type_code_stable BEFORE UPDATE OF code ON leave_type "
        "FOR EACH ROW WHEN (OLD.code IS DISTINCT FROM NEW.code) EXECUTE FUNCTION hrms_reject_code_change('code');"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS leave_type_code_stable ON leave_type")
    for table in APPEND_ONLY:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update_delete ON {table}")
    op.drop_index(op.f('ix_leave_routing_event_leave_request_id'), table_name='leave_routing_event')
    op.drop_table('leave_routing_event')
    op.drop_index(op.f('ix_leave_request_attachment_leave_request_id'), table_name='leave_request_attachment')
    op.drop_table('leave_request_attachment')
    op.drop_index('uq_leave_ledger_period', table_name='leave_ledger_entry', postgresql_where=sa.text('period_key IS NOT NULL'))
    op.drop_index('ix_leave_ledger_employee_year', table_name='leave_ledger_entry')
    op.drop_table('leave_ledger_entry')
    op.drop_index('ix_permission_request_employee_date', table_name='permission_request')
    op.drop_table('permission_request')
    op.drop_index('ix_overtime_request_employee_date', table_name='overtime_request')
    op.drop_table('overtime_request')
    op.drop_index('ix_leave_request_status_created', table_name='leave_request')
    op.drop_index('ix_leave_request_employee_dates', table_name='leave_request')
    op.drop_table('leave_request')
    op.drop_index(op.f('ix_leave_workflow_history_workflow_id'), table_name='leave_workflow_history')
    op.drop_table('leave_workflow_history')
    op.drop_index(op.f('ix_leave_policy_leave_type_id'), table_name='leave_policy')
    op.drop_table('leave_policy')
    op.drop_index('uq_holiday_location_date', table_name='holiday', postgresql_where=sa.text('work_location_id IS NOT NULL'))
    op.drop_index('uq_holiday_company_date', table_name='holiday', postgresql_where=sa.text('work_location_id IS NULL'))
    op.drop_table('holiday')
    op.drop_index('ix_request_event_request', table_name='request_event')
    op.drop_table('request_event')
    op.drop_index('ix_notification_outbox_status', table_name='notification_outbox')
    op.drop_table('notification_outbox')
    op.drop_table('leave_type')
    op.drop_table('leave_approval_workflow')
