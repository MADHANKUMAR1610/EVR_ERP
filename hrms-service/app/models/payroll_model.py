"""Payroll (Module 7): salary components, structures, employee salary records, payroll periods with their
history and results, payslips, payroll configurations and their assignments (contracts E4 and H4).

Nothing is pre-filled: components, rates, slabs, structures and salaries are entered by HR (decision Q3).
Money is numeric(14,2); calculation uses Decimal.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import AuditMixin, Base, UUIDPrimaryKeyMixin, VersionMixin


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


COMPONENT_TYPES = ("earning", "deduction", "employer_contribution")
FORMULA_TYPES = ("fixed", "percent", "balance_of_gross", "overtime_rate", "slab")


class SalaryComponent(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """A pay component with one formula type (decision Q3). Rates, caps and slabs are HR-entered."""

    __tablename__ = "salary_component"

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(25), nullable=False)
    formula: Mapped[str] = mapped_column(String(20), nullable=False)
    # percent: rate in %; overtime_rate: amount per hour (default for employees without their own rate).
    rate: Mapped[float | None] = mapped_column(Numeric(14, 4))
    # percent / slab base: "gross" (all earnings calculated before) or component codes.
    base: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list, server_default=text("'{}'"))
    base_cap: Mapped[float | None] = mapped_column(Numeric(14, 2))
    max_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    # slab: [{"from": n, "to": n|null, "amount": n|null, "rate": n|null}], chosen by the base amount.
    slabs: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'"))
    prorate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    taxable: Mapped[bool | None] = mapped_column(Boolean)
    statutory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    __table_args__ = (
        CheckConstraint("code ~ '^[A-Z0-9_-]{1,20}$'", name="code_format"),
        CheckConstraint(_in("type", COMPONENT_TYPES), name="type"),
        CheckConstraint(_in("formula", FORMULA_TYPES), name="formula"),
        CheckConstraint("rate IS NULL OR rate >= 0", name="rate"),
        CheckConstraint("base_cap IS NULL OR base_cap >= 0", name="base_cap"),
        CheckConstraint("max_amount IS NULL OR max_amount >= 0", name="max_amount"),
    )


class SalaryStructure(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    __tablename__ = "salary_structure"

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # Ordered component ids (calculation order).
    component_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default=text("'{}'"))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    __table_args__ = (CheckConstraint("code ~ '^[A-Z0-9_-]{1,20}$'", name="code_format"),)


class EmployeeSalary(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """A salary record from `effective_from`. Append-only: a revision is a new record (history kept)."""

    __tablename__ = "employee_salary"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False)
    structure_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("salary_structure.id", ondelete="RESTRICT"), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    monthly_gross: Mapped[float | None] = mapped_column(Numeric(14, 2))
    # {component_id: {"amount": n|null, "rate": n|null}} for fixed amounts and per-employee overtime rates.
    values: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'"))
    reason: Mapped[str] = mapped_column(String(500), nullable=False)

    __table_args__ = (
        UniqueConstraint("employee_id", "effective_from", name="uq_employee_salary_employee_date"),
        CheckConstraint("monthly_gross IS NULL OR monthly_gross >= 0", name="monthly_gross"),
        Index("ix_employee_salary_employee", "employee_id", "effective_from"),
    )


PERIOD_STATUSES = ("open", "validated", "calculated", "submitted", "approved", "rejected", "payslips_published")


class PayrollPeriod(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    __tablename__ = "payroll_period"

    month: Mapped[str] = mapped_column(String(7), nullable=False, unique=True)  # YYYY-MM
    from_date: Mapped[date] = mapped_column(Date, nullable=False)
    to_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    employees_included: Mapped[int | None] = mapped_column(Integer)
    validation: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        CheckConstraint(_in("status", PERIOD_STATUSES), name="status"),
        CheckConstraint("month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="month_format"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("to_date >= from_date", name="dates"),
    )


class PayrollPeriodEvent(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Period history (WorkflowEvent shape), append-only."""

    __tablename__ = "payroll_period_event"

    period_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("payroll_period.id", ondelete="RESTRICT"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (CheckConstraint("action IN ('submitted', 'approved', 'rejected', 'cancelled', 'updated', 'commented')", name="action"),)


class PayrollResult(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """One employee's calculated pay for a period (replaced on recalculation until approval)."""

    __tablename__ = "payroll_result"

    period_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("payroll_period.id", ondelete="RESTRICT"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False)
    days_in_period: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    paid_days: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    loss_of_pay_days: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    leave_days: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    overtime_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    gross: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    deductions: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    employer_contributions: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    net: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    previous_net: Mapped[float | None] = mapped_column(Numeric(14, 2))
    exceptions: Mapped[list[str]] = mapped_column(ARRAY(String(30)), nullable=False, default=list)
    # [{"componentId", "code", "name", "type", "amount"}]
    lines: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    salary_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employee_salary.id", ondelete="RESTRICT"))
    configuration_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("payroll_configuration.id", ondelete="RESTRICT"))

    __table_args__ = (UniqueConstraint("period_id", "employee_id", name="uq_payroll_result_period_employee"), Index("ix_payroll_result_employee", "employee_id"))


class Payslip(UUIDPrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "payslip"

    period_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("payroll_period.id", ondelete="RESTRICT"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False)
    result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("payroll_result.id", ondelete="RESTRICT"), nullable=False)
    net_pay: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("period_id", "employee_id", name="uq_payslip_period_employee"), Index("ix_payslip_employee", "employee_id"))


FREQUENCIES = ("monthly", "semi_monthly", "biweekly", "weekly")


class PayrollConfiguration(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """A configurable set of payroll rules and components (H4). Holds no formulas, rates or amounts."""

    __tablename__ = "payroll_configuration"

    code: Mapped[str] = mapped_column(String(12), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    frequency: Mapped[str] = mapped_column(String(15), nullable=False)
    structure_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("salary_structure.id", ondelete="RESTRICT"))
    component_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default=text("'{}'"))
    overtime_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    overtime_policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("overtime_policy_option.id", ondelete="RESTRICT"))
    attendance_rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("attendance_policy_option.id", ondelete="RESTRICT"))
    loss_of_pay_rule: Mapped[str | None] = mapped_column(String(40))
    employee_category_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default=text("'{}'"))
    approval_workflow_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workflow.id", ondelete="RESTRICT"))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")

    __table_args__ = (
        CheckConstraint("char_length(code) BETWEEN 2 AND 12", name="code_length"),
        CheckConstraint(_in("frequency", FREQUENCIES), name="frequency"),
        CheckConstraint("status IN ('active', 'inactive')", name="status"),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="dates"),
    )


SCOPES = ("company", "department", "employee")


class PayrollAssignment(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """Who a configuration applies to, and when. Never edited or deleted, only ended (H4)."""

    __tablename__ = "payroll_assignment"

    configuration_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("payroll_configuration.id", ondelete="RESTRICT"), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(10), nullable=False)
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("department.id", ondelete="RESTRICT"), index=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), index=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        CheckConstraint(_in("scope", SCOPES), name="scope"),
        CheckConstraint("(scope = 'company' AND department_id IS NULL AND employee_id IS NULL) OR (scope = 'department' AND department_id IS NOT NULL AND employee_id IS NULL)"
                        " OR (scope = 'employee' AND employee_id IS NOT NULL AND department_id IS NULL)", name="scope_target"),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="dates"),
    )


class PayrollAssignmentHistory(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Append-only history of assignment creation and ending."""

    __tablename__ = "payroll_assignment_history"

    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("payroll_assignment.id", ondelete="RESTRICT"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)

    __table_args__ = (CheckConstraint("action IN ('assigned', 'ended')", name="action"),)
