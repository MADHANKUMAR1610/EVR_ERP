"""Company settings (contract G7). Nothing is pre-filled: until an administrator saves them, the fields are empty."""

from __future__ import annotations

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import StaleVersionError
from app.models.platform_model import CompanySettings
from app.schemas.platform_schema import AddressModel, CompanySettingsIn, CompanySettingsOut
from app.services.audit_service import AuditService, diff
from app.utils.validation import FieldErrors, ensure_version

LOCALE = re.compile(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _out(c: CompanySettings | None) -> CompanySettingsOut:
    if c is None:
        return CompanySettingsOut(legal_name="", display_name="", registration_number="", tax_id="", address=AddressModel(), phone="", email="", website="", time_zone="", currency="",
                                  locale="", date_format=None, time_format=None, week_start=None, working_days=[], fiscal_year_start_month=None, version=0, updated_at=None, updated_by="")
    return CompanySettingsOut(legal_name=c.legal_name, display_name=c.display_name, registration_number=c.registration_number, tax_id=c.tax_id, address=AddressModel(**c.address),
                              phone=c.phone, email=c.email, website=c.website, time_zone=c.time_zone, currency=c.currency, locale=c.locale, date_format=c.date_format,
                              time_format=c.time_format, week_start=c.week_start, working_days=list(c.working_days), fiscal_year_start_month=c.fiscal_year_start_month,
                              version=c.version, updated_at=c.updated_at, updated_by=c.updated_by_name)


class SettingsService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self) -> CompanySettingsOut:
        return _out(await self.session.scalar(select(CompanySettings)))

    async def save(self, data: CompanySettingsIn) -> CompanySettingsOut:
        err = FieldErrors()
        if not data.legal_name.strip():
            err.add("legalName", "Enter the legal name.")
        if not data.display_name.strip():
            err.add("displayName", "Enter the display name.")
        try:
            ZoneInfo(data.time_zone)
        except (ZoneInfoNotFoundError, ValueError):
            err.add("timeZone", "Choose an IANA time zone, for example Asia/Kolkata.")
        if not re.match(r"^[A-Z]{3}$", data.currency):
            err.add("currency", "Enter the ISO 4217 currency code, for example INR.")
        if not LOCALE.match(data.locale):
            err.add("locale", "Enter a BCP 47 locale, for example en-IN.")
        if data.email and not EMAIL.match(data.email):
            err.add("email", "Enter a valid email address.")
        if data.website and not data.website.lower().startswith("https://"):
            err.add("website", "Use an https:// address.")
        if not 1 <= data.week_start <= 7:
            err.add("weekStart", "Choose a weekday from 1 (Monday) to 7 (Sunday).")
        if not data.working_days or any(d not in range(1, 8) for d in data.working_days) or len(set(data.working_days)) != len(data.working_days):
            err.add("workingDays", "Choose the working days (each weekday once).")
        if not 1 <= data.fiscal_year_start_month <= 12:
            err.add("fiscalYearStartMonth", "Choose a month from 1 to 12.")
        err.raise_if_any()
        current = await self.session.scalar(select(CompanySettings).with_for_update())
        values = dict(legal_name=data.legal_name.strip(), display_name=data.display_name.strip(), registration_number=data.registration_number.strip(), tax_id=data.tax_id.strip(),
                      address=data.address.model_dump(), phone=data.phone.strip(), email=data.email.strip(), website=data.website.strip(), time_zone=data.time_zone, currency=data.currency,
                      locale=data.locale, date_format=data.date_format, time_format=data.time_format, week_start=data.week_start, working_days=sorted(data.working_days),
                      fiscal_year_start_month=data.fiscal_year_start_month)
        before = _out(current).model_dump(exclude={"version", "updated_at", "updated_by"})
        if current is None:
            if data.version != 0:  # someone else saved the first version meanwhile
                raise StaleVersionError()
            current = CompanySettings(singleton=True, **values)
            self.session.add(current)
        else:
            ensure_version(current, data.version)
            for k, v in values.items():
                setattr(current, k, v)
        await self.session.flush()
        after = _out(current).model_dump(exclude={"version", "updated_at", "updated_by"})
        AuditService(self.session).record(module="Platform", action="company_settings.saved", summary="Company settings saved", entity_type="company_settings", entity_label=values["display_name"],
                                          changes=diff({k: str(v) for k, v in before.items()}, {k: str(v) for k, v in after.items()}))
        await self.session.commit()
        await self.session.refresh(current)
        return _out(current)
