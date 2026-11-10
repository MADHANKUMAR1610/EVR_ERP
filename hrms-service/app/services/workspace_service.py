"""HR workspace (Module 10, contract B7; MODULE_10_DECISIONS.md): summary, derived task queue, activity, events.

Read-only. Tasks are derived on read from the employee data and disappear when the work is done. The task and
metric rules are the contract's proposals (D19, D20), pending HR confirmation. Organizational scope applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.permissions import P
from app.models.employee_document_model import EmployeeDocument
from app.models.employee_model import Employee, EmployeeContact, EmployeeHistory
from app.repositories.base_repository import PageResult
from app.repositories.employee_repository import ACTIVE
from app.schemas.common import PageMeta
from app.schemas.employee_schema import NamedRefOut
from app.schemas.report_schema import MetricOut
from app.schemas.workspace_schema import (
    EmployeeSubjectOut,
    HrTaskOut,
    TaskCountsOut,
    TaskPageOut,
    TaskTypeCountsOut,
    UpcomingEventOut,
    WorkforceSummaryOut,
    WorkspaceActivityOut,
)
from app.services.attendance.attendance_data import AttendanceData
from app.services.employee_scope_service import EmployeeScopeService
from app.services.employee_support import Caller, References, company_today
from app.services.leave.approvals_service import ApprovalsService

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
PRESENT_TODAY = ("present", "late", "half_day", "missing_punch")
TASK_PERMISSION = {"employee_record_incomplete": P.EMPLOYEES_EDIT, "onboarding_documents": P.DOCUMENTS_UPLOAD, "probation_review_due": P.EMPLOYEES_CHANGE_STATUS}
NO_PERMISSION = "You do not have permission to see this figure."


def _subject(e: Employee) -> EmployeeSubjectOut:
    return EmployeeSubjectOut(id=str(e.id), employee_code=e.employee_code, name=e.full_name)


def _anniversary(joining: date, year: int) -> date:
    try:
        return joining.replace(year=year)
    except ValueError:  # 29 February in a non-leap year
        return date(year, 3, 1)


@dataclass
class _Task:
    out: HrTaskOut
    due: date | None


class WorkspaceService:
    def __init__(self, session: AsyncSession, caller: Caller):
        self.session = session
        self.caller = caller
        self.scope = EmployeeScopeService.clause(caller.scope)

    async def _employees(self, *, in_employment: bool = True) -> list[Employee]:
        stmt = select(Employee).where(self.scope)
        if in_employment:
            stmt = stmt.where(ACTIVE)
        return list((await self.session.scalars(stmt.order_by(Employee.employee_code))).all())

    # ---- Summary ------------------------------------------------------------------------------------------------

    async def summary(self) -> WorkforceSummaryOut:
        employees = await self._employees()
        codes = get_settings().workspace_active_status_codes
        active = (MetricOut(value=sum(1 for e in employees if e.status_code in codes)) if codes
                  else MetricOut(value=None, unavailable_reason="HR has not yet chosen which employee statuses count as active (setting WORKSPACE_ACTIVE_STATUS_CODES)."))
        if self.caller.has(P.ATTENDANCE_VIEW):
            today = company_today()
            days = await AttendanceData(self.session).compute(employees, today, today)
            present = MetricOut(value=sum(1 for e in employees if (r := days[e.id].days.get(today)) is not None and r.status in PRESENT_TODAY))
        else:
            present = MetricOut(value=None, unavailable_reason=NO_PERMISSION)
        if self.caller.has(P.APPROVALS_VIEW):
            inbox = await ApprovalsService(self.session, self.caller).inbox(type_=None, page=1, page_size=10)
            approvals = MetricOut(value=inbox.meta.total_items)
        else:
            approvals = MetricOut(value=None, unavailable_reason=NO_PERMISSION)
        return WorkforceSummaryOut(total_employees=MetricOut(value=len(employees)), active_employees=active, present_today=present, pending_approvals=approvals, as_of=datetime.now(UTC))

    # ---- Tasks ----------------------------------------------------------------------------------------------------

    async def _derive(self) -> list[_Task]:
        today = company_today()
        allowed = {t for t, perm in TASK_PERMISSION.items() if self.caller.has(perm)}
        if not allowed:
            return []
        employees = await self._employees()
        ids = [e.id for e in employees]
        contacts = {c.employee_id: c for c in (await self.session.scalars(select(EmployeeContact).where(EmployeeContact.employee_id.in_(ids))))} if ids else {}
        with_docs = set((await self.session.scalars(select(EmployeeDocument.employee_id).where(EmployeeDocument.employee_id.in_(ids)).distinct()))) if ids else set()
        tasks: list[_Task] = []
        for e in employees:
            if "employee_record_incomplete" in allowed:
                c = contacts.get(e.id)
                missing = [label for label, ok in (
                    ("Attendance ID", e.attendance_id), ("Shift", e.shift_id), ("Attendance policy", e.attendance_policy_id), ("Work location", e.work_location_id),
                    ("Emergency contact", c and c.emergency_name and c.emergency_phone)) if not ok]
                if missing:
                    recent = today - timedelta(days=30) <= e.joining_date <= today
                    due = e.joining_date + timedelta(days=7) if recent else None
                    tasks.append(_Task(HrTaskOut(id=f"record:{e.id}", type="employee_record_incomplete", title="Complete the employee record",
                                                 description=f"{len(missing)} item(s) missing from the record.", priority="high" if recent else "medium", status="pending",
                                                 due_date=due.isoformat() if due else None, subject=_subject(e), missing_items=missing), due))
            if "onboarding_documents" in allowed and abs((e.joining_date - today).days) <= 30 and e.id not in with_docs:
                tasks.append(_Task(HrTaskOut(id=f"documents:{e.id}", type="onboarding_documents", title="Collect onboarding documents",
                                             description="No document has been uploaded for this joiner.", priority="medium", status="pending",
                                             due_date=e.joining_date.isoformat(), subject=_subject(e)), e.joining_date))
            if ("probation_review_due" in allowed and e.probation_applicable and e.probation_end_date and e.confirmation_date is None
                    and e.probation_end_date <= today + timedelta(days=30)):
                days_left = (e.probation_end_date - today).days
                text = f"Probation ended {-days_left} day(s) ago." if days_left < 0 else ("Probation ends today." if days_left == 0 else f"Probation ends in {days_left} day(s).")
                tasks.append(_Task(HrTaskOut(id=f"probation:{e.id}", type="probation_review_due", title="Probation review due",
                                             description=f"{text} Record the confirmation decision.", priority="high" if days_left <= 7 else "medium", status="pending",
                                             due_date=e.probation_end_date.isoformat(), subject=_subject(e)), e.probation_end_date))
        tasks.sort(key=lambda t: (t.due is None, t.due or date.max, PRIORITY_ORDER[t.out.priority], t.out.subject.employee_code, t.out.type))
        return tasks

    async def tasks(self, *, type_: str | None, priority: str | None, due: str | None, page: int, page_size: int) -> TaskPageOut:
        today = company_today()
        everything = await self._derive()
        counts = TaskCountsOut(total=len(everything), overdue=sum(1 for t in everything if t.due and t.due < today), high_priority=sum(1 for t in everything if t.out.priority == "high"),
                               by_type=TaskTypeCountsOut(**{k: sum(1 for t in everything if t.out.type == k) for k in TASK_PERMISSION}))
        items = everything
        if type_:
            items = [t for t in items if t.out.type == type_]
        if priority:
            items = [t for t in items if t.out.priority == priority]
        if due == "overdue":
            items = [t for t in items if t.due and t.due < today]
        elif due in ("next7", "next30"):
            limit = today + timedelta(days=7 if due == "next7" else 30)
            items = [t for t in items if t.due and today <= t.due <= limit]
        result = PageResult([], page, page_size, len(items))
        meta = PageMeta(page=result.page, page_size=result.page_size, total_items=result.total_items, total_pages=result.total_pages)
        return TaskPageOut(items=[t.out for t in items[(page - 1) * page_size: page * page_size]], meta=meta, counts=counts)

    # ---- Activity and events ----------------------------------------------------------------------------------------

    async def activity(self, limit: int) -> list[WorkspaceActivityOut]:
        rows = (await self.session.execute(select(EmployeeHistory, Employee).join(Employee, Employee.id == EmployeeHistory.employee_id).where(self.scope)
                                           .order_by(EmployeeHistory.created_at.desc(), EmployeeHistory.id.desc()).limit(limit))).all()
        refs = await References.load(self.session)
        return [WorkspaceActivityOut(id=str(h.id), at=h.created_at, actor=NamedRefOut(id=str(h.created_by), name=h.created_by_name), action=h.action, summary=h.summary, comment=h.comment,
                                     effective_date=h.effective_date.isoformat() if h.effective_date else None, changes=h.changes, from_status=refs.status_label(h.from_status),
                                     to_status=refs.status_label(h.to_status), subject=_subject(e)) for h, e in rows]

    async def upcoming(self, days: int) -> list[UpcomingEventOut]:
        today = company_today()
        end = today + timedelta(days=days)
        events: list[UpcomingEventOut] = []
        for e in await self._employees():
            if today <= e.joining_date <= end:
                events.append(UpcomingEventOut(id=f"join:{e.id}", type="joining", date=e.joining_date.isoformat(), subject=_subject(e)))
            for year in range(today.year, end.year + 1):
                d = _anniversary(e.joining_date, year)
                years = year - e.joining_date.year
                if years >= 1 and today <= d <= end:
                    events.append(UpcomingEventOut(id=f"anniv:{e.id}:{year}", type="work_anniversary", date=d.isoformat(), subject=_subject(e), years=years))
        events.sort(key=lambda x: (x.date, x.subject.employee_code, x.type))
        return events
