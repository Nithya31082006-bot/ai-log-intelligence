"""Central configuration and constants (overridable through environment variables)."""
from __future__ import annotations

import os
from pathlib import Path

MAX_UPLOAD_BYTES: int = int(os.getenv("LOGINTEL_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
# Features are held as dense float32 matrices, so keep the row cap modest.
MAX_ROWS: int = int(os.getenv("LOGINTEL_MAX_ROWS", "100000"))
MIN_ROWS_FOR_ANALYSIS: int = 30
MAX_MESSAGE_CHARS: int = 2000
DEFAULT_DB_PATH: Path = Path(os.getenv("LOGINTEL_DB", "data/logintel.db"))

LEVEL_ORDER: dict[str, int] = {"TRACE": 0, "DEBUG": 1, "INFO": 2, "WARN": 3, "ERROR": 4, "FATAL": 5}
LEVEL_ALIASES: dict[str, str] = {
    "WARNING": "WARN", "ERR": "ERROR", "CRITICAL": "FATAL", "CRIT": "FATAL", "SEVERE": "FATAL",
    "NOTICE": "INFO", "FINE": "DEBUG", "VERBOSE": "TRACE", "EMERG": "FATAL", "ALERT": "FATAL",
}
UNKNOWN_LEVEL = "UNKNOWN"
UNKNOWN_SERVICE = "unknown"
