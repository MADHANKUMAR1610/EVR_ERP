"""Mounts every concept controller under the API prefix (/api/v1).

Each business concept has its own controller module in app/api/controllers/.
"""

from fastapi import APIRouter

from app.api.controllers import (
    approvals_controller,
    attendance_admin_controller,
    attendance_controller,
    department_controller,
    document_compliance_controller,
    document_settings_controller,
    designation_controller,
    employee_access_scope_controller,
    employee_controller,
    employee_document_controller,
    employee_import_controller,
    health_controller,
    internal_controller,
    leave_controller,
    leave_setup_controller,
    payroll_controller,
    performance_controller,
    report_controller,
    workspace_controller,
    reference_data_controller,
    reference_setup_controller,
    reporting_line_controller,
    shift_controller,
    short_request_controller,
)

api_router = APIRouter()
# Module 1: organization and reference data
api_router.include_router(reference_data_controller.router)  # before shift_controller: /hr/shifts/options
api_router.include_router(employee_access_scope_controller.router)  # before the generic /hr/setup/{kind}
api_router.include_router(attendance_admin_controller.setup_router)  # before the generic /hr/setup/{kind}
api_router.include_router(document_settings_controller.router)  # before the generic /hr/setup/{kind}
api_router.include_router(leave_setup_controller.router)  # Module 6; before the generic /hr/setup/{kind}
api_router.include_router(payroll_controller.setup_router)  # Module 7; before the generic /hr/setup/{kind}
api_router.include_router(performance_controller.setup_router)  # Module 8; before the generic /hr/setup/{kind}
api_router.include_router(reference_setup_controller.router)
api_router.include_router(department_controller.router)
api_router.include_router(designation_controller.router)
api_router.include_router(shift_controller.router)

# Module 2: employees (after reference_data_controller: /hr/employees/payroll-fields)
api_router.include_router(employee_controller.router)
api_router.include_router(reporting_line_controller.router)

# Module 3: employee documents
api_router.include_router(employee_document_controller.router)
api_router.include_router(document_compliance_controller.router)

# Module 4: employee import
api_router.include_router(employee_import_controller.router)

# Module 5: time & attendance
api_router.include_router(attendance_controller.router)
api_router.include_router(attendance_controller.shifts_router)
api_router.include_router(attendance_controller.devices_router)
api_router.include_router(attendance_admin_controller.policies_router)
api_router.include_router(attendance_admin_controller.workflows_router)

# Module 6: leave management, permission and overtime requests, approval inbox
api_router.include_router(leave_controller.lookups_router)
api_router.include_router(leave_controller.router)
api_router.include_router(short_request_controller.permission_router)
api_router.include_router(short_request_controller.overtime_router)
api_router.include_router(approvals_controller.router)

# Module 7: payroll
api_router.include_router(payroll_controller.router)
api_router.include_router(payroll_controller.me_router)

# Module 8: performance
api_router.include_router(performance_controller.router)

# Module 9: reports
api_router.include_router(report_controller.router)

# Module 10: HR workspace
api_router.include_router(workspace_controller.router)

# Views for the Platform service's administration screens (audit, overview)
api_router.include_router(internal_controller.router)

root_router = APIRouter()
root_router.include_router(health_controller.router)
