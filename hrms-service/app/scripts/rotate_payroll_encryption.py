"""Re-encrypts every sensitive payroll value with the first key in PAYROLL_ENCRYPTION_KEYS.

Key rotation:
1. put the new key FIRST in PAYROLL_ENCRYPTION_KEYS, keep the old keys after it, restart;
2. run this script (values are re-encrypted in one transaction, as the system actor, audited);
3. remove the old keys and restart.

    python -m app.scripts.rotate_payroll_encryption
"""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.context import SYSTEM_PRINCIPAL
from app.database.audit_listener import acting_as
from app.database.session import dispose_engine, get_session_factory
from app.repositories.employee_repository import EmployeeRepository
from app.services.audit_service import AuditService


async def rotate_all(session: AsyncSession) -> int:
    with acting_as(SYSTEM_PRINCIPAL):
        rows = await EmployeeRepository(session).all_encrypted_payroll_values()
        for row in rows:
            row.value = crypto.rotate(row.value)
        AuditService(session).record(module="Employees", action="payroll_values.reencrypted", summary=f"{len(rows)} sensitive payroll value(s) re-encrypted with the current key")
        await session.commit()
    return len(rows)


async def _main() -> None:
    try:
        async with get_session_factory()() as session:
            count = await rotate_all(session)
    finally:
        await dispose_engine()
    print(f"Re-encrypted {count} value(s) with the first key.")


if __name__ == "__main__":
    asyncio.run(_main())
