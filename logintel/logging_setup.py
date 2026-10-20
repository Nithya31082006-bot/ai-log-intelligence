"""Structured (JSON) logging."""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}
_CONFIGURED = False


class JsonFormatter(logging.Formatter):
    """One JSON object per line; extra= fields are included as top-level keys."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str | None = None) -> None:
    """Idempotently install the JSON handler on the 'logintel' logger."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logger = logging.getLogger("logintel")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel((level or os.getenv("LOGINTEL_LOG_LEVEL", "INFO")).upper())
    logger.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(f"logintel.{name}")
