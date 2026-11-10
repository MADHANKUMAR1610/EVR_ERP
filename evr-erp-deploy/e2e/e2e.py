"""End-to-end over HTTP: Identity sign-in -> the same cookie works in HRMS, Platform and Manufacturing; role changes,
the audit merge, the overview, HRMS -> Platform notification delivery with a service token, and sign-out revocation."""
import asyncio, json, subprocess, sys
import httpx

cfg = json.load(open("e2e_secrets.json"))
ORIGIN = {"Origin": "http://localhost:5173"}
ID, HR, PF, MF = "http://127.0.0.1:8001/api/v1", "http://127.0.0.1:8000/api/v1", "http://127.0.0.1:8002/api/v1", "http://127.0.0.1:8003/api/v1"
results = []


def check(name, ok, info=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{info}]" if info and not ok else ""))


async def main():
    async with httpx.AsyncClient(headers=ORIGIN, timeout=20) as c:
        r = await c.post(f"{ID}/auth/login", json={"username": "e2e.admin", "password": cfg["admin_password"]})
        check("Identity sign-in sets the session cookie", r.status_code == 200 and "evr_session" in c.cookies, r.text[:200])
        cookie = {"Cookie": f"evr_session={c.cookies['evr_session']}"}
        admin = r.json()["user"]

        # A role with HR and module permissions for the admin (applies at the next session restore).
        roles = (await c.get(f"{ID}/admin/roles", headers=cookie)).json()
        r = await c.post(f"{ID}/admin/roles", json={"name": "E2E All Modules", "permissions": ["*"]}, headers=cookie)
        check("Identity creates a role", r.status_code == 201, r.text[:200])
        role = r.json()
        me = (await c.get(f"{ID}/admin/users/{admin['id']}", headers=cookie)).json()
        r = await c.put(f"{ID}/admin/users/{admin['id']}", json={"username": me["username"], "displayName": me["displayName"], "email": me["email"],
                                                                "roleIds": [x["id"] for x in me["roles"]] + [role["id"]], "departmentId": None, "employeeId": None, "version": me["version"]}, headers=cookie)
        check("Identity assigns the role", r.status_code == 200, r.text[:200])
        r = await c.get(f"{ID}/auth/session", headers=cookie)
        check("Session restore returns the new permissions", "*" in r.json()["user"]["permissions"], r.text[:200])
        cookie = {"Cookie": f"evr_session={r.cookies.get('evr_session') or c.cookies['evr_session']}"}

        # The same cookie works in every service.
        r = await c.get(f"{HR}/hr/departments", headers=cookie)
        check("HRMS accepts the Identity session (JWKS + revocation check)", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
        r = await c.post(f"{HR}/admin/departments", json={"code": "E2E", "name": "End to end", "headEmployeeId": None, "parentId": None, "active": True}, headers={**cookie, **ORIGIN})
        check("HRMS write with the Identity session (CSRF origin check passes)", r.status_code in (200, 201), f"{r.status_code} {r.text[:300]}")
        dept = r.json() if r.status_code in (200, 201) else {"id": None}
        r = await c.get(f"{MF}/dashboard/summary", headers=cookie)
        check("Manufacturing accepts the Identity session", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
        r = await c.get(f"{MF}/production/work-orders", headers=cookie)
        check("Manufacturing work orders answer (empty tables)", r.status_code == 200 and r.json()["meta"]["totalItems"] == 0, r.text[:200])

        # Identity reads the department name from HRMS with the caller's session.
        if dept["id"]:
            r = await c.post(f"{ID}/admin/users", json={"username": "e2e.user", "displayName": "E2E User", "email": "e2e.user@example.com", "roleIds": [], "departmentId": dept["id"], "employeeId": None,
                                                        "password": "E2e-user-pass-2026", "mustChangePassword": False}, headers=cookie)
            check("Identity snapshots the department name from HRMS", r.status_code == 201 and r.json()["department"] == {"id": dept["id"], "name": "End to end"}, r.text[:300])

        # Platform: overview and the merged audit log.
        r = await c.get(f"{PF}/admin/overview", headers=cookie)
        ov = r.json() if r.status_code == 200 else {}
        check("Platform overview combines Identity and HRMS counts", r.status_code == 200 and ov["users"]["total"] >= 2 and ov["departments"] >= 1, f"{r.status_code} {r.text[:300]}")
        r = await c.get(f"{PF}/admin/audit-events", params={"pageSize": 100}, headers=cookie)
        mods = set(r.json()["facets"]["modules"]) if r.status_code == 200 else set()
        check("Platform audit log merges Identity and HRMS events", "Identity" in mods and len(mods) >= 2, f"{r.status_code} {sorted(mods)} {r.text[:200]}")

        # HRMS -> Platform notification delivery through the outbox with a service token.
        code = f'''
import asyncio
from app.core.context import SYSTEM_PRINCIPAL
from app.database.audit_listener import acting_as
from app.database.session import get_session_factory
from app.services.leave.notifications import queue, deliver_pending
async def run():
    async with get_session_factory()() as s:
        with acting_as(SYSTEM_PRINCIPAL):
            queue(s, category="approval", title="E2E: leave request awaiting your approval", message="EVR-0001 · 1 day", link="/hr/approvals", user_ids=["{admin['id']}"])
            await s.commit()
            print(await deliver_pending(s))
            await s.commit()
asyncio.run(run())
'''
        sys.path.insert(0, ".")
        from launch import env_for, ROOT
        p = subprocess.run([str(ROOT / "hrms-service/.venv/bin/python"), "-c", code], cwd=ROOT / "hrms-service", env=env_for("hrms"), capture_output=True, text=True)
        check("HRMS worker delivers to Platform with a service token", "'delivered': 1" in p.stdout, (p.stdout + p.stderr)[-400:])
        r = await c.get(f"{PF}/notifications", headers=cookie)
        check("The notification reaches the user's bell feed", r.status_code == 200 and any(n["title"].startswith("E2E") for n in r.json()["items"]), r.text[:200])

        # Sign-out revokes the session everywhere.
        old = dict(cookie)
        r = await c.post(f"{ID}/auth/logout", headers={**cookie, **ORIGIN})
        check("Sign-out", r.status_code == 204)
        for name, url in (("HRMS", f"{HR}/hr/departments"), ("Platform", f"{PF}/notifications"), ("Manufacturing", f"{MF}/dashboard/summary")):
            r = await c.get(url, headers=old)
            check(f"{name} refuses the signed-out session", r.status_code == 401, f"{r.status_code}")
    print(f"\n{sum(ok for _, ok in results)}/{len(results)} checks passed")


asyncio.run(main())
