"""Platform service configuration, read only from environment variables (and a local `.env` in development).

Nothing secret has a default. Production refuses to start with development-only settings.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "staging", "production"] = "development"
    service_name: str = "platform-service"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    allowed_origins: list[str] = Field(default_factory=list)
    docs_enabled: bool = True

    database_url: str
    database_pool_size: int = 10
    database_max_overflow: int = 10
    database_echo: bool = False

    # --- Session tokens issued by the Identity service (verified like HRMS does) -------------------------
    auth_cookie_name: str = "evr_session"
    auth_jwt_algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    auth_jwt_public_key: str | None = None
    auth_jwks_url: str | None = None
    auth_jwks_cache_seconds: int = 3600
    auth_jwt_issuer: str | None = "evr-identity"
    auth_jwt_audience: str | None = "evr-erp"
    auth_leeway_seconds: int = 30
    auth_claim_user_id: str = "sub"
    auth_claim_name: str = "name"
    auth_claim_session_id: str = "sid"
    auth_claim_employee_id: str = "employeeId"
    auth_claim_roles: str = "roles"
    auth_claim_permissions: str = "permissions"
    auth_revocation_url: str | None = None  # Identity /internal/sessions; empty = no check (development only)
    auth_revocation_cache_seconds: int = 60
    auth_revocation_stale_seconds: int = 300
    auth_dev_mode: bool = False
    auth_dev_secret: str | None = None

    # --- Service-to-service --------------------------------------------------------------------------------
    identity_base_url: str | None = None  # e.g. http://identity:8001 (internal network)
    identity_client_id: str | None = None
    identity_client_secret: str | None = Field(default=None, repr=False)
    hrms_base_url: str | None = None  # e.g. http://hrms:8000

    # --- Integrations: Fernet keys for secrets at rest (JSON list; first encrypts, all decrypt) --------------
    integration_encryption_keys: list[str] = Field(default_factory=list, repr=False)

    # --- Notifications ---------------------------------------------------------------------------------------
    # Categories whose in-app delivery a user cannot switch off (PENDING HR/IT; empty = none mandatory).
    notification_mandatory_categories: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_production_safety(self) -> "Settings":
        if self.environment == "production":
            if self.auth_dev_mode:
                raise ValueError("AUTH_DEV_MODE must be false in production.")
            if not (self.auth_jwt_public_key or self.auth_jwks_url):
                raise ValueError("Set AUTH_JWT_PUBLIC_KEY or AUTH_JWKS_URL in production.")
            if not self.auth_revocation_url:
                raise ValueError("Set AUTH_REVOCATION_URL in production.")
            if not self.allowed_origins:
                raise ValueError("Set ALLOWED_ORIGINS in production.")
            if self.docs_enabled:
                raise ValueError("Set DOCS_ENABLED=false in production (or protect /docs at the proxy).")
            if not self.integration_encryption_keys:
                raise ValueError("Set INTEGRATION_ENCRYPTION_KEYS in production.")
        if self.auth_dev_mode and not self.auth_dev_secret:
            raise ValueError("AUTH_DEV_MODE needs AUTH_DEV_SECRET.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
