"""Integrations (contract G9).

- The five known integrations (INT-ZOHO, INT-DEVICES, INT-EMAIL, INT-SMS, INT-SSO) are listed with the settings
  each needs. The setting keys are a technical proposal, pending IT confirmation.
- Secrets are write-only: stored encrypted (INTEGRATION_ENCRYPTION_KEYS), never returned (`value` is null, only
  `isSet`), never in audit changes, logs or messages. An omitted secret keeps the stored value.
- Connection status, last sync and last error come only from an integration connector. None is built yet, so the
  status stays `unknown` and a test answers ok = false with the reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt
from app.core.errors import NotFoundError, ValidationFailedError
from app.models.platform_model import Integration
from app.schemas.platform_schema import IntegrationIn, IntegrationOut, IntegrationSettingOut, IntegrationTestOut, LastErrorOut
from app.services.audit_service import AuditService, diff
from app.utils.validation import ensure_version


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    secret: bool = False
    required: bool = True


@dataclass(frozen=True)
class Definition:
    id: str
    name: str
    category: str
    description: str
    settings: tuple[Setting, ...]


DEFINITIONS: dict[str, Definition] = {d.id: d for d in [
    Definition("INT-ZOHO", "Zoho Books", "Accounting", "Accounting entries and invoices.",
               (Setting("organizationId", "Organization ID"), Setting("apiDomain", "API domain"), Setting("clientId", "Client ID"), Setting("clientSecret", "Client secret", True),
                Setting("refreshToken", "Refresh token", True))),
    Definition("INT-DEVICES", "Attendance terminals", "Attendance", "Biometric attendance devices. Device keys themselves are issued in HRMS (Attendance devices).",
               (Setting("vendor", "Device vendor"), Setting("serverUrl", "Vendor server URL", required=False), Setting("apiKey", "Vendor API key", True, required=False))),
    Definition("INT-EMAIL", "Email (SMTP)", "Notifications", "Outgoing email for notifications.",
               (Setting("smtpHost", "SMTP host"), Setting("smtpPort", "SMTP port"), Setting("fromAddress", "From address"), Setting("username", "Username", required=False),
                Setting("password", "Password", True, required=False))),
    Definition("INT-SMS", "SMS gateway", "Notifications", "Outgoing SMS for notifications.",
               (Setting("provider", "Provider"), Setting("senderId", "Sender ID"), Setting("apiKey", "API key", True))),
    Definition("INT-SSO", "Identity provider (SSO)", "Identity", "Single sign-on with the company identity provider.",
               (Setting("issuerUrl", "Issuer URL"), Setting("clientId", "Client ID"), Setting("clientSecret", "Client secret", True))),
]}
NO_CONNECTOR = "No connector for this integration is built yet, so the connection cannot be tested. The settings are saved."


def _status(d: Definition, row: Integration | None) -> str:
    return _status_of(d, *((row.values, row.secrets) if row else ({}, {})))


def _status_of(d: Definition, values: dict, secrets: dict) -> str:
    set_keys = {k for k, v in values.items() if v} | {k for k, v in secrets.items() if v}
    if not set_keys:
        return "not_configured"
    return "configured" if all(s.key in set_keys for s in d.settings if s.required) else "incomplete"


def _out(d: Definition, row: Integration | None) -> IntegrationOut:
    values, secrets = (row.values, row.secrets) if row else ({}, {})
    return IntegrationOut(
        id=d.id, name=d.name, category=d.category, description=d.description, configuration_status=_status(d, row),
        connection_status=row.connection_status if row else "unknown", last_successful_sync_at=row.last_successful_sync_at if row else None,
        last_error=LastErrorOut(at=row.last_error_at, message=row.last_error) if row and row.last_error and row.last_error_at else None,
        enabled=row.enabled if row else False,
        settings=[IntegrationSettingOut(key=s.key, label=s.label, secret=s.secret, value=None if s.secret else (values.get(s.key) or None),
                                        is_set=bool(secrets.get(s.key) if s.secret else values.get(s.key)), required=s.required) for s in d.settings],
        version=row.version if row else 0,
    )


class IntegrationService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _rows(self) -> dict[str, Integration]:
        return {r.code: r for r in (await self.session.scalars(select(Integration))).all()}

    async def list(self) -> list[IntegrationOut]:
        rows = await self._rows()
        return [_out(d, rows.get(d.id)) for d in DEFINITIONS.values()]

    async def needing_attention(self) -> int:
        """Enabled but not fully configured, or reporting an error."""
        rows = await self._rows()
        return sum(1 for d in DEFINITIONS.values() if (r := rows.get(d.id)) and r.enabled and (_status(d, r) != "configured" or r.connection_status == "error"))

    async def save(self, integration_id: str, data: IntegrationIn) -> IntegrationOut:
        d = DEFINITIONS.get(integration_id)
        if d is None:
            raise NotFoundError()
        known = {s.key: s for s in d.settings}
        bad = [k for k in [*data.values, *data.secrets] if k not in known]
        wrong_kind = [k for k in data.values if k in known and known[k].secret] + [k for k in data.secrets if k in known and not known[k].secret]
        if bad or wrong_kind:
            raise ValidationFailedError(details=[{"field": f"values.{k}" if k in data.values else f"secrets.{k}", "message": "Not a setting of this integration." if k in bad else "Wrong kind of setting."}
                                                 for k in bad + wrong_kind])
        row = await self.session.scalar(select(Integration).where(Integration.code == d.id).with_for_update())
        if row is None and data.version != 0:
            from app.core.errors import StaleVersionError

            raise StaleVersionError()
        if row is not None:
            ensure_version(row, data.version)
        before_values = dict(row.values) if row else {}
        before_secrets = {k: bool(v) for k, v in (row.secrets if row else {}).items()}
        values = dict(before_values)
        for k, v in data.values.items():
            values[k] = v.strip()
        secrets = dict(row.secrets) if row else {}
        for k, v in data.secrets.items():
            if v:
                secrets[k] = encrypt(v)  # only the encrypted value is stored
        if data.enabled and _status_of(d, values, secrets) != "configured":
            raise ValidationFailedError(details=[{"field": "enabled", "message": "Enter every required setting before enabling the integration."}])
        if row is None:  # created only once the request is valid
            row = Integration(code=d.id, enabled=False, values={}, secrets={})
            self.session.add(row)
        row.values, row.secrets, row.enabled = values, secrets, data.enabled
        await self.session.flush()
        changes = diff(before_values, values) + [{"field": k, "before": "set" if before_secrets.get(k) else "not set", "after": "changed"} for k, v in data.secrets.items() if v]
        if before_values == values and not any(data.secrets.values()):
            changes = []
        AuditService(self.session).record(module="Platform", action="integration.saved", summary=f"Integration {d.name} saved ({'enabled' if data.enabled else 'disabled'})",
                                          entity_type="integration", entity_id=d.id, entity_label=d.name, changes=changes)
        await self.session.commit()
        await self.session.refresh(row)
        return _out(d, row)

    async def test(self, integration_id: str) -> IntegrationTestOut:
        d = DEFINITIONS.get(integration_id)
        if d is None:
            raise NotFoundError()
        row = (await self._rows()).get(d.id)
        status = _status(d, row)
        message = NO_CONNECTOR if status == "configured" else "Enter every required setting before testing the connection."
        AuditService(self.session).record(module="Platform", action="integration.tested", summary=f"Connection test of {d.name}: not available", entity_type="integration", entity_id=d.id, entity_label=d.name)
        await self.session.commit()
        return IntegrationTestOut(ok=False, message=message, checked_at=datetime.now(UTC))
