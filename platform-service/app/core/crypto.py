"""Encryption at rest for integration secrets (Fernet = AES-128-CBC + HMAC-SHA256).

Keys come from INTEGRATION_ENCRYPTION_KEYS: the first encrypts, every key decrypts (rotation). Plain secrets
exist only in memory while saving; they are never logged, audited or returned.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings
from app.core.errors import ServiceUnavailableError


@lru_cache
def _cipher() -> MultiFernet:
    keys = get_settings().integration_encryption_keys
    if not keys:
        raise ServiceUnavailableError("Secrets cannot be stored: INTEGRATION_ENCRYPTION_KEYS is not set.")
    return MultiFernet([Fernet(k.encode()) for k in keys])


def encrypt(value: str) -> str:
    return _cipher().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _cipher().decrypt(token.encode()).decode()
    except InvalidToken:
        raise ServiceUnavailableError("A stored secret cannot be read with the configured keys.") from None
