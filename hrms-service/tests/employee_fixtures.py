"""Shared setup for the employee tests: the reference template, scope assignments and a payload builder."""

from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.context import SYSTEM_PRINCIPAL
from app.database.audit_listener import acting_as
from app.models.department_model import Department
from app.models.designation_model import Designation
from app.models.employee_access_scope_model import EmployeeAccessScope
from app.models.reference_data_model import DocumentCategory, DocumentType, EmploymentType, WorkLocation
from app.models.shift_model import Shift
from app.scripts.load_reference_data import Loader, read_file
from tests.conftest import auth

TEMPLATE = Path(__file__).resolve().parents[1] / "setup" / "reference_data.yaml"

# Test roles. Real role codes come from the Identity service; assignments are a management decision.
HR_ALL, HR_QA, MANAGER, HEAD, SELF = "test-hr-all", "test-hr-qa", "test-manager", "test-head", "test-self"

HR_PERMS = [
    "hr.employees:view", "hr.employees:create", "hr.employees:edit", "hr.employees:change-status",
    "hr.employees:view-contact", "hr.employees:view-sensitive",
]


def hr(perms: list[str] | None = None, roles: list[str] | None = None, **kw) -> dict[str, str]:
    return auth(perms if perms is not None else HR_PERMS, roles=roles if roles is not None else [HR_ALL], name=kw.pop("name", "Asha HR"), **kw)


class Org:
    def __init__(self, ids: dict[str, dict[str, str]]):
        self.ids = ids

    def __getattr__(self, name: str) -> dict[str, str]:
        return self.ids[name]


@pytest.fixture
async def org(db) -> Org:
    await Loader(db).run(read_file(TEMPLATE))

    async def codes(model) -> dict[str, str]:
        return {c: str(i) for c, i in (await db.execute(select(model.code, model.id))).all()}

    ids = {
        "dept": await codes(Department), "desig": await codes(Designation), "etype": await codes(EmploymentType),
        "loc": await codes(WorkLocation), "shift": await codes(Shift),
        "dtype": await codes(DocumentType), "dcat": await codes(DocumentCategory),
    }
    with acting_as(SYSTEM_PRINCIPAL):
        db.add_all([
            EmployeeAccessScope(role_code=HR_ALL, scope_type="all"),
            EmployeeAccessScope(role_code=HR_QA, scope_type="departments", department_ids=[await db.scalar(select(Department.id).where(Department.code == "QA"))]),
            EmployeeAccessScope(role_code=MANAGER, scope_type="reporting_tree"),
            EmployeeAccessScope(role_code=HEAD, scope_type="headed_departments"),
            EmployeeAccessScope(role_code=SELF, scope_type="own_record"),
        ])
        await db.commit()
    return Org(ids)


def payload(org: Org, code: str = "EVR-1001", *, dept: str = "QA", status: str = "active", first: str = "Ravi", last: str = "Iyer", **over) -> dict:
    body = {
        "employeeCode": code,
        "personal": {
            "firstName": first, "lastName": last, "dateOfBirth": "1990-05-21", "mobile": "+91 98765 43210", "email": f"{code.lower()}@example.com",
            "address": {"line1": "12 Main Road", "city": "Chennai", "country": "India"}, "emergencyContact": {"name": "Meena", "relationship": "Spouse", "phone": "+91 99999 11111"},
        },
        "employment": {
            "joiningDate": "2020-01-15", "departmentId": org.dept[dept], "designationId": org.desig["ENG"], "employmentTypeId": org.etype["PERM"], "statusCode": status,
            "reportingManagerId": None, "workLocationId": org.loc["PLANT1"], "probation": {"applicable": False, "endDate": None, "confirmationDate": None},
        },
        "work": {"attendanceId": code.split("-")[-1], "shiftId": org.shift["GEN"], "attendancePolicyId": None, "overtimePolicyId": None},
        "payroll": {"payrollGroup": "group_a", "paymentMode": "bank_transfer", "bankAccountNumber": "000012345678", "bankIfsc": "ABCD0123456"},
    }
    for path, value in over.items():
        target = body
        *parents, last_key = path.split("__")
        for p in parents:
            target = target[p]
        target[last_key] = value
    return body


async def create(client, org: Org, code: str = "EVR-1001", headers: dict | None = None, **over) -> dict:
    r = await client.post("/api/v1/hr/employees", json=payload(org, code, **over), headers=headers or hr())
    assert r.status_code == 201, r.text
    return r.json()


def details(r) -> dict[str, str]:
    return {d["field"]: d["message"] for d in r.json()["error"]["details"]}
