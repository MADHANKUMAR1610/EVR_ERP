"""Signing and verifying session and service tokens (RS256), and the public JWKS (hrms-service docs/AUTH_INTEGRATION.md).

- User session token: claims sub, name, sid, employeeId, roles (role ids), permissions, mustChangePassword,
  iss, aud = evr-erp, iat, exp. While mustChangePassword is true the token carries no permissions.
- Service token: sub = client id, aud = evr-internal, permissions = the client's internal scopes.
The private key comes only from the environment (JWT_PRIVATE_KEY). Nothing is stored in the source.
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from app.core.config import Settings
from app.core.errors import ServiceUnavailableError, UnauthenticatedError

INTERNAL_AUDIENCE = "evr-internal"


def _b64(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@lru_cache(maxsize=4)
def _load(pem: str) -> tuple[RSAPrivateKey, RSAPublicKey]:
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, RSAPrivateKey):
        raise ValueError("JWT_PRIVATE_KEY must be an RSA private key (PEM).")
    return key, key.public_key()


@dataclass(frozen=True)
class SessionClaims:
    user_id: str
    name: str
    session_id: str
    employee_id: str | None
    roles: list[str]
    permissions: list[str]
    must_change_password: bool
    expires_at: datetime


class TokenService:
    def __init__(self, settings: Settings):
        self.s = settings

    def _keys(self) -> tuple[RSAPrivateKey, RSAPublicKey]:
        if not self.s.jwt_private_key:
            raise ServiceUnavailableError("Sign-in is not configured (JWT_PRIVATE_KEY is not set).")
        return _load(self.s.jwt_private_key)

    def public_pem(self) -> str:
        return self._keys()[1].public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    def jwks(self) -> dict:
        numbers = self._keys()[1].public_numbers()
        return {"keys": [{"kty": "RSA", "use": "sig", "alg": "RS256", "kid": self.s.jwt_key_id, "n": _b64(numbers.n), "e": _b64(numbers.e)}]}

    def _sign(self, claims: dict) -> str:
        return jwt.encode(claims, self._keys()[0], algorithm="RS256", headers={"kid": self.s.jwt_key_id})

    def issue_session(self, c: SessionClaims) -> str:
        now = datetime.now(UTC)
        return self._sign({
            "iss": self.s.jwt_issuer, "aud": self.s.jwt_audience, "sub": c.user_id, "name": c.name, "sid": c.session_id, "employeeId": c.employee_id,
            "roles": c.roles, "permissions": [] if c.must_change_password else c.permissions, "mustChangePassword": c.must_change_password,
            "iat": int(now.timestamp()), "exp": int(c.expires_at.timestamp()),
        })

    def issue_service(self, client_id: str, scopes: list[str]) -> tuple[str, str, datetime]:
        now = datetime.now(UTC)
        exp = now + timedelta(minutes=self.s.service_token_minutes)
        jti = uuid.uuid4().hex
        token = self._sign({"iss": self.s.jwt_issuer, "aud": INTERNAL_AUDIENCE, "sub": client_id, "name": client_id, "permissions": scopes, "jti": jti,
                            "iat": int(now.timestamp()), "exp": int(exp.timestamp())})
        return token, jti, exp

    def decode(self, token: str, *, audience: str | None = None) -> dict:
        try:
            return jwt.decode(token, self._keys()[1], algorithms=["RS256"], audience=audience or self.s.jwt_audience, issuer=self.s.jwt_issuer, leeway=30,
                              options={"require": ["exp", "sub", "iat"]})
        except jwt.PyJWTError:
            raise UnauthenticatedError() from None
