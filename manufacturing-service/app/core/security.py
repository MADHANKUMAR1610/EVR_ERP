"""Verification of session tokens issued by the Identity service (hrms-service docs/AUTH_INTEGRATION.md).

Platform never signs user tokens and never sees passwords. It accepts a JWT from the session cookie
(preferred: the frontend always sends cookies) or from `Authorization: Bearer`, verifies its
signature, expiry, issuer and audience, then checks the session has not been revoked.
"""

import logging
import time
from dataclasses import dataclass

import httpx
import jwt
from jwt import PyJWKClient

from app.core.config import Settings
from app.core.context import Principal
from app.core.errors import ServiceUnavailableError, UnauthenticatedError
from app.core.service_tokens import ServiceTokenProvider

logger = logging.getLogger("manufacturing.auth")


@dataclass
class _RevocationEntry:
    active: bool
    checked_at: float


class TokenVerifier:
    def __init__(self, settings: Settings):
        self.s = settings
        self._jwks = PyJWKClient(settings.auth_jwks_url, cache_keys=True, lifespan=settings.auth_jwks_cache_seconds) if settings.auth_jwks_url else None
        self._revocations: dict[str, _RevocationEntry] = {}
        self.service_tokens = ServiceTokenProvider(settings.identity_base_url, settings.identity_client_id, settings.identity_client_secret)

    # --- Token -------------------------------------------------------------------------------
    def _key_and_algorithms(self, token: str) -> tuple[object, list[str]]:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg", "")
        if self.s.auth_dev_mode and alg == "HS256":
            return self.s.auth_dev_secret, ["HS256"]
        if alg not in self.s.auth_jwt_algorithms:
            raise UnauthenticatedError()
        if self._jwks is not None:
            return self._jwks.get_signing_key_from_jwt(token).key, self.s.auth_jwt_algorithms
        if self.s.auth_jwt_public_key:
            return self.s.auth_jwt_public_key, self.s.auth_jwt_algorithms
        raise UnauthenticatedError()

    def decode(self, token: str) -> Principal:
        try:
            key, algorithms = self._key_and_algorithms(token)
            claims = jwt.decode(
                token,
                key=key,  # type: ignore[arg-type]
                algorithms=algorithms,
                audience=self.s.auth_jwt_audience,
                issuer=self.s.auth_jwt_issuer,
                leeway=self.s.auth_leeway_seconds,
                options={"require": ["exp", self.s.auth_claim_user_id], "verify_aud": self.s.auth_jwt_audience is not None},
            )
        except UnauthenticatedError:
            raise
        except jwt.PyJWTError as exc:
            # The reason is logged for operators, never returned to the caller.
            logger.info("token rejected", extra={"reason": type(exc).__name__})
            raise UnauthenticatedError() from None

        permissions = claims.get(self.s.auth_claim_permissions)
        if not isinstance(permissions, list) or not all(isinstance(p, str) for p in permissions):
            logger.info("token rejected", extra={"reason": "missing permissions claim"})
            raise UnauthenticatedError()
        roles = claims.get(self.s.auth_claim_roles) or []
        employee_id = claims.get(self.s.auth_claim_employee_id)
        return Principal(
            user_id=str(claims[self.s.auth_claim_user_id]),
            name=str(claims.get(self.s.auth_claim_name) or claims[self.s.auth_claim_user_id]),
            permissions=frozenset(permissions),
            roles=frozenset(str(r) for r in roles) if isinstance(roles, list) else frozenset(),
            employee_id=str(employee_id) if employee_id else None,
            session_id=str(claims[self.s.auth_claim_session_id]) if claims.get(self.s.auth_claim_session_id) else None,
        )

    def decode_service(self, token: str) -> Principal:
        """A service token from Identity (aud evr-internal): its permissions are the client's internal scopes."""
        try:
            key, algorithms = self._key_and_algorithms(token)
            claims = jwt.decode(token, key=key, algorithms=algorithms, audience="evr-internal", issuer=self.s.auth_jwt_issuer, leeway=self.s.auth_leeway_seconds,  # type: ignore[arg-type]
                                options={"require": ["exp", "sub"]})
        except UnauthenticatedError:
            raise
        except jwt.PyJWTError:
            raise UnauthenticatedError() from None
        perms = claims.get("permissions") or []
        return Principal(user_id=str(claims["sub"]), name=str(claims["sub"]), permissions=frozenset(p for p in perms if isinstance(p, str)))

    # --- Revocation ----------------------------------------------------------------------------
    async def ensure_active(self, principal: Principal) -> None:
        if not self.s.auth_revocation_url or not principal.session_id:
            return
        now = time.monotonic()
        cached = self._revocations.get(principal.session_id)
        if cached and now - cached.checked_at < self.s.auth_revocation_cache_seconds:
            if not cached.active:
                raise UnauthenticatedError()
            return
        url = self.s.auth_revocation_url.rstrip("/") + f"/{principal.session_id}"
        try:
            headers = {"Authorization": f"Bearer {await self.service_tokens.token()}"}
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url, headers=headers)
            response.raise_for_status()
            active = bool(response.json().get("active"))
        except (httpx.HTTPError, ValueError, ServiceUnavailableError):
            logger.warning("revocation check failed", extra={"target": "identity"})
            if cached and now - cached.checked_at < self.s.auth_revocation_stale_seconds:
                if not cached.active:
                    raise UnauthenticatedError() from None
                return
            raise ServiceUnavailableError("Sign-in could not be confirmed right now. Try again shortly.") from None
        self._revocations[principal.session_id] = _RevocationEntry(active, now)
        if not active:
            raise UnauthenticatedError()
