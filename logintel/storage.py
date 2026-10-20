"""SQLite persistence for batches, logs, analysis runs, findings and incidents."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from .exceptions import NotFoundError
from .logging_setup import get_logger

log = get_logger("storage")

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, filename TEXT, sha256 TEXT NOT NULL,
  source_format TEXT NOT NULL, n_rows INTEGER NOT NULL, n_malformed INTEGER NOT NULL DEFAULT 0,
  has_labels INTEGER NOT NULL DEFAULT 0, t_min TEXT, t_max TEXT, warnings TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
  row_idx INTEGER NOT NULL, ts TEXT, level TEXT NOT NULL, service TEXT NOT NULL, message TEXT NOT NULL,
  template TEXT NOT NULL, label INTEGER);
CREATE INDEX IF NOT EXISTS idx_logs_batch ON logs(batch_id, row_idx);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, detector TEXT NOT NULL, params TEXT NOT NULL, train_batch_id INTEGER,
  n_train INTEGER, n_scored INTEGER, n_anomalies INTEGER, threshold REAL, metrics TEXT,
  status TEXT NOT NULL, error TEXT);
CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  log_id INTEGER NOT NULL REFERENCES logs(id) ON DELETE CASCADE, raw_score REAL, score REAL,
  in_training INTEGER NOT NULL DEFAULT 0, evidence TEXT);
CREATE INDEX IF NOT EXISTS idx_findings_run ON findings(run_id, score);
CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  group_id INTEGER NOT NULL, rank_in_group INTEGER NOT NULL, service TEXT NOT NULL, start_ts TEXT, end_ts TEXT,
  n_events INTEGER, category TEXT, signature TEXT, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_incidents_run ON incidents(run_id, group_id, rank_in_group);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso(v: Any) -> str | None:
    return None if v is None or pd.isna(v) else pd.Timestamp(v).isoformat()


class Storage:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._memory_conn: sqlite3.Connection | None = None
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        if str(self.db_path) == ":memory:":
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._memory_conn.row_factory = sqlite3.Row
                self._memory_conn.execute("PRAGMA foreign_keys=ON")
            conn = self._memory_conn
        else:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if conn is not self._memory_conn:
                conn.close()

    # -- batches --------------------------------------------------------
    def create_batch(self, name: str, filename: str, sha256: str, source_format: str, df: pd.DataFrame,
                     n_malformed: int, warnings: list[str], templates: list[str]) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO batches(name, filename, sha256, source_format, n_rows, n_malformed, has_labels,"
                " t_min, t_max, warnings, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (name, filename, sha256, source_format, len(df), n_malformed, int(df["label"].notna().any()),
                 _iso(df["timestamp"].min()), _iso(df["timestamp"].max()), json.dumps(warnings), _now()))
            batch_id = int(cur.lastrowid)
            c.executemany(
                "INSERT INTO logs(batch_id,row_idx,ts,level,service,message,template,label) VALUES (?,?,?,?,?,?,?,?)",
                [(batch_id, i, _iso(r.timestamp), r.level, r.service, r.message, templates[i],
                  None if pd.isna(r.label) else int(r.label)) for i, r in enumerate(df.itertuples(index=False))])
        log.info("batch stored", extra={"batch_id": batch_id, "rows": len(df)})
        return batch_id

    def get_batch(self, batch_id: int) -> dict[str, Any]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Batch {batch_id} not found.")
        d = dict(row)
        d["warnings"] = json.loads(d["warnings"] or "[]")
        d["has_labels"] = bool(d["has_labels"])
        return d

    def list_batches(self) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM batches ORDER BY id DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["warnings"] = json.loads(d["warnings"] or "[]")
            d["has_labels"] = bool(d["has_labels"])
            out.append(d)
        return out

    def get_logs_df(self, batch_id: int) -> pd.DataFrame:
        with self._conn() as c:
            rows = c.execute("SELECT id, row_idx, ts, level, service, message, template, label FROM logs "
                             "WHERE batch_id=? ORDER BY row_idx", (batch_id,)).fetchall()
        df = pd.DataFrame([tuple(r) for r in rows],
                          columns=["log_id", "row_idx", "ts", "level", "service", "message", "template", "label"])
        df["timestamp"] = pd.to_datetime(df["ts"], utc=True, errors="coerce", format="ISO8601")
        df["label"] = df["label"].astype("Int64")
        return df.drop(columns=["ts"])

    # -- runs -----------------------------------------------------------
    def create_run(self, batch_id: int, detector: str, params: dict[str, Any], train_batch_id: int | None) -> int:
        with self._conn() as c:
            cur = c.execute("INSERT INTO runs(batch_id, created_at, detector, params, train_batch_id, status)"
                            " VALUES (?,?,?,?,?, 'running')",
                            (batch_id, _now(), detector, json.dumps(params), train_batch_id))
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, *, n_train: int, n_scored: int, n_anomalies: int, threshold: float,
                   metrics: dict[str, Any] | None) -> None:
        with self._conn() as c:
            c.execute("UPDATE runs SET status='completed', n_train=?, n_scored=?, n_anomalies=?, threshold=?, metrics=?"
                      " WHERE id=?", (n_train, n_scored, n_anomalies, threshold, json.dumps(metrics), run_id))

    def fail_run(self, run_id: int, error: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE runs SET status='failed', error=? WHERE id=?", (error[:1000], run_id))

    def get_run(self, run_id: int) -> dict[str, Any]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Run {run_id} not found.")
        return self._run_dict(row)

    def list_runs(self, batch_id: int | None = None) -> list[dict[str, Any]]:
        with self._conn() as c:
            if batch_id is None:
                rows = c.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
            else:
                rows = c.execute("SELECT * FROM runs WHERE batch_id=? ORDER BY id DESC", (batch_id,)).fetchall()
        return [self._run_dict(r) for r in rows]

    @staticmethod
    def _run_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["params"] = json.loads(d["params"] or "{}")
        d["metrics"] = json.loads(d["metrics"]) if d["metrics"] else None
        return d

    # -- findings / incidents -------------------------------------------
    def save_findings(self, run_id: int, rows: list[tuple[int, float, float, bool, dict[str, Any]]]) -> None:
        with self._conn() as c:
            c.executemany("INSERT INTO findings(run_id, log_id, raw_score, score, in_training, evidence) VALUES (?,?,?,?,?,?)",
                          [(run_id, lid, raw, sc, int(tr), json.dumps(ev)) for lid, raw, sc, tr, ev in rows])

    def get_findings(self, run_id: int, service: str | None = None, level: str | None = None,
                     min_score: float | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        q = ("SELECT f.id AS finding_id, f.log_id, f.raw_score, f.score, f.in_training, f.evidence, l.ts, l.level,"
             " l.service, l.message, l.template, l.label FROM findings f JOIN logs l ON l.id=f.log_id WHERE f.run_id=?")
        args: list[Any] = [run_id]
        if service:
            q += " AND l.service=?"; args.append(service)
        if level:
            q += " AND l.level=?"; args.append(level.upper())
        if min_score is not None:
            q += " AND f.score>=?"; args.append(min_score)
        q += " ORDER BY f.raw_score DESC, f.id LIMIT ? OFFSET ?"
        args += [limit, offset]
        with self._conn() as c:
            rows = c.execute(q, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["evidence"] = json.loads(d["evidence"] or "{}")
            d["in_training"] = bool(d["in_training"])
            out.append(d)
        return out

    def count_findings(self, run_id: int) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM findings WHERE run_id=?", (run_id,)).fetchone()[0])

    def save_incidents(self, run_id: int, incidents: list[dict[str, Any]]) -> None:
        with self._conn() as c:
            c.executemany(
                "INSERT INTO incidents(run_id, group_id, rank_in_group, service, start_ts, end_ts, n_events, category,"
                " signature, payload) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(run_id, i["group_id"], i["rank_in_group"], i["service"], i["start"], i["end"], i["n_events"],
                  i["category"], i["signature"], json.dumps(i)) for i in incidents])

    def get_incidents(self, run_id: int) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT payload FROM incidents WHERE run_id=? ORDER BY group_id, rank_in_group",
                             (run_id,)).fetchall()
        return [json.loads(r["payload"]) for r in rows]

    # -- history --------------------------------------------------------
    def prior_runs(self, run_id: int, detector: str) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM runs WHERE id<? AND detector=? AND status='completed' ORDER BY id",
                             (run_id, detector)).fetchall()
        return [self._run_dict(r) for r in rows]

    def flagged_templates(self, run_id: int) -> dict[str, int]:
        with self._conn() as c:
            rows = c.execute("SELECT l.template, COUNT(*) AS n FROM findings f JOIN logs l ON l.id=f.log_id "
                             "WHERE f.run_id=? GROUP BY l.template", (run_id,)).fetchall()
        return {r["template"]: int(r["n"]) for r in rows}

    def incident_signatures(self, run_id: int) -> set[str]:
        with self._conn() as c:
            rows = c.execute("SELECT DISTINCT signature FROM incidents WHERE run_id=?", (run_id,)).fetchall()
        return {r["signature"] for r in rows}
