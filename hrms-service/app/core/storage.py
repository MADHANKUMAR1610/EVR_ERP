"""Private storage for employee document files.

Files live under STORAGE_DIR (outside anything the web server serves), under random names that
reveal nothing about the employee or the document, encrypted with DOCUMENT_ENCRYPTION_KEYS.
They are read only by the download endpoint after its permission and scope checks; no URL to a
stored file ever exists. Directories are created 0700 and files 0600.
"""

import os
import uuid
from pathlib import Path

from app.core import crypto
from app.core.config import get_settings


class StorageError(RuntimeError):
    pass


def _root() -> Path:
    return Path(get_settings().storage_dir).resolve() / "documents"


def _path(key: str) -> Path:
    # Keys are generated here (hex UUIDs); anything else is refused, so no path can escape the root.
    if len(key) != 32 or any(c not in "0123456789abcdef" for c in key):
        raise StorageError("invalid storage key")
    return _root() / key[:2] / key[2:4] / key


def put(content: bytes) -> str:
    """Encrypts and stores the content; returns the new storage key."""
    key = uuid.uuid4().hex
    path = _path(key)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_suffix(".part")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(crypto.encrypt_document(content))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(temp, path)
    return key


def get(key: str) -> bytes:
    path = _path(key)
    if not path.is_file():
        raise StorageError("stored file is missing")
    return crypto.decrypt_document(path.read_bytes())


def delete(key: str) -> None:
    """Used only to clean up a file whose database record was not saved."""
    try:
        _path(key).unlink(missing_ok=True)
    except StorageError:
        pass


def raw_path(key: str) -> Path:
    """For tests and operations only (checking that files are encrypted at rest)."""
    return _path(key)
