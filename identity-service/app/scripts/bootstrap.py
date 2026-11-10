"""Creates the built-in roles and, on a new installation, the first administrator account.

    python -m app.scripts.bootstrap --username admin.it --display-name "IT Administrator" --email it@example.com

The password is read from the BOOTSTRAP_ADMIN_PASSWORD environment variable or asked for interactively; it is
never a default, never printed and never stored except as an Argon2id hash. Running again changes nothing.

Built-in roles (contract G1, decided): "System Administrator" holds every administration code (admin:*);
"HR Manager" holds the administration codes HR uses (users, roles, organization, workflows, policies; no company
settings or integration management). HR adds the HR module permissions to roles through the role screen.
"""

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.context import SYSTEM_PRINCIPAL
from app.core.passwords import hash_password, policy_problems
from app.database.audit_listener import acting_as
from app.database.session import dispose_engine, get_session_factory
from app.models.identity_model import Role, UserAccount, UserAccountEvent
from app.services.audit_service import AuditService

HR_MANAGER_ADMIN = ["admin:view", "admin:users.view", "admin:users.manage", "admin:roles.view", "admin:roles.manage", "admin:organization.view", "admin:organization.manage",
                    "admin:workflows.view", "admin:workflows.manage", "admin:workflows.publish", "admin:settings.view", "admin:policies.view", "admin:policies.manage",
                    "admin:policies.payroll-manage", "admin:notifications.view", "admin:audit.view", "admin:integrations.view"]
SYSTEM_ROLES = {"System Administrator": ("All administration, including company settings and integrations.", ["admin:*"]),
                "HR Manager": ("Users, roles, organization, workflows and HR policies. HR module permissions are added by HR.", HR_MANAGER_ADMIN)}


async def run(username: str | None, display_name: str | None, email: str | None) -> int:
    factory = get_session_factory()
    with acting_as(SYSTEM_PRINCIPAL):  # around the transaction: the commit's flush needs the actor too
        async with factory() as session, session.begin():
            roles = {}
            for name, (description, perms) in SYSTEM_ROLES.items():
                role = await session.scalar(select(Role).where(func.lower(Role.name) == name.lower()))
                if role is None:
                    role = Role(name=name, description=description, permissions=perms, system=True, active=True)
                    session.add(role)
                    await session.flush()
                    print(f"Created built-in role {name}")
                roles[name] = role
            if await session.scalar(select(func.count()).select_from(UserAccount)):
                print("Accounts already exist: no administrator created.")
                return 0
            if not (username and display_name and email):
                print("No accounts yet: pass --username, --display-name and --email to create the first administrator.", file=sys.stderr)
                return 1
            password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD") or getpass.getpass("Password for the first administrator: ")
            problems = policy_problems(password, username, get_settings())
            if problems:
                print("Password refused: " + " ".join(problems), file=sys.stderr)
                return 1
            from datetime import UTC, datetime

            user = UserAccount(username=username, display_name=display_name, email=email, status="active", password_hash=hash_password(password), password_set_at=datetime.now(UTC),
                               must_change_password=False, role_ids=[roles["System Administrator"].id])
            session.add(user)
            await session.flush()
            session.add(UserAccountEvent(user_id=user.id, action="created", summary="First administrator created by the bootstrap script"))
            AuditService(session).record(module="Identity", action="user.bootstrapped", summary=f"First administrator {username} created", entity_type="user_account", entity_id=user.id)
            print(f"Created the first administrator {username}")
    await dispose_engine()
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--username")
    p.add_argument("--display-name")
    p.add_argument("--email")
    a = p.parse_args()
    sys.exit(asyncio.run(run(a.username, a.display_name, a.email)))


if __name__ == "__main__":
    main()
