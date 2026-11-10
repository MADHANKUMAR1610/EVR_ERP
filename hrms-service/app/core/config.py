"""Service configuration, read only from environment variables (and a local `.env` in development).

Nothing secret has a default. Production refuses to start with development-only settings.
"""

from functools import lru_cache
from typing import Literal

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Service -------------------------------------------------------------------------
    environment: Literal["development", "test", "staging", "production"] = "development"
    service_name: str = "hrms-service"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    # Browser origins allowed to make state-changing requests (CSRF protection) and CORS calls.
    allowed_origins: list[str] = Field(default_factory=list)
    docs_enabled: bool = True

    # --- Database --------------------------------------------------------------------------
    # postgresql+asyncpg://user:password@host:5432/hrms
    database_url: str
    database_pool_size: int = 10
    database_max_overflow: int = 10
    database_echo: bool = False

    # --- Authentication: tokens issued by the Identity service (see docs/AUTH_INTEGRATION.md) -----
    auth_cookie_name: str = "evr_session"
    auth_jwt_algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    auth_jwt_public_key: str | None = None  # PEM
    auth_jwks_url: str | None = None
    auth_jwks_cache_seconds: int = 3600
    auth_jwt_issuer: str | None = None
    auth_jwt_audience: str | None = None
    auth_leeway_seconds: int = 30
    auth_claim_user_id: str = "sub"
    auth_claim_name: str = "name"
    auth_claim_session_id: str = "sid"
    auth_claim_employee_id: str = "employeeId"
    auth_claim_roles: str = "roles"
    auth_claim_permissions: str = "permissions"
    # Session revocation check against Identity: empty = disabled (development only).
    auth_revocation_url: str | None = None
    auth_revocation_cache_seconds: int = 60
    auth_revocation_stale_seconds: int = 300
    # Service token HRMS sends to Identity's internal endpoints (see docs/AUTH_INTEGRATION.md section 4).
    identity_service_token: str | None = None
    # Preferred: service tokens from Identity by client credentials (replace the static tokens above and below).
    identity_base_url: str | None = None
    identity_client_id: str | None = None
    identity_client_secret: str | None = Field(default=None, repr=False)
    # Development only: accept HS256 tokens signed with this secret.
    auth_dev_mode: bool = False
    auth_dev_secret: str | None = None

    # --- Files -------------------------------------------------------------------------------
    # Private storage for employee documents: never served by the web server, never public URLs.
    storage_dir: str = "storage"
    # Upper bound for any upload; each document type sets its own (lower) limit.
    max_upload_bytes: int = 10 * 1024 * 1024
    # Fernet keys for documents at rest (JSON list; first encrypts, all decrypt). Separate from payroll keys.
    document_encryption_keys: list[str] = Field(default_factory=list, repr=False)
    # Malware scanning of uploads: "clamav" (clamd over TCP) or "none" (development and tests only).
    malware_scanner: Literal["none", "clamav"] = "none"
    clamav_host: str = "localhost"
    clamav_port: int = 3310
    clamav_timeout_seconds: float = 30.0

    # --- Employee import (contract B6; limits are the contract's proposals, pending HR/IT, R5) -------
    import_max_rows: int = Field(default=2000, ge=1, le=20000)
    import_max_file_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    # Rows committed together with the job's progress; a crash resumes after the last committed batch.
    import_batch_size: int = Field(default=50, ge=1, le=1000)

    # --- Background worker (python -m app.worker) -------------------------------------------------
    worker_poll_seconds: float = 2.0
    # A running job whose heartbeat is older than this is taken over by another worker and resumed.
    worker_stale_seconds: int = 300

    # --- Employee data -------------------------------------------------------------------------
    # Fernet keys for sensitive payroll values (bank account numbers). JSON list; the first key
    # encrypts, all keys decrypt (rotation). Generate one with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    payroll_encryption_keys: list[str] = Field(default_factory=list, repr=False)
    # IANA zone used for "today" (date-of-birth check, default effective dates). Must match the
    # company time zone in Platform's company settings (pending confirmation, see docs).
    company_time_zone: str = "UTC"

    # --- Leave management (Module 6) -------------------------------------------------------------
    # Company working days as ISO weekdays (1 = Monday), JSON list, e.g. [1,2,3,4,5,6]. PENDING
    # (L18): to be taken from Platform's company settings once reachable. Empty: the
    # "working_days" escalation unit cannot be chosen, and leave of employees without a shift is
    # counted without excluding weekly offs (with a warning). Nothing is guessed.
    company_working_days: list[int] = Field(default_factory=list)
    # Leave attachments: the frontend constant ATTACHMENT_RULES (.pdf .jpg .jpeg .png, 5 MB; L14).
    # Payslip PDF heading (Module 7). Empty: the heading is just "Payslip". The final layout is pending HR.
    payslip_company_name: str = Field(default="", max_length=200)
    # HR workspace (Module 10): employee status codes counted as "active" on the dashboard (JSON list, e.g.
    # ["active","on_probation"]). PENDING HR (D20). Empty: the metric is shown as unavailable, never guessed.
    workspace_active_status_codes: list[str] = Field(default_factory=list)
    leave_attachment_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    leave_max_attachments: int = Field(default=5, ge=1, le=20)

    # --- Notifications to the Platform service (POST /internal/notifications) ---------------------
    # Until both are set, notifications stay queued in notification_outbox (L28).
    platform_notifications_url: str | None = None
    platform_service_token: str | None = Field(default=None, repr=False)
    notification_max_attempts: int = Field(default=8, ge=1, le=50)

    @model_validator(mode="after")
    def _check_production_safety(self) -> "Settings":
        if self.environment == "production":
            if self.auth_dev_mode:
                raise ValueError("AUTH_DEV_MODE must be false in production.")
            if not (self.auth_jwt_public_key or self.auth_jwks_url):
                raise ValueError("Set AUTH_JWT_PUBLIC_KEY or AUTH_JWKS_URL in production.")
            if not self.allowed_origins:
                raise ValueError("Set ALLOWED_ORIGINS in production.")
            if self.docs_enabled:
                raise ValueError("Set DOCS_ENABLED=false in production (or protect /docs at the proxy).")
            if not self.payroll_encryption_keys:
                raise ValueError("Set PAYROLL_ENCRYPTION_KEYS in production.")
            if not self.document_encryption_keys:
                raise ValueError("Set DOCUMENT_ENCRYPTION_KEYS in production.")
            if self.malware_scanner == "none":
                raise ValueError("Set MALWARE_SCANNER=clamav in production: uploads must be scanned (contract A9).")
        try:
            ZoneInfo(self.company_time_zone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"COMPANY_TIME_ZONE '{self.company_time_zone}' is not a known IANA time zone.") from None
        if any(d not in range(1, 8) for d in self.company_working_days) or len(set(self.company_working_days)) != len(self.company_working_days):
            raise ValueError("COMPANY_WORKING_DAYS must list distinct ISO weekdays (1 = Monday ... 7 = Sunday).")
        if self.auth_dev_mode and not self.auth_dev_secret:
            raise ValueError("AUTH_DEV_MODE needs AUTH_DEV_SECRET.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
