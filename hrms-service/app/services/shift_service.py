"""Shift master data: list, options, create and update (HR → Shift Management).

The rules and messages mirror the frontend shift form (features/hr/attendance/schemas.ts).
Shift assignments belong to the employees/attendance modules.
"""

from __future__ import annotations

import re
import uuid
from datetime import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.employee_model import Employee
from app.models.shift_model import Shift, ShiftDepartment
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.department_repository import DepartmentRepository
from app.repositories.shift_repository import ShiftRepository
from app.schemas.department_schema import DepartmentRef
from app.schemas.reference_data_schema import OptionItem
from app.schemas.shift_schema import ShiftInput, ShiftOut
from app.services.audit_service import AuditService, diff
from app.utils.ids import body_id
from app.utils.validation import FieldErrors, ensure_version

TIME = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
SHIFT_CODE = re.compile(r"^[A-Za-z0-9-]+$")
MAX_SHIFT_MINUTES = 16 * 60
MAX_BREAK_MINUTES = 180
MAX_GRACE_MINUTES = 120


def hhmm(t: time) -> str:
    return t.strftime("%H:%M")


def _parse(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def _length_minutes(start: time, end: time) -> int:
    s, e = start.hour * 60 + start.minute, end.hour * 60 + end.minute
    return e - s if e > s else e + 24 * 60 - s


def _snapshot(s: Shift) -> dict:
    return {
        "code": s.code,
        "name": s.name,
        "start": hhmm(s.start_time),
        "end": hhmm(s.end_time),
        "overnight": s.overnight,
        "breakMinutes": s.break_minutes,
        "graceMinutes": s.grace_minutes,
        "workingDays": ",".join(str(d) for d in s.working_days),
        "departmentIds": ",".join(sorted(str(link.department_id) for link in s.department_links)),
        "active": s.active,
    }


def _out(s: Shift, assigned: int) -> ShiftOut:
    return ShiftOut(
        id=str(s.id),
        code=s.code,
        name=s.name,
        start=hhmm(s.start_time),
        end=hhmm(s.end_time),
        overnight=s.overnight,
        break_minutes=s.break_minutes,
        grace_minutes=s.grace_minutes,
        working_days=list(s.working_days),
        departments=[DepartmentRef(id=str(link.department.id), name=link.department.name) for link in s.department_links],
        active=s.active,
        # Employees whose current shift is this one (employee record, work.shiftId), not counting
        # statuses marked "employment ended". Dated shift assignments come with the attendance module.
        assigned_employees=assigned,
        version=s.version,
        updated_at=s.updated_at,
        updated_by=s.updated_by_name or "",
    )


def option(s: Shift) -> OptionItem:
    description = f"{hhmm(s.start_time)}–{hhmm(s.end_time)}" + (", overnight" if s.overnight else "")
    return OptionItem(id=str(s.id), name=s.name, description=description)


class ShiftService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ShiftRepository(session)
        self.departments = DepartmentRepository(session)
        self.audit = AuditService(session)

    async def list(self) -> list[ShiftOut]:
        counts = await EmployeeRepository(self.session).active_counts(Employee.shift_id)
        return [_out(s, counts.get(s.id, 0)) for s in await self.repo.list_all()]

    async def options(self) -> list[OptionItem]:
        return [option(s) for s in await self.repo.list_active()]

    async def _validate(self, data: ShiftInput, current: Shift | None) -> dict:
        errors = FieldErrors()
        code, name = data.code.strip(), data.name.strip()
        if not code:
            errors.add("code", "Enter a short code.")
        elif len(code) > 10:
            errors.add("code", "Use at most 10 characters.")
        elif not SHIFT_CODE.match(code):
            errors.add("code", "Use letters, digits and hyphens only.")
        elif await self.repo.code_taken(code, current.id if current else None):
            errors.add("code", "Another shift already uses this code.")
        if len(name) < 2:
            errors.add("name", "Enter a name.")
        elif len(name) > 60:
            errors.add("name", "Use at most 60 characters.")
        if not TIME.match(data.start):
            errors.add("start", "Enter a start time.")
        if not TIME.match(data.end):
            errors.add("end", "Enter an end time.")
        for field, value, limit in (("breakMinutes", data.break_minutes, MAX_BREAK_MINUTES), ("graceMinutes", data.grace_minutes, MAX_GRACE_MINUTES)):
            if value < 0:
                errors.add(field, "Cannot be negative.")
            elif value > limit:
                errors.add(field, f"At most {limit} minutes.")
        days = sorted(set(data.working_days))
        if not days:
            errors.add("workingDays", "Select at least one working day.")
        elif any(d < 1 or d > 7 for d in days):
            errors.add("workingDays", "Use weekdays 1 (Monday) to 7 (Sunday).")

        start = end = None
        if TIME.match(data.start) and TIME.match(data.end):
            start, end = _parse(data.start), _parse(data.end)
            if start == end:
                errors.add("end", "End time must differ from start time.")
            else:
                ends_next_day = end < start
                if ends_next_day and not data.overnight:
                    errors.add("overnight", "This shift ends after midnight. Confirm it is an overnight shift, or correct the times.")
                if not ends_next_day and data.overnight:
                    errors.add("overnight", "An overnight shift must end earlier in the day than it starts (e.g. 22:00–06:00).")
                length = _length_minutes(start, end)
                if length > MAX_SHIFT_MINUTES:
                    errors.add("end", "A shift cannot be longer than 16 hours.")
                if not errors.has("breakMinutes") and data.break_minutes >= length:
                    errors.add("breakMinutes", "The break must be shorter than the shift.")

        ids = [body_id(v) for v in data.department_ids]
        department_ids = list(dict.fromkeys(i for i in ids if i is not None))
        if None in ids or len(await self.departments.get_many(department_ids)) != len(department_ids):
            errors.add("departmentIds", "Select existing departments.")
        errors.raise_if_any()
        return {
            "code": code, "name": name, "start_time": start, "end_time": end, "overnight": data.overnight, "break_minutes": data.break_minutes,
            "grace_minutes": data.grace_minutes, "working_days": days, "active": data.active, "department_ids": department_ids,
        }

    @staticmethod
    def _apply(shift: Shift, values: dict) -> None:
        department_ids = values.pop("department_ids")
        for key, value in values.items():
            setattr(shift, key, value)
        wanted = set(department_ids)
        shift.department_links = [link for link in shift.department_links if link.department_id in wanted]
        have = {link.department_id for link in shift.department_links}
        shift.department_links.extend(ShiftDepartment(department_id=d) for d in department_ids if d not in have)

    async def create(self, data: ShiftInput) -> ShiftOut:
        values = await self._validate(data, None)
        shift = Shift(department_links=[])
        self._apply(shift, values)
        self.repo.add(shift)
        await self.session.flush()
        self.audit.record(
            module="Attendance", action="shift.created", summary=f"Shift {shift.code} created", entity_type="shift", entity_id=shift.id, entity_label=shift.name, changes=diff({}, _snapshot(shift))
        )
        await self.session.commit()
        return await self._reloaded(shift.id)

    async def update(self, shift_id: uuid.UUID, data: ShiftInput) -> ShiftOut:
        shift = await self.repo.get(shift_id)
        if shift is None:
            raise NotFoundError()
        ensure_version(shift, data.version)
        values = await self._validate(data, shift)
        before = _snapshot(shift)
        self._apply(shift, values)
        changes = diff(before, _snapshot(shift))
        if changes:
            await self.session.flush()
            self.audit.record(
                module="Attendance", action="shift.updated", summary=f"Shift {shift.code} updated", entity_type="shift", entity_id=shift.id, entity_label=shift.name, changes=changes
            )
            await self.session.commit()
        return await self._reloaded(shift.id)

    async def _reloaded(self, shift_id: uuid.UUID) -> ShiftOut:
        shift = await self.repo.get(shift_id)
        assert shift is not None
        await self.session.refresh(shift, ["department_links"])
        return _out(shift, await EmployeeRepository(self.session).active_count(Employee.shift_id, shift.id))
