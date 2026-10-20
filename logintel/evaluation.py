"""Evaluation metrics for labelled data (never fabricated: returns None when undefined)."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, precision_recall_fscore_support, roc_auc_score


def evaluate(y_true: np.ndarray, y_pred: np.ndarray, raw_score: np.ndarray) -> dict[str, object]:
    y_true = np.asarray(y_true).astype(int)
    y_pred = np.asarray(y_pred).astype(int)
    n = int(len(y_true))
    tp = int(((y_true == 1) & (y_pred == 1)).sum())
    fp = int(((y_true == 0) & (y_pred == 1)).sum())
    fn = int(((y_true == 1) & (y_pred == 0)).sum())
    tn = int(((y_true == 0) & (y_pred == 0)).sum())
    p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", pos_label=1, zero_division=0) \
        if n else (0.0, 0.0, 0.0, None)
    both = len(np.unique(y_true)) == 2
    return {
        "n_evaluated": n, "n_positive": int(y_true.sum()),
        "precision": float(p), "recall": float(r), "f1": float(f1),
        "roc_auc": float(roc_auc_score(y_true, raw_score)) if both else None,
        "pr_auc": float(average_precision_score(y_true, raw_score)) if both else None,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
    }
