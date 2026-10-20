"""Explainability: feature-level evidence, template rarity and nearest-normal examples."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .parsing import normalize_template
from .pipeline import PipelineOutput


class Explainer:
    """Builds per-finding evidence from a fitted pipeline. Everything shown is either an exact
    decomposition of the model score (logistic/PCA) or a plainly-described heuristic."""

    def __init__(self, out: PipelineOutput, train_df: pd.DataFrame, max_reference: int = 3000, seed: int = 0) -> None:
        self.out = out
        normal = np.where(out.detector.score(out.X_train) < out.detector.threshold)[0]
        if len(normal) == 0:
            normal = np.arange(len(train_df))
        if len(normal) > max_reference:
            normal = np.random.default_rng(seed).choice(normal, max_reference, replace=False)
        self._ref_X = out.X_train[normal]
        norms = np.linalg.norm(self._ref_X, axis=1, keepdims=True)
        self._ref_unit = self._ref_X / np.maximum(norms, 1e-9)
        self._ref_msgs = train_df["message"].astype(str).to_numpy()[normal]

    def explain(self, rows: np.ndarray, df: pd.DataFrame, top_k: int = 5) -> list[dict[str, object]]:
        """`rows` are positional indices into the pipeline's X_all / df."""
        if len(rows) == 0:
            return []
        out = self.out
        X = out.X_all[rows]
        contrib = out.detector.contributions(X, top_k)
        unit = X / np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-9)
        sims = unit @ self._ref_unit.T
        nearest = sims.argmax(axis=1)
        results: list[dict[str, object]] = []
        for k, i in enumerate(rows):
            msg = str(df["message"].iloc[i])
            tpl = normalize_template(msg).lower()
            seen = int(out.features.template_counts.get(tpl, 0))
            ex = {
                "method": out.detector.explanation_method,
                "top_features": [{"feature": n, "contribution": round(v, 4)} for n, v in contrib[k]],
                "template_seen_in_reference": seen,
                "reference_size": out.features.n_reference,
                "nearest_normal_example": {"message": str(self._ref_msgs[nearest[k]]),
                                           "similarity": round(float(sims[k, nearest[k]]), 3)},
            }
            ex["summary"] = self._summary(out.detector.name, float(out.score[i]), ex)
            results.append(ex)
        return results

    @staticmethod
    def _summary(name: str, score: float, ex: dict[str, object]) -> str:
        parts = [f"{name} score {score:.2f}"]
        seen = ex["template_seen_in_reference"]
        parts.append("message pattern never seen in reference data" if seen == 0
                     else f"pattern seen {seen}x in {ex['reference_size']} reference records")
        feats = ex["top_features"]
        if feats:
            parts.append("top evidence: " + ", ".join(f["feature"] for f in feats[:3]))  # type: ignore[index]
        return "; ".join(parts)
