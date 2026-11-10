"""Encryption at rest: sensitive payroll values (bank account numbers, any field marked sensitive) and
employee document files. Each uses its own keys.

Fernet = AES-128-CBC with HMAC-SHA256 authentication. Keys come from PAYROLL_ENCRYPTION_KEYS; the
first encrypts, every key can decrypt, so keys can be rotated without downtime. Plain values exist
only in memory, inside the employee service; they are never logged, audited or returned in full.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings

MASK = "••••"


class EncryptionUnavailableError(RuntimeError):
    """No key is configured, or a stored value cannot be decrypted with the configured keys."""


@lru_cache
def _cipher() -> MultiFernet:
    keys = get_settings().payroll_encryption_keys
    if not keys:
        raise EncryptionUnavailableError("PAYROLL_ENCRYPTION_KEYS is not set.")
    try:
        return MultiFernet([Fernet(k.encode()) for k in keys])
    except ValueError as exc:
        raise EncryptionUnavailableError("PAYROLL_ENCRYPTION_KEYS contains an invalid key.") from exc


def encrypt(value: str) -> str:
    return _cipher().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _cipher().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionUnavailableError("A stored value cannot be decrypted with the configured keys.") from exc


def rotate(token: str) -> str:
    """Re-encrypts with the first (newest) key."""
    return _cipher().rotate(token.encode()).decode()


def mask(value: str | None) -> str | None:
    """'••••' plus the last 4 characters (B4); shorter values reveal nothing."""
    if value is None or value == "":
        return None
    return MASK + value[-4:] if len(value) > 4 else MASK


# --- Employee documents (separate keys: DOCUMENT_ENCRYPTION_KEYS) -----------------------------------


@lru_cache
def _document_cipher() -> MultiFernet:
    keys = get_settings().document_encryption_keys
    if not keys:
        raise EncryptionUnavailableError("DOCUMENT_ENCRYPTION_KEYS is not set.")
    try:
        return MultiFernet([Fernet(k.encode()) for k in keys])
    except ValueError as exc:
        raise EncryptionUnavailableError("DOCUMENT_ENCRYPTION_KEYS contains an invalid key.") from exc


def encrypt_document(content: bytes) -> bytes:
    return _document_cipher().encrypt(content)


def decrypt_document(token: bytes) -> bytes:
    try:
        return _document_cipher().decrypt(token)
    except InvalidToken as exc:
        raise EncryptionUnavailableError("A stored document cannot be decrypted with the configured keys.") from exc


def reset_cache() -> None:
    _cipher.cache_clear()
    _document_cipher.cache_clear()
