"""Imports every model so Alembic autogenerate and the tests see all tables."""

from app.models import audit_log_model, platform_model  # noqa: F401
