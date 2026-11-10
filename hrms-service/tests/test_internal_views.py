"""Views for the Platform service: the HRMS audit slice and the administration counts (caller's own permissions)."""

from tests.conftest import auth
from tests.employee_fixtures import create, org  # noqa: F401


async def test_audit_slice_and_admin_counts(client, org):
    await create(client, org, "EVR-1")
    audit = await client.get("/api/v1/hr/internal/audit-events", params={"limit": 5}, headers=auth(["admin:audit.view"]))
    assert audit.status_code == 200, audit.text
    body = audit.json()
    assert body["total"] >= 1 and body["items"][0]["module"] and set(body) == {"items", "total", "facets"} and "actors" in body["facets"]
    assert (await client.get("/api/v1/hr/internal/audit-events", headers=auth(["admin:view"]))).status_code == 403
    counts = (await client.get("/api/v1/hr/internal/admin-counts", headers=auth(["admin:view"]))).json()
    workflows = (await client.get("/api/v1/admin/workflows", headers=auth(["admin:workflows.view"]))).json()
    published = {w["process"] for w in workflows if w["status"] == "published"}
    assert counts["departments"] == 15 and counts["workflows"]["published"] == sum(w["status"] == "published" for w in workflows)
    assert set(counts["workflows"]["processesWithoutWorkflow"]) == {"leave", "attendance_correction", "overtime", "payroll", "performance_review"} - published
