# HRMS Database: Entity-Relationship Diagram

Database `hrms`, owned only by the HRMS service. Every business table also has `created_at`,
`created_by`, `updated_at` and `updated_by` (not repeated below), and editable tables have
`version`. User IDs (`*_by`, `reviewer_user_id`, …) are plain UUIDs from the Identity service:
there are **no foreign keys across services**.

Diagrams are split by area so they stay readable. Shared tables (`employee`, `department`)
appear in several diagrams.

## Organization and employees

```mermaid
erDiagram
  department ||--o{ department : "parent"
  department ||--o{ employee : "employs"
  department }o--o| employee : "head"
  designation ||--o{ employee : ""
  designation }o--o{ department : "designation_department"
  employment_type ||--o{ employee : ""
  employee_status ||--o{ employee : "status_code"
  employee_status ||--o{ employee_status_transition : "from / to"
  work_location ||--o{ employee : ""
  employee ||--o{ employee : "reporting_manager"
  employee ||--o{ employee_payroll_value : "encrypted values"
  employee ||--o{ employee_status_change : ""
  employee ||--o{ employee_history : ""
  employee ||--o{ reporting_line_change : ""
  document_category ||--o{ document_type : ""
  document_type ||--o{ employee_document : ""
  employee ||--o{ employee_document : ""
  employee_document ||--o{ document_verification_event : ""

  employee {
    uuid id PK
    string employee_code UK
    string first_name
    string last_name
    date date_of_birth
    string email UK
    string mobile
    jsonb address
    date joining_date
    uuid department_id FK
    uuid designation_id FK
    uuid employment_type_id FK
    string status_code FK
    uuid reporting_manager_id FK
    uuid work_location_id FK
    string attendance_id UK
    uuid shift_id FK
    int version
  }
  employee_document {
    uuid id PK
    uuid employee_id FK
    uuid document_type_id FK
    string file_name
    string content_type
    bigint size_bytes
    string storage_key UK
    string sha256
    date expiry_date
    string verification_status
    string scan_status
  }
```

## Attendance

```mermaid
erDiagram
  shift ||--o{ shift_department : ""
  department ||--o{ shift_department : ""
  shift ||--o{ shift_assignment : ""
  employee ||--o{ shift_assignment : ""
  attendance_device ||--o{ device_sync_run : ""
  attendance_device ||--o{ attendance_event : "fingerprint"
  employee ||--o{ attendance_event : ""
  attendance_event ||--o| attendance_event : "duplicate of"
  employee ||--o{ attendance_day : "one per date"
  shift ||--o{ attendance_day : ""
  employee ||--o{ attendance_correction : ""
  attendance_correction ||--o{ request_event : "history"

  attendance_event {
    uuid id PK
    uuid employee_id FK
    date attendance_date
    timestamptz at
    string direction
    string source
    uuid device_id FK
    string original_reference UK
    timestamptz received_at
    string sync_status
    string processing_status
    jsonb warnings
    jsonb mobile_validation
  }
  attendance_day {
    uuid id PK
    uuid employee_id FK
    date date
    string status
    timestamptz first_in
    timestamptz last_out
    int worked_minutes
    int late_minutes
    int early_exit_minutes
    int overtime_minutes
    jsonb exceptions
    bool corrected
  }
```

## Leave and requests

```mermaid
erDiagram
  leave_type ||--o{ leave_policy : ""
  leave_type ||--o{ leave_request : ""
  leave_type ||--o{ leave_ledger_entry : ""
  employee ||--o{ leave_request : ""
  employee ||--o{ leave_ledger_entry : "allocations, carry-forward"
  leave_request ||--o{ leave_request_attachment : ""
  leave_request ||--o{ leave_approval_event : "assigned, reminder, escalated"
  leave_request ||--o{ request_event : "submitted, approved, …"
  leave_approval_workflow ||--o{ leave_workflow_department : ""
  department ||--o{ leave_workflow_department : ""
  leave_approval_workflow ||--o{ leave_request : "applied"
  employee ||--o{ permission_request : ""
  employee ||--o{ overtime_request : ""

  leave_request {
    uuid id PK
    uuid employee_id FK
    uuid leave_type_id FK
    date from_date
    date to_date
    string portion
    numeric days
    string status
    uuid workflow_id FK
    string stage
    string current_approver_type
    uuid current_approver_ref
    timestamptz escalation_due_at
    timestamptz escalated_at
    int version
  }
  holiday {
    uuid id PK
    date date UK
    string name
    string type
  }
```

## Payroll

```mermaid
erDiagram
  salary_structure ||--o{ salary_structure_component : ""
  salary_component ||--o{ salary_structure_component : ""
  employee ||--o{ employee_salary : "effective-dated"
  salary_structure ||--o{ employee_salary : ""
  payroll_configuration ||--o{ payroll_configuration_component : ""
  salary_component ||--o{ payroll_configuration_component : ""
  payroll_configuration ||--o{ payroll_configuration_assignment : ""
  department ||--o{ payroll_configuration_assignment : "scope = department"
  employee ||--o{ payroll_configuration_assignment : "scope = employee"
  payroll_period ||--o{ payroll_validation_run : ""
  payroll_period ||--o{ payroll_input : ""
  payroll_period ||--o{ payroll_result : ""
  payroll_result ||--o{ payroll_result_line : ""
  salary_component ||--o{ payroll_result_line : ""
  payroll_period ||--o{ payslip : ""
  employee ||--o{ payslip : ""

  payroll_period {
    uuid id PK
    string month UK
    date from_date
    date to_date
    string status
    string currency
    timestamptz calculated_at
    timestamptz locked_at
    int version
  }
  payroll_configuration_assignment {
    uuid id PK
    uuid configuration_id FK
    string scope
    uuid department_id FK
    uuid employee_id FK
    date effective_from
    date effective_to
    string status
  }
  payroll_result_line {
    uuid id PK
    uuid result_id FK
    uuid component_id FK
    numeric amount
  }
```

## Performance

```mermaid
erDiagram
  rating_scale ||--o{ rating_level : ""
  rating_scale ||--o{ appraisal_cycle : ""
  appraisal_cycle ||--o{ cycle_competency : ""
  competency ||--o{ cycle_competency : ""
  appraisal_cycle ||--o{ goal : ""
  employee ||--o{ goal : ""
  goal ||--o{ goal_progress_update : ""
  appraisal_cycle ||--o{ performance_review : ""
  employee ||--o{ performance_review : "reviewee"
  performance_review ||--o{ review_assessment : "self, manager"
  review_assessment ||--o{ review_competency_rating : ""
  employee ||--o{ development_plan : ""
  development_plan ||--o{ development_action : ""
```

## HR administration and platform

```mermaid
erDiagram
  approval_workflow ||--o{ approval_workflow_step : ""
  approval_workflow ||--o{ approval_workflow_history : ""
  hr_policy_document ||--o{ hr_policy_history : ""

  hr_policy_document {
    uuid id PK
    string area UK
    jsonb policy_values
    date effective_from
    int version
  }
  audit_log {
    uuid id PK
    timestamptz at
    uuid actor_id
    string actor_name
    string module
    string action
    string entity_type
    string entity_id
    string result
    string request_id
    string summary
    jsonb changes
  }
  background_job {
    uuid id PK
    string type
    string status
    int processed
    int total
    jsonb payload
    jsonb result
    string error
    timestamptz run_after
    uuid requested_by
  }
```

`audit_log` is insert-only: a trigger rejects UPDATE and DELETE, and the application's database
role has only INSERT and SELECT on it.


## Employees (migration 0004)

```mermaid
erDiagram
    department ||--o{ employee : "department_id"
    employee |o--o{ department : "head_employee_id"
    designation ||--o{ employee : "designation_id"
    employment_type ||--o{ employee : "employment_type_id"
    employee_status ||--o{ employee : "status_code"
    work_location |o--o{ employee : "work_location_id"
    shift |o--o{ employee : "shift_id"
    attendance_policy_option |o--o{ employee : "attendance_policy_id"
    overtime_policy_option |o--o{ employee : "overtime_policy_id"
    employee |o--o{ employee : "reporting_manager_id"
    employee ||--o| employee_contact : "contact (view-contact only)"
    employee ||--o{ employee_payroll_value : "values (sensitive = encrypted)"
    payroll_field_definition ||--o{ employee_payroll_value : "field_key"
    employee ||--o{ employee_history : "append-only"
    employee ||--o{ employee_reporting_line : "effective-dated managers"
    employee_access_scope {
        string role_code
        string scope_type "all | departments | headed_departments | reporting_tree | own_record"
        uuid_array department_ids
    }
```


## Employee documents (migration 0005)

```mermaid
erDiagram
    employee ||--o{ employee_document : "copies (newest decides the state)"
    document_type ||--o{ employee_document : "document_type_id"
    employee_document ||--o{ employee_document_event : "verification history (append-only)"
    employee_document {
        string file_name "display name only"
        string content_type "detected from the content"
        bigint size_bytes
        string sha256 "integrity check on download"
        string storage_key "random; encrypted file in private storage; never returned"
        date document_date
        date expiry_date
        string verification_status "pending | verified | rejected"
    }
    document_settings {
        int expiry_window_days "HR setting, pending confirmation (30)"
    }
```


## Employee import jobs (migration 0006)

```mermaid
erDiagram
    employee_import_job {
        string status "queued | running | succeeded | failed | cancelled"
        bool skip_duplicates
        jsonb principal "owner's identity at submission (scope and permissions for the run)"
        jsonb rows "submitted rows; cleared when the job finishes"
        int total
        int processed "committed together with the batch's employees"
        int created_count "created + skipped + failed = processed (check constraint)"
        int skipped_count
        int failed_count
        jsonb failures "rowNumber + reasons, kept for the owner"
        timestamptz heartbeat_at "stale heartbeat: another worker resumes the job"
    }
    employee_import_job ||--o{ employee : "creates (history action 'imported')"
```


## Time & attendance (migration 0007)

```mermaid
erDiagram
    employee ||--o{ shift_assignment : "dated shifts (effective_from)"
    shift ||--o{ shift_assignment : ""
    employee ||--o{ shift_assignment_change : "append-only: old/new shift, reason, affected days"
    attendance_device ||--o{ device_sync_run : "pushes"
    attendance_device ||--o{ attendance_event : "punches (append-only)"
    device_sync_run ||--o{ attendance_event : ""
    employee ||--o{ attendance_event : "via attendance_id"
    attendance_event |o--o{ attendance_event : "duplicate of"
    employee ||--o{ attendance_day : "stored results of finished days"
    employee ||--o{ attendance_correction : "requests"
    workflow |o--o{ attendance_correction : "steps copied at submission"
    attendance_correction ||--o{ attendance_correction_event : "approval history (append-only)"
    workflow ||--o{ workflow_history : "publication history (append-only)"
    policy_setting {
        string area "attendance | shifts | overtime"
        jsonb values "HR settings, empty until set"
        date effective_from "never backwards"
    }
    attendance_lock_period {
        date from_date
        date to_date "finalized payroll: no changes"
    }
    background_job {
        string type "attendance.recalculate | attendance.close_day | shift.sync_current | workflow.escalate"
        string dedupe_key
    }
```

## Leave management (migration 0008)

Adds tables only; no Module 1–5 table changes. Append-only (database trigger): `leave_ledger_entry`,
`request_event`, `leave_routing_event`, `leave_workflow_history`. `leave_type.code` cannot change.

```mermaid
erDiagram
    leave_type ||--o{ leave_policy : "effective-dated rules entered by HR"
    leave_type ||--o{ leave_ledger_entry : ""
    employee ||--o{ leave_ledger_entry : "balance transactions (append-only)"
    leave_policy |o--o{ leave_ledger_entry : "accrual / carry-forward source"
    work_location |o--o{ holiday : "empty = company-wide"
    employee ||--o{ leave_request : "applications"
    leave_type ||--o{ leave_request : ""
    leave_approval_workflow |o--o{ leave_request : "routing copied at submission"
    leave_approval_workflow ||--o{ leave_workflow_history : "append-only"
    leave_request ||--o{ leave_request_attachment : "encrypted private storage"
    leave_request ||--o{ leave_routing_event : "assigned / reminder_sent / escalated"
    leave_request |o--o{ leave_ledger_entry : "usage / usage_reversal"
    employee ||--o{ permission_request : ""
    employee ||--o{ overtime_request : ""
    workflow |o--o{ overtime_request : "G5 steps copied at submission"
    request_event {
        string request_kind "leave | permission | overtime"
        uuid request_id
        string action "submitted | approved | rejected | cancelled | commented"
    }
    leave_ledger_entry {
        string entry_type "allocation | accrual | carry_forward | lapse | usage | usage_reversal | adjustment"
        numeric days "signed"
        int leave_year
        string period_key "unique per employee and type: idempotent credits and usage"
    }
    notification_outbox {
        string status "pending | delivered | failed"
        int attempts
    }
```
