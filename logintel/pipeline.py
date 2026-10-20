"""Fit-and-score pipeline shared by the service layer and the experiment script."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .detectors import BaseDetector, create_detector
from .exceptions import AnalysisError
from .features import FeatureBuilder


@dataclass
class PipelineOutput:
    detector: BaseDetector
    features: FeatureBuilder
    X_train: np.ndarray
    X_all: np.ndarray
    raw: np.ndarray
    score: np.ndarray
    pred: np.ndarray


def run_pipeline(train_df: pd.DataFrame, target_df: pd.DataFrame, detector_name: str,
                 contamination: float = 0.05, normal_only: bool = False,
                 random_state: int = 42) -> PipelineOutput:
    """Fit features+detector on `train_df`, score every row of `target_df`."""
    det = create_detector(detector_name, contamination=contamination, random_state=random_state)
    fb = FeatureBuilder().fit(train_df)
    X_train = fb.transform(train_df)
    X_all = fb.transform(target_df)

    y = None
    labelled = train_df["label"].notna().to_numpy()
    if det.supervised:
        if not labelled.any():
            raise AnalysisError(f"{detector_name} needs labelled training data (a 'label' column).")
        y = train_df["label"].astype("float").to_numpy()
    fit_mask = np.ones(len(train_df), dtype=bool)
    if det.supervised:
        fit_mask = labelled
    elif normal_only:
        if not labelled.any():
            raise AnalysisError("normal_only training requires labels in the training data.")
        fit_mask = labelled & (train_df["label"].astype("float").fillna(-1).to_numpy() == 0)
    if fit_mask.sum() < 10:
        raise AnalysisError("Too few usable training rows (need at least 10).")
    det.fit(X_train[fit_mask], None if y is None else y[fit_mask], fb.feature_names)
    raw = det.raw_score(X_all)
    score = det.score(X_all)
    return PipelineOutput(det, fb, X_train, X_all, raw, score, score >= det.threshold)
