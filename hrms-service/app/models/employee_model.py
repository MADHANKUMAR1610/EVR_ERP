"""Employee records: the employee, their contact details, payroll values, history and reporting lines."""

import uuid
from datetime import date

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import AuditMixin, Base, UUIDPrimaryKeyMixin, VersionMixin

HISTORY_ACTIONS = ("created", "updated", "status_changed", "document_uploaded", "imported")


class Employee(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    __tablename__ = "employee"

    employee_code: Mapped[str] = mapped_column(String(30), nullable=False)
    first_name: Mapped[str] = mapped_column(String(50), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(50))
    last_name: Mapped[str | None] = mapped_column(String(50))
    # Maintained by the service from the name parts; used for search and sorting.
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date)

    joining_date: Mapped[date] = mapped_column(Date, nullable=False)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("department.id", ondelete="RESTRICT"), nullable=False)
    designation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("designation.id", ondelete="RESTRICT"), nullable=False)
    employment_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employment_type.id", ondelete="RESTRICT"), nullable=False)
    status_code: Mapped[str] = mapped_column(String(30), ForeignKey("employee_status.code", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False)
    reporting_manager_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"))
    work_location_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("work_location.id", ondelete="RESTRICT"))
    probation_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    probation_end_date: Mapped[date | None] = mapped_column(Date)
    confirmation_date: Mapped[date | None] = mapped_column(Date)

    attendance_id: Mapped[str | None] = mapped_column(String(30))
    shift_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("shift.id", ondelete="RESTRICT"))
    attendance_policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("attendance_policy_option.id", ondelete="RESTRICT"))
    overtime_policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("overtime_policy_option.id", ondelete="RESTRICT"))

    contact: Mapped["EmployeeContact | None"] = relationship(back_populates="employee", cascade="all, delete-orphan", uselist=False, lazy="raise")
    payroll_values: Mapped[list["EmployeePayrollValue"]] = relationship(cascade="all, delete-orphan", lazy="raise")

    __table_args__ = (
        CheckConstraint("reporting_manager_id IS NULL OR reporting_manager_id <> id", name="not_own_manager"),
        CheckConstraint("employee_code !~ '\\s'", name="code_without_spaces"),
        CheckConstraint("NOT probation_applicable OR probation_end_date IS NOT NULL", name="probation_end_date"),
        Index("uq_employee_code_lower", func.lower(employee_code), unique=True),
        Index("uq_employee_attendance_id", "attendance_id", unique=True, postgresql_where=text("attendance_id IS NOT NULL")),
        Index("ix_employee_full_name_lower", func.lower(full_name)),
        Index("ix_employee_department_id", "department_id"),
        Index("ix_employee_designation_id", "designation_id"),
        Index("ix_employee_status_code", "status_code"),
        Index("ix_employee_reporting_manager_id", "reporting_manager_id"),
        Index("ix_employee_shift_id", "shift_id"),
    )


class EmployeeContact(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Contact details, kept apart so they are read only for callers with hr.employees:view-contact."""

    __tablename__ = "employee_contact"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="CASCADE"), nullable=False, unique=True)
    mobile: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(254))
    address_line1: Mapped[str | None] = mapped_column(String(120))
    address_line2: Mapped[str | None] = mapped_column(String(120))
    address_city: Mapped[str | None] = mapped_column(String(60))
    address_state: Mapped[str | None] = mapped_column(String(60))
    address_postal_code: Mapped[str | None] = mapped_column(String(12))
    address_country: Mapped[str | None] = mapped_column(String(60))
    emergency_name: Mapped[str | None] = mapped_column(String(100))
    emergency_relationship: Mapped[str | None] = mapped_column(String(40))
    emergency_phone: Mapped[str | None] = mapped_column(String(20))

    employee: Mapped[Employee] = relationship(back_populates="contact", lazy="raise")

    __table_args__ = (Index("uq_employee_contact_email_lower", func.lower(email), unique=True, postgresql_where=text("email IS NOT NULL")),)


class EmployeePayrollValue(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """One payroll field value. Values of sensitive fields are stored encrypted (app/core/crypto.py)."""

    __tablename__ = "employee_payroll_value"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="CASCADE"), nullable=False)
    field_key: Mapped[str] = mapped_column(String(50), ForeignKey("payroll_field_definition.key", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (UniqueConstraint("employee_id", "field_key"),)


class EmployeeHistory(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """What the profile's history tab shows. Append-only (database trigger). Never stores field values."""

    __tablename__ = "employee_history"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    changes: Mapped[list[str] | None] = mapped_column(ARRAY(String(60)))
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str | None] = mapped_column(String(30))
    effective_date: Mapped[date | None] = mapped_column(Date)
    comment: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(f"action IN ({', '.join(repr(a) for a in HISTORY_ACTIONS)})", name="action"),
        Index("ix_employee_history_employee_created", "employee_id", "created_at"),
    )


class EmployeeReportingLine(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Effective-dated reporting manager history. The current manager is also on employee.reporting_manager_id."""

    __tablename__ = "employee_reporting_line"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300))

    __table_args__ = (Index("ix_employee_reporting_line_employee", "employee_id", "effective_from"),)
