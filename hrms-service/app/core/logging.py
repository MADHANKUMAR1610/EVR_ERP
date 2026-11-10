"""Structured JSON logging to stdout (Docker collects and rotates it on the VPS).

Each line carries the request ID and, when known, the user ID. Never pass passwords, tokens,
request bodies or personal data in `extra`: fields named like secrets are dropped.
"""

import json
import logging
import sys
from datetime import UTC, datetime

from app.core.context import current_principal, current_request_id

_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime", "taskName", "color_message"}
_FORBIDDEN = ("password", "token", "secret", "authorization", "cookie")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = current_request_id()
        if request_id:
            entry["request_id"] = request_id
        principal = current_principal()
        if principal:
            entry["user_id"] = principal.user_id
        for key, value in vars(record).items():
            if key in _STANDARD or key.startswith("_"):
                continue
            if any(word in key.lower() for word in _FORBIDDEN):
                continue
            entry[key] = value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Uvicorn's own access log is replaced by the access-log middleware.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True
    # SQL statements may contain personal data: never log them above DEBUG.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
