"""Module 9: reports (the append-only report activity log).

Adds one table. Reuses hrms_append_only() (0007).

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-05 08:49:46.736503+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0011'
down_revision: Union[str, None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('report_activity',
    sa.Column('report_id', sa.String(length=40), nullable=False),
    sa.Column('report_title', sa.String(length=120), nullable=False),
    sa.Column('action', sa.String(length=10), nullable=False),
    sa.Column('format', sa.String(length=4), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_by_name', sa.String(length=200), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_by_name', sa.String(length=200), nullable=False),
    sa.CheckConstraint("(action = 'exported') = (format IS NOT NULL)", name=op.f('ck_report_activity_format_with_export')),
    sa.CheckConstraint("action IN ('generated', 'exported')", name=op.f('ck_report_activity_action')),
    sa.CheckConstraint("format IS NULL OR format IN ('csv', 'xlsx')", name=op.f('ck_report_activity_format')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_report_activity'))
    )
    op.create_index('ix_report_activity_created', 'report_activity', ['created_at'], unique=False)
    op.execute("CREATE TRIGGER report_activity_no_update_delete BEFORE UPDATE OR DELETE ON report_activity FOR EACH ROW EXECUTE FUNCTION hrms_append_only()")
    op.execute("CREATE TRIGGER report_activity_no_truncate BEFORE TRUNCATE ON report_activity FOR EACH STATEMENT EXECUTE FUNCTION hrms_append_only()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS report_activity_no_truncate ON report_activity")
    op.execute("DROP TRIGGER IF EXISTS report_activity_no_update_delete ON report_activity")
    op.drop_index('ix_report_activity_created', table_name='report_activity')
    op.drop_table('report_activity')
