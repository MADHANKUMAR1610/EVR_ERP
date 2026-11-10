"""Collects field errors so a form gets every problem in one 422 response."""

from typing import Any

from app.core.errors import StaleVersionError, ValidationFailedError


class FieldErrors:
    def __init__(self) -> None:
        self.details: list[dict[str, str]] = []

    def add(self, field: str, message: str) -> None:
        if not any(d["field"] == field for d in self.details):
            self.details.append({"field": field, "message": message})

    def has(self, field: str) -> bool:
        return any(d["field"] == field for d in self.details)

    def raise_if_any(self, *, code: str | None = None, use_first_message: bool = False) -> None:
        """`code` overrides VALIDATION_FAILED (e.g. INVALID_TRANSITION); `use_first_message` puts the
        first field message in the top-level message, for dialogs that only show that."""
        if self.details:
            message = self.details[0]["message"] if use_first_message else None
            raise ValidationFailedError(message, details=self.details, code=code)


def ensure_version(record: Any, version: int | None) -> None:
    """Optimistic concurrency: when the client sends the version it edited, it must still be current."""
    if version is not None and version != record.version:
        raise StaleVersionError()
