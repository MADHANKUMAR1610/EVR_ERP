"""Module 7: payroll (components, structures, salaries, periods, results, payslips, configurations).

Adds tables only. Reuses hrms_append_only() (0007) and hrms_reject_code_change() (0003).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-05 04:56:16.043745+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

APPEND_ONLY = ("employee_salary", "payroll_period_event", "payroll_assignment_history")

# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('payroll_period',
    sa.Column('month', sa.String(length=7), nullable=False),
    sa.Column('from_date', sa.Date(), nullable=False),
    sa.Column('to_date', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('employees_included', sa.Integer(), nullable=True),
    sa.Column('validation', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
    sa.Column('validated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('calculated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('submitted_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f('ck_payroll_period_currency_format')),
    sa.CheckConstraint("month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name=op.f('ck_payroll_period_month_format')),
    sa.CheckConstraint("status IN ('open', 'validated', 'calculated', 'submitted', 'approved', 'rejected', 'payslips_published')", name=op.f('ck_payroll_period_status')),
    sa.CheckConstraint('to_date >= from_date', name=op.f('ck_payroll_period_dates')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_period')),
    sa.UniqueConstraint('month', name=op.f('uq_payroll_period_month'))
    )
    op.create_table('salary_component',
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('type', sa.String(length=25), nullable=False),
    sa.Column('formula', sa.String(length=20), nullable=False),
    sa.Column('rate', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('base', postgresql.ARRAY(sa.String(length=20)), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('base_cap', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('max_amount', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('slabs', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('prorate', sa.Boolean(), nullable=False),
    sa.Column('taxable', sa.Boolean(), nullable=True),
    sa.Column('statutory', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("code ~ '^[A-Z0-9_-]{1,20}$'", name=op.f('ck_salary_component_code_format')),
    sa.CheckConstraint("formula IN ('fixed', 'percent', 'balance_of_gross', 'overtime_rate', 'slab')", name=op.f('ck_salary_component_formula')),
    sa.CheckConstraint("type IN ('earning', 'deduction', 'employer_contribution')", name=op.f('ck_salary_component_type')),
    sa.CheckConstraint('base_cap IS NULL OR base_cap >= 0', name=op.f('ck_salary_component_base_cap')),
    sa.CheckConstraint('max_amount IS NULL OR max_amount >= 0', name=op.f('ck_salary_component_max_amount')),
    sa.CheckConstraint('rate IS NULL OR rate >= 0', name=op.f('ck_salary_component_rate')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_salary_component')),
    sa.UniqueConstraint('code', name=op.f('uq_salary_component_code'))
    )
    op.create_table('salary_structure',
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('component_ids', postgresql.ARRAY(sa.UUID()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("code ~ '^[A-Z0-9_-]{1,20}$'", name=op.f('ck_salary_structure_code_format')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_salary_structure')),
    sa.UniqueConstraint('code', name=op.f('uq_salary_structure_code'))
    )
    op.create_table('payroll_configuration',
    sa.Column('code', sa.String(length=12), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('frequency', sa.String(length=15), nullable=False),
    sa.Column('structure_id', sa.UUID(), nullable=True),
    sa.Column('component_ids', postgresql.ARRAY(sa.UUID()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('overtime_eligible', sa.Boolean(), nullable=False),
    sa.Column('overtime_policy_id', sa.UUID(), nullable=True),
    sa.Column('attendance_rule_id', sa.UUID(), nullable=True),
    sa.Column('loss_of_pay_rule', sa.String(length=40), nullable=True),
    sa.Column('employee_category_ids', postgresql.ARRAY(sa.UUID()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('approval_workflow_id', sa.UUID(), nullable=True),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("frequency IN ('monthly', 'semi_monthly', 'biweekly', 'weekly')", name=op.f('ck_payroll_configuration_frequency')),
    sa.CheckConstraint("status IN ('active', 'inactive')", name=op.f('ck_payroll_configuration_status')),
    sa.CheckConstraint('char_length(code) BETWEEN 2 AND 12', name=op.f('ck_payroll_configuration_code_length')),
    sa.CheckConstraint('effective_to IS NULL OR effective_to >= effective_from', name=op.f('ck_payroll_configuration_dates')),
    sa.ForeignKeyConstraint(['approval_workflow_id'], ['workflow.id'], name=op.f('fk_payroll_configuration_approval_workflow_id_workflow'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['attendance_rule_id'], ['attendance_policy_option.id'], name=op.f('fk_payroll_configuration_attendance_rule_id_attendance_policy_option'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['overtime_policy_id'], ['overtime_policy_option.id'], name=op.f('fk_payroll_configuration_overtime_policy_id_overtime_policy_option'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['structure_id'], ['salary_structure.id'], name=op.f('fk_payroll_configuration_structure_id_salary_structure'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_configuration')),
    sa.UniqueConstraint('code', name=op.f('uq_payroll_configuration_code'))
    )
    op.create_table('payroll_period_event',
    sa.Column('period_id', sa.UUID(), nullable=False),
    sa.Column('action', sa.String(length=10), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.CheckConstraint("action IN ('submitted', 'approved', 'rejected', 'cancelled', 'updated', 'commented')", name=op.f('ck_payroll_period_event_action')),
    sa.ForeignKeyConstraint(['period_id'], ['payroll_period.id'], name=op.f('fk_payroll_period_event_period_id_payroll_period'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_period_event'))
    )
    op.create_index(op.f('ix_payroll_period_event_period_id'), 'payroll_period_event', ['period_id'], unique=False)
    op.create_table('employee_salary',
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('structure_id', sa.UUID(), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('monthly_gross', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('values', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('reason', sa.String(length=500), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.CheckConstraint('monthly_gross IS NULL OR monthly_gross >= 0', name=op.f('ck_employee_salary_monthly_gross')),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], name=op.f('fk_employee_salary_employee_id_employee'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['structure_id'], ['salary_structure.id'], name=op.f('fk_employee_salary_structure_id_salary_structure'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_employee_salary')),
    sa.UniqueConstraint('employee_id', 'effective_from', name='uq_employee_salary_employee_date')
    )
    op.create_index('ix_employee_salary_employee', 'employee_salary', ['employee_id', 'effective_from'], unique=False)
    op.create_table('payroll_assignment',
    sa.Column('configuration_id', sa.UUID(), nullable=False),
    sa.Column('scope', sa.String(length=10), nullable=False),
    sa.Column('department_id', sa.UUID(), nullable=True),
    sa.Column('employee_id', sa.UUID(), nullable=True),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('reason', sa.String(length=500), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("(scope = 'company' AND department_id IS NULL AND employee_id IS NULL) OR (scope = 'department' AND department_id IS NOT NULL AND employee_id IS NULL) OR (scope = 'employee' AND employee_id IS NOT NULL AND department_id IS NULL)", name=op.f('ck_payroll_assignment_scope_target')),
    sa.CheckConstraint("scope IN ('company', 'department', 'employee')", name=op.f('ck_payroll_assignment_scope')),
    sa.CheckConstraint('effective_to IS NULL OR effective_to >= effective_from', name=op.f('ck_payroll_assignment_dates')),
    sa.ForeignKeyConstraint(['configuration_id'], ['payroll_configuration.id'], name=op.f('fk_payroll_assignment_configuration_id_payroll_configuration'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['department_id'], ['department.id'], name=op.f('fk_payroll_assignment_department_id_department'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], name=op.f('fk_payroll_assignment_employee_id_employee'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_assignment'))
    )
    op.create_index(op.f('ix_payroll_assignment_configuration_id'), 'payroll_assignment', ['configuration_id'], unique=False)
    op.create_index(op.f('ix_payroll_assignment_department_id'), 'payroll_assignment', ['department_id'], unique=False)
    op.create_index(op.f('ix_payroll_assignment_employee_id'), 'payroll_assignment', ['employee_id'], unique=False)
    op.create_table('payroll_assignment_history',
    sa.Column('assignment_id', sa.UUID(), nullable=False),
    sa.Column('action', sa.String(length=10), nullable=False),
    sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('summary', sa.String(length=500), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.CheckConstraint("action IN ('assigned', 'ended')", name=op.f('ck_payroll_assignment_history_action')),
    sa.ForeignKeyConstraint(['assignment_id'], ['payroll_assignment.id'], name=op.f('fk_payroll_assignment_history_assignment_id_payroll_assignment'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_assignment_history'))
    )
    op.create_index(op.f('ix_payroll_assignment_history_assignment_id'), 'payroll_assignment_history', ['assignment_id'], unique=False)
    op.create_table('payroll_result',
    sa.Column('period_id', sa.UUID(), nullable=False),
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('days_in_period', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('paid_days', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('loss_of_pay_days', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('leave_days', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('overtime_minutes', sa.Integer(), nullable=False),
    sa.Column('gross', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('deductions', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('employer_contributions', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('net', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('previous_net', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('exceptions', postgresql.ARRAY(sa.String(length=30)), nullable=False),
    sa.Column('lines', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('salary_id', sa.UUID(), nullable=True),
    sa.Column('configuration_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['configuration_id'], ['payroll_configuration.id'], name=op.f('fk_payroll_result_configuration_id_payroll_configuration'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], name=op.f('fk_payroll_result_employee_id_employee'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['period_id'], ['payroll_period.id'], name=op.f('fk_payroll_result_period_id_payroll_period'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['salary_id'], ['employee_salary.id'], name=op.f('fk_payroll_result_salary_id_employee_salary'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_result')),
    sa.UniqueConstraint('period_id', 'employee_id', name='uq_payroll_result_period_employee')
    )
    op.create_index('ix_payroll_result_employee', 'payroll_result', ['employee_id'], unique=False)
    op.create_table('payslip',
    sa.Column('period_id', sa.UUID(), nullable=False),
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('result_id', sa.UUID(), nullable=False),
    sa.Column('net_pay', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], name=op.f('fk_payslip_employee_id_employee'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['period_id'], ['payroll_period.id'], name=op.f('fk_payslip_period_id_payroll_period'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['result_id'], ['payroll_result.id'], name=op.f('fk_payslip_result_id_payroll_result'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payslip')),
    sa.UniqueConstraint('period_id', 'employee_id', name='uq_payslip_period_employee')
    )
    op.create_index('ix_payslip_employee', 'payslip', ['employee_id'], unique=False)
    for table in APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_no_update_delete BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION hrms_append_only()")
        op.execute(f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION hrms_append_only()")
    for table in ("salary_component", "salary_structure", "payroll_configuration"):
        op.execute(f"CREATE TRIGGER {table}_code_stable BEFORE UPDATE OF code ON {table} FOR EACH ROW WHEN (OLD.code IS DISTINCT FROM NEW.code) EXECUTE FUNCTION hrms_reject_code_change('code')")


def downgrade() -> None:
    for table in ("salary_component", "salary_structure", "payroll_configuration"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_code_stable ON {table}")
    for table in APPEND_ONLY:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update_delete ON {table}")
    op.drop_index('ix_payslip_employee', table_name='payslip')
    op.drop_table('payslip')
    op.drop_index('ix_payroll_result_employee', table_name='payroll_result')
    op.drop_table('payroll_result')
    op.drop_index(op.f('ix_payroll_assignment_history_assignment_id'), table_name='payroll_assignment_history')
    op.drop_table('payroll_assignment_history')
    op.drop_index(op.f('ix_payroll_assignment_employee_id'), table_name='payroll_assignment')
    op.drop_index(op.f('ix_payroll_assignment_department_id'), table_name='payroll_assignment')
    op.drop_index(op.f('ix_payroll_assignment_configuration_id'), table_name='payroll_assignment')
    op.drop_table('payroll_assignment')
    op.drop_index('ix_employee_salary_employee', table_name='employee_salary')
    op.drop_table('employee_salary')
    op.drop_index(op.f('ix_payroll_period_event_period_id'), table_name='payroll_period_event')
    op.drop_table('payroll_period_event')
    op.drop_table('payroll_configuration')
    op.drop_table('salary_structure')
    op.drop_table('salary_component')
    op.drop_table('payroll_period')
