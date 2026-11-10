# Background Worker: Configuration and Operation

The worker runs long jobs outside the API: **employee import jobs** (Module 4) and the **generic
background jobs** of Module 5. It is the same code and image as the API, started with a different command.

```bash
python -m app.worker
```

## What it does

1. **Polls** the database every `WORKER_POLL_SECONDS` for work.
2. **Claims** the oldest `queued` job with `SELECT … FOR UPDATE SKIP LOCKED`, so several workers never take the same job. It also claims a `running` job whose `heartbeat_at` is older than `WORKER_STALE_SECONDS`, because its worker has stopped.
3. **Runs** the job as the user who submitted it: their permissions, roles and current organizational scope. Rows are processed in batches of `IMPORT_BATCH_SIZE`.
   - Each row is saved in its own savepoint.
   - Each batch is committed together with the job's progress and counts.
   - The heartbeat is refreshed after every batch.
4. **Finishes** the job:
   - `succeeded`, with counts and per-row failures; or
   - `failed`, with the counts so far and a plain explanation of what was and was not created.

   The submitted rows are cleared when the job finishes.
5. **Stops gracefully** on SIGTERM or SIGINT: the current batch completes, then the process exits.

## Background jobs (Module 5, table `background_job`)

| Type | Queued by | Does |
|---|---|---|
| `attendance.close_day` | the worker, once per day (for yesterday) | Stores every employee's calculated day record (`attendance_day`) |
| `attendance.recalculate` | back-dated shift assignments, approved corrections, late punches | Refreshes stored day records of the affected finished, unlocked dates |
| `shift.sync_current` | the worker, once per day | Sets `employee.shift_id` to the assignment in force today (future-dated assignments start on their date) |
| `workflow.escalate` | the worker, once per hour | Marks overdue approval steps (attendance corrections, overtime requests) as escalated so their fallback approver may act |
| `leave.escalate` | the worker, every 15 minutes | Sends due leave reminders and escalates overdue leave requests to their recipient (never decides them) |
| `leave.accrue` | the worker, once per day | Applies the accrual and carry-forward of the leave policies HR entered; idempotent through ledger period keys |
| `notifications.deliver` | the worker, every 5 minutes, only when Platform delivery is configured and notifications are pending | Posts queued notifications to Platform with retries and backoff |

Scheduled jobs are queued at most once per minute and carry a dedupe key (for example
`close-day:2026-11-02`), so several workers never queue the same job twice. Failed jobs keep their
error on the row (`status = failed`, `error`).

Module 6 settings for the worker: `PLATFORM_NOTIFICATIONS_URL`, `PLATFORM_SERVICE_TOKEN` (a secret, never
in git or a ZIP) and `NOTIFICATION_MAX_ATTEMPTS`. Until the URL and token are set, notifications stay
queued and `GET /api/v1/hr/setup/notification-outbox` shows the backlog.

## Configuration (environment variables, see `.env.example`)

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | — | Same database as the API |
| `WORKER_POLL_SECONDS` | 2 | Wait between polls when there is nothing to do |
| `WORKER_STALE_SECONDS` | 300 | A running job with an older heartbeat is taken over and resumed. Keep it well above the time one batch takes. |
| `IMPORT_BATCH_SIZE` | 50 | Rows per transaction |
| `IMPORT_MAX_ROWS`, `IMPORT_MAX_FILE_BYTES` | 2000, 5 MB | Import limits (contract proposals, pending HR/IT) |
| `LOG_LEVEL` | INFO | JSON logs to stdout, the same format as the API |

The worker needs the same secrets as the API: database credentials, `PAYROLL_ENCRYPTION_KEYS` (an
imported employee's payroll values are never imported today, but the code path is shared) and
`DOCUMENT_ENCRYPTION_KEYS`.

## Running it

- **Development:** run the API and `python -m app.worker` in two terminals. Without a worker, import jobs stay `queued`; the API still accepts them, so nothing is lost.
- **Production:** run at least one worker process next to the API. The Docker phase adds a `worker` service using the same image, and systemd or Docker restarts it if it exits. More workers can run for throughput; jobs never run twice.
- **Health:** watch the logs for `hrms.worker` and `hrms.import` lines. A simple check for stuck work is:

  ```sql
  SELECT id, status, processed, total, heartbeat_at FROM employee_import_job WHERE status IN ('queued', 'running') ORDER BY created_at;
  SELECT type, status, created_at, error FROM background_job WHERE status IN ('queued', 'running', 'failed') ORDER BY created_at DESC LIMIT 20;
  ```

## Failure handling

| Situation | What happens |
|---|---|
| The worker process is killed mid-job | Committed batches stay. After `WORKER_STALE_SECONDS`, another (or the restarted) worker resumes after the last committed row. No row is imported twice. |
| The database is briefly unavailable | The job ends `failed` with counts and an explanation. The user re-imports the remaining rows; already-created employees show up as duplicates and are skipped or reported. |
| One bad row | Only that row is rolled back and listed with its reasons. |
| Two imports create the same employee at once | The database's unique constraint decides; the losing row fails with an explanation. |

## Tests

`tests/test_employee_import.py` and `tests/test_employee_import_files.py` cover:
- claiming, and not claiming a running job that has a fresh heartbeat;
- resuming a stale job;
- an unexpected stop mid-job;
- a constraint race;
- a 2,000-row job.

The process itself was started and stopped with SIGTERM and exited cleanly.
