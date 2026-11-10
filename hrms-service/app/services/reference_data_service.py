"""HR reference lists: the read endpoints the frontend uses, and the /hr/setup endpoints HR uses to
maintain them. Every value is company configuration entered by HR; nothing here is a statutory rule.
"""

import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.reference_data_model import (
    AttendancePolicyOption,
    DocumentCategory,
    DocumentType,
    EmployeeStatus,
    EmployeeStatusTransition,
    EmploymentType,
    OvertimePolicyOption,
    PayrollFieldDefinition,
    WorkLocation,
)
from app.core import crypto
from app.core.config import get_settings
from app.core.file_inspection import SUPPORTED_EXTENSIONS
from app.models.employee_model import Employee
from app.repositories.department_repository import DepartmentRepository
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.designation_repository import DesignationRepository
from app.repositories.reference_data_repository import ReferenceDataRepository
from app.schemas.reference_data_schema import (
    CodedItemInput,
    CodedItemSetupOut,
    DocumentTypeInput,
    DocumentTypeOption,
    DocumentTypeSetupOut,
    EmployeeStatusInput,
    EmployeeStatusOption,
    EmployeeStatusSetupOut,
    NamedRef,
    OptionItem,
    PayrollFieldDefinitionOut,
    PayrollFieldInput,
    PayrollFieldSetupOut,
    ReferenceItem,
    SelectOption,
)
from app.services.audit_service import AuditService, diff
from app.utils.ids import body_id
from app.utils.validation import FieldErrors, ensure_version

# URL segment under /hr/setup → (model, label used in messages and the audit log)
CODED_KINDS: dict[str, tuple[type, str]] = {
    "employment-types": (EmploymentType, "employment type"),
    "work-locations": (WorkLocation, "work location"),
    "attendance-policies": (AttendancePolicyOption, "attendance policy"),
    "overtime-policies": (OvertimePolicyOption, "overtime policy"),
    "document-categories": (DocumentCategory, "document category"),
}
CODE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
CODE_MESSAGE = "Use 1–20 letters, digits, hyphens or underscores."


def _coded_kind(kind: str) -> tuple[type, str]:
    if kind not in CODED_KINDS:
        raise NotFoundError()
    return CODED_KINDS[kind]


def _has_description(model: type) -> bool:
    return "description" in model.__table__.columns


def _status_out(s: EmployeeStatus) -> EmployeeStatusSetupOut:
    return EmployeeStatusSetupOut(
        id=str(s.id), code=s.code, label=s.label, tone=s.tone, active=s.active, allowed_on_create=s.allowed_on_create, transitions=[t.to_code for t in s.transitions], sort_order=s.sort_order,
        employment_ended=s.employment_ended, reason_required=s.reason_required, version=s.version,
    )


def _document_type_out(d: DocumentType) -> DocumentTypeSetupOut:
    return DocumentTypeSetupOut(
        id=str(d.id), code=d.code, name=d.name, category=NamedRef(id=str(d.category.id), name=d.category.name), required=d.required, expiry_required=d.expiry_required,
        allowed_extensions=list(d.allowed_extensions), max_size_bytes=d.max_size_bytes, active=d.active, version=d.version,
    )


def _payroll_out(f: PayrollFieldDefinition) -> PayrollFieldSetupOut:
    return PayrollFieldSetupOut(
        id=str(f.id), key=f.key, label=f.label, type=f.type, required=f.required, sensitive=f.sensitive, max_length=f.max_length, pattern=f.pattern, pattern_message=f.pattern_message,
        options=[SelectOption(**o) for o in f.options] if f.options else None, hint=f.hint, sort_order=f.sort_order, active=f.active, version=f.version,
    )


def _columns(obj: Any, names: list[str]) -> dict[str, Any]:
    return {n: getattr(obj, n) for n in names}


class ReferenceDataService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ReferenceDataRepository(session)
        self.audit = AuditService(session)

    # ---- Read endpoints used by the frontend forms -----------------------------------------------

    async def departments(self) -> list[ReferenceItem]:
        return [ReferenceItem(id=str(d.id), code=d.code, name=d.name, active=d.active) for d in await DepartmentRepository(self.session).list_all()]

    async def own_department(self, employee_id: uuid.UUID | None) -> list[ReferenceItem]:
        if employee_id is None:
            return []
        employee = await self.session.get(Employee, employee_id)
        department = await DepartmentRepository(self.session).get(employee.department_id) if employee else None
        return [ReferenceItem(id=str(department.id), code=department.code, name=department.name, active=department.active)] if department else []

    async def designations(self) -> list[ReferenceItem]:
        return [ReferenceItem(id=str(d.id), code=d.code, name=d.name, active=d.active) for d in await DesignationRepository(self.session).list_all()]

    async def coded_items(self, model: type) -> list[ReferenceItem]:
        return [ReferenceItem(id=str(i.id), code=i.code, name=i.name, active=i.active) for i in await self.repo.list_coded(model)]

    async def policy_options(self, model: type) -> list[OptionItem]:
        return [OptionItem(id=str(i.id), name=i.name, description=i.description) for i in await self.repo.list_coded(model, active_only=True)]

    async def employee_statuses(self, *, include_transitions: bool) -> list[EmployeeStatusOption]:
        """`transitions` is filled only for callers who may change a status (field-level rule)."""
        return [
            EmployeeStatusOption(code=s.code, label=s.label, tone=s.tone, active=s.active, allowed_on_create=s.allowed_on_create, transitions=[t.to_code for t in s.transitions] if include_transitions else [])
            for s in await self.repo.list_statuses()
        ]

    async def document_types(self) -> list[DocumentTypeOption]:
        return [DocumentTypeOption.model_validate(_document_type_out(d).model_dump()) for d in await self.repo.list_document_types()]

    async def payroll_fields(self) -> list[PayrollFieldDefinitionOut]:
        return [PayrollFieldDefinitionOut.model_validate(_payroll_out(f).model_dump()) for f in await self.repo.list_payroll_fields()]

    # ---- Setup: simple coded lists ------------------------------------------------------------------

    async def setup_list_coded(self, kind: str) -> list[CodedItemSetupOut]:
        model, _ = _coded_kind(kind)
        return [self._coded_out(model, i) for i in await self.repo.list_coded(model)]

    @staticmethod
    def _coded_out(model: type, item: Any) -> CodedItemSetupOut:
        return CodedItemSetupOut(id=str(item.id), code=item.code, name=item.name, description=item.description if _has_description(model) else None, active=item.active, version=item.version)

    async def _validate_coded(self, model: type, label: str, data: CodedItemInput, current_id: uuid.UUID | None) -> None:
        errors = FieldErrors()
        if not CODE.match(data.code):
            errors.add("code", CODE_MESSAGE)
        elif await self.repo.coded_code_taken(model, data.code, current_id):
            errors.add("code", f"Another {label} uses this code.")
        if data.description and not _has_description(model):
            errors.add("description", f"A {label} has no description.")
        errors.raise_if_any()

    async def setup_create_coded(self, kind: str, data: CodedItemInput) -> CodedItemSetupOut:
        model, label = _coded_kind(kind)
        await self._validate_coded(model, label, data, None)
        fields = {"code": data.code, "name": data.name, "active": data.active}
        if _has_description(model):
            fields["description"] = (data.description or "").strip() or None
        item = model(**fields)
        self.repo.add(item)
        await self.session.flush()
        self.audit.record(module="HR Setup", action=f"{model.__tablename__}.created", summary=f"{label.capitalize()} {data.code} created", entity_type=model.__tablename__, entity_id=item.id, entity_label=data.name, changes=diff({}, fields))
        await self.session.commit()
        return self._coded_out(model, item)

    async def setup_update_coded(self, kind: str, item_id: uuid.UUID, data: CodedItemInput) -> CodedItemSetupOut:
        model, label = _coded_kind(kind)
        item = await self.repo.get_coded(model, item_id)
        if item is None:
            raise NotFoundError()
        ensure_version(item, data.version)
        await self._validate_coded(model, label, data, item.id)
        names = ["code", "name", "active"] + (["description"] if _has_description(model) else [])
        before = _columns(item, names)
        item.code, item.name, item.active = data.code, data.name, data.active
        if _has_description(model):
            item.description = (data.description or "").strip() or None
        await self._commit_update(item, before, names, model.__tablename__, f"{label.capitalize()} {item.code} updated", item.name)
        return self._coded_out(model, item)

    async def _commit_update(self, item: Any, before: dict, names: list[str], entity_type: str, summary: str, label: str, after: dict | None = None) -> None:
        changes = diff(before, after if after is not None else _columns(item, names))
        if not changes:
            return
        await self.session.flush()
        self.audit.record(module="HR Setup", action=f"{entity_type}.updated", summary=summary, entity_type=entity_type, entity_id=item.id, entity_label=label, changes=changes)
        await self.session.commit()

    # ---- Setup: employee statuses -------------------------------------------------------------------

    async def setup_list_statuses(self) -> list[EmployeeStatusSetupOut]:
        return [_status_out(s) for s in await self.repo.list_statuses()]

    async def _validate_status(self, data: EmployeeStatusInput, current: EmployeeStatus | None) -> list[str]:
        errors = FieldErrors()
        if current is not None and data.code != current.code:
            errors.add("code", "The code cannot be changed; employee records refer to it.")
        elif current is None and await self.repo.get_status_by_code(data.code) is not None:
            errors.add("code", "Another status uses this code.")
        targets = list(dict.fromkeys(data.transitions))
        if data.code in targets:
            errors.add("transitions", "A status cannot move to itself.")
        else:
            missing = sorted(set(targets) - await self.repo.existing_status_codes(targets))
            if missing:
                errors.add("transitions", f"Unknown status: {', '.join(missing)}.")
        errors.raise_if_any()
        return targets

    @staticmethod
    def _status_snapshot(s: EmployeeStatus, transitions: list[str]) -> dict:
        return {
            "code": s.code, "label": s.label, "tone": s.tone, "active": s.active, "allowedOnCreate": s.allowed_on_create, "sortOrder": s.sort_order,
            "employmentEnded": s.employment_ended, "reasonRequired": s.reason_required, "transitions": ",".join(sorted(transitions)),
        }

    async def setup_create_status(self, data: EmployeeStatusInput) -> EmployeeStatusSetupOut:
        targets = await self._validate_status(data, None)
        status = EmployeeStatus(
            code=data.code, label=data.label.strip(), tone=data.tone, active=data.active, allowed_on_create=data.allowed_on_create, sort_order=data.sort_order,
            employment_ended=data.employment_ended, reason_required=data.reason_required, transitions=[],
        )
        status.transitions = [EmployeeStatusTransition(to_code=c) for c in targets]
        self.repo.add(status)
        await self.session.flush()
        self.audit.record(module="HR Setup", action="employee_status.created", summary=f"Employee status {data.code} created", entity_type="employee_status", entity_id=status.id, entity_label=status.label, changes=diff({}, self._status_snapshot(status, targets)))
        await self.session.commit()
        return await self._status_reloaded(status.id)

    async def setup_update_status(self, status_id: uuid.UUID, data: EmployeeStatusInput) -> EmployeeStatusSetupOut:
        status = await self.repo.get_status(status_id)
        if status is None:
            raise NotFoundError()
        ensure_version(status, data.version)
        targets = await self._validate_status(data, status)
        before = self._status_snapshot(status, [t.to_code for t in status.transitions])
        status.label, status.tone, status.active, status.allowed_on_create, status.sort_order = data.label.strip(), data.tone, data.active, data.allowed_on_create, data.sort_order
        status.employment_ended, status.reason_required = data.employment_ended, data.reason_required
        keep = [t for t in status.transitions if t.to_code in targets]
        have = {t.to_code for t in keep}
        status.transitions = keep + [EmployeeStatusTransition(to_code=c) for c in targets if c not in have]
        await self._commit_update(status, before, [], "employee_status", f"Employee status {status.code} updated", status.label, after=self._status_snapshot(status, targets))
        return await self._status_reloaded(status.id)

    async def _status_reloaded(self, status_id: uuid.UUID) -> EmployeeStatusSetupOut:
        status = await self.repo.get_status(status_id)
        assert status is not None
        await self.session.refresh(status, ["transitions"])
        return _status_out(status)

    # ---- Setup: document types ----------------------------------------------------------------------

    async def setup_list_document_types(self) -> list[DocumentTypeSetupOut]:
        return [_document_type_out(d) for d in await self.repo.list_document_types()]

    async def _validate_document_type(self, data: DocumentTypeInput, current_id: uuid.UUID | None) -> uuid.UUID:
        errors = FieldErrors()
        if not CODE.match(data.code):
            errors.add("code", CODE_MESSAGE)
        elif await self.repo.coded_code_taken(DocumentType, data.code, current_id):
            errors.add("code", "Another document type uses this code.")
        category_id = body_id(data.category_id)
        if category_id is None or await self.repo.get_coded(DocumentCategory, category_id) is None:
            errors.add("categoryId", "Select an existing document category.")
        unsupported = [e for e in data.allowed_extensions if e not in SUPPORTED_EXTENSIONS]
        if unsupported:
            # Uploads are checked by content; only formats with a content check can be accepted.
            errors.add("allowedExtensions", f"Supported file types: {', '.join(SUPPORTED_EXTENSIONS)}.")
        if data.max_size_bytes > get_settings().max_upload_bytes:
            errors.add("maxSizeBytes", f"The service accepts uploads up to {get_settings().max_upload_bytes // (1024 * 1024)} MB (MAX_UPLOAD_BYTES).")
        errors.raise_if_any()
        assert category_id is not None
        return category_id

    _DOC_FIELDS = ["code", "name", "category_id", "required", "expiry_required", "allowed_extensions", "max_size_bytes", "active"]

    def _doc_values(self, data: DocumentTypeInput, category_id: uuid.UUID) -> dict:
        return {"code": data.code, "name": data.name.strip(), "category_id": category_id, "required": data.required, "expiry_required": data.expiry_required, "allowed_extensions": data.allowed_extensions, "max_size_bytes": data.max_size_bytes, "active": data.active}

    async def setup_create_document_type(self, data: DocumentTypeInput) -> DocumentTypeSetupOut:
        category_id = await self._validate_document_type(data, None)
        values = self._doc_values(data, category_id)
        doc_type = DocumentType(**values)
        self.repo.add(doc_type)
        await self.session.flush()
        self.audit.record(module="HR Setup", action="document_type.created", summary=f"Document type {data.code} created", entity_type="document_type", entity_id=doc_type.id, entity_label=doc_type.name, changes=diff({}, values))
        await self.session.commit()
        return await self._document_type_reloaded(doc_type.id)

    async def setup_update_document_type(self, type_id: uuid.UUID, data: DocumentTypeInput) -> DocumentTypeSetupOut:
        doc_type = await self.repo.get_coded(DocumentType, type_id)
        if doc_type is None:
            raise NotFoundError()
        ensure_version(doc_type, data.version)
        category_id = await self._validate_document_type(data, doc_type.id)
        before = _columns(doc_type, self._DOC_FIELDS)
        for key, value in self._doc_values(data, category_id).items():
            setattr(doc_type, key, value)
        await self._commit_update(doc_type, before, self._DOC_FIELDS, "document_type", f"Document type {doc_type.code} updated", doc_type.name)
        return await self._document_type_reloaded(doc_type.id)

    async def _document_type_reloaded(self, type_id: uuid.UUID) -> DocumentTypeSetupOut:
        doc_type = await self.repo.get_coded(DocumentType, type_id)
        assert doc_type is not None
        await self.session.refresh(doc_type, ["category"])
        return _document_type_out(doc_type)

    # ---- Setup: payroll fields ----------------------------------------------------------------------

    async def setup_list_payroll_fields(self) -> list[PayrollFieldSetupOut]:
        return [_payroll_out(f) for f in await self.repo.list_payroll_fields(active_only=False)]

    async def _validate_payroll_field(self, data: PayrollFieldInput, current: PayrollFieldDefinition | None) -> None:
        errors = FieldErrors()
        if current is not None and data.key != current.key:
            errors.add("key", "The key cannot be changed; employee payroll details are stored under it.")
        elif current is None and await self.repo.payroll_key_taken(data.key):
            errors.add("key", "Another payroll field uses this key.")
        if data.type == "select":
            if not data.options:
                errors.add("options", "Add at least one option.")
            elif len({o.value for o in data.options}) != len(data.options):
                errors.add("options", "Each option needs a different value.")
        elif data.options:
            errors.add("options", "Only select fields have options.")
        if data.pattern:
            try:
                re.compile(data.pattern)
            except re.error:
                errors.add("pattern", "Enter a valid pattern.")
        if data.pattern_message and not data.pattern:
            errors.add("patternMessage", "Add a pattern for this message.")
        errors.raise_if_any()

    _PAYROLL_FIELDS = ["key", "label", "type", "required", "sensitive", "max_length", "pattern", "pattern_message", "options", "hint", "sort_order", "active"]

    @staticmethod
    def _payroll_values(data: PayrollFieldInput) -> dict:
        return {
            "key": data.key, "label": data.label.strip(), "type": data.type, "required": data.required, "sensitive": data.sensitive, "max_length": data.max_length, "pattern": data.pattern or None,
            "pattern_message": data.pattern_message or None, "options": [o.model_dump() for o in data.options] if data.options else None, "hint": data.hint or None, "sort_order": data.sort_order, "active": data.active,
        }

    async def setup_create_payroll_field(self, data: PayrollFieldInput) -> PayrollFieldSetupOut:
        await self._validate_payroll_field(data, None)
        values = self._payroll_values(data)
        field = PayrollFieldDefinition(**values)
        self.repo.add(field)
        await self.session.flush()
        self.audit.record(module="HR Setup", action="payroll_field_definition.created", summary=f"Payroll field {data.key} created", entity_type="payroll_field_definition", entity_id=field.id, entity_label=field.label, changes=diff({}, values))
        await self.session.commit()
        return _payroll_out(field)

    async def setup_update_payroll_field(self, field_id: uuid.UUID, data: PayrollFieldInput) -> PayrollFieldSetupOut:
        field = await self.repo.get_payroll_field(field_id)
        if field is None:
            raise NotFoundError()
        ensure_version(field, data.version)
        await self._validate_payroll_field(data, field)
        before = _columns(field, self._PAYROLL_FIELDS)
        was_sensitive = field.sensitive
        for key, value in self._payroll_values(data).items():
            setattr(field, key, value)
        if field.sensitive != was_sensitive:
            # Stored employee values follow the field: encrypted exactly when it is sensitive.
            for row in await EmployeeRepository(self.session).payroll_values_for_field(field.key):
                if field.sensitive and not row.encrypted:
                    row.value, row.encrypted = crypto.encrypt(row.value), True
                elif not field.sensitive and row.encrypted:
                    row.value, row.encrypted = crypto.decrypt(row.value), False
        await self._commit_update(field, before, self._PAYROLL_FIELDS, "payroll_field_definition", f"Payroll field {field.key} updated", field.label)
        return _payroll_out(field)
