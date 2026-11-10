"""Module 8: performance (scales, competencies, recommendations, cycles, goals, reviews, development plans).

Adds tables only. Reuses hrms_append_only() (0007) and hrms_reject_code_change() (0003).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-05 08:25:36.705068+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

APPEND_ONLY = ("appraisal_cycle_event", "goal_progress_update", "performance_review_event")

# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('competency',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_competency')),
    sa.UniqueConstraint('name', name=op.f('uq_competency_name'))
    )
    op.create_table('performance_recommendation',
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("code ~ '^[a-z0-9_]{1,30}$'", name=op.f('ck_performance_recommendation_code_format')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_performance_recommendation')),
    sa.UniqueConstraint('code', name=op.f('uq_performance_recommendation_code'))
    )
    op.create_table('rating_scale',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('levels', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rating_scale')),
    sa.UniqueConstraint('name', name=op.f('uq_rating_scale_name'))
    )
    op.create_table('appraisal_cycle',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('period_from', sa.Date(), nullable=False),
    sa.Column('period_to', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('goal_setting_due', sa.Date(), nullable=False),
    sa.Column('self_assessment_due', sa.Date(), nullable=False),
    sa.Column('manager_review_due', sa.Date(), nullable=False),
    sa.Column('rating_scale_id', sa.UUID(), nullable=True),
    sa.Column('competency_ids', postgresql.ARRAY(sa.UUID()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('recommendation_options', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("status IN ('draft', 'goal_setting', 'self_assessment', 'manager_review', 'closed')", name=op.f('ck_appraisal_cycle_status')),
    sa.CheckConstraint('goal_setting_due <= self_assessment_due AND self_assessment_due <= manager_review_due', name=op.f('ck_appraisal_cycle_due_order')),
    sa.CheckConstraint('period_to >= period_from', name=op.f('ck_appraisal_cycle_dates')),
    sa.ForeignKeyConstraint(['rating_scale_id'], ['rating_scale.id'], name=op.f('fk_appraisal_cycle_rating_scale_id_rating_scale'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_appraisal_cycle')),
    sa.UniqueConstraint('name', name=op.f('uq_appraisal_cycle_name'))
    )
    op.create_table('appraisal_cycle_event',
    sa.Column('cycle_id', sa.UUID(), nullable=False),
    sa.Column('action', sa.String(length=10), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.CheckConstraint("action IN ('submitted', 'approved', 'rejected', 'cancelled', 'updated', 'commented')", name=op.f('ck_appraisal_cycle_event_action')),
    sa.ForeignKeyConstraint(['cycle_id'], ['appraisal_cycle.id'], name=op.f('fk_appraisal_cycle_event_cycle_id_appraisal_cycle'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_appraisal_cycle_event'))
    )
    op.create_index(op.f('ix_appraisal_cycle_event_cycle_id'), 'appraisal_cycle_event', ['cycle_id'], unique=False)
    op.create_table('development_plan',
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('focus', sa.Text(), server_default='', nullable=False),
    sa.Column('owner_name', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("status IN ('active', 'completed')", name=op.f('ck_development_plan_status')),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], name=op.f('fk_development_plan_employee_id_employee'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_development_plan'))
    )
    op.create_index(op.f('ix_development_plan_employee_id'), 'development_plan', ['employee_id'], unique=False)
    op.create_table('goal',
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('cycle_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('kpi', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
    sa.Column('weight', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('progress', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("status <> 'completed' OR progress = 100", name=op.f('ck_goal_completed_at_100')),
    sa.CheckConstraint("status IN ('not_started', 'on_track', 'at_risk', 'off_track', 'completed', 'cancelled')", name=op.f('ck_goal_status')),
    sa.CheckConstraint('progress BETWEEN 0 AND 100', name=op.f('ck_goal_progress')),
    sa.CheckConstraint('weight IS NULL OR (weight > 0 AND weight <= 100)', name=op.f('ck_goal_weight')),
    sa.ForeignKeyConstraint(['cycle_id'], ['appraisal_cycle.id'], name=op.f('fk_goal_cycle_id_appraisal_cycle'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], name=op.f('fk_goal_employee_id_employee'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_goal'))
    )
    op.create_index(op.f('ix_goal_cycle_id'), 'goal', ['cycle_id'], unique=False)
    op.create_index(op.f('ix_goal_employee_id'), 'goal', ['employee_id'], unique=False)
    op.create_table('performance_review',
    sa.Column('cycle_id', sa.UUID(), nullable=False),
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('reviewer_employee_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('manager', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
    sa.Column('manager_submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('recommendation', sa.String(length=30), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("status IN ('not_started', 'self_assessment', 'manager_review', 'completed')", name=op.f('ck_performance_review_status')),
    sa.ForeignKeyConstraint(['cycle_id'], ['appraisal_cycle.id'], name=op.f('fk_performance_review_cycle_id_appraisal_cycle'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], name=op.f('fk_performance_review_employee_id_employee'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['reviewer_employee_id'], ['employee.id'], name=op.f('fk_performance_review_reviewer_employee_id_employee'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_performance_review')),
    sa.UniqueConstraint('cycle_id', 'employee_id', name='uq_performance_review_cycle_employee')
    )
    op.create_index(op.f('ix_performance_review_employee_id'), 'performance_review', ['employee_id'], unique=False)
    op.create_index(op.f('ix_performance_review_reviewer_employee_id'), 'performance_review', ['reviewer_employee_id'], unique=False)
    op.create_table('development_action',
    sa.Column('plan_id', sa.UUID(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('type', sa.String(length=15), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.CheckConstraint("(status = 'done') = (completed_at IS NOT NULL)", name=op.f('ck_development_action_completed_at')),
    sa.CheckConstraint("status IN ('planned', 'in_progress', 'done')", name=op.f('ck_development_action_status')),
    sa.CheckConstraint("type IN ('training', 'mentoring', 'project', 'certification', 'other')", name=op.f('ck_development_action_type')),
    sa.ForeignKeyConstraint(['plan_id'], ['development_plan.id'], name=op.f('fk_development_action_plan_id_development_plan'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_development_action')),
    sa.UniqueConstraint('plan_id', 'position', name='uq_development_action_plan_position')
    )
    op.create_index('ix_development_action_due', 'development_action', ['status', 'due_date'], unique=False)
    op.create_table('goal_progress_update',
    sa.Column('goal_id', sa.UUID(), nullable=False),
    sa.Column('progress', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('value', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('note', sa.Text(), server_default='', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.CheckConstraint("status IN ('not_started', 'on_track', 'at_risk', 'off_track', 'completed', 'cancelled')", name=op.f('ck_goal_progress_update_status')),
    sa.CheckConstraint('progress BETWEEN 0 AND 100', name=op.f('ck_goal_progress_update_progress')),
    sa.ForeignKeyConstraint(['goal_id'], ['goal.id'], name=op.f('fk_goal_progress_update_goal_id_goal'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_goal_progress_update'))
    )
    op.create_index(op.f('ix_goal_progress_update_goal_id'), 'goal_progress_update', ['goal_id'], unique=False)
    op.create_table('performance_review_event',
    sa.Column('review_id', sa.UUID(), nullable=False),
    sa.Column('action', sa.String(length=10), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.CheckConstraint("action IN ('submitted', 'approved', 'rejected', 'cancelled', 'updated', 'commented')", name=op.f('ck_performance_review_event_action')),
    sa.ForeignKeyConstraint(['review_id'], ['performance_review.id'], name=op.f('fk_performance_review_event_review_id_performance_review'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_performance_review_event'))
    )
    op.create_index(op.f('ix_performance_review_event_review_id'), 'performance_review_event', ['review_id'], unique=False)
    for table in APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_no_update_delete BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION hrms_append_only()")
        op.execute(f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION hrms_append_only()")
    for table in ("performance_recommendation",):
        op.execute(f"CREATE TRIGGER {table}_code_stable BEFORE UPDATE OF code ON {table} FOR EACH ROW WHEN (OLD.code IS DISTINCT FROM NEW.code) EXECUTE FUNCTION hrms_reject_code_change('code')")


def downgrade() -> None:
    for table in ("performance_recommendation",):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_code_stable ON {table}")
    for table in APPEND_ONLY:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update_delete ON {table}")
    op.drop_index(op.f('ix_performance_review_event_review_id'), table_name='performance_review_event')
    op.drop_table('performance_review_event')
    op.drop_index(op.f('ix_goal_progress_update_goal_id'), table_name='goal_progress_update')
    op.drop_table('goal_progress_update')
    op.drop_index('ix_development_action_due', table_name='development_action')
    op.drop_table('development_action')
    op.drop_index(op.f('ix_performance_review_reviewer_employee_id'), table_name='performance_review')
    op.drop_index(op.f('ix_performance_review_employee_id'), table_name='performance_review')
    op.drop_table('performance_review')
    op.drop_index(op.f('ix_goal_employee_id'), table_name='goal')
    op.drop_index(op.f('ix_goal_cycle_id'), table_name='goal')
    op.drop_table('goal')
    op.drop_index(op.f('ix_development_plan_employee_id'), table_name='development_plan')
    op.drop_table('development_plan')
    op.drop_index(op.f('ix_appraisal_cycle_event_cycle_id'), table_name='appraisal_cycle_event')
    op.drop_table('appraisal_cycle_event')
    op.drop_table('appraisal_cycle')
    op.drop_table('rating_scale')
    op.drop_table('performance_recommendation')
    op.drop_table('competency')
