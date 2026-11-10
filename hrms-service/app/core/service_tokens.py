"""Client-credentials service tokens from the Identity service (POST /internal/service-tokens), cached until
shortly before they expire. Used for calls that have no user behind them."""

import time

import httpx

from app.core.errors import ServiceUnavailableError

# Tests replace this with an httpx.MockTransport.
transport: httpx.AsyncBaseTransport | None = None


class ServiceTokenProvider:
    def __init__(self, base_url: str | None, client_id: str | None, client_secret: str | None):
        self.base_url = (base_url or "").rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: str | None = None
        self._expires = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.client_id and self.client_secret)

    async def token(self) -> str:
        if not self.configured:
            raise ServiceUnavailableError("Service-to-service access is not configured (IDENTITY_BASE_URL, IDENTITY_CLIENT_ID, IDENTITY_CLIENT_SECRET).")
        if self._token and time.monotonic() < self._expires - 30:
            return self._token
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=5.0, transport=transport) as client:
                r = await client.post("/internal/service-tokens", json={"clientId": self.client_id, "clientSecret": self.client_secret})
            r.raise_for_status()
            body = r.json()
        except (httpx.HTTPError, ValueError):
            raise ServiceUnavailableError("The Identity service could not issue a service token. Try again shortly.") from None
        self._token, self._expires = body["accessToken"], time.monotonic() + int(body.get("expiresIn", 60))
        return self._token


_provider: ServiceTokenProvider | None = None


def service_tokens() -> ServiceTokenProvider:
    """The HRMS client of Identity (IDENTITY_BASE_URL, IDENTITY_CLIENT_ID, IDENTITY_CLIENT_SECRET)."""
    global _provider
    if _provider is None:
        from app.core.config import get_settings

        s = get_settings()
        _provider = ServiceTokenProvider(s.identity_base_url, s.identity_client_id, s.identity_client_secret)
    return _provider


async def bearer_for(static_token: str | None) -> str | None:
    """A service token from Identity (client credentials) when configured, else the static token setting."""
    provider = service_tokens()
    if provider.configured:
        return await provider.token()
    return static_token
