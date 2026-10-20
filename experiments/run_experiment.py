"""Reproducible detector comparison on synthetic logs (no DB, no network).

Protocol: for each seed, generate a labelled log stream; fit on the first 60% (chronological),
evaluate on the last 40%. The test half contains a failure scenario ('disk_full') that never
occurs in the training half. Unsupervised detectors are fit on unlabelled (contaminated) training
data unless marked '(normal-only)'. Results are for SYNTHETIC data only and say nothing about
real-world performance or about the base paper's numbers.

Usage: python experiments/run_experiment.py [--seeds 1 2 3 4 5] [--out results]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logintel.evaluation import evaluate  # noqa: E402
from logintel.pipeline import run_pipeline  # noqa: E402
from logintel.synthetic import generate_logs  # noqa: E402

VARIANTS = [("level_baseline", False), ("isolation_forest", False), ("isolation_forest", True),
            ("pca_reconstruction", False), ("pca_reconstruction", True), ("logistic_regression", False)]
KEYS = ["precision", "recall", "f1", "roc_auc", "pr_auc"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    ap.add_argument("--out", default="results")
    ap.add_argument("--contamination", type=float, default=0.05)
    args = ap.parse_args()

    per_variant: dict[str, dict[str, list[float]]] = {}
    novel_recall: dict[str, list[float]] = {}
    for seed in args.seeds:
        df = generate_logs(seed)
        df["label"] = df["label"].astype("Int64")
        n_train = int(len(df) * 0.6)
        train, test_pos = df.iloc[:n_train].reset_index(drop=True), np.arange(n_train, len(df))
        for det, normal_only in VARIANTS:
            label = f"{det}{' (normal-only)' if normal_only else ''}"
            out = run_pipeline(train, df, det, args.contamination, normal_only)
            y = df["label"].astype(int).to_numpy()
            m = evaluate(y[test_pos], out.pred[test_pos], out.raw[test_pos])
            for k in KEYS:
                if m[k] is not None:
                    per_variant.setdefault(label, {}).setdefault(k, []).append(float(m[k]))  # type: ignore[arg-type]
            mask = (df["scenario"] == "disk_full").to_numpy() & (np.arange(len(df)) >= n_train)
            novel_recall.setdefault(label, []).append(float(out.pred[mask].mean()))

    summary = {lbl: {k: {"mean": float(np.mean(v)), "std": float(np.std(v))} for k, v in d.items()}
               for lbl, d in per_variant.items()}
    for lbl, v in novel_recall.items():
        summary[lbl]["novel_scenario_recall"] = {"mean": float(np.mean(v)), "std": float(np.std(v))}
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "experiment_results.json").write_text(json.dumps(
        {"seeds": args.seeds, "contamination": args.contamination, "summary": summary}, indent=2))

    cols = KEYS + ["novel_scenario_recall"]
    lines = ["| Detector | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for lbl, d in summary.items():
        lines.append(f"| {lbl} | " + " | ".join(f"{d[c]['mean']:.3f} +/- {d[c]['std']:.3f}" if c in d else "n/a" for c in cols) + " |")
    table = "\n".join(lines)
    (out_dir / "experiment_results.md").write_text(
        f"# Synthetic-data detector comparison\n\nSeeds: {args.seeds}; contamination={args.contamination}; "
        f"chronological 60/40 split. Mean +/- std over seeds. **Synthetic data only.**\n\n{table}\n")
    print(table)


if __name__ == "__main__":
    main()
