"""Reads employee and department names from HRMS for user accounts (contract G2: department, employee, reporting manager).

Calls HRMS with the caller's own session token, so Identity sees only what the caller may see in HRMS.
Without HRMS_BASE_URL (local development) the ids are kept and the names stay empty.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.core.errors import ServiceUnavailableError

# Tests replace this with an httpx.MockTransport.
transport: httpx.AsyncBaseTransport | None = None


@dataclass
class EmployeeInfo:
    id: str
    code: str
    name: str
    department_id: str | None
    department_name: str | None
    manager_id: str | None
    manager_name: str | None


class HrmsClient:
    def __init__(self, token: str | None):
        self.base = (get_settings().hrms_base_url or "").rstrip("/")
        self.token = token

    @property
    def enabled(self) -> bool:
        return bool(self.base)

    async def _get(self, path: str) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            async with httpx.AsyncClient(base_url=self.base, timeout=5.0, transport=transport) as client:
                return await client.get(path, headers=headers)
        except httpx.HTTPError:
            raise ServiceUnavailableError("HRMS could not be reached to look up the employee or department. Try again shortly.") from None

    async def employee(self, employee_id: str) -> EmployeeInfo | None:
        r = await self._get(f"/api/v1/hr/employees/{employee_id}")
        if r.status_code in (403, 404, 422):
            return None
        if r.status_code != 200:
            raise ServiceUnavailableError("HRMS could not return the employee. Try again shortly.")
        e = r.json()
        display = e.get("display") or {}
        manager = display.get("reportingManager") or None
        return EmployeeInfo(id=e["id"], code=e.get("employeeCode", ""), name=display.get("fullName", ""), department_id=(e.get("employment") or {}).get("departmentId"),
                            department_name=display.get("department"), manager_id=manager["id"] if manager else None, manager_name=manager["name"] if manager else None)

    async def department_name(self, department_id: str) -> str | None:
        r = await self._get("/api/v1/hr/departments")
        if r.status_code != 200:
            return None
        for d in r.json():
            if d.get("id") == department_id:
                return d.get("name")
        return None
