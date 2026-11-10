"""Loads the starting reference data from a YAML file (see setup/reference_data.yaml).

Create-only: an item whose code (or key) already exists is skipped and never overwritten, so the
command is safe to run again. Every item goes through the same services and validation as the API,
runs as the system actor and is written to the audit log. Change existing values through the API.

    python -m app.scripts.load_reference_data --file setup/reference_data.yaml --dry-run
    python -m app.scripts.load_reference_data --file setup/reference_data.yaml
"""

import argparse
import asyncio
import uuid
import logging
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import SYSTEM_PRINCIPAL
from app.core.errors import AppError
from app.database.audit_listener import acting_as
from app.database.session import dispose_engine, get_session_factory
from app.models.department_model import Department
from app.models.designation_model import Designation
from app.models.reference_data_model import DocumentCategory, DocumentType, EmployeeStatus, PayrollFieldDefinition
from app.models.shift_model import Shift
from app.repositories.reference_data_repository import ReferenceDataRepository
from app.schemas.department_schema import DepartmentInput
from app.schemas.designation_schema import DesignationInput
from app.schemas.reference_data_schema import CodedItemInput, DocumentTypeInput, EmployeeStatusInput, PayrollFieldInput
from app.schemas.shift_schema import ShiftInput
from app.services.department_service import DepartmentService
from app.services.designation_service import DesignationService
from app.services.reference_data_service import CODED_KINDS, ReferenceDataService
from app.services.shift_service import ShiftService

logger = logging.getLogger("hrms.setup")

# YAML section → /hr/setup kind, in loading order (document categories before document types).
CODED_SECTIONS = {
    "employment_types": "employment-types",
    "work_locations": "work-locations",
    "attendance_policies": "attendance-policies",
    "overtime_policies": "overtime-policies",
    "document_categories": "document-categories",
}
KNOWN_SECTIONS = {"departments", "designations", "employee_statuses", "shifts", "document_types", "payroll_fields", "workflows", *CODED_SECTIONS}
# Approval record kept in the file itself: the template stays "pending HR confirmation" until HR signs off.
APPROVAL_KEYS = {"hr_confirmed", "hr_confirmed_by", "hr_confirmed_on"}


class SetupFileError(ValueError):
    pass


def hr_confirmed(path: Path) -> bool:
    """True only when the file records an HR approval (hr_confirmed: true, with who and when)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("hr_confirmed") is True and bool(data.get("hr_confirmed_by")) and bool(data.get("hr_confirmed_on"))


def read_file(path: Path) -> dict[str, list[dict[str, Any]]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SetupFileError("The setup file must be a mapping of section names to lists.")
    data = {k: v for k, v in data.items() if k not in APPROVAL_KEYS}
    unknown = set(data) - KNOWN_SECTIONS
    if unknown:
        raise SetupFileError(f"Unknown sections: {', '.join(sorted(unknown))}")
    for name, items in data.items():
        if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
            raise SetupFileError(f"Section '{name}' must be a list of items.")
    return data


class Loader:
    def __init__(self, session: AsyncSession, *, dry_run: bool = False):
        self.session = session
        self.dry_run = dry_run
        self.summary: dict[str, dict[str, int]] = {}

    def _count(self, section: str, outcome: str) -> None:
        self.summary.setdefault(section, {"created": 0, "skipped": 0})[outcome] += 1

    async def _ids_by_code(self, model: type, codes: list[str], section: str, item: str) -> list[str]:
        if not codes:
            return []
        rows = dict((await self.session.execute(select(model.code, model.id).where(model.code.in_(codes)))).all())
        missing = [c for c in codes if c not in rows]
        if missing:
            raise SetupFileError(f"{section} '{item}': unknown codes {', '.join(missing)}")
        return [str(rows[c]) for c in codes]

    async def _exists(self, model: type, column: str, value: str) -> bool:
        return await self.session.scalar(select(model.id).where(getattr(model, column) == value)) is not None

    async def _create(self, section: str, model: type, column: str, value: str, create) -> None:
        if await self._exists(model, column, value):
            self._count(section, "skipped")
            return
        self._count(section, "created")
        if not self.dry_run:
            await create()

    async def run(self, data: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, int]]:
        with acting_as(SYSTEM_PRINCIPAL):
            await self._departments(data.get("departments", []))
            await self._designations(data.get("designations", []))
            ref = ReferenceDataService(self.session)
            for section, kind in CODED_SECTIONS.items():
                model = CODED_KINDS[kind][0]
                for item in data.get(section, []):
                    payload = CodedItemInput(code=str(item["code"]), name=item["name"], description=item.get("description"), active=item.get("active", True))
                    await self._create(section, model, "code", payload.code, lambda p=payload, k=kind: ref.setup_create_coded(k, p))
            await self._statuses(data.get("employee_statuses", []), ref)
            await self._shifts(data.get("shifts", []))
            await self._document_types(data.get("document_types", []), ref)
            await self._workflows(data.get("workflows", []))
            for item in data.get("payroll_fields", []):
                payload = PayrollFieldInput(**item)
                await self._create("payroll_fields", PayrollFieldDefinition, "key", payload.key, lambda p=payload: ref.setup_create_payroll_field(p))
        return self.summary

    async def _workflows(self, items: list[dict]) -> None:
        from app.models.attendance_model import Workflow
        from app.schemas.workflow_schema import WorkflowIn
        from app.services.attendance.workflow_service import WorkflowService
        from app.services.employee_support import company_today

        service = WorkflowService(self.session)
        for item in items:
            exists = await self.session.scalar(select(Workflow.id).where(Workflow.name == item["name"], Workflow.process == item["process"]))
            if exists:
                self._count("workflows", "skipped")
                continue
            self._count("workflows", "created")
            if self.dry_run:
                continue
            out = await service.save(None, WorkflowIn(name=item["name"], description=item.get("description", ""), process=item["process"], effective_from=company_today().isoformat(), steps=item["steps"]))
            if item.get("publish"):
                await service.publish(uuid.UUID(out.id), out.version, "Published by the setup loader (template pending HR confirmation)")

    async def _departments(self, items: list[dict]) -> None:
        service = DepartmentService(self.session)
        # Parents first: items without a parent, then the rest in file order.
        for item in sorted(items, key=lambda i: i.get("parent") is not None):
            code = str(item["code"]).strip().upper()

            async def create(item=item, code=code):
                parent = (await self._ids_by_code(Department, [str(item["parent"]).upper()], "departments", code))[0] if item.get("parent") else None
                await service.create(DepartmentInput(code=code, name=item["name"], parent_id=parent, active=item.get("active", True)))

            await self._create("departments", Department, "code", code, create)

    async def _designations(self, items: list[dict]) -> None:
        service = DesignationService(self.session)
        for item in items:
            code = str(item["code"]).strip().upper()

            async def create(item=item, code=code):
                deps = await self._ids_by_code(Department, [str(c).upper() for c in item.get("departments", [])], "designations", code)
                await service.create(DesignationInput(code=code, name=item["name"], description=item.get("description", ""), department_ids=deps, active=item.get("active", True)))

            await self._create("designations", Designation, "code", code, create)

    async def _statuses(self, items: list[dict], ref: ReferenceDataService) -> None:
        # Pass 1 creates the statuses; pass 2 adds transitions, which may point at statuses created later.
        created: list[dict] = []
        for item in items:
            base = {k: v for k, v in item.items() if k != "transitions"}

            async def create(base=base, item=item):
                created.append(item)
                await ref.setup_create_status(EmployeeStatusInput(**base))

            await self._create("employee_statuses", EmployeeStatus, "code", item["code"], create)
        repo = ReferenceDataRepository(self.session)
        for item in created:
            if not item.get("transitions"):
                continue
            status = await repo.get_status_by_code(item["code"])
            assert status is not None
            await ref.setup_update_status(status.id, EmployeeStatusInput(**item, version=status.version))

    async def _shifts(self, items: list[dict]) -> None:
        service = ShiftService(self.session)
        for item in items:
            code = str(item["code"]).strip()

            async def create(item=item, code=code):
                deps = await self._ids_by_code(Department, [str(c).upper() for c in item.get("departments", [])], "shifts", code)
                fields = {k: v for k, v in item.items() if k != "departments"}
                await service.create(ShiftInput(**fields, department_ids=deps))

            # Shift codes are unique without regard to case.
            exists = await self.session.scalar(select(Shift.id).where(Shift.code.ilike(code)))
            if exists:
                self._count("shifts", "skipped")
            else:
                self._count("shifts", "created")
                if not self.dry_run:
                    await create()

    async def _document_types(self, items: list[dict], ref: ReferenceDataService) -> None:
        for item in items:

            async def create(item=item):
                category = (await self._ids_by_code(DocumentCategory, [item["category"]], "document_types", item["code"]))[0]
                fields = {k: v for k, v in item.items() if k not in ("category", "max_size_mb")}
                await ref.setup_create_document_type(DocumentTypeInput(**fields, category_id=category, max_size_bytes=int(item["max_size_mb"] * 1024 * 1024)))

            await self._create("document_types", DocumentType, "code", item["code"], create)


async def _main(path: Path, dry_run: bool) -> int:
    data = read_file(path)
    confirmed = hr_confirmed(path)
    if not confirmed:
        if get_settings().environment == "production" and not dry_run:
            print("Refused: this file is still pending HR confirmation (hr_confirmed is false, or who/when is missing).")
            return 2
        print("WARNING: values in this file are PENDING HR CONFIRMATION. Loaded items are sample values, not company policy.")
    try:
        async with get_session_factory()() as session:
            summary = await Loader(session, dry_run=dry_run).run(data)
    except AppError as exc:
        details = "; ".join(f"{d['field']}: {d['message']}" for d in exc.details)
        print(f"Stopped: {exc.message} {details}")
        return 1
    finally:
        await dispose_engine()
    title = "Dry run (nothing written)" if dry_run else "Loaded"
    print(title)
    for section, counts in summary.items():
        print(f"  {section:22} created {counts['created']:3}  skipped {counts['skipped']:3}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=Path("setup/reference_data.yaml"))
    parser.add_argument("--dry-run", action="store_true", help="Report what would be created without writing")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args.file, args.dry_run)))


if __name__ == "__main__":
    main()
