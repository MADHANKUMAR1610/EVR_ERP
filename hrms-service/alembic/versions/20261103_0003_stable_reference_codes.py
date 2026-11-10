"""Stable reference codes: employee status codes and payroll field keys can never be renamed.

Approved decision (2026-11-03): employee records store these values, so they must stay stable once
created. The service refuses the change with a field error; this migration adds the same rule in the
database, so no other path (manual SQL, a future script) can rename them.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-03 12:00:00+00:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FK = 'fk_employee_status_transition_to_code_employee_status'


def upgrade() -> None:
    # A status code referenced by a transition may no longer cascade a rename.
    op.drop_constraint(FK, 'employee_status_transition', type_='foreignkey')
    op.create_foreign_key(FK, 'employee_status_transition', 'employee_status', ['to_code'], ['code'], onupdate='RESTRICT', ondelete='RESTRICT')

    op.execute(
        """
        CREATE FUNCTION hrms_reject_code_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% of % cannot be changed once created', TG_ARGV[0], TG_TABLE_NAME
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER employee_status_code_stable BEFORE UPDATE OF code ON employee_status "
        "FOR EACH ROW WHEN (OLD.code IS DISTINCT FROM NEW.code) EXECUTE FUNCTION hrms_reject_code_change('code');"
    )
    op.execute(
        "CREATE TRIGGER payroll_field_key_stable BEFORE UPDATE OF key ON payroll_field_definition "
        "FOR EACH ROW WHEN (OLD.key IS DISTINCT FROM NEW.key) EXECUTE FUNCTION hrms_reject_code_change('key');"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER payroll_field_key_stable ON payroll_field_definition;")
    op.execute("DROP TRIGGER employee_status_code_stable ON employee_status;")
    op.execute("DROP FUNCTION hrms_reject_code_change();")
    op.drop_constraint(FK, 'employee_status_transition', type_='foreignkey')
    op.create_foreign_key(FK, 'employee_status_transition', 'employee_status', ['to_code'], ['code'], onupdate='CASCADE', ondelete='RESTRICT')
