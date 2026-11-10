"""Password hashing (Argon2id) and the password policy (configurable; pending IT confirmation).

Passwords are never stored, logged, audited or returned: only the Argon2id hash is kept.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings

_hasher = PasswordHasher()  # Argon2id with the library's current recommended parameters
# A fixed hash checked when the username is unknown, so a wrong username takes as long as a wrong password.
_DUMMY = _hasher.hash("timing-equalizer-not-a-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def policy_problems(password: str, username: str, s: Settings) -> list[str]:
    problems = []
    if len(password) < s.password_min_length:
        problems.append(f"Use at least {s.password_min_length} characters.")
    if len(password) > 256:
        problems.append("Use at most 256 characters.")
    if s.password_require_letter_and_digit and not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        problems.append("Use at least one letter and one number.")
    if username and username.lower() in password.lower():
        problems.append("The password must not contain the username.")
    return problems
