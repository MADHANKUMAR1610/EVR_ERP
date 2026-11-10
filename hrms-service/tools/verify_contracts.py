"""Compares the backend schemas and routes (modules 1 to 10) with the frontend TypeScript contracts.

    FRONTEND_SRC=/path/to/EVR-ERP/src python tools/verify_contracts.py
"""
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os
FE = Path(os.environ.get('FRONTEND_SRC', '../EVR-ERP/src')) / 'features'

def ts_fields(file, name):
    src = (FE / file).read_text()
    m = re.search(r'export interface ' + name + r'\b(?:\s+extends\s+(\w+))?\s*\{(.*?)\n\}', src, re.S)
    body = re.sub(r'/\*.*?\*/|//[^\n]*', '', m.group(2), flags=re.S)
    fields = {}
    depth = 0
    for line in body.split('\n'):
        if depth == 0:
            mm = re.match(r'\s*(\w+)(\?)?:', line)
            if mm:
                fields[mm.group(1)] = bool(mm.group(2))
        depth += line.count('{') - line.count('}')
    if m.group(1):
        fields.update(ts_fields(file, m.group(1)))
    return fields

from app.schemas import reference_data_schema as R, department_schema as D, designation_schema as G, shift_schema as S, employee_schema as E, employee_document_schema as DOC, import_schema as IM, attendance_schema as AT_, workflow_schema as WF, policy_schema as PO, leave_schema as L, payroll_schema as PY, performance_schema as PF, report_schema as RP, workspace_schema as WS_

def py_fields(model):
    return {(f.alias or n): (not f.is_required()) for n, f in model.model_fields.items()}

RD = 'hr/reference-data/api/referenceData.service.ts'
AD = 'admin/api/admin.service.ts'
AT = 'hr/attendance/api/attendance.service.ts'
EM = 'hr/employees/api/employees.service.ts'
DS = 'hr/documents/api/documents.service.ts'
IS = 'hr/employee-import/api/employeeImport.service.ts'
WS = 'hr/shared/workflow.ts'
LV = 'hr/leave/api/leave.service.ts'
AP = 'hr/approvals/api/approvals.service.ts'
PR = 'hr/payroll/api/payroll.service.ts'
PS = 'hr/performance/api/performance.service.ts'
RS = 'hr/reports/api/reports.service.ts'
WK = 'hr/workspace/api/workspace.service.ts'
pairs = [
    (RD, 'ReferenceItem', R.ReferenceItem, 'out'), (RD, 'EmployeeStatusOption', R.EmployeeStatusOption, 'out'), (RD, 'OptionItem', R.OptionItem, 'out'),
    (RD, 'DocumentTypeOption', R.DocumentTypeOption, 'out'), (RD, 'PayrollFieldDefinition', R.PayrollFieldDefinitionOut, 'out'),
    (AD, 'Department', D.DepartmentOut, 'out'), (AD, 'Designation', G.DesignationOut, 'out'), (AT, 'Shift', S.ShiftOut, 'out'),
    (AD, 'DepartmentInput', D.DepartmentInput, 'in'), (AD, 'DesignationInput', G.DesignationInput, 'in'), (AT, 'ShiftInput', S.ShiftInput, 'in'),
    # Module 2
    (EM, 'EmployeeListItem', E.EmployeeListItemOut, 'out'), (EM, 'Employee', E.EmployeeOut, 'out'), (EM, 'PersonalDetails', E.PersonalOut, 'out'),
    (EM, 'Address', E.AddressModel, 'out'), (EM, 'EmergencyContact', E.EmergencyContactModel, 'out'), (EM, 'EmploymentDetails', E.EmploymentOut, 'out'),
    (EM, 'WorkReferences', E.WorkModel, 'out'), (EM, 'PayrollDetails', E.PayrollOut, 'out'), (EM, 'AuditInfo', E.AuditInfoOut, 'out'),
    (EM, 'EmployeeLookupItem', E.EmployeeLookupItemOut, 'out'), (EM, 'EmployeeHistoryEntry', E.HistoryEntryOut, 'out'), (AD, 'ReportingLine', E.ReportingLineOut, 'out'),
    (EM, 'EmployeeUpsertRequest', E.EmployeeUpsertIn, 'in'), (EM, 'StatusChangeRequest', E.StatusChangeIn, 'in'), (EM, 'EmploymentDetails', E.EmploymentIn, 'in'),
    # Module 3
    (DS, 'EmployeeDocument', DOC.EmployeeDocumentOut, 'out'), (DS, 'DocumentVerification', DOC.DocumentVerificationOut, 'out'), (DS, 'VerificationEvent', DOC.VerificationEventOut, 'out'),
    (DS, 'ChecklistItem', DOC.ChecklistItemOut, 'out'), (DS, 'CompletionCounts', DOC.CompletionCountsOut, 'out'), (DS, 'DocumentChecklist', DOC.DocumentChecklistOut, 'out'),
    (DS, 'DocumentComplianceRow', DOC.DocumentComplianceRowOut, 'out'), (DS, 'AttentionEmployee', DOC.ComplianceEmployeeOut, 'out'),
    (DS, 'ComplianceSummary', DOC.ComplianceSummaryOut, 'out'), (DS, 'ComplianceAttention', DOC.ComplianceAttentionOut, 'out'),
    # Module 4 (ImportValidationResult gains an extra `summary`, which the frontend ignores)
    (IS, 'ImportFieldDefinition', IM.ImportFieldOut, 'out'), (IS, 'ImportRow', IM.ImportRowIn, 'in'), (IS, 'ImportMessage', IM.ImportMessageOut, 'out'),
    (IS, 'ImportRowResult', IM.ImportRowResultOut, 'out'), (IS, 'ImportJob', IM.ImportJobOut, 'out'),
    # Module 5
    (AT, 'DailyAttendanceRecord', AT_.DailyRecordOut, 'out'), (AT, 'Punch', AT_.PunchOut, 'out'), (AT, 'DailyAttendanceDetail', AT_.DailyDetailOut, 'out'),
    (AT, 'MobileValidation', AT_.MobileValidationOut, 'out'), (AT, 'AttendanceEvent', AT_.AttendanceEventOut, 'out'), (AT, 'CalendarDay', AT_.CalendarDayOut, 'out'),
    (AT, 'CalendarSummary', AT_.CalendarSummaryOut, 'out'), (AT, 'AttendanceCalendar', AT_.CalendarOut, 'out'), (AT, 'DeviceSyncRun', AT_.DeviceSyncRunOut, 'out'),
    (AT, 'DepartmentAttendance', AT_.DepartmentAttendanceOut, 'out'), (AT, 'AttendanceSummary', AT_.SummaryOut, 'out'), (AT, 'MonthlyAttendanceRow', AT_.MonthlyRowOut, 'out'),
    (AT, 'MonthlyAttendanceDetail', AT_.MonthlyDetailOut, 'out'), (AT, 'PunchPair', AT_.PunchPairOut, 'out'), (AT, 'CorrectionRequest', AT_.CorrectionOut, 'out'),
    (AT, 'SubmitCorrectionInput', AT_.CorrectionIn, 'in'), (AT, 'ShiftAssignmentInput', AT_.ShiftAssignmentIn, 'in'), (AT, 'ShiftAssignmentResult', AT_.ShiftAssignmentOut, 'out'),
    (AT, 'AttendanceDevice', AT_.DeviceOut, 'out'), (AT, 'DeviceList', AT_.DeviceListOut, 'out'), (AT, 'ShiftRef', AT_.ShiftRefOut, 'out'),
    (WS, 'EmployeeRef', AT_.EmployeeRefOut, 'out'), (WS, 'WorkflowEvent', AT_.WorkflowEventOut, 'out'), (WS, 'DecisionInput', AT_.DecisionIn, 'in'),
    (AD, 'WorkflowStep', WF.WorkflowStep, 'out'), (AD, 'StepCondition', WF.StepCondition, 'out'), (AD, 'Workflow', WF.WorkflowOut, 'out'), (AD, 'ProcessDefinition', WF.ProcessDefinitionOut, 'out'),
    (AD, 'PolicyField', PO.PolicyFieldOut, 'out'), (AD, 'PolicyDocument', PO.PolicyDocumentOut, 'out'),
    # Module 6 (LeaveWorkflowInput is a TS type alias, checked by the tests; the application is multipart)
    (LV, 'LeaveType', L.LeaveTypeOut, 'out'), (LV, 'LeaveAttachment', L.LeaveAttachmentOut, 'out'), (LV, 'LeaveRequest', L.LeaveRequestOut, 'out'),
    (LV, 'ApproverRef', L.ApproverRefOut, 'out'), (LV, 'LeaveWorkflowNotifications', L.NotificationsOut, 'out'), (LV, 'LeaveApprovalWorkflow', L.LeaveWorkflowOut, 'out'),
    (LV, 'LeaveWorkflowOptions', L.LeaveWorkflowOptionsOut, 'out'), (LV, 'LeaveApprovalState', L.LeaveApprovalStateOut, 'out'), (LV, 'LeaveEstimate', L.LeaveEstimateOut, 'out'),
    (LV, 'LeaveBalance', L.LeaveBalanceOut, 'out'), (LV, 'EmployeeBalances', L.EmployeeBalancesOut, 'out'), (LV, 'LeavePolicy', L.LeavePolicyOut, 'out'),
    (LV, 'Holiday', L.HolidayOut, 'out'), (LV, 'LeaveSummary', L.LeaveSummaryOut, 'out'), (LV, 'PermissionRequest', L.PermissionRequestOut, 'out'),
    (LV, 'PermissionInput', L.PermissionIn, 'in'), (LV, 'OvertimeRequest', L.OvertimeRequestOut, 'out'), (LV, 'OvertimeInput', L.OvertimeIn, 'in'),
    (AP, 'ApprovalItem', L.ApprovalItemOut, 'out'),
    # Module 7 (ResultsPage extends the shared Paginated type: checked by the tests)
    (PR, 'PayrollPeriod', PY.PayrollPeriodOut, 'out'), (PR, 'Money', PY.MoneyOut, 'out'), (PR, 'PeriodSummary', PY.PeriodSummaryOut, 'out'),
    (PR, 'ValidationCheck', PY.ValidationCheckOut, 'out'), (PR, 'ValidationResult', PY.ValidationResultOut, 'out'), (PR, 'PayrollInputRow', PY.PayrollInputRowOut, 'out'),
    (PR, 'PayrollResultRow', PY.PayrollResultRowOut, 'out'), (PR, 'ResultLine', PY.ResultLineOut, 'out'), (PR, 'PayrollResultDetail', PY.PayrollResultDetailOut, 'out'),
    (PR, 'SalaryComponent', PY.SalaryComponentOut, 'out'), (PR, 'SalaryStructure', PY.SalaryStructureOut, 'out'), (PR, 'EmployeeSalaryRow', PY.EmployeeSalaryRowOut, 'out'),
    (PR, 'EmployeeSalaryDetail', PY.EmployeeSalaryDetailOut, 'out'), (PR, 'Payslip', PY.PayslipOut, 'out'), (PR, 'PayrollReport', PY.PayrollReportOut, 'out'),
    (PR, 'PayrollConfiguration', PY.PayrollConfigurationOut, 'out'), (PR, 'PayrollConfigurationInput', PY.PayrollConfigurationIn, 'in'),
    (PR, 'PayrollConfigurationOptions', PY.PayrollConfigurationOptionsOut, 'out'), (PR, 'PayrollAssignment', PY.PayrollAssignmentOut, 'out'),
    (PR, 'PayrollAssignmentInput', PY.PayrollAssignmentIn, 'in'), (PR, 'AssignmentImpact', PY.AssignmentImpactOut, 'out'),
    (PR, 'EffectiveConfiguration', PY.EffectiveConfigurationOut, 'out'), (PR, 'AssignmentHistoryEntry', PY.AssignmentHistoryEntryOut, 'out'),
    # Module 8 (ReviewListItem is a Pick<> type alias and reviewsByStatus a Record<>: both checked by the tests)
    (PS, 'RatingLevel', PF.RatingLevelOut, 'out'), (PS, 'RatingScale', PF.RatingScaleOut, 'out'), (PS, 'Competency', PF.CompetencyOut, 'out'),
    (PS, 'AppraisalCycle', PF.AppraisalCycleOut, 'out'), (PS, 'CycleInput', PF.CycleIn, 'in'), (PS, 'PerformanceConfig', PF.PerformanceConfigOut, 'out'),
    (PS, 'GoalKpi', PF.GoalKpiOut, 'out'), (PS, 'ProgressUpdate', PF.ProgressUpdateOut, 'out'), (PS, 'Goal', PF.GoalOut, 'out'), (PS, 'GoalInput', PF.GoalIn, 'in'),
    (PS, 'ProgressInput', PF.ProgressIn, 'in'), (PS, 'Assessment', PF.AssessmentOut, 'out'), (PS, 'Review', PF.ReviewOut, 'out'),
    (PS, 'ManagerAssessmentInput', PF.ManagerAssessmentIn, 'in'), (PS, 'DevelopmentAction', PF.DevelopmentActionOut, 'out'), (PS, 'DevelopmentPlan', PF.DevelopmentPlanOut, 'out'),
    (PS, 'PlanInput', PF.PlanIn, 'in'), (PS, 'PerformanceSummary', PF.PerformanceSummaryOut, 'out'),
    # Module 9
    (RS, 'ReportDefinition', RP.ReportDefinitionOut, 'out'), (RS, 'ReportColumn', RP.ReportColumnOut, 'out'), (RS, 'ReportResult', RP.ReportResultOut, 'out'),
    (RS, 'ReportActivity', RP.ReportActivityOut, 'out'), (RS, 'ReportsDashboard', RP.ReportsDashboardOut, 'out'), (WK, 'Metric', RP.MetricOut, 'out'),
    # Module 10 (TaskPage extends the shared Paginated type and WorkspaceActivity is an intersection alias: checked by the tests)
    (WK, 'WorkforceSummary', WS_.WorkforceSummaryOut, 'out'), (WK, 'EmployeeSubject', WS_.EmployeeSubjectOut, 'out'), (WK, 'HrTask', WS_.HrTaskOut, 'out'),
    (WK, 'UpcomingEvent', WS_.UpcomingEventOut, 'out'),
]
from pydantic.alias_generators import to_camel
# Documented additions to frontend shapes (the frontend ignores unknown response fields).
ALLOWED_EXTRA = {"ShiftAssignmentResult": {"affectedAttendanceDays", "backdated"}}
ok = True
for file, name, model, kind in pairs:
    ts = ts_fields(file, name)
    py = {(f.serialization_alias or f.alias or to_camel(n)): (not f.is_required()) for n, f in model.model_fields.items()}
    if kind == 'out':
        missing, extra = set(ts) - set(py), set(py) - set(ts) - ALLOWED_EXTRA.get(name, set())
        req = [k for k, opt in ts.items() if not opt and k in py and py[k] and model.model_fields[[n for n in model.model_fields if to_camel(n) == k][0]].default is not None]
    else:
        missing = set(ts) - set(py)          # every frontend field must be accepted
        extra = {k for k in set(py) - set(ts) if not py[k]}  # backend-only fields must be optional
        req = []
    status = 'OK' if not missing and not extra else 'MISMATCH'
    ok &= status == 'OK'
    print(f'{status:8} {name:24} frontend={len(ts):2} backend={len(py):2}' + (f' missing={sorted(missing)}' if missing else '') + (f' extra={sorted(extra)}' if extra else ''))

# Routes: every frontend call of module 1 must exist with the same method.
from app.main import create_app
routes = {(m, r.path) for r in create_app().routes if hasattr(r, 'methods') for m in r.methods}
calls = [('GET', '/hr/departments'), ('GET', '/hr/designations'), ('GET', '/hr/employment-types'), ('GET', '/hr/employee-statuses'), ('GET', '/hr/work-locations'),
         ('GET', '/hr/shifts/options'), ('GET', '/hr/attendance-policies/options'), ('GET', '/hr/overtime-policies/options'), ('GET', '/hr/document-types'),
         ('GET', '/hr/employees/payroll-fields'), ('GET', '/admin/departments'), ('POST', '/admin/departments'), ('PUT', '/admin/departments/{department_id}'),
         ('GET', '/admin/designations'), ('POST', '/admin/designations'), ('PUT', '/admin/designations/{designation_id}'), ('GET', '/hr/shifts'), ('POST', '/hr/shifts'), ('PUT', '/hr/shifts/{shift_id}'),
         ('GET', '/hr/employees'), ('GET', '/hr/employees/{employee_id}'), ('POST', '/hr/employees'), ('PATCH', '/hr/employees/{employee_id}'), ('GET', '/hr/employees/lookup'),
         ('GET', '/hr/employees/{employee_id}/history'), ('POST', '/hr/employees/{employee_id}/status-changes'), ('GET', '/admin/reporting-lines'), ('POST', '/admin/reporting-lines/{employee_id}'),
         ('GET', '/hr/employees/{employee_id}/documents'), ('POST', '/hr/employees/{employee_id}/documents'), ('GET', '/hr/employees/{employee_id}/documents/{document_id}/content'),
         ('GET', '/hr/employees/{employee_id}/document-checklist'), ('GET', '/hr/document-compliance'), ('GET', '/hr/document-compliance/summary'), ('GET', '/hr/document-compliance/attention'),
         ('GET', '/hr/employee-imports/fields'), ('POST', '/hr/employee-imports/validate'), ('POST', '/hr/employee-imports'), ('GET', '/hr/employee-imports/{job_id}'),
         ('GET', '/hr/attendance/summary'), ('GET', '/hr/attendance/daily'), ('GET', '/hr/attendance/daily/{employee_id}'), ('GET', '/hr/attendance/monthly'),
         ('GET', '/hr/attendance/monthly/{employee_id}'), ('GET', '/hr/attendance/monthly/export'), ('GET', '/hr/attendance/employees/{employee_id}/calendar'),
         ('GET', '/hr/attendance/events'), ('GET', '/hr/attendance/events/{event_id}'), ('GET', '/hr/attendance/corrections'), ('GET', '/hr/attendance/corrections/{correction_id}'),
         ('POST', '/hr/attendance/corrections'), ('POST', '/hr/attendance/corrections/{correction_id}/decision'), ('POST', '/hr/shifts/{shift_id}/assignments'),
         ('GET', '/hr/attendance-devices'), ('GET', '/hr/attendance-devices/{device_id}/sync-history'),
         ('GET', '/admin/workflow-processes'), ('GET', '/admin/workflows'), ('GET', '/admin/workflows/{workflow_id}'), ('POST', '/admin/workflows'), ('PUT', '/admin/workflows/{workflow_id}'),
         ('POST', '/admin/workflows/{workflow_id}/publication'), ('POST', '/admin/workflows/{workflow_id}/archive'), ('GET', '/admin/policies/{area}'), ('PUT', '/admin/policies/{area}'),
         # Module 6
         ('GET', '/hr/leave-types'), ('GET', '/hr/leave/summary'), ('GET', '/hr/leave/requests'), ('GET', '/hr/leave/requests/{request_id}'), ('GET', '/hr/leave/requests/estimate'),
         ('POST', '/hr/leave/requests'), ('POST', '/hr/leave/requests/{request_id}/decision'), ('POST', '/hr/leave/requests/{request_id}/cancellation'),
         ('POST', '/hr/leave/requests/{request_id}/comments'), ('GET', '/hr/leave/approval-workflows'), ('GET', '/hr/leave/approval-workflows/options'),
         ('POST', '/hr/leave/approval-workflows'), ('PUT', '/hr/leave/approval-workflows/{workflow_id}'), ('GET', '/hr/leave/balances'), ('GET', '/hr/me/leave/balances'),
         ('GET', '/hr/leave/policies'), ('GET', '/hr/holidays'), ('GET', '/hr/permission-requests'), ('GET', '/hr/permission-requests/{request_id}'),
         ('POST', '/hr/permission-requests'), ('POST', '/hr/permission-requests/{request_id}/decision'), ('GET', '/hr/overtime-requests'),
         ('GET', '/hr/overtime-requests/{request_id}'), ('POST', '/hr/overtime-requests'), ('POST', '/hr/overtime-requests/{request_id}/decision'), ('GET', '/hr/approvals'),
         # Module 7
         ('GET', '/hr/payroll/periods'), ('GET', '/hr/payroll/periods/{period_id}/summary'), ('POST', '/hr/payroll/periods/{period_id}/validation'),
         ('GET', '/hr/payroll/periods/{period_id}/validation'), ('GET', '/hr/payroll/periods/{period_id}/inputs'), ('POST', '/hr/payroll/periods/{period_id}/calculation'),
         ('GET', '/hr/payroll/periods/{period_id}/results'), ('GET', '/hr/payroll/periods/{period_id}/results/{employee_id}'), ('POST', '/hr/payroll/periods/{period_id}/submission'),
         ('POST', '/hr/payroll/periods/{period_id}/decision'), ('POST', '/hr/payroll/periods/{period_id}/payslips/publication'), ('GET', '/hr/payroll/salary-components'),
         ('GET', '/hr/payroll/salary-structures'), ('GET', '/hr/payroll/employee-salaries'), ('GET', '/hr/payroll/employee-salaries/{employee_id}'), ('GET', '/hr/me/payslips'),
         ('GET', '/hr/payroll/payslips'), ('GET', '/hr/payroll/payslips/{payslip_id}/document'), ('GET', '/hr/payroll/reports/register'), ('GET', '/hr/payroll/reports/register/export'),
         ('GET', '/hr/payroll/configurations'), ('GET', '/hr/payroll/configurations/options'), ('POST', '/hr/payroll/configurations'), ('PUT', '/hr/payroll/configurations/{config_id}'),
         ('GET', '/hr/payroll/configuration-assignments'), ('POST', '/hr/payroll/configuration-assignments/preview'), ('POST', '/hr/payroll/configuration-assignments'),
         ('POST', '/hr/payroll/configuration-assignments/{assignment_id}/end'), ('GET', '/hr/payroll/employees/{employee_id}/effective-configuration'),
         ('GET', '/hr/payroll/configuration-assignments/history'),
         # Module 8
         ('GET', '/hr/performance/summary'), ('GET', '/hr/performance/configuration'), ('GET', '/hr/performance/cycles'), ('POST', '/hr/performance/cycles'),
         ('POST', '/hr/performance/cycles/{cycle_id}/advance'), ('GET', '/hr/performance/goals'), ('GET', '/hr/performance/goals/{goal_id}'), ('POST', '/hr/performance/goals'),
         ('POST', '/hr/performance/goals/{goal_id}/progress'), ('GET', '/hr/performance/reviews'), ('GET', '/hr/performance/reviews/{review_id}'),
         ('PUT', '/hr/performance/reviews/{review_id}/manager-assessment'), ('GET', '/hr/performance/development-plans'), ('POST', '/hr/performance/development-plans'),
         ('PATCH', '/hr/performance/development-plans/{plan_id}/actions/{action_id}'),
         # Module 9
         ('GET', '/hr/reports'), ('GET', '/hr/reports/dashboard'), ('GET', '/hr/reports/{report_id}'), ('GET', '/hr/reports/{report_id}/export'), ('GET', '/hr/reports/activity'),
         # Module 10
         ('GET', '/hr/workspace/summary'), ('GET', '/hr/tasks'), ('GET', '/hr/activity'), ('GET', '/hr/upcoming-events')]
missing_routes = [c for c in calls if (c[0], '/api/v1' + c[1]) not in routes]
print('routes  ', 'OK' if not missing_routes else f'MISSING {missing_routes}', f'({len(calls) - len(missing_routes)}/{len(calls)})')
ok &= not missing_routes
sys.exit(0 if ok else 1)
