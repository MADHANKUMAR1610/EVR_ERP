"""Owner decision 2 under real concurrency: the original approver and the escalation recipient
decide the same request at the same time, on separate database connections. Exactly one decision
commits; the other gets 409 INVALID_TRANSITION; usage is charged once.

This test commits its own rows (separate connections cannot see the per-test transaction) and
removes them afterwards. The append-only triggers are switched off only for that cleanup, by the
table owner, inside the cleanup transaction.
"""

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.context import SYSTEM_PRINCIPAL, Principal, principal_var
from app.core.errors import InvalidTransitionError
from app.database.audit_listener import acting_as
from app.models.audit_log_model import AuditLog
from app.models.department_model import Department
from app.models.designation_model import Designation
from app.models.employee_model import Employee
from app.models.leave_model import LeaveLedgerEntry, LeaveRequest, LeaveRoutingEvent, LeaveType, RequestEvent
from app.models.reference_data_model import EmployeeStatus, EmploymentType
from app.schemas.attendance_schema import DecisionIn
from app.services.employee_support import caller_context, company_today
from app.services.leave import request_service
from app.services.leave.request_service import LeaveRequestService
from tests.conftest import TEST_DB_URL

APPEND_ONLY = ("audit_log", "request_event", "leave_routing_event", "leave_ledger_entry")


@pytest.fixture
async def committed():
    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tag = uuid.uuid4().hex[:6].upper()
    ids: dict = {}
    with acting_as(SYSTEM_PRINCIPAL):
        async with factory() as s:
            dept = Department(code=f"C{tag[:5]}", name=f"Concurrency {tag}")
            desig = Designation(code=f"D{tag[:5]}", name="Tester")
            etype = EmploymentType(code=f"E{tag}", name="Test type")
            status = EmployeeStatus(code=f"conc_{tag.lower()}", label="Active", tone="success")
            s.add_all([dept, desig, etype, status])
            await s.flush()
            common = dict(joining_date=date(2020, 1, 1), department_id=dept.id, designation_id=desig.id, employment_type_id=etype.id, status_code=status.code)
            manager = Employee(employee_code=f"M-{tag}", first_name="Mona", full_name="Mona Manager", **common)
            s.add(manager)
            await s.flush()
            employee = Employee(employee_code=f"E-{tag}", first_name="Eli", full_name="Eli Employee", reporting_manager_id=manager.id, **common)
            lt = LeaveType(code=f"T{tag}", name="Test leave", paid=True, balance_tracked=True)
            s.add_all([employee, lt])
            await s.flush()
            start = company_today() + timedelta(days=30)
            req = LeaveRequest(employee_id=employee.id, leave_type_id=lt.id, from_date=start, to_date=start, portion="full", days=1, days_by_year={str(start.year): 1.0},
                               charged_dates=[start], reason="Concurrency test", status="pending", stage="escalated", escalated_at=datetime.now(UTC), approver_kind="reporting_manager",
                               approver_employee_id=manager.id, approver_name=manager.full_name, recipient_kind="role", recipient_ref="test-esc", recipient_name="HR desk")
            s.add(req)
            await s.commit()
            ids.update(dept=dept.id, desig=desig.id, etype=etype.id, status=status.code, manager=manager.id, employee=employee.id, type=lt.id, request=req.id)
    yield factory, ids
    async with factory() as s:
        for t in APPEND_ONLY:
            await s.execute(text(f"ALTER TABLE {t} DISABLE TRIGGER USER"))
        await s.execute(delete(AuditLog).where(AuditLog.entity_id == str(ids["request"])))
        await s.execute(delete(RequestEvent).where(RequestEvent.request_id == ids["request"]))
        await s.execute(delete(LeaveRoutingEvent).where(LeaveRoutingEvent.leave_request_id == ids["request"]))
        await s.execute(delete(LeaveLedgerEntry).where(LeaveLedgerEntry.leave_request_id == ids["request"]))
        await s.execute(delete(LeaveRequest).where(LeaveRequest.id == ids["request"]))
        await s.execute(delete(LeaveType).where(LeaveType.id == ids["type"]))
        await s.execute(delete(Employee).where(Employee.id == ids["employee"]))
        await s.execute(delete(Employee).where(Employee.id == ids["manager"]))
        await s.execute(delete(EmployeeStatus).where(EmployeeStatus.code == ids["status"]))
        await s.execute(delete(EmploymentType).where(EmploymentType.id == ids["etype"]))
        await s.execute(delete(Designation).where(Designation.id == ids["desig"]))
        await s.execute(delete(Department).where(Department.id == ids["dept"]))
        for t in APPEND_ONLY:
            await s.execute(text(f"ALTER TABLE {t} ENABLE TRIGGER USER"))
        await s.commit()
    await engine.dispose()


async def test_concurrent_decisions_only_the_first_valid_one_commits(committed, monkeypatch):
    factory, ids = committed
    original = LeaveRequestService._ledger

    async def slow_ledger(self, *args, **kwargs):
        await asyncio.sleep(0.5)  # hold the row lock while the other decision arrives
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(request_service.LeaveRequestService, "_ledger", slow_ledger)
    manager = Principal(user_id=str(uuid.uuid4()), name="Mona Manager", permissions=frozenset({"hr.approvals:act"}), employee_id=str(ids["manager"]))
    desk = Principal(user_id=str(uuid.uuid4()), name="HR desk user", permissions=frozenset({"hr.approvals:act"}), roles=frozenset({"test-esc"}))

    async def act(principal: Principal, decision: str):
        principal_var.set(principal)
        async with factory() as s:
            service = LeaveRequestService(s, await caller_context(s, principal))
            try:
                out = await service.decide(ids["request"], DecisionIn(decision=decision, comment="Concurrent decision", version=1))
                return ("ok", out.status)
            except InvalidTransitionError as exc:
                return ("409", exc.code)

    results = await asyncio.gather(act(manager, "approve"), act(desk, "reject"))
    assert sorted(r[0] for r in results) == ["409", "ok"], results
    assert [r[1] for r in results if r[0] == "409"] == ["INVALID_TRANSITION"]
    async with factory() as s:
        req = await s.get(LeaveRequest, ids["request"])
        decided = [e for e in (await s.scalars(select(RequestEvent.action).where(RequestEvent.request_id == ids["request"]))).all()]
        usage = (await s.scalars(select(LeaveLedgerEntry).where(LeaveLedgerEntry.leave_request_id == ids["request"]))).all()
    assert len(decided) == 1 and req.status == decided[0], "one decision only: never approved twice, or approved and rejected"
    assert len(usage) == (1 if req.status == "approved" else 0)
