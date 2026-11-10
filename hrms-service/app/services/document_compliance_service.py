"""Document completion across employees (contract B5: document-compliance, summary, attention).

Computed from the configured document types and the latest copy of each type. Only employees inside
the caller's organizational scope are included, and employees whose status is marked "employment
ended" are left out (the contract's proposal, D23, pending HR confirmation; the same HR setting as
the employee picker). Rows carry names and counts only, never document content.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import false, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError
from app.models.department_model import Department
from app.models.designation_model import Designation
from app.models.employee_document_model import EmployeeDocument
from app.models.employee_model import Employee
from app.models.reference_data_model import DocumentCategory, DocumentType
from app.repositories.base_repository import PageResult
from app.repositories.employee_document_repository import EmployeeDocumentRepository
from app.repositories.employee_repository import ACTIVE, text_match
from app.schemas.common import Page, PageParams
from app.schemas.employee_document_schema import (
    AttentionDocumentOut,
    AwaitingItemOut,
    AwaitingListOut,
    ComplianceAttentionOut,
    ComplianceEmployeeOut,
    ComplianceSummaryOut,
    DocumentComplianceRowOut,
    ExpiringItemOut,
    ExpiringListOut,
    MissingItemOut,
    MissingListOut,
)
from app.schemas.employee_schema import NamedRefOut
from app.services.audit_service import AuditService
from app.services.document_support import Completion, completion, expires_in, state_of, type_order
from app.services.employee_scope_service import EmployeeScopeService
from app.services.employee_support import Caller, company_today
from app.utils.ids import body_id

SORTS = ("employeeCode", "fullName", "department", "completion", "status")


@dataclass
class _Row:
    employee: Employee
    out: ComplianceEmployeeOut
    result: Completion
    latest: dict[uuid.UUID, EmployeeDocument]


class DocumentComplianceService:
    def __init__(self, session: AsyncSession, caller: Caller):
        self.session = session
        self.caller = caller
        self.repo = EmployeeDocumentRepository(session)
        self.audit = AuditService(session)
        self.scope_clause = EmployeeScopeService.clause(caller.scope)

    async def _rows(self, *, q: str | None = None, department_id: str | None = None, category_id: str | None = None) -> tuple[list[_Row], dict[uuid.UUID, DocumentType], int]:
        stmt = select(Employee).where(self.scope_clause, ACTIVE)
        if q:
            stmt = stmt.where(text_match(q))
        if department_id:
            dep = body_id(department_id)
            stmt = stmt.where(Employee.department_id == dep) if dep else stmt.where(false())
        employees = list((await self.session.scalars(stmt)).all())
        types = {t.id: t for t in (await self.session.scalars(select(DocumentType).where(DocumentType.active.is_(True)))).all()}
        categories = {c.id: c.name for c in (await self.session.scalars(select(DocumentCategory))).all()}
        # Same order as the checklist: required first, then category, then name.
        counted = sorted((t for t in types.values() if not category_id or str(t.category_id) == category_id), key=lambda t: type_order(t, categories.get(t.category_id, "")))
        departments = {d.id: d.name for d in (await self.session.scalars(select(Department))).all()}
        designations = {d.id: d.name for d in (await self.session.scalars(select(Designation))).all()}
        latest_all = await self.repo.latest_per_type(e.id for e in employees)
        window = (await self.repo.settings()).expiry_window_days
        today = company_today()
        rows = []
        for e in employees:
            latest = {type_id: d for (emp, type_id), d in latest_all.items() if emp == e.id and type_id in types}
            rows.append(
                _Row(
                    employee=e,
                    out=ComplianceEmployeeOut(
                        id=str(e.id), employee_code=e.employee_code, full_name=e.full_name,
                        department=NamedRefOut(id=str(e.department_id), name=departments.get(e.department_id, "")),
                        designation=NamedRefOut(id=str(e.designation_id), name=designations.get(e.designation_id, "")),
                    ),
                    result=completion(counted, latest, today, window),
                    latest={k: v for k, v in latest.items() if k in {t.id for t in counted}},
                )
            )
        return rows, types, window

    def _audit_view(self, what: str) -> None:
        self.audit.record(module="Documents", action="document_compliance.viewed", summary=f"Document completion {what} viewed")

    # ---- List ---------------------------------------------------------------------------------------

    async def list(self, params: PageParams, *, department_id: str | None, category_id: str | None, verification: str | None, status: str | None) -> Page:
        field, _, direction = (params.sort or "employeeCode:asc").partition(":")
        direction = direction or "asc"
        if field not in SORTS or direction not in ("asc", "desc"):
            raise BadRequestError(f"Sorting by '{params.sort}' is not supported.", details=[{"field": "sort", "message": f"Use one of: {', '.join(SORTS)} with :asc or :desc."}])
        rows, _, _ = await self._rows(q=params.q, department_id=department_id, category_id=category_id)
        if verification:
            rows = [r for r in rows if any(d.verification_status == verification for d in r.latest.values())]
        if status:
            rows = [r for r in rows if r.result.status == status]
        keys = {
            "employeeCode": lambda r: r.employee.employee_code.lower(),
            "fullName": lambda r: r.employee.full_name.lower(),
            "department": lambda r: r.out.department.name.lower(),
            "completion": lambda r: (r.result.completed_count / r.result.required_count) if r.result.required_count else 1.0,
            "status": lambda r: r.result.status,
        }
        rows.sort(key=lambda r: (keys[field](r), r.employee.employee_code.lower()), reverse=direction == "desc")
        start = (params.page - 1) * params.page_size
        page = rows[start : start + params.page_size]
        items = [DocumentComplianceRowOut(employee=r.out, pending_documents=r.result.pending_types, **r.result.counts()) for r in page]
        self._audit_view("list")
        await self.session.commit()
        return Page.build(PageResult(page, params.page, params.page_size, len(rows)), items)

    # ---- Summary ------------------------------------------------------------------------------------

    async def summary(self) -> ComplianceSummaryOut:
        rows, _, window = await self._rows()
        required_total = sum(r.result.required_count for r in rows)
        provided = sum(r.result.completed_count for r in rows)
        today = company_today()
        awaiting = sum(1 for r in rows for d in r.latest.values() if state_of(d, today) == "pending_verification")
        expiring = sum(r.result.expiring_soon_count for r in rows)
        self._audit_view("summary")
        await self.session.commit()
        return ComplianceSummaryOut(
            required_documents_total=required_total,
            required_documents_provided=provided,
            missing_required_documents=required_total - provided,
            employees_complete=sum(1 for r in rows if r.result.status == "complete"),
            employees_with_pending_documents=sum(1 for r in rows if r.result.status == "documents_pending"),
            documents_awaiting_verification=awaiting,
            documents_expiring_soon=expiring,
            expiry_window_days=window,
            as_of=datetime.now(UTC),
        )

    # ---- Needs attention ------------------------------------------------------------------------------

    async def attention(self, limit: int) -> ComplianceAttentionOut:
        rows, types, window = await self._rows()
        today = company_today()
        expiring, awaiting, missing = [], [], []
        for r in rows:
            for type_id, d in r.latest.items():
                ref = AttentionDocumentOut(id=str(d.id), type_id=str(type_id), type_name=types[type_id].name)
                state = state_of(d, today)
                days = expires_in(d, today)
                if state in ("verified", "pending_verification") and days is not None and 0 <= days <= window:
                    expiring.append(ExpiringItemOut(employee=r.out, document=ref, expiry_date=d.expiry_date.isoformat(), expires_in_days=days))
                if state == "pending_verification":
                    awaiting.append((d.created_at, AwaitingItemOut(employee=r.out, document=ref, uploaded_at=d.created_at)))
            if r.result.pending_types:
                missing.append(MissingItemOut(employee=r.out, missing=r.result.pending_types))
        expiring.sort(key=lambda i: (i.expires_in_days, i.employee.employee_code))
        awaiting.sort(key=lambda t: t[0])
        missing.sort(key=lambda i: (-len(i.missing), i.employee.employee_code))
        self._audit_view("attention list")
        await self.session.commit()
        return ComplianceAttentionOut(
            expiring_soon=ExpiringListOut(total=len(expiring), items=expiring[:limit]),
            awaiting_verification=AwaitingListOut(total=len(awaiting), items=[a for _, a in awaiting[:limit]]),
            missing_required=MissingListOut(total=len(missing), items=missing[:limit]),
        )
