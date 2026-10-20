"""Feature extraction: TF-IDF over log templates + structured log features."""
from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import StandardScaler

from .config import LEVEL_ORDER
from .exceptions import AnalysisError
from .parsing import normalize_template

STRUCT_NAMES = [
    "level_ord", "is_error_or_worse", "has_timestamp", "log_msg_len", "digit_ratio",
    "log_token_count", "template_rarity", "service_events_per_min", "service_errors_per_min",
]


class FeatureBuilder:
    """Fits on a reference (training) frame, then transforms any frame to a dense float32 matrix.

    Text features: TF-IDF (word 1-2 grams) over masked templates.
    Structured features: level, message shape, template rarity vs. the reference,
    per-service event/error rate in the same minute, and service one-hot indicators.
    Hour-of-day is deliberately NOT used: on short logs it only encodes "when" the
    training window happened and causes spurious novelty alerts.
    """

    def __init__(self, max_features: int = 400) -> None:
        self.max_features = max_features
        self._tfidf: TfidfVectorizer | None = None
        self._scaler: StandardScaler | None = None
        self._services: list[str] = []
        self._template_counts: Counter[str] = Counter()
        self._n_ref = 0
        self.feature_names: list[str] = []

    @property
    def template_counts(self) -> Counter[str]:
        return self._template_counts

    @property
    def n_reference(self) -> int:
        return self._n_ref

    def fit(self, df: pd.DataFrame) -> "FeatureBuilder":
        if df.empty:
            raise AnalysisError("Cannot fit features on an empty frame.")
        templates = self._templates(df)
        self._template_counts = Counter(templates)
        self._n_ref = len(df)
        self._services = sorted(df["service"].astype(str).unique())
        min_df = 2 if len(df) >= 100 else 1
        self._tfidf = TfidfVectorizer(
            lowercase=True, token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z_]+\b", ngram_range=(1, 2),
            max_features=self.max_features, min_df=min_df, sublinear_tf=True,
        )
        try:
            self._tfidf.fit(templates)
        except ValueError as exc:  # empty vocabulary
            raise AnalysisError(f"Could not build a text vocabulary from the messages: {exc}") from exc
        self._scaler = StandardScaler().fit(self._structured(df))
        self.feature_names = (
            [f"tfidf:{t}" for t in self._tfidf.get_feature_names_out()]
            + [f"struct:{n}" for n in STRUCT_NAMES]
            + [f"service={s}" for s in self._services]
        )
        return self

    def transform(self, df: pd.DataFrame) -> np.ndarray:
        if self._tfidf is None or self._scaler is None:
            raise AnalysisError("FeatureBuilder must be fitted before transform().")
        text = self._tfidf.transform(self._templates(df)).toarray().astype(np.float32)
        struct = self._scaler.transform(self._structured(df)).astype(np.float32)
        svc = df["service"].astype(str)
        onehot = np.stack([(svc == s).to_numpy(dtype=np.float32) for s in self._services], axis=1) \
            if self._services else np.zeros((len(df), 0), dtype=np.float32)
        return np.hstack([text, struct, onehot])

    # -- internals ------------------------------------------------------
    @staticmethod
    def _templates(df: pd.DataFrame) -> list[str]:
        return [normalize_template(m).lower() for m in df["message"].astype(str)]

    def _structured(self, df: pd.DataFrame) -> np.ndarray:
        lvl = df["level"].map(LEVEL_ORDER).fillna(2).astype(float).to_numpy()
        msg = df["message"].astype(str)
        length = msg.str.len().clip(lower=1).to_numpy(dtype=float)
        digits = msg.str.count(r"\d").to_numpy(dtype=float)
        tokens = msg.str.split().str.len().fillna(0).to_numpy(dtype=float)
        tpl = pd.Series(self._templates(df), index=df.index)
        counts = tpl.map(lambda t: self._template_counts.get(t, 0)).to_numpy(dtype=float)
        rarity = -np.log((counts + 1.0) / (self._n_ref + 1.0))

        ts = df["timestamp"]
        has_ts = ts.notna().to_numpy(dtype=float)
        rate = np.zeros(len(df))
        err_rate = np.zeros(len(df))
        if ts.notna().any():
            tmp = pd.DataFrame({"svc": df["service"].astype(str).to_numpy(),
                                "bucket": ts.dt.floor("min").to_numpy(),
                                "err": (lvl >= LEVEL_ORDER["ERROR"]).astype(float)})
            grp = tmp.groupby(["svc", "bucket"])["err"]
            rate = grp.transform("size").fillna(0).to_numpy(dtype=float)
            err_rate = grp.transform("sum").fillna(0).to_numpy(dtype=float)
        cols = [lvl, (lvl >= LEVEL_ORDER["ERROR"]).astype(float), has_ts, np.log1p(length),
                digits / length, np.log1p(tokens), rarity, np.log1p(rate), np.log1p(err_rate)]
        return np.stack(cols, axis=1)
