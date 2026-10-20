"""Downloadable reports (JSON / CSV / Markdown)."""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from .exceptions import ValidationError


def build_report(run: dict[str, Any], batch: dict[str, Any], findings: list[dict[str, Any]],
                 incidents: list[dict[str, Any]], history: dict[str, Any], fmt: str) -> tuple[str, str]:
    fmt = fmt.lower()
    if fmt == "json":
        return json.dumps({"run": run, "batch": batch, "incidents": incidents, "findings": findings,
                           "history": history}, indent=2, default=str), "application/json"
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["log_id", "timestamp", "level", "service", "score", "raw_score", "label", "message", "summary"])
        for f in findings:
            w.writerow([f["log_id"], f["ts"], f["level"], f["service"], round(f["score"], 4), round(f["raw_score"], 4),
                        f["label"], f["message"], f["evidence"].get("summary", "")])
        return buf.getvalue(), "text/csv"
    if fmt in ("md", "markdown"):
        return _markdown(run, batch, findings, incidents, history), "text/markdown"
    raise ValidationError("format must be one of: json, csv, md")


def _markdown(run, batch, findings, incidents, history) -> str:
    L = [f"# Log analysis report - run {run['id']}", "",
         f"- Batch: {batch['id']} ({batch['name']}), {batch['n_rows']} records, format {batch['source_format']}",
         f"- Detector: `{run['detector']}`; params: `{json.dumps(run['params'])}`",
         f"- Scored: {run['n_scored']}; trained on: {run['n_train']}; anomalies flagged: {run['n_anomalies']}", ""]
    m = run.get("metrics")
    L.append("## Evaluation")
    if m:
        L += [f"Protocol: {m.get('protocol')}.", "",
              "| precision | recall | F1 | ROC-AUC | PR-AUC | n evaluated | n positive |", "|---|---|---|---|---|---|---|",
              "| {} | {} | {} | {} | {} | {} | {} |".format(
                  *(f"{m[k]:.3f}" if m.get(k) is not None else "n/a" for k in ("precision", "recall", "f1", "roc_auc", "pr_auc")),
                  m["n_evaluated"], m["n_positive"])]
    else:
        L.append("No ground-truth labels were available on held-out rows; no metrics computed.")
    L += ["", "## Incidents (heuristic root-cause hints)"]
    if not incidents:
        L.append("None.")
    for i in incidents:
        L.append(f"- **Group {i['group_id']} / rank {i['rank_in_group']}** `{i['service']}` {i['start']} -> {i['end']} "
                 f"({i['n_events']} events, {i['category']}): {i['hypothesis']}")
    L += ["", "## Top findings"]
    for f in findings[:25]:
        L.append(f"- [{f['level']}] `{f['service']}` {f['ts']} score={f['score']:.2f}: {f['message']}  \n  _{f['evidence'].get('summary', '')}_")
    L += ["", "## History comparison",
          f"- Prior runs of this detector: {history['n_prior_runs']}",
          f"- New anomalous patterns vs history: {len(history['new_patterns'])}; recurring: {len(history['recurring_patterns'])}", ""]
    return "\n".join(L)
