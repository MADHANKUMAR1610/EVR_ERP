"""Attendance devices: status list and sync history (contract E1/H2), device setup with API keys, and
punch ingestion (POST /hr/attendance/events/ingest).

Ingestion is authenticated per device with an API key sent in `X-Device-Key` (only its SHA-256 is
stored). For each punch: unknown attendance ID -> rejected; not employed on the date -> rejected;
a date inside a locked (finalized payroll) period -> rejected; the same device reference sent again
-> recognised and not stored twice; the same employee, direction and device within the duplicate
window (HR setting, empty = only exact resends) -> duplicate; received later than the delayed-sync
threshold (HR setting, empty = never) -> accepted but flagged delayed. Only accepted punches count.
Mobile-app punches are refused until mobile attendance is approved (decision D2).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Principal
from app.core.errors import NotFoundError, UnauthenticatedError
from app.database.audit_listener import acting_as
from app.models.attendance_model import AttendanceDevice, AttendanceEvent, DeviceSyncRun
from app.models.employee_model import Employee
from app.models.reference_data_model import WorkLocation
from app.schemas.attendance_schema import DeviceKeyOut, DeviceListOut, DeviceOut, DeviceSetupIn, DeviceSetupOut, DeviceSyncRunOut, IngestIn, IngestOut
from app.schemas.employee_schema import NamedRefOut
from app.services.attendance.attendance_data import AttendanceData, company_tz, locked_dates
from app.services.attendance.calculator import attendance_date_for
from app.services.attendance.jobs import enqueue_recalculation
from app.services.attendance.policy_service import policy_values_on
from app.services.audit_service import AuditService
from app.services.employee_support import company_today
from app.utils.ids import body_id
from app.utils.validation import FieldErrors, ensure_version

# Device clocks may run slightly ahead; later timestamps are refused (technical tolerance, not HR policy).
CLOCK_TOLERANCE = timedelta(minutes=5)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def device_principal(device: AttendanceDevice) -> Principal:
    """Audit identity for ingestion: the device, not a user."""
    return Principal(user_id=f"device:{device.serial_number}", name=f"Device {device.name}", permissions=frozenset())


class DeviceService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _locations(self) -> dict[uuid.UUID, str]:
        return {w.id: w.name for w in (await self.session.scalars(select(WorkLocation))).all()}

    # ---- Read (frontend) -----------------------------------------------------------------------------

    async def list(self) -> DeviceListOut:
        devices = (await self.session.scalars(select(AttendanceDevice).where(AttendanceDevice.active.is_(True)).order_by(AttendanceDevice.name))).all()
        locations = await self._locations()
        items = []
        for d in devices:
            if d.key_hash is None or d.last_sync_at is None:
                connection = "not_connected"
            elif d.last_sync_result == "failed":
                connection = "error"
            else:
                # "online" means its last push was received; an offline threshold is pending IT (D1).
                connection = "online"
            items.append(DeviceOut(
                id=str(d.id), name=d.name, location=locations.get(d.work_location_id, "") if d.work_location_id else "", serial_number=d.serial_number, connection=connection,
                last_sync_at=d.last_sync_at, last_sync_result=d.last_sync_result, records_last_sync=d.records_last_sync, error_message=d.error_message,
            ))
        return DeviceListOut(items=items, integration_configured=any(d.key_hash for d in devices), as_of=datetime.now(UTC))

    async def sync_history(self, device_id: uuid.UUID) -> list[DeviceSyncRunOut]:
        if await self.session.get(AttendanceDevice, device_id) is None:
            raise NotFoundError()
        runs = (await self.session.scalars(select(DeviceSyncRun).where(DeviceSyncRun.device_id == device_id).order_by(DeviceSyncRun.started_at.desc()).limit(50))).all()
        return [DeviceSyncRunOut(id=str(r.id), started_at=r.started_at, finished_at=r.finished_at, result=r.result, events_received=r.events_received, message=r.message) for r in runs]

    # ---- Setup (hr.devices:manage) ----------------------------------------------------------------------

    async def _setup_out(self, d: AttendanceDevice) -> DeviceSetupOut:
        locations = await self._locations()
        loc = NamedRefOut(id=str(d.work_location_id), name=locations.get(d.work_location_id, "")) if d.work_location_id else None
        return DeviceSetupOut(id=str(d.id), name=d.name, serial_number=d.serial_number, location=loc, active=d.active, key_issued=d.key_hash is not None, version=d.version)

    async def setup_list(self) -> list[DeviceSetupOut]:
        return [await self._setup_out(d) for d in (await self.session.scalars(select(AttendanceDevice).order_by(AttendanceDevice.name))).all()]

    async def save(self, device_id: uuid.UUID | None, data: DeviceSetupIn) -> DeviceSetupOut:
        err = FieldErrors()
        location_id = body_id(data.work_location_id)
        if data.work_location_id and (location_id is None or await self.session.get(WorkLocation, location_id) is None):
            err.add("workLocationId", "Select an existing work location.")
        serial = data.serial_number.strip()
        clash = await self.session.scalar(select(AttendanceDevice.id).where(AttendanceDevice.serial_number == serial, AttendanceDevice.id != (device_id or uuid.uuid4())))
        if clash:
            err.add("serialNumber", "Another device uses this serial number.")
        err.raise_if_any()
        if device_id is None:
            device = AttendanceDevice(name=data.name.strip(), serial_number=serial, work_location_id=location_id, active=data.active)
            self.session.add(device)
            action = "created"
        else:
            device = await self.session.get(AttendanceDevice, device_id)
            if device is None:
                raise NotFoundError()
            ensure_version(device, data.version)
            device.name, device.serial_number, device.work_location_id, device.active = data.name.strip(), serial, location_id, data.active
            action = "updated"
        await self.session.flush()
        AuditService(self.session).record(module="Attendance", action=f"attendance_device.{action}", summary=f"Attendance device {device.name} {action}", entity_type="attendance_device", entity_id=device.id, entity_label=device.name)
        await self.session.commit()
        return await self._setup_out(device)

    async def issue_key(self, device_id: uuid.UUID) -> DeviceKeyOut:
        """Issues a new API key (the old one stops working). The key is shown only in this response."""
        device = await self.session.get(AttendanceDevice, device_id)
        if device is None:
            raise NotFoundError()
        key = "evrdev_" + secrets.token_urlsafe(32)
        device.key_hash = hash_key(key)
        await self.session.flush()
        AuditService(self.session).record(module="Attendance", action="attendance_device.key_issued", summary=f"New API key issued for device {device.name}", entity_type="attendance_device", entity_id=device.id, entity_label=device.name)
        await self.session.commit()
        return DeviceKeyOut(device_id=str(device.id), api_key=key)

    # ---- Ingestion (device key) -----------------------------------------------------------------------------

    async def authenticate(self, key: str | None) -> AttendanceDevice:
        if not key:
            raise UnauthenticatedError("Send the device API key in X-Device-Key.")
        device = await self.session.scalar(select(AttendanceDevice).where(AttendanceDevice.key_hash == hash_key(key), AttendanceDevice.active.is_(True)))
        if device is None:
            raise UnauthenticatedError("Unknown or revoked device key.")
        return device

    async def ingest(self, device: AttendanceDevice, data: IngestIn) -> IngestOut:
        tz = company_tz()
        received = datetime.now(UTC)
        today = company_today()
        policy = await policy_values_on(self.session, today)
        window = policy.get("attendance", "duplicateWindowSeconds")
        delayed_after = policy.get("attendance", "delayedSyncMinutes")
        err = FieldErrors()
        parsed = []
        for i, ev in enumerate(data.events):
            try:
                at = datetime.fromisoformat(ev.at.replace("Z", "+00:00"))
                if at.tzinfo is None:
                    raise ValueError
            except ValueError:
                err.add(f"events.{i}.at", "Send the time in ISO 8601 with its time zone offset.")
                continue
            parsed.append((ev, at))
        err.raise_if_any()

        codes = {ev.attendance_id for ev, _ in parsed}
        employees = {e.attendance_id: e for e in (await self.session.scalars(select(Employee).where(Employee.attendance_id.in_(codes)))).all()}
        data_loader = AttendanceData(self.session)
        await data_loader._shifts()
        assignments = await data_loader.assignments([e.id for e in employees.values()])
        exits = await data_loader.exit_dates(list(employees.values()))
        dates = [at.astimezone(tz).date() for _, at in parsed]
        locks = await locked_dates(self.session, min(dates) - timedelta(days=1), max(dates)) if dates else set()

        with acting_as(device_principal(device)):
            run = DeviceSyncRun(device_id=device.id, started_at=received, result="success", events_received=len(parsed))
            self.session.add(run)
            await self.session.flush()
            counts = {"accepted": 0, "duplicate": 0, "rejected": 0, "already": 0}
            touched: dict[uuid.UUID, set] = {}
            refs = [ev.reference for ev, _ in parsed if ev.reference]
            seen_refs = set((await self.session.scalars(select(AttendanceEvent.original_reference).where(AttendanceEvent.device_id == device.id, AttendanceEvent.original_reference.in_(refs))))) if refs else set()
            for ev, at in parsed:
                if ev.reference and ev.reference in seen_refs:
                    counts["already"] += 1  # a resend of a punch already received: stored once
                    continue
                if ev.reference:
                    seen_refs.add(ev.reference)
                employee = employees.get(ev.attendance_id)
                event = AttendanceEvent(
                    employee_id=employee.id if employee else None, reported_attendance_id=ev.attendance_id, at=at, direction=ev.direction, source=ev.source,
                    device_id=device.id, sync_run_id=run.id, original_reference=ev.reference, received_at=received, sync_status="synced", processing_status="accepted", warnings=[],
                )
                warnings: list[str] = []
                if ev.source == "mobile_app":
                    event.processing_status, event.exception = "rejected", "Mobile-app attendance is not enabled."
                elif employee is None:
                    event.processing_status, event.exception = "rejected", "Unknown attendance ID."
                elif at > received + CLOCK_TOLERANCE:
                    event.processing_status, event.exception = "rejected", "The punch time is in the future (check the device clock)."
                else:
                    day = attendance_date_for(at, tz, lambda d, e=employee: _shift_on(data_loader, assignments, e.id, d))
                    event.attendance_date = day
                    if day < employee.joining_date or (employee.id in exits and day > exits[employee.id]):
                        event.processing_status, event.exception = "rejected", "The employee was not employed on this date."
                    elif day in locks:
                        event.processing_status, event.exception = "rejected", "The date is in a finalized payroll period."
                    elif window:
                        original = await self.session.scalar(
                            select(AttendanceEvent).where(
                                AttendanceEvent.employee_id == employee.id, AttendanceEvent.device_id == device.id, AttendanceEvent.direction == ev.direction,
                                AttendanceEvent.processing_status == "accepted", AttendanceEvent.at.between(at - timedelta(seconds=window), at + timedelta(seconds=window)),
                            ).limit(1)
                        )
                        if original is not None:
                            event.processing_status, event.original_event_id = "duplicate", original.id
                            warnings.append("duplicate_event")
                    if delayed_after and received - at > timedelta(minutes=delayed_after):
                        event.sync_status = "delayed"
                        warnings.append("delayed_sync")
                if event.processing_status == "rejected":
                    warnings.append("rejected_event")
                event.warnings = warnings
                self.session.add(event)
                if window:
                    await self.session.flush()  # the duplicate check of later punches must see this one
                counts[event.processing_status] += 1
                if event.processing_status == "accepted" and event.attendance_date and event.attendance_date < today:
                    touched.setdefault(employee.id, set()).add(event.attendance_date)
            await self.session.flush()
            stored = counts["accepted"] + counts["duplicate"] + counts["rejected"]
            run.result = "success" if counts["rejected"] == 0 else ("partial" if counts["accepted"] or counts["duplicate"] else "failed")
            run.finished_at = datetime.now(UTC)
            run.message = f"{counts['accepted']} accepted, {counts['duplicate']} duplicate, {counts['rejected']} rejected, {counts['already']} already received" if stored or counts["already"] else None
            device.last_sync_at, device.last_sync_result, device.records_last_sync = run.finished_at, run.result, len(parsed)
            device.error_message = None if run.result != "failed" else "All punches in the last push were rejected."
            for employee_id, days in touched.items():
                await enqueue_recalculation(self.session, [employee_id], min(days), max(days), reason="late punches")
            AuditService(self.session).record(module="Attendance", action="attendance_device.synced", summary=f"Device {device.name}: {run.message or 'no punches'}", entity_type="attendance_device", entity_id=device.id, entity_label=device.name)
            await self.session.commit()
        return IngestOut(sync_run_id=str(run.id), received=len(parsed), accepted=counts["accepted"], duplicates=counts["duplicate"], rejected=counts["rejected"], already_received=counts["already"], result=run.result)


def _shift_on(loader: AttendanceData, assignments: dict, employee_id: uuid.UUID, day):
    from bisect import bisect_right

    from app.services.attendance.attendance_data import shift_info

    rows = assignments.get(employee_id, [])
    i = bisect_right([d for d, _ in rows], day)
    if not i:
        return None
    shift = loader.shifts.get(rows[i - 1][1])
    return shift_info(shift) if shift else None

