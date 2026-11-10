"""Prints a development token for Swagger or curl (AUTH_DEV_MODE only; refused in production).

    python -m app.scripts.dev_token --permissions "hr.employees:view,hr.employees:create" --roles hr-manager --employee-id <employee uuid>
"""

import argparse
import time
import uuid

import jwt

from app.core.config import get_settings


def main() -> None:
    s = get_settings()
    if s.environment == "production" or not s.auth_dev_mode or not s.auth_dev_secret:
        raise SystemExit("Development tokens need AUTH_DEV_MODE=true and AUTH_DEV_SECRET, outside production.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--permissions", default="*", help="Comma-separated permission codes")
    parser.add_argument("--user-id", default=str(uuid.UUID(int=42)))
    parser.add_argument("--name", default="Developer")
    parser.add_argument("--employee-id", default=None, help="HRMS employee UUID of the caller")
    parser.add_argument("--roles", default="", help="Comma-separated Identity role codes (organizational scopes are assigned to roles)")
    parser.add_argument("--hours", type=int, default=8)
    a = parser.parse_args()
    now = int(time.time())
    claims = {"sub": a.user_id, "name": a.name, "permissions": [p.strip() for p in a.permissions.split(",") if p.strip()], "employeeId": a.employee_id, "roles": [r.strip() for r in a.roles.split(",") if r.strip()], "sid": uuid.uuid4().hex, "iat": now, "exp": now + a.hours * 3600}
    print(jwt.encode(claims, s.auth_dev_secret, algorithm="HS256"))


if __name__ == "__main__":
    main()
