"""Anomaly detectors sharing one interface.

All detectors expose:
  raw_score(X)  -> higher = more anomalous (used for ranking metrics)
  score(X)      -> 0..1 "severity" (empirical CDF of training scores, or probability)
  threshold     -> decision threshold in score() space
  contributions -> transparent per-feature evidence for individual rows
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LogisticRegression

from .exceptions import AnalysisError

Contribution = list[tuple[str, float]]


class BaseDetector(ABC):
    name: str = "base"
    supervised: bool = False
    explanation_method: str = ""

    def __init__(self, contamination: float = 0.05, random_state: int = 42) -> None:
        if not 0.0 < contamination < 0.5:
            raise AnalysisError("contamination must be in (0, 0.5).")
        self.contamination = contamination
        self.random_state = random_state
        self.threshold: float = 1.0 - contamination
        self._train_sorted: np.ndarray | None = None
        self.feature_names: list[str] = []

    @abstractmethod
    def fit(self, X: np.ndarray, y: np.ndarray | None = None, feature_names: list[str] | None = None) -> "BaseDetector": ...

    @abstractmethod
    def raw_score(self, X: np.ndarray) -> np.ndarray: ...

    def score(self, X: np.ndarray) -> np.ndarray:
        if self._train_sorted is None:
            raise AnalysisError("Detector is not fitted.")
        raw = self.raw_score(X)
        return np.searchsorted(self._train_sorted, raw, side="right") / len(self._train_sorted)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.score(X) >= self.threshold

    def contributions(self, X: np.ndarray, top_k: int = 5) -> list[Contribution]:
        return [[] for _ in range(len(X))]

    def _remember_train(self, X: np.ndarray) -> None:
        self._train_sorted = np.sort(self.raw_score(X))

    @staticmethod
    def _top(values: np.ndarray, names: list[str], top_k: int) -> Contribution:
        idx = np.argsort(values)[::-1][:top_k]
        return [(names[i], float(values[i])) for i in idx if values[i] > 0]


class IsolationForestDetector(BaseDetector):
    """Unsupervised. Evidence = standardised positive deviation from the reference mean
    (a transparent heuristic; it is NOT the forest's internal attribution)."""
    name = "isolation_forest"
    explanation_method = "z-score deviation from reference data (heuristic)"

    def fit(self, X, y=None, feature_names=None):
        self.feature_names = feature_names or [f"f{i}" for i in range(X.shape[1])]
        self._model = IsolationForest(n_estimators=200, random_state=self.random_state, n_jobs=1)
        self._model.fit(X)
        self._mean = X.mean(axis=0)
        self._std = np.maximum(X.std(axis=0), 0.05)
        self._remember_train(X)
        return self

    def raw_score(self, X):
        return -self._model.score_samples(X)

    def contributions(self, X, top_k=5):
        z = np.clip((X - self._mean) / self._std, 0, None)
        return [self._top(row, self.feature_names, top_k) for row in z]


class PCAReconstructionDetector(BaseDetector):
    """Unsupervised linear-autoencoder analogue: anomaly = PCA reconstruction error.
    Evidence = exact per-feature decomposition of the squared reconstruction error."""
    name = "pca_reconstruction"
    explanation_method = "per-feature squared reconstruction error (exact decomposition)"

    def fit(self, X, y=None, feature_names=None):
        self.feature_names = feature_names or [f"f{i}" for i in range(X.shape[1])]
        k = max(1, min(15, X.shape[1] - 1, X.shape[0] - 1))
        self._pca = PCA(n_components=k, random_state=self.random_state).fit(X)
        self._remember_train(X)
        return self

    def _residual(self, X: np.ndarray) -> np.ndarray:
        recon = self._pca.inverse_transform(self._pca.transform(X))
        return (X - recon) ** 2

    def raw_score(self, X):
        return self._residual(X).sum(axis=1)

    def contributions(self, X, top_k=5):
        return [self._top(row, self.feature_names, top_k) for row in self._residual(X)]


class LogisticRegressionDetector(BaseDetector):
    """Supervised (needs labels). Evidence = coefficient x feature value (exact additive logit terms)."""
    name = "logistic_regression"
    supervised = True
    explanation_method = "coefficient x feature value (exact additive terms of the logit)"

    def __init__(self, contamination: float = 0.05, random_state: int = 42) -> None:
        super().__init__(contamination, random_state)
        self.threshold = 0.5

    def fit(self, X, y=None, feature_names=None):
        if y is None:
            raise AnalysisError("logistic_regression is supervised and requires labelled training data.")
        y = np.asarray(y).astype(int)
        if len(np.unique(y)) < 2:
            raise AnalysisError("Training data must contain both normal (0) and anomalous (1) labels.")
        self.feature_names = feature_names or [f"f{i}" for i in range(X.shape[1])]
        self._model = LogisticRegression(class_weight="balanced", max_iter=2000, C=1.0, random_state=self.random_state)
        self._model.fit(X, y)
        self._train_sorted = np.sort(self.raw_score(X))
        return self

    def raw_score(self, X):
        return self._model.predict_proba(X)[:, 1]

    def score(self, X):
        return self.raw_score(X)

    def contributions(self, X, top_k=5):
        terms = X * self._model.coef_[0]
        return [self._top(row, self.feature_names, top_k) for row in terms]


class LevelBaselineDetector(BaseDetector):
    """Naive sanity baseline: flag every ERROR/FATAL record."""
    name = "level_baseline"
    explanation_method = "log level >= ERROR"

    def __init__(self, contamination: float = 0.05, random_state: int = 42) -> None:
        super().__init__(contamination, random_state)
        self.threshold = 0.5

    def fit(self, X, y=None, feature_names=None):
        self.feature_names = feature_names or []
        try:
            self._idx = self.feature_names.index("struct:is_error_or_worse")
        except ValueError as exc:
            raise AnalysisError("level_baseline needs the structured level feature.") from exc
        col = X[:, self._idx]
        self._cut = float((col.min() + col.max()) / 2.0) if col.max() > col.min() else float("inf")
        self._train_sorted = np.array([0.0, 1.0])
        return self

    def raw_score(self, X):
        return (X[:, self._idx] > self._cut).astype(float)

    def score(self, X):
        return self.raw_score(X)

    def contributions(self, X, top_k=5):
        return [[("level>=ERROR", 1.0)] if v else [] for v in self.raw_score(X)]


DETECTORS: dict[str, type[BaseDetector]] = {
    cls.name: cls for cls in (IsolationForestDetector, PCAReconstructionDetector,
                              LogisticRegressionDetector, LevelBaselineDetector)
}


def create_detector(name: str, **kwargs) -> BaseDetector:
    if name not in DETECTORS:
        raise AnalysisError(f"Unknown detector '{name}'. Available: {sorted(DETECTORS)}")
    return DETECTORS[name](**kwargs)
