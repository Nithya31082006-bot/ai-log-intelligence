"""Application service: orchestrates ingestion, analysis, history comparison and reporting."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import DEFAULT_DB_PATH, MAX_UPLOAD_BYTES, MIN_ROWS_FOR_ANALYSIS
from .detectors import DETECTORS
from .evaluation import evaluate
from .exceptions import AnalysisError, LogIntelError, ValidationError
from .explain import Explainer
from .incidents import IncidentGrouper
from .logging_setup import get_logger
from .parsing import LogParser, normalize_template
from .pipeline import run_pipeline
from .reporting import build_report
from .storage import Storage

log = get_logger("service")


class AnalysisService:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.storage = Storage(db_path or os.getenv("LOGINTEL_DB", str(DEFAULT_DB_PATH)))
        self.parser = LogParser()

    # -- ingestion ------------------------------------------------------
    def ingest_bytes(self, data: bytes, filename: str = "upload", name: str | None = None) -> dict[str, Any]:
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValidationError(f"File exceeds the {MAX_UPLOAD_BYTES} byte upload limit.")
        result = self.parser.parse_bytes(data, filename)
        df = result.df
        templates = [normalize_template(m) for m in df["message"]]
        sha = hashlib.sha256(data).hexdigest()
        duplicate = [b["id"] for b in self.storage.list_batches() if b["sha256"] == sha]
        warnings = list(result.warnings)
        if duplicate:
            warnings.append(f"Identical content was already uploaded as batch {duplicate[0]}.")
        batch_id = self.storage.create_batch(name or filename, filename, sha, result.source_format, df,
                                             result.n_malformed, warnings, templates)
        return self.storage.get_batch(batch_id)

    # -- analysis -------------------------------------------------------
    def analyze(self, batch_id: int, detector: str = "isolation_forest", contamination: float = 0.05,
                train_batch_id: int | None = None, train_fraction: float = 0.6, normal_only: bool = False,
                gap_seconds: int = 120, max_explained: int = 500,
                min_incident_events: int = 3) -> dict[str, Any]:
        if detector not in DETECTORS:
            raise AnalysisError(f"Unknown detector '{detector}'. Available: {sorted(DETECTORS)}")
        if not 0.1 <= train_fraction <= 0.9:
            raise ValidationError("train_fraction must be between 0.1 and 0.9.")
        if not 0.0 < contamination < 0.5:
            raise ValidationError("contamination must be in (0, 0.5).")
        if gap_seconds < 1:
            raise ValidationError("gap_seconds must be >= 1.")
        if train_batch_id is not None and train_batch_id == batch_id:
            raise ValidationError("train_batch_id must differ from batch_id.")
        self.storage.get_batch(batch_id)
        df = self.storage.get_logs_df(batch_id)
        if len(df) < MIN_ROWS_FOR_ANALYSIS:
            raise ValidationError(f"Need at least {MIN_ROWS_FOR_ANALYSIS} records to analyse; got {len(df)}.")
        params = {"contamination": contamination, "train_fraction": train_fraction, "normal_only": normal_only,
                  "gap_seconds": gap_seconds, "min_incident_events": min_incident_events}
        run_id = self.storage.create_run(batch_id, detector, params, train_batch_id)
        try:
            if train_batch_id is not None:
                self.storage.get_batch(train_batch_id)
                train_df = self.storage.get_logs_df(train_batch_id)
                train_mask = np.zeros(len(df), dtype=bool)
            else:
                order = df.sort_values(["timestamp", "row_idx"], na_position="last").index.to_numpy()
                n_train = max(10, int(len(df) * train_fraction))
                train_mask = np.zeros(len(df), dtype=bool)
                train_mask[order[:n_train]] = True
                train_df = df.loc[order[:n_train]].reset_index(drop=True)
            out = run_pipeline(train_df, df, detector, contamination, normal_only)

            held = (~train_mask) & df["label"].notna().to_numpy()
            metrics = None
            if held.any():
                metrics = evaluate(df["label"].astype(float).to_numpy()[held], out.pred[held], out.raw[held])
                metrics["protocol"] = ("trained on reference batch; all rows evaluated" if train_batch_id is not None
                                       else f"chronological split: first {train_fraction:.0%} fit, rest evaluated")

            flagged = np.where(out.pred)[0]
            flagged = flagged[np.argsort(-out.raw[flagged])]
            explainer = Explainer(out, train_df)
            to_explain = flagged[:max_explained]
            evidence = explainer.explain(to_explain, df)
            ev_by_pos = dict(zip(to_explain.tolist(), evidence))
            rows = [(int(df["log_id"].iloc[i]), float(out.raw[i]), float(out.score[i]), bool(train_mask[i]),
                     ev_by_pos.get(int(i), {"summary": "Evidence omitted (beyond max_explained cap)."}))
                    for i in flagged]
            self.storage.save_findings(run_id, rows)

            fl = df.iloc[flagged][["timestamp", "service", "level", "message", "template"]].copy()
            fl["score"] = out.score[flagged]
            incidents = [i.to_dict() for i in IncidentGrouper(gap_seconds, gap_seconds, min_incident_events).group(fl)]
            self.storage.save_incidents(run_id, incidents)
            self.storage.finish_run(run_id, n_train=len(train_df), n_scored=len(df), n_anomalies=len(flagged),
                                    threshold=float(out.detector.threshold), metrics=metrics)
            log.info("run completed", extra={"run_id": run_id, "detector": detector, "anomalies": int(len(flagged))})
        except LogIntelError as exc:
            self.storage.fail_run(run_id, str(exc))
            raise
        except Exception as exc:  # noqa: BLE001 - convert unexpected failures into a clean domain error
            log.exception("analysis failed", extra={"run_id": run_id})
            self.storage.fail_run(run_id, repr(exc))
            raise AnalysisError(f"Unexpected analysis failure: {exc}") from exc
        return self.storage.get_run(run_id)

    def compare_detectors(self, batch_id: int, detectors: list[str] | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        """Run several detectors on the same batch with the same protocol; failures are reported per detector."""
        results: list[dict[str, Any]] = []
        for name in detectors or list(DETECTORS):
            try:
                results.append(self.analyze(batch_id, detector=name, **kwargs))
            except LogIntelError as exc:
                results.append({"detector": name, "status": "failed", "error": str(exc)})
        return results

    # -- history --------------------------------------------------------
    def history_comparison(self, run_id: int) -> dict[str, Any]:
        run = self.storage.get_run(run_id)
        prior = self.storage.prior_runs(run_id, run["detector"])
        cur_rate = (run["n_anomalies"] or 0) / max(run["n_scored"] or 1, 1)
        cur_tpl = self.storage.flagged_templates(run_id)
        seen: dict[str, int] = {}
        for p in prior:
            for t in self.storage.flagged_templates(p["id"]):
                seen[t] = seen.get(t, 0) + 1
        cur_sigs = self.storage.incident_signatures(run_id)
        sig_seen: dict[str, int] = {}
        for p in prior:
            for s in self.storage.incident_signatures(p["id"]):
                sig_seen[s] = sig_seen.get(s, 0) + 1
        prior_rows = [{"run_id": p["id"], "batch_id": p["batch_id"], "anomaly_rate": (p["n_anomalies"] or 0) / max(p["n_scored"] or 1, 1),
                       "f1": (p["metrics"] or {}).get("f1")} for p in prior]
        mean_rate = float(np.mean([r["anomaly_rate"] for r in prior_rows])) if prior_rows else None
        return {
            "run_id": run_id, "detector": run["detector"], "n_prior_runs": len(prior),
            "current_anomaly_rate": cur_rate, "prior_mean_anomaly_rate": mean_rate,
            "rate_delta": None if mean_rate is None else cur_rate - mean_rate, "prior_runs": prior_rows,
            "new_patterns": sorted([{"template": t, "count": n} for t, n in cur_tpl.items() if t not in seen],
                                   key=lambda d: -d["count"]),
            "recurring_patterns": sorted([{"template": t, "count": n, "seen_in_prior_runs": seen[t]}
                                          for t, n in cur_tpl.items() if t in seen], key=lambda d: -d["count"]),
            "recurring_incident_signatures": sorted([{"signature": s, "seen_in_prior_runs": sig_seen[s]}
                                                     for s in cur_sigs if s in sig_seen], key=lambda d: -d["seen_in_prior_runs"]),
            "note": "Comparison is between runs of the same detector; different batches may not be comparable.",
        }

    # -- reporting ------------------------------------------------------
    def report(self, run_id: int, fmt: str = "json") -> tuple[str, str]:
        """Return (content, media_type)."""
        run = self.storage.get_run(run_id)
        findings = self.storage.get_findings(run_id, limit=1000)
        incidents = self.storage.get_incidents(run_id)
        history = self.history_comparison(run_id)
        return build_report(run, self.storage.get_batch(run["batch_id"]), findings, incidents, history, fmt)
