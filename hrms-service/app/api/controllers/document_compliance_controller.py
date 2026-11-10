"""HR → Employee Documents: completion across employees (contract B5). Scoped to the caller's employees."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import CurrentPrincipal, DbSession, require
from app.core.permissions import P
from app.schemas.common import Page, PageParams, page_params
from app.schemas.employee_document_schema import ComplianceAttentionOut, ComplianceSummaryOut, DocumentComplianceRowOut
from app.services.document_compliance_service import DocumentComplianceService
from app.services.employee_support import caller_context

router = APIRouter(prefix="/hr/document-compliance", tags=["Employee documents"], dependencies=[Depends(require(P.DOCUMENTS_VIEW))])


async def _service(session, principal) -> DocumentComplianceService:
    return DocumentComplianceService(session, await caller_context(session, principal))


@router.get("", response_model=Page[DocumentComplianceRowOut], summary="Document completion per employee")
async def compliance(
    session: DbSession,
    principal: CurrentPrincipal,
    params: Annotated[PageParams, Depends(page_params)],
    department_id: Annotated[str | None, Query(alias="departmentId")] = None,
    category_id: Annotated[str | None, Query(alias="categoryId")] = None,
    verification: Annotated[Literal["pending", "verified", "rejected"] | None, Query()] = None,
    status: Annotated[Literal["complete", "awaiting_verification", "documents_pending"] | None, Query()] = None,
):
    return await (await _service(session, principal)).list(params, department_id=department_id, category_id=category_id, verification=verification, status=status)


@router.get("/summary", response_model=ComplianceSummaryOut, summary="Completion totals")
async def summary(session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).summary()


@router.get("/attention", response_model=ComplianceAttentionOut, summary="Needs attention: expiring, awaiting verification, missing")
async def attention(session: DbSession, principal: CurrentPrincipal, limit: Annotated[int, Query(ge=1, le=20)] = 5):
    return await (await _service(session, principal)).attention(limit)
