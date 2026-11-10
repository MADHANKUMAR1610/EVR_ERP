"""Platform (frontend admin.service.ts and notifications.service.ts; contracts B2, G7–G10). Field names match the frontend."""

from typing import Literal

from pydantic import Field

from app.schemas.common import CamelModel, Page, PageMeta, ResponseModel, UtcDateTime

Category = Literal["approval", "attendance", "leave", "overtime", "payroll", "employee", "documents", "performance", "system"]
Channel = Literal["in_app", "email", "sms"]
DateFormat = Literal["DD-MM-YYYY", "DD/MM/YYYY", "YYYY-MM-DD", "DD MMM YYYY"]


# --- Company settings (G7) -----------------------------------------------------------------------------


class AddressModel(CamelModel):
    line1: str = Field(default="", max_length=120)
    line2: str = Field(default="", max_length=120)
    city: str = Field(default="", max_length=60)
    state: str = Field(default="", max_length=60)
    postal_code: str = Field(default="", max_length=12)
    country: str = Field(default="", max_length=60)


class CompanySettingsOut(ResponseModel):
    legal_name: str
    display_name: str
    registration_number: str
    tax_id: str
    address: AddressModel
    phone: str
    email: str
    website: str
    time_zone: str
    currency: str
    locale: str
    # Null until an administrator saves the settings (nothing is pre-filled).
    date_format: DateFormat | None
    time_format: Literal["24h", "12h"] | None
    week_start: int | None
    working_days: list[int]
    fiscal_year_start_month: int | None
    version: int
    updated_at: UtcDateTime | None
    updated_by: str


class CompanySettingsIn(CamelModel):
    legal_name: str = Field(max_length=200)
    display_name: str = Field(max_length=120)
    registration_number: str = Field(default="", max_length=60)
    tax_id: str = Field(default="", max_length=60)
    address: AddressModel
    phone: str = Field(default="", max_length=30)
    email: str = Field(default="", max_length=254)
    website: str = Field(default="", max_length=300)
    time_zone: str = Field(max_length=60)
    currency: str = Field(max_length=3)
    locale: str = Field(max_length=35)
    date_format: DateFormat
    time_format: Literal["24h", "12h"]
    week_start: int
    working_days: list[int] = Field(max_length=7)
    fiscal_year_start_month: int
    version: int


# --- Notifications (B2, G8) ------------------------------------------------------------------------------


class NotificationOut(ResponseModel):
    id: str
    title: str
    message: str | None = None
    category: Category
    created_at: UtcDateTime
    read: bool
    link: str | None = None


class NotificationFeedOut(ResponseModel):
    items: list[NotificationOut]
    unread_count: int


class NotificationPageOut(Page[NotificationOut]):
    unread_count: int


class ChannelStateOut(ResponseModel):
    channel: Channel
    available: bool
    reason: str | None = None


class CategoryPreferenceOut(ResponseModel):
    category: Category
    label: str
    description: str
    channels: dict[str, bool]
    mandatory: bool


class NotificationPreferencesOut(ResponseModel):
    channels: list[ChannelStateOut]
    categories: list[CategoryPreferenceOut]
    version: int


class CategoryChoiceIn(CamelModel):
    category: Category
    channels: dict[Channel, bool]


class NotificationPreferencesIn(CamelModel):
    categories: list[CategoryChoiceIn] = Field(max_length=20)
    version: int


class InternalNotificationIn(CamelModel):
    """From other services (hrms-service docs/AUTH_INTEGRATION.md section 4). roleCodes are Identity role ids."""

    user_ids: list[str] = Field(default_factory=list, max_length=1000)
    employee_ids: list[str] = Field(default_factory=list, max_length=1000)
    role_codes: list[str] = Field(default_factory=list, max_length=50)
    category: Category
    title: str = Field(max_length=200)
    message: str | None = Field(default=None, max_length=2000)
    link: str | None = Field(default=None, max_length=500)


class DeliveryOut(ResponseModel):
    delivered: int
    skipped: int


# --- Integrations (G9) --------------------------------------------------------------------------------------


class IntegrationSettingOut(ResponseModel):
    key: str
    label: str
    secret: bool
    value: str | None
    is_set: bool
    required: bool


class LastErrorOut(ResponseModel):
    at: UtcDateTime
    message: str


class IntegrationOut(ResponseModel):
    id: str
    name: str
    category: str
    description: str
    configuration_status: Literal["not_configured", "incomplete", "configured"]
    connection_status: Literal["connected", "disconnected", "error", "unknown"]
    last_successful_sync_at: UtcDateTime | None
    last_error: LastErrorOut | None
    enabled: bool
    settings: list[IntegrationSettingOut]
    version: int


class IntegrationIn(CamelModel):
    enabled: bool
    values: dict[str, str] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)
    version: int


class IntegrationTestOut(ResponseModel):
    ok: bool
    message: str
    checked_at: UtcDateTime


# --- Audit and overview (G10) --------------------------------------------------------------------------------


class ActorOut(ResponseModel):
    id: str
    name: str


class RecordOut(ResponseModel):
    type: str
    id: str
    label: str


class ChangeOut(ResponseModel):
    field: str
    before: str | None
    after: str | None


class AuditEventOut(ResponseModel):
    id: str
    at: UtcDateTime
    actor: ActorOut
    module: str
    action: str
    record: RecordOut | None
    result: Literal["success", "failure", "denied"]
    summary: str
    changes: list[ChangeOut] | None


class AuditFacetsOut(ResponseModel):
    modules: list[str]
    actions: list[str]
    actors: list[ActorOut]


class AuditPageOut(Page[AuditEventOut]):
    facets: AuditFacetsOut


class AuditSliceOut(ResponseModel):
    """What each service returns to the audit screen: its newest matching events, the count and facets."""

    items: list[AuditEventOut]
    total: int
    facets: AuditFacetsOut


class UserCountsOut(ResponseModel):
    total: int
    active: int
    invited: int
    inactive: int
    locked: int


class RoleCountsOut(ResponseModel):
    total: int
    administrators: int


class WorkflowCountsOut(ResponseModel):
    published: int
    draft: int
    processes_without_workflow: list[str]


class AdminOverviewOut(ResponseModel):
    users: UserCountsOut
    roles: RoleCountsOut
    departments: int
    designations: int
    workflows: WorkflowCountsOut
    integrations_needing_attention: int
    recent_audit: list[AuditEventOut]


__all__ = ["PageMeta"]
