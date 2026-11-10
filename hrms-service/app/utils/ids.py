"""Parsing of record IDs taken from paths and request bodies."""

import uuid

from app.core.errors import NotFoundError


def path_id(value: str) -> uuid.UUID:
    """An ID from the URL. Anything that is not a UUID cannot exist, so it is a 404."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise NotFoundError() from None


def body_id(value: str | None) -> uuid.UUID | None:
    """An ID from the request body; None when it is missing or not a UUID (callers report the field)."""
    if value is None or value == "":
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None
