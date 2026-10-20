"""Ingestion: CSV and plain-text log parsing, normalisation and template extraction."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pandas as pd

from .config import (LEVEL_ALIASES, LEVEL_ORDER, MAX_MESSAGE_CHARS, MAX_ROWS, UNKNOWN_LEVEL,
                     UNKNOWN_SERVICE)
from .exceptions import ValidationError
from .logging_setup import get_logger

log = get_logger("parsing")

COLUMNS = ["timestamp", "level", "service", "message", "label"]

_ALIASES: dict[str, list[str]] = {
    "timestamp": ["timestamp", "time", "ts", "@timestamp", "datetime", "date", "asctime", "log_time"],
    "level": ["level", "severity", "loglevel", "log_level", "lvl"],
    "service": ["service", "component", "app", "application", "logger", "source", "module", "service_name"],
    "message": ["message", "msg", "log", "text", "event", "content", "body"],
    "label": ["label", "is_anomaly", "anomaly", "ground_truth", "y"],
}
_TRUE = {"1", "true", "yes", "y", "anomaly", "anomalous", "abnormal"}
_FALSE = {"0", "false", "no", "n", "normal"}

_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")
_HEX = re.compile(r"\b0x[0-9a-fA-F]+\b")
_ID = re.compile(r"\b[A-Za-z]+[_\-]\d+\b")
_NUM = re.compile(r"(?<![A-Za-z_])-?\d+(?:\.\d+)?")
_WS = re.compile(r"\s+")

_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s+"
    r"(?P<level>TRACE|DEBUG|INFO|NOTICE|WARNING|WARN|ERROR|ERR|FATAL|CRITICAL|SEVERE)\b:?\s*"
    r"(?:\[(?P<service>[^\]]{1,64})\]\s*)?(?P<msg>.*)$",
    re.IGNORECASE,
)
_SVC_IN_MSG = re.compile(r"\b(?:service|svc|app)=([\w.\-]+)")
_CONTINUATION = re.compile(r"^(\s+|Traceback|Caused by|at\s)")


def normalize_template(message: str) -> str:
    """Mask variable parts (UUIDs, IPs, hex, ids, numbers) to obtain a log template."""
    text = _UUID.sub("<UUID>", message)
    text = _IP.sub("<IP>", text)
    text = _HEX.sub("<HEX>", text)
    text = _ID.sub("<ID>", text)
    text = _NUM.sub("<NUM>", text)
    return _WS.sub(" ", text).strip()


def normalize_level(raw: str | None) -> str:
    if raw is None:
        return UNKNOWN_LEVEL
    up = str(raw).strip().upper()
    up = LEVEL_ALIASES.get(up, up)
    return up if up in LEVEL_ORDER else UNKNOWN_LEVEL


def _parse_timestamps(series: pd.Series) -> pd.Series:
    """Parse mixed timestamps/epochs to tz-aware UTC; unparsable values become NaT."""
    as_str = series.astype("object").map(lambda v: None if v is None or str(v).strip() == "" else str(v).strip())
    numeric = pd.to_numeric(as_str, errors="coerce")
    if len(as_str) and numeric.notna().mean() > 0.9:
        unit = "ms" if float(numeric.dropna().median()) > 1e11 else "s"
        return pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
    for fmt in ("ISO8601", "mixed"):
        try:
            out = pd.to_datetime(as_str, format=fmt, utc=True, errors="coerce")
        except (ValueError, TypeError):
            continue
        if fmt == "mixed" or out.notna().mean() >= 0.5:
            return out
    return pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns, UTC]")


def _parse_label(series: pd.Series) -> pd.Series:
    low = series.astype(str).str.strip().str.lower()
    out = pd.Series(pd.NA, index=series.index, dtype="Int64")
    out[low.isin(_TRUE)] = 1
    out[low.isin(_FALSE)] = 0
    return out


@dataclass
class ParseResult:
    df: pd.DataFrame
    source_format: str
    n_input_lines: int
    n_malformed: int = 0
    warnings: list[str] = field(default_factory=list)


class LogParser:
    """Parses CSV or plain-text logs into a normalised DataFrame with COLUMNS."""

    def __init__(self, max_rows: int = MAX_ROWS) -> None:
        self.max_rows = max_rows

    # -- public ---------------------------------------------------------
    def parse_bytes(self, data: bytes, filename: str = "") -> ParseResult:
        if not data or not data.strip():
            raise ValidationError("Uploaded file is empty.")
        text = data.decode("utf-8", errors="replace")
        fmt = self._detect_format(text, filename)
        result = self.parse_csv(text) if fmt == "csv" else self.parse_text(text)
        if len(result.df) == 0:
            raise ValidationError("No log records could be parsed from the input.")
        if len(result.df) > self.max_rows:
            raise ValidationError(f"Input has {len(result.df)} records; the limit is {self.max_rows}.")
        log.info("parsed input", extra={"format": fmt, "rows": len(result.df), "malformed": result.n_malformed})
        return result

    def parse_csv(self, text: str) -> ParseResult:
        try:
            raw = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, on_bad_lines="skip")
        except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            raise ValidationError(f"Invalid CSV: {exc}") from exc
        lowered = {c.strip().lower(): c for c in raw.columns}
        mapping: dict[str, str] = {}
        for target, names in _ALIASES.items():
            for name in names:
                if name in lowered:
                    mapping[target] = lowered[name]
                    break
        if "message" not in mapping:
            raise ValidationError(
                "CSV needs a message column (accepted names: " + ", ".join(_ALIASES["message"]) + ")."
            )
        warnings: list[str] = []
        n_in = len(raw)
        df = pd.DataFrame(index=raw.index)
        df["message"] = raw[mapping["message"]].astype(str).str.strip()
        if "timestamp" in mapping:
            df["timestamp"] = _parse_timestamps(raw[mapping["timestamp"]])
            if df["timestamp"].isna().mean() > 0.2:
                warnings.append(f"{df['timestamp'].isna().mean():.0%} of timestamps could not be parsed.")
        else:
            df["timestamp"] = pd.Series(pd.NaT, index=raw.index, dtype="datetime64[ns, UTC]")
            warnings.append("No timestamp column found; time-based features and incident grouping are disabled.")
        df["level"] = (raw[mapping["level"]].map(normalize_level) if "level" in mapping else UNKNOWN_LEVEL)
        if "service" in mapping:
            svc = raw[mapping["service"]].astype(str).str.strip()
            df["service"] = svc.where(svc != "", UNKNOWN_SERVICE)
        else:
            df["service"] = self._service_from_message(df["message"])
        df["label"] = (_parse_label(raw[mapping["label"]]) if "label" in mapping
                       else pd.Series(pd.NA, index=raw.index, dtype="Int64"))
        df = self._finalise(df)
        return ParseResult(df, "csv", n_in, n_malformed=n_in - len(df), warnings=warnings)

    def parse_text(self, text: str) -> ParseResult:
        rows: list[dict[str, object]] = []
        malformed = 0
        lines = [ln.rstrip("\r") for ln in text.split("\n") if ln.strip()]
        for line in lines:
            m = _LINE.match(line)
            if m:
                msg = m.group("msg").strip()
                svc = m.group("service")
                if not svc:
                    s2 = _SVC_IN_MSG.search(msg)
                    svc = s2.group(1) if s2 else UNKNOWN_SERVICE
                rows.append({"timestamp": m.group("ts").replace(",", "."), "level": normalize_level(m.group("level")),
                             "service": svc.strip(), "message": msg})
            elif rows and _CONTINUATION.match(line):
                rows[-1]["message"] = (str(rows[-1]["message"]) + " | " + line.strip())[:MAX_MESSAGE_CHARS]
            else:
                malformed += 1
        if lines and malformed / len(lines) > 0.5:
            raise ValidationError(
                "More than half of the lines did not match a supported format "
                "('<ISO timestamp> <LEVEL> [service] message')."
            )
        if not rows:
            raise ValidationError("No log records could be parsed from the input.")
        df = pd.DataFrame(rows)
        df["timestamp"] = _parse_timestamps(df["timestamp"])
        df["label"] = pd.Series(pd.NA, index=df.index, dtype="Int64")
        df = self._finalise(df)
        warnings = [f"{malformed} malformed line(s) skipped."] if malformed else []
        return ParseResult(df, "text", len(lines), n_malformed=malformed, warnings=warnings)

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _detect_format(text: str, filename: str) -> str:
        name = filename.lower()
        if name.endswith(".csv"):
            return "csv"
        if name.endswith((".log", ".txt")):
            return "text"
        first = text.lstrip().split("\n", 1)[0].lower()
        if "," in first and any(a in first for a in _ALIASES["message"]):
            return "csv"
        return "text"

    @staticmethod
    def _service_from_message(messages: pd.Series) -> pd.Series:
        found = messages.str.extract(_SVC_IN_MSG.pattern, expand=False)
        return found.fillna(UNKNOWN_SERVICE)

    @staticmethod
    def _finalise(df: pd.DataFrame) -> pd.DataFrame:
        df = df[df["message"].str.len() > 0].copy()
        df["message"] = df["message"].str.slice(0, MAX_MESSAGE_CHARS)
        df = df.reset_index(drop=True)
        return df[COLUMNS]
