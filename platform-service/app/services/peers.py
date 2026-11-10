"""Calls to the Identity service and HRMS.

- With the caller's own session token (audit events, overview counts): each service applies its own
  permissions and scoping, so Platform never sees more than the caller may.
- With a service token (notification recipients): there is no user behind those calls.
A peer that is not configured (local development) is skipped; one that is configured but unreachable is a 503.
"""

from __future__ import annotations

import httpx

from app.core.errors import ServiceUnavailableError

# Tests replace this with an httpx.MockTransport.
transport: httpx.AsyncBaseTransport | None = None


async def get_json(base_url: str | None, path: str, token: str | None, params: dict | None = None, *, name: str) -> dict | list | None:
    if not base_url:
        return None
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=5.0, transport=transport) as client:
            r = await client.get(path, params={k: v for k, v in (params or {}).items() if v is not None}, headers=headers)
    except httpx.HTTPError:
        raise ServiceUnavailableError(f"The {name} service could not be reached. Try again shortly.") from None
    if r.status_code in (401, 403):
        return None  # the caller may not see that part; it is left out
    if r.status_code != 200:
        raise ServiceUnavailableError(f"The {name} service returned an error. Try again shortly.")
    return r.json()
