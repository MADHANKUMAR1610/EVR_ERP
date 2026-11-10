"""Payroll (frontend payroll.service.ts, contracts E4 and H4). Field names match the frontend exactly.

Amounts are numbers in the period's currency. They are null when the caller lacks hr.payroll:view-amounts.
HR setup schemas (components, structures, employee salaries, periods) are additions without a frontend screen.
"""

from typing import Literal

from pydantic import Field

from app.schemas.attendance_schema import EmployeeRefOut, WorkflowEventOut
from app.schemas.common import CamelModel, Page, ResponseModel, UtcDateTime
from app.schemas.employee_schema import NamedRefOut

PeriodStatus = Literal["open", "validated", "calculated", "submitted", "approved", "rejected", "payslips_published"]
ComponentType = Literal["earning", "deduction", "employer_contribution"]
Formula = Literal["fixed", "percent", "balance_of_gross", "overtime_rate", "slab"]
ResultException = Literal["missing_salary", "attendance_exceptions", "pending_requests", "prorated", "large_change"]
Frequency = Literal["monthly", "semi_monthly", "biweekly", "weekly"]
Scope = Literal["company", "department", "employee"]


class PayrollPeriodOut(ResponseModel):
    id: str
    month: str
    label: str
    from_: str = Field(alias="from", serialization_alias="from")
    to: str
    status: PeriodStatus
    currency: str
    employees_included: int | None
    calculated_at: UtcDateTime | None = None
    history: list[WorkflowEventOut]
    version: int


class MoneyOut(ResponseModel):
    gross: float | None
    deductions: float | None
    net: float | None


class PeriodSummaryOut(ResponseModel):
    period: PayrollPeriodOut
    employees_included: int
    needing_review: int
    missing_salary: int
    attendance_exceptions: int
    pending_approvals: int
    totals: MoneyOut | None
    as_of: UtcDateTime


class ValidationCheckOut(ResponseModel):
    code: str
    label: str
    status: Literal["passed", "warning", "blocking"]
    count: int
    detail: str
    link: str | None = None


class ValidationResultOut(ResponseModel):
    checks: list[ValidationCheckOut]
    can_calculate: bool
    validated_at: UtcDateTime


class ValidationWithPeriodOut(ValidationResultOut):
    period: PayrollPeriodOut


class PayrollInputRowOut(ResponseModel):
    employee: EmployeeRefOut
    days_in_period: float
    paid_days: float
    loss_of_pay_days: float
    leave_days: float
    overtime_minutes: int
    salary_assigned: bool
    issues: list[str]


class PayrollResultRowOut(MoneyOut):
    employee: EmployeeRefOut
    paid_days: float
    exceptions: list[ResultException]


class ComponentRefOut(ResponseModel):
    code: str
    name: str
    type: ComponentType


class ResultLineOut(ResponseModel):
    component: ComponentRefOut
    amount: float | None


class PayrollResultDetailOut(PayrollResultRowOut):
    lines: list[ResultLineOut]
    previous_net: float | None


class ResultsPageOut(Page[PayrollResultRowOut]):
    totals: MoneyOut
    currency: str


class VersionIn(CamelModel):
    version: int


class SubmissionIn(CamelModel):
    version: int
    comment: str | None = Field(default=None, max_length=1000)


class PeriodDecisionIn(CamelModel):
    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=1000)
    version: int


# --- Configuration ------------------------------------------------------------------------------------------


class SalaryComponentOut(ResponseModel):
    id: str
    code: str
    name: str
    type: ComponentType
    rule: str
    taxable: bool | None
    statutory: bool
    active: bool


class StructureComponentOut(ResponseModel):
    component_id: str
    code: str
    name: str
    type: ComponentType
    rule: str


class SalaryStructureOut(ResponseModel):
    id: str
    code: str
    name: str
    description: str
    components: list[StructureComponentOut]
    employees_assigned: int
    effective_from: str
    active: bool


class StructureRefOut(ResponseModel):
    id: str
    name: str


class EmployeeSalaryRowOut(ResponseModel):
    employee: EmployeeRefOut
    structure: StructureRefOut | None
    effective_from: str | None
    monthly_gross: float | None
    currency: str


class SalaryHistoryOut(ResponseModel):
    effective_from: str
    structure_name: str
    monthly_gross: float | None
    reason: str


class EmployeeSalaryDetailOut(EmployeeSalaryRowOut):
    lines: list[ResultLineOut]
    history: list[SalaryHistoryOut]


# --- Payslips and reports -----------------------------------------------------------------------------------


class PayslipPeriodOut(ResponseModel):
    id: str
    label: str
    month: str


class PayslipOut(ResponseModel):
    id: str
    employee: EmployeeRefOut
    period: PayslipPeriodOut
    net_pay: float | None
    currency: str
    published_at: UtcDateTime


class DepartmentTotalsOut(MoneyOut):
    department: NamedRefOut
    employees: int


class ComponentTotalOut(ResponseModel):
    component: ComponentRefOut
    amount: float


class ReportTotalsOut(MoneyOut):
    employees: int


class PayrollReportOut(ResponseModel):
    period: PayrollPeriodOut
    currency: str
    by_department: list[DepartmentTotalsOut]
    component_totals: list[ComponentTotalOut]
    totals: ReportTotalsOut


# --- Configurations and assignments (H4) --------------------------------------------------------------------------


class ComponentLinkOut(ResponseModel):
    component_id: str
    code: str
    name: str


class OvertimeConfigOut(ResponseModel):
    eligible: bool
    policy: NamedRefOut | None


class PayrollConfigurationOut(ResponseModel):
    id: str
    code: str
    name: str
    description: str
    frequency: Frequency
    structure: NamedRefOut | None
    earnings: list[ComponentLinkOut]
    deductions: list[ComponentLinkOut]
    employer_contributions: list[ComponentLinkOut]
    overtime: OvertimeConfigOut
    attendance_rule: NamedRefOut | None
    loss_of_pay_rule: NamedRefOut | None
    employee_categories: list[NamedRefOut]
    approval_workflow: NamedRefOut | None
    effective_from: str
    effective_to: str | None
    status: Literal["active", "inactive"]
    assignments_count: int
    created_at: UtcDateTime
    created_by: str
    updated_at: UtcDateTime
    updated_by: str
    version: int


class PayrollConfigurationIn(CamelModel):
    code: str = Field(max_length=40)
    name: str = Field(max_length=200)
    description: str = Field(default="", max_length=2000)
    frequency: Frequency
    structure_id: str | None = None
    component_ids: list[str] = Field(default_factory=list, max_length=200)
    overtime_eligible: bool = False
    overtime_policy_id: str | None = None
    attendance_rule_id: str | None = None
    loss_of_pay_rule_id: str | None = None
    employee_category_ids: list[str] = Field(default_factory=list, max_length=100)
    approval_workflow_id: str | None = None
    effective_from: str = Field(max_length=10)
    effective_to: str | None = Field(default=None, max_length=10)
    status: Literal["active", "inactive"]
    version: int | None = None


class OptionComponentOut(ResponseModel):
    id: str
    code: str
    name: str
    type: ComponentType


class PayrollConfigurationOptionsOut(ResponseModel):
    structures: list[NamedRefOut]
    components: list[OptionComponentOut]
    employee_categories: list[NamedRefOut]
    approval_workflows: list[NamedRefOut]
    attendance_rules: list[NamedRefOut]
    loss_of_pay_rules: list[NamedRefOut]
    overtime_policies: list[NamedRefOut]


class ConfigurationRefOut(ResponseModel):
    id: str
    code: str
    name: str


class PayrollAssignmentOut(ResponseModel):
    id: str
    configuration: ConfigurationRefOut
    scope: Scope
    department: NamedRefOut | None
    employee: EmployeeRefOut | None
    effective_from: str
    effective_to: str | None
    status: Literal["active", "scheduled", "ended"]
    reason: str | None
    conflict: bool
    created_at: UtcDateTime
    created_by: str
    version: int


class PayrollAssignmentIn(CamelModel):
    configuration_id: str
    scope: Scope
    department_id: str | None = None
    employee_id: str | None = None
    effective_from: str = Field(max_length=10)
    effective_to: str | None = Field(default=None, max_length=10)
    reason: str = Field(max_length=500)
    confirm_period_in_progress: bool | None = None


class AssignmentEndIn(CamelModel):
    effective_to: str = Field(max_length=10)
    reason: str = Field(max_length=500)
    version: int
    confirm_period_in_progress: bool | None = None


class PeriodRefOut(ResponseModel):
    id: str
    label: str
    status: PeriodStatus


class AssignmentImpactOut(ResponseModel):
    affected_employees: int
    period_in_progress: PeriodRefOut | None
    overlapping: list[PayrollAssignmentOut]
    blocked_by: str | None


class EffectiveConfigurationOut(ResponseModel):
    employee: EmployeeRefOut
    date: str
    status: Literal["resolved", "missing", "conflict"]
    configuration: ConfigurationRefOut | None
    source: Scope | None
    assignment: PayrollAssignmentOut | None
    candidates: list[PayrollAssignmentOut]
    salary_structure: NamedRefOut | None
    configuration_structure: NamedRefOut | None
    warnings: list[str]


class AssignmentHistoryEntryOut(ResponseModel):
    id: str
    at: UtcDateTime
    by: str
    action: Literal["assigned", "ended"]
    assignment: PayrollAssignmentOut
    summary: str


# --- HR setup (additions) ------------------------------------------------------------------------------------------


class SlabIn(CamelModel):
    from_: float = Field(alias="from", ge=0)
    to: float | None = None
    amount: float | None = Field(default=None, ge=0)
    rate: float | None = Field(default=None, ge=0, le=100)


class SalaryComponentIn(CamelModel):
    code: str = Field(max_length=20)
    name: str = Field(max_length=200)
    type: ComponentType
    formula: Formula
    rate: float | None = Field(default=None, ge=0)
    base: list[str] = Field(default_factory=list, max_length=50)
    base_cap: float | None = Field(default=None, ge=0)
    max_amount: float | None = Field(default=None, ge=0)
    slabs: list[SlabIn] = Field(default_factory=list, max_length=50)
    prorate: bool = False
    taxable: bool | None = None
    statutory: bool = False
    active: bool = True
    version: int | None = None


class SalaryComponentSetupOut(SalaryComponentOut):
    formula: Formula
    rate: float | None
    base: list[str]
    base_cap: float | None
    max_amount: float | None
    slabs: list[dict]
    prorate: bool
    version: int


class SalaryStructureIn(CamelModel):
    code: str = Field(max_length=20)
    name: str = Field(max_length=200)
    description: str = Field(default="", max_length=2000)
    component_ids: list[str] = Field(max_length=100)
    effective_from: str = Field(max_length=10)
    active: bool = True
    version: int | None = None


class SalaryValueIn(CamelModel):
    component_id: str
    amount: float | None = Field(default=None, ge=0)
    rate: float | None = Field(default=None, ge=0)


class EmployeeSalaryIn(CamelModel):
    employee_id: str
    structure_id: str
    effective_from: str = Field(max_length=10)
    monthly_gross: float | None = Field(default=None, ge=0)
    values: list[SalaryValueIn] = Field(default_factory=list, max_length=100)
    reason: str = Field(max_length=500)


class PayrollPeriodIn(CamelModel):
    month: str = Field(max_length=7)
    currency: str = Field(max_length=3)
