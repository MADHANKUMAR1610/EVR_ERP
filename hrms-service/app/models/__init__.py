"""Imports every model module so Base.metadata is complete (used by Alembic and tests)."""

from app.models import (  # noqa: F401
    attendance_model,
    audit_log_model,
    department_model,
    designation_model,
    employee_access_scope_model,
    employee_document_model,
    employee_model,
    import_job_model,
    leave_model,
    payroll_model,
    performance_model,
    report_model,
    reference_data_model,
    shift_model,
)
