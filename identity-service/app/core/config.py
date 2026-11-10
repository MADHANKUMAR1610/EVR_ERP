"""Identity service configuration, read only from environment variables (and a local `.env` in development).

Nothing secret has a default: the signing key, database URL and service-client secrets come from the
environment. Production refuses to start with development-only settings.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Service ---------------------------------------------------------------------------------
    environment: Literal["development", "test", "staging", "production"] = "development"
    service_name: str = "identity-service"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    allowed_origins: list[str] = Field(default_factory=list)
    docs_enabled: bool = True

    # --- Database ----------------------------------------------------------------------------------
    database_url: str
    database_pool_size: int = 10
    database_max_overflow: int = 10
    database_echo: bool = False

    # --- Session tokens (docs/AUTH_INTEGRATION.md of hrms-service) -----------------------------------
    # RS256 private key (PEM). Identity signs; every service verifies with the public key (JWKS).
    jwt_private_key: str | None = Field(default=None, repr=False)
    jwt_key_id: str = "identity-1"
    jwt_issuer: str = "evr-identity"
    jwt_audience: str = "evr-erp"
    session_hours: float = Field(default=8, gt=0, le=24)
    auth_cookie_name: str = "evr_session"
    # Secure cookies need HTTPS. Only local HTTP development may switch this off.
    auth_cookie_secure: bool = True
    auth_cookie_domain: str | None = None

    # --- Password policy and lockout (pending IT confirmation; docs/DECISIONS.md) ---------------------
    password_min_length: int = Field(default=12, ge=8, le=128)
    password_require_letter_and_digit: bool = True
    lockout_attempts: int = Field(default=5, ge=1, le=100)
    lockout_minutes: int = Field(default=15, ge=1, le=1440)
    # Sign-in attempts per client IP per minute, across usernames (429 above it).
    login_rate_per_ip_per_minute: int = Field(default=30, ge=1, le=10000)

    # --- HRMS (employee and department names for user accounts) ---------------------------------------
    # Identity calls HRMS with the caller's own session, so it sees only what the caller may see.
    hrms_base_url: str | None = None

    # --- Service clients (client-credentials grant for service tokens) --------------------------------
    # JSON object {"client_id": "sha256 hex of the secret"}; scopes in service_client_scopes.
    service_clients: dict[str, str] = Field(default_factory=dict, repr=False)
    service_client_scopes: dict[str, list[str]] = Field(default_factory=dict)
    service_token_minutes: int = Field(default=15, ge=1, le=120)

    @model_validator(mode="after")
    def _check_production_safety(self) -> "Settings":
        if self.environment == "production":
            if not self.jwt_private_key:
                raise ValueError("Set JWT_PRIVATE_KEY in production.")
            if not self.auth_cookie_secure:
                raise ValueError("AUTH_COOKIE_SECURE must be true in production.")
            if not self.allowed_origins:
                raise ValueError("Set ALLOWED_ORIGINS in production.")
            if self.docs_enabled:
                raise ValueError("Set DOCS_ENABLED=false in production (or protect /docs at the proxy).")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
