"""Identity schema: roles, user accounts, sessions, account history, service-token log, audit log.

The audit log and the history tables are append-only (trigger).

Revision ID: 0001
Revises: 
Create Date: 2026-11-05 09:27:52.215187+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

APPEND_ONLY = ("audit_log", "user_account_event", "service_token_issue")

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
    op.create_table('role',
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('permissions', sa.ARRAY(sa.String(length=80)), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('system', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_role'))
    )
    op.create_index('uq_role_name_lower', 'role', [sa.text('lower(name)')], unique=True)
    op.create_table('service_token_issue',
    sa.Column('client_id', sa.String(length=60), nullable=False),
    sa.Column('jti', sa.String(length=60), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_service_token_issue')),
    sa.UniqueConstraint('jti', name='uq_service_token_issue_jti')
    )
    op.create_table('user_account',
    sa.Column('username', sa.String(length=60), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('password_set_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('must_change_password', sa.Boolean(), nullable=False),
    sa.Column('role_ids', sa.ARRAY(sa.UUID()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('department_id', sa.String(length=60), nullable=True),
    sa.Column('department_name', sa.String(length=160), nullable=True),
    sa.Column('employee_id', sa.String(length=60), nullable=True),
    sa.Column('employee_code', sa.String(length=40), nullable=True),
    sa.Column('employee_name', sa.String(length=160), nullable=True),
    sa.Column('manager_id', sa.String(length=60), nullable=True),
    sa.Column('manager_name', sa.String(length=160), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failed_attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.CheckConstraint("status IN ('active', 'invited', 'inactive', 'locked')", name=op.f('ck_user_account_status')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_account'))
    )
    op.create_index('uq_user_account_email_lower', 'user_account', [sa.text('lower(email)')], unique=True)
    op.create_index('uq_user_account_employee_id', 'user_account', ['employee_id'], unique=True, postgresql_where=sa.text('employee_id IS NOT NULL'))
    op.create_index('uq_user_account_username_lower', 'user_account', [sa.text('lower(username)')], unique=True)
    op.create_table('user_account_event',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('summary', sa.String(length=500), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user_account.id'], name=op.f('fk_user_account_event_user_id_user_account'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_account_event'))
    )
    op.create_index(op.f('ix_user_account_event_user_id'), 'user_account_event', ['user_id'], unique=False)
    op.create_table('user_session',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_reason', sa.String(length=40), nullable=True),
    sa.Column('client_ip', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user_account.id'], name=op.f('fk_user_session_user_id_user_account'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_session'))
    )
    op.create_index(op.f('ix_user_session_user_id'), 'user_session', ['user_id'], unique=False)
    op.execute(
        """
        CREATE FUNCTION identity_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
        END;
        $$
        """
    )
    for table in APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_no_update_delete BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION identity_append_only()")
        op.execute(f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION identity_append_only()")


def downgrade() -> None:
    for table in APPEND_ONLY:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update_delete ON {table}")
    op.drop_index(op.f('ix_user_session_user_id'), table_name='user_session')
    op.drop_table('user_session')
    op.drop_index(op.f('ix_user_account_event_user_id'), table_name='user_account_event')
    op.drop_table('user_account_event')
    op.drop_index('uq_user_account_username_lower', table_name='user_account')
    op.drop_index('uq_user_account_employee_id', table_name='user_account', postgresql_where=sa.text('employee_id IS NOT NULL'))
    op.drop_index('uq_user_account_email_lower', table_name='user_account')
    op.drop_table('user_account')
    op.drop_table('service_token_issue')
    op.drop_index('uq_role_name_lower', table_name='role')
    op.drop_table('role')
    op.drop_index('ix_audit_log_request_id', table_name='audit_log')
    op.drop_index('ix_audit_log_module_action', table_name='audit_log')
    op.drop_index('ix_audit_log_entity', table_name='audit_log')
    op.drop_index('ix_audit_log_created_at', table_name='audit_log')
    op.drop_index('ix_audit_log_actor_user_id', table_name='audit_log')
    op.drop_table('audit_log')
    op.execute("DROP FUNCTION IF EXISTS identity_append_only()")
