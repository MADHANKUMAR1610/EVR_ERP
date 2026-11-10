"""Platform schema: company settings, notifications and preferences, integrations, audit log.

The audit log is append-only (trigger).

Revision ID: 0001
Revises: 
Create Date: 2026-11-05 09:38:38.702937+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

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
    op.create_table('company_settings',
    sa.Column('singleton', sa.Boolean(), nullable=False),
    sa.Column('legal_name', sa.String(length=200), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('registration_number', sa.String(length=60), nullable=False),
    sa.Column('tax_id', sa.String(length=60), nullable=False),
    sa.Column('address', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('phone', sa.String(length=30), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('website', sa.String(length=300), nullable=False),
    sa.Column('time_zone', sa.String(length=60), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('locale', sa.String(length=35), nullable=False),
    sa.Column('date_format', sa.String(length=12), nullable=False),
    sa.Column('time_format', sa.String(length=3), nullable=False),
    sa.Column('week_start', sa.Integer(), nullable=False),
    sa.Column('working_days', postgresql.ARRAY(sa.Integer()), nullable=False),
    sa.Column('fiscal_year_start_month', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f('ck_company_settings_currency_format')),
    sa.CheckConstraint("time_format IN ('24h', '12h')", name=op.f('ck_company_settings_time_format')),
    sa.CheckConstraint('fiscal_year_start_month BETWEEN 1 AND 12', name=op.f('ck_company_settings_fiscal_month')),
    sa.CheckConstraint('singleton', name=op.f('ck_company_settings_singleton')),
    sa.CheckConstraint('week_start BETWEEN 1 AND 7', name=op.f('ck_company_settings_week_start')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_settings')),
    sa.UniqueConstraint('singleton', name=op.f('uq_company_settings_singleton'))
    )
    op.create_table('integration',
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('values', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('secrets', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('connection_status', sa.String(length=12), nullable=False),
    sa.Column('last_successful_sync_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.String(length=500), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("connection_status IN ('connected', 'disconnected', 'error', 'unknown')", name=op.f('ck_integration_connection_status')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_integration')),
    sa.UniqueConstraint('code', name='uq_integration_code')
    )
    op.create_table('notification',
    sa.Column('user_id', sa.String(length=60), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('link', sa.String(length=500), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source', sa.String(length=60), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.CheckConstraint("category IN ('approval', 'attendance', 'leave', 'overtime', 'payroll', 'employee', 'documents', 'performance', 'system')", name=op.f('ck_notification_category')),
    sa.CheckConstraint("link IS NULL OR (link LIKE '/%' AND link NOT LIKE '//%')", name=op.f('ck_notification_app_relative_link')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notification'))
    )
    op.create_index('ix_notification_user_created', 'notification', ['user_id', 'created_at'], unique=False)
    op.create_table('notification_preference',
    sa.Column('user_id', sa.String(length=60), nullable=False),
    sa.Column('categories', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notification_preference')),
    sa.UniqueConstraint('user_id', name=op.f('uq_notification_preference_user_id'))
    )
    op.execute(
        """
        CREATE FUNCTION platform_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
        END;
        $$
        """
    )
    op.execute("CREATE TRIGGER audit_log_no_update_delete BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION platform_append_only()")
    op.execute("CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log FOR EACH STATEMENT EXECUTE FUNCTION platform_append_only()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log")
    op.drop_table('notification_preference')
    op.drop_index('ix_notification_user_created', table_name='notification')
    op.drop_table('notification')
    op.drop_table('integration')
    op.drop_table('company_settings')
    op.drop_index('ix_audit_log_request_id', table_name='audit_log')
    op.drop_index('ix_audit_log_module_action', table_name='audit_log')
    op.drop_index('ix_audit_log_entity', table_name='audit_log')
    op.drop_index('ix_audit_log_created_at', table_name='audit_log')
    op.drop_index('ix_audit_log_actor_user_id', table_name='audit_log')
    op.drop_table('audit_log')
    op.execute("DROP FUNCTION IF EXISTS platform_append_only()")
