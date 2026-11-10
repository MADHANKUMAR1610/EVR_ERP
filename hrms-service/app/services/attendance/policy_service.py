"""HR policies (contract G6): areas `attendance`, `shifts`, `overtime` (Module 5), `leave` (Module 6) and `payroll` (Module 7).

The backend defines the fields; HR enters the values. Every field starts EMPTY (null): nothing is
pre-filled, and a rule whose value is empty is simply not applied (the calculation reports a warning
where that matters). Changes apply from `effectiveFrom` (today or later), never backwards.
The other G6 area (performance) arrives with its module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, StaleVersionError
from app.core.permissions import A
from app.models.attendance_model import PolicySetting
from app.schemas.policy_schema import PolicyDocumentOut, PolicyFieldOut, PolicyOptionOut, PolicySaveIn
from app.services.audit_service import AuditService, diff
from app.services.employee_support import company_today, parse_date
from app.utils.validation import FieldErrors


@dataclass(frozen=True)
class PolicyField:
    key: str
    label: str
    help: str
    type: str  # number | boolean | select
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    options: tuple[tuple[str, str], ...] | None = None  # select: (value, label)


FIELDS: dict[str, tuple[PolicyField, ...]] = {
    "attendance": (
        PolicyField("deductBreak", "Deduct shift break from worked time", "When on, the shift's break minutes are subtracted from worked time.", "boolean"),
        PolicyField("halfDayBelowMinutes", "Half day below", "Worked time below this counts as a half day. Empty: not applied.", "number", "minutes", 1, 1440),
        PolicyField("absentBelowMinutes", "Absent below", "Worked time below this counts as absent. Empty: not applied.", "number", "minutes", 1, 1440),
        PolicyField("correctionWindowDays", "Correction window", "How many days back a correction may be requested. Empty: no limit applied.", "number", "days", 1, 366),
        PolicyField("duplicateWindowSeconds", "Duplicate punch window", "Punches of the same employee, direction and device within this time are duplicates. Empty: only exact resends are duplicates.", "number", "seconds", 1, 3600),
        PolicyField("delayedSyncMinutes", "Delayed sync after", "A punch received later than this after it happened is flagged as delayed. Empty: not flagged.", "number", "minutes", 1, 10080),
    ),
    "shifts": (
        PolicyField("allowBackdatedAssignments", "Allow back-dated shift assignments", "Off (empty) by default. When on, users with hr.shifts:assign-backdated may assign shifts from a past date, with a reason.", "boolean"),
        PolicyField("maxBackdatedDays", "Back-dating limit", "How many days back an assignment may start. Empty: no limit when back-dating is allowed.", "number", "days", 1, 366),
    ),
    "overtime": (
        PolicyField("calculateOvertime", "Calculate overtime", "When on, overtime is calculated for employees who have an overtime policy assigned.", "boolean"),
        PolicyField("minimumMinutes", "Minimum overtime", "Time beyond the shift below this is not overtime. Empty: no minimum.", "number", "minutes", 1, 1440),
        PolicyField("roundingMinutes", "Round down to", "Overtime is rounded down to a multiple of this. Empty: no rounding.", "number", "minutes", 1, 240),
        PolicyField("maxMinutesPerDay", "Daily overtime cap", "Overtime per day is capped at this. Empty: no cap.", "number", "minutes", 1, 1440),
    ),
    # Module 6 (MODULE_6_DECISIONS.md). Every value is entered by HR; empty means the rule is not applied.
    "leave": (
        PolicyField("allowNegativeBalance", "Allow applications beyond the balance", "Off (empty) by default: an application that needs more days than are available is refused. When on, it is accepted and the balance may go negative.", "boolean"),
        PolicyField("countOffsWithinLeave", "Charge weekly offs and holidays inside leave", "When on, weekly offs and holidays between the first and last day are charged as leave. Empty: they are not charged.", "boolean"),
        PolicyField("minimumNoticeDays", "Minimum notice", "Leave must be applied at least this many days before it starts. Empty: no minimum.", "number", "days", 1, 365),
        PolicyField("backdatedWindowDays", "Back-dated leave window", "How many days back leave may be applied for. Empty: no limit.", "number", "days", 1, 366),
        PolicyField("leaveYearStartMonth", "Leave year starts in", "Month (1-12) the leave year starts. Empty: the calendar year (January).", "number", "month", 1, 12),
        PolicyField("lowBalanceThreshold", "Low balance alert at", "The leave dashboard lists balances at or below this. Empty: no list.", "number", "days", 0, 365),
        PolicyField("upcomingWindowDays", "Upcoming leave window", "The leave dashboard lists approved leave starting within this many days. Empty: no list.", "number", "days", 1, 90),
    ),
    # Module 7 (MODULE_7_DECISIONS.md). Pay-affecting: needs admin:policies.payroll-manage. All empty until HR sets them.
    "payroll": (
        PolicyField("prorationBasis", "Days in a pay period", "How the days of a period are counted for proration. Empty: payroll cannot be calculated.", "select",
                    options=(("calendar_days", "Calendar days of the month"), ("working_days", "Working days of the employee (shift, minus holidays)"), ("fixed_days", "A fixed number of days"))),
        PolicyField("fixedDaysPerMonth", "Fixed days per month", "Used when the basis is a fixed number of days.", "number", "days", 1, 31),
        PolicyField("absenceIsLossOfPay", "Absences are loss of pay", "When on, attendance absences (and the unworked half of half days) without leave are unpaid. Unpaid leave types are always loss of pay.", "boolean"),
        PolicyField("largeChangePercent", "Flag a large change in net pay at", "Results whose net pay differs from the previous period by more than this percentage are flagged. Empty: not flagged.", "number", "%", 1, 1000),
        PolicyField("allowSelfApproval", "Allow the submitter to approve", "Off (empty) by default: the approver must be a different person from the one who submitted the period.", "boolean"),
    ),
}
# G6: attendance (pay-affecting) needs the payroll-manage permission; other areas policies.manage.
MANAGE_PERMISSION = {"attendance": A.POLICIES_PAYROLL_MANAGE, "shifts": A.POLICIES_MANAGE, "overtime": A.POLICIES_MANAGE, "leave": A.POLICIES_MANAGE, "payroll": A.POLICIES_PAYROLL_MANAGE}


def _field_out(f: PolicyField) -> PolicyFieldOut:
    options = [PolicyOptionOut(value=v, label=label) for v, label in f.options] if f.options else None
    return PolicyFieldOut(key=f.key, label=f.label, help=f.help, type=f.type, unit=f.unit, min=f.min, max=f.max, options=options, optional=True)


class PolicyValues:
    """Values of the policy areas in force on a given date (empty values are None)."""

    def __init__(self, values: dict[str, dict]):
        self._values = values

    def get(self, area: str, key: str):
        return self._values.get(area, {}).get(key)

    def on(self, area: str, key: str) -> bool:
        return self.get(area, key) is True


async def policy_values_on(session: AsyncSession, day: date) -> PolicyValues:
    out: dict[str, dict] = {}
    for area in FIELDS:
        row = await session.scalar(select(PolicySetting).where(PolicySetting.area == area, PolicySetting.effective_from <= day).order_by(PolicySetting.effective_from.desc()).limit(1))
        out[area] = dict(row.values) if row else {}
    return PolicyValues(out)


class PolicyService:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _area(area: str) -> tuple[PolicyField, ...]:
        if area not in FIELDS:
            raise NotFoundError("This policy area is not available yet.")
        return FIELDS[area]

    async def _latest(self, area: str) -> PolicySetting | None:
        return await self.session.scalar(select(PolicySetting).where(PolicySetting.area == area).order_by(PolicySetting.effective_from.desc()).limit(1))

    async def get(self, area: str) -> PolicyDocumentOut:
        fields = self._area(area)
        row = await self._latest(area)
        values = {f.key: (row.values.get(f.key) if row else None) for f in fields}
        return PolicyDocumentOut(
            area=area, fields=[_field_out(f) for f in fields], values=values, effective_from=row.effective_from.isoformat() if row else None,
            version=row.version if row else 0, updated_at=row.updated_at if row else None, updated_by=row.updated_by_name if row else None,
        )

    async def save(self, area: str, data: PolicySaveIn) -> PolicyDocumentOut:
        fields = {f.key: f for f in self._area(area)}
        latest = await self._latest(area)
        if (latest.version if latest else 0) != data.version:
            raise StaleVersionError()
        err = FieldErrors()
        effective = None
        try:
            effective = parse_date(data.effective_from)
        except ValueError:
            pass
        if effective is None:
            err.add("effectiveFrom", "Enter the date the change takes effect.")
        elif effective < company_today():
            err.add("effectiveFrom", "Changes cannot take effect in the past.")
        clean: dict = {}
        for key, value in data.values.items():
            f = fields.get(key)
            if f is None:
                err.add(f"values.{key}", "This setting does not exist.")
                continue
            if value is None or value == "":
                clean[key] = None
            elif f.type == "boolean":
                if not isinstance(value, bool):
                    err.add(f"values.{key}", "Choose on or off.")
                clean[key] = value
            elif f.type == "select":
                if value not in {v for v, _ in f.options or ()}:
                    err.add(f"values.{key}", "Choose one of the listed options.")
                clean[key] = value
            else:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != int(value):
                    err.add(f"values.{key}", "Enter a whole number.")
                    continue
                if (f.min is not None and value < f.min) or (f.max is not None and value > f.max):
                    err.add(f"values.{key}", f"Enter a value from {f.min:g} to {f.max:g}.")
                clean[key] = int(value)
        err.raise_if_any()
        full = {k: clean.get(k) for k in fields}
        before = dict(latest.values) if latest else {k: None for k in fields}
        row = await self.session.scalar(select(PolicySetting).where(PolicySetting.area == area, PolicySetting.effective_from == effective))
        if row is None:
            row = PolicySetting(area=area, values=full, effective_from=effective)
            self.session.add(row)
        else:
            row.values = full
        await self.session.flush()
        AuditService(self.session).record(
            module="HR Policies", action="policy.updated", summary=f"{area.capitalize()} policy changed from {effective.isoformat()}", entity_type="policy_setting", entity_id=row.id,
            entity_label=area, changes=diff(before, full),
        )
        await self.session.commit()
        return await self.get(area)
