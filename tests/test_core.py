import unittest

import numpy as np
import pandas as pd

from logintel.detectors import PCAReconstructionDetector, create_detector
from logintel.evaluation import evaluate
from logintel.exceptions import AnalysisError
from logintel.features import FeatureBuilder
from logintel.incidents import IncidentGrouper, infer_category
from logintel.pipeline import run_pipeline
from logintel.synthetic import generate_logs, to_csv


def _frame(seed=1, minutes=60):
    df = generate_logs(seed, minutes=minutes)
    df["label"] = df["label"].astype("Int64")
    return df


class TestSynthetic(unittest.TestCase):
    def test_reproducible(self):
        a, b, c = generate_logs(3, minutes=30), generate_logs(3, minutes=30), generate_logs(4, minutes=30)
        pd.testing.assert_frame_equal(a, b)
        self.assertFalse(a.equals(c))

    def test_has_both_classes_and_csv_roundtrip(self):
        df = generate_logs(1, minutes=60)
        self.assertTrue(set(df["label"]) == {0, 1})
        self.assertIn("timestamp,level,service,message,label", to_csv(df))


class TestFeatures(unittest.TestCase):
    def test_shape_names_and_unseen_service(self):
        df = _frame()
        fb = FeatureBuilder().fit(df)
        X = fb.transform(df)
        self.assertEqual(X.shape, (len(df), len(fb.feature_names)))
        self.assertEqual(X.dtype, np.float32)
        other = df.head(5).copy()
        other["service"] = "brand_new_service"
        X2 = fb.transform(other)
        self.assertEqual(X2.shape[1], X.shape[1])
        self.assertTrue((X2[:, -5:] == 0).all())  # all service one-hots are zero

    def test_unseen_template_has_higher_rarity(self):
        df = _frame()
        fb = FeatureBuilder().fit(df)
        probe = df.head(2).copy()
        probe.loc[probe.index[1], "message"] = "completely novel kernel panic zzz"
        X = fb.transform(probe)
        i = fb.feature_names.index("struct:template_rarity")
        self.assertGreater(X[1, i], X[0, i])


class TestDetectors(unittest.TestCase):
    def setUp(self):
        self.df = _frame(minutes=120)
        n = int(len(self.df) * 0.6)
        self.train = self.df.iloc[:n].reset_index(drop=True)

    def test_all_detectors_run_and_return_valid_shapes(self):
        for name in ("isolation_forest", "pca_reconstruction", "logistic_regression", "level_baseline"):
            out = run_pipeline(self.train, self.df, name)
            self.assertEqual(out.raw.shape, (len(self.df),), name)
            self.assertTrue(((out.score >= 0) & (out.score <= 1)).all(), name)

    def test_supervised_requires_labels(self):
        unl = self.train.copy()
        unl["label"] = pd.array([pd.NA] * len(unl), dtype="Int64")
        with self.assertRaises(AnalysisError):
            run_pipeline(unl, self.df, "logistic_regression")

    def test_supervised_requires_both_classes(self):
        one = self.train[self.train["label"] == 0].reset_index(drop=True)
        with self.assertRaises(AnalysisError):
            run_pipeline(one, self.df, "logistic_regression")

    def test_unknown_detector(self):
        with self.assertRaises(AnalysisError):
            create_detector("nope")

    def test_bad_contamination(self):
        with self.assertRaises(AnalysisError):
            create_detector("isolation_forest", contamination=0.9)

    def test_pca_contributions_sum_to_raw_score(self):
        fb = FeatureBuilder().fit(self.train)
        X = fb.transform(self.train)
        det = PCAReconstructionDetector().fit(X, None, fb.feature_names)
        raw = det.raw_score(X[:20])
        k = len(fb.feature_names)
        contrib = det.contributions(X[:20], top_k=k)
        sums = np.array([sum(v for _, v in c) for c in contrib])
        np.testing.assert_allclose(sums, raw, rtol=1e-3, atol=1e-3)

    def test_logreg_beats_chance_on_synthetic(self):
        out = run_pipeline(self.train, self.df, "logistic_regression")
        y = self.df["label"].astype(int).to_numpy()
        n = len(self.train)
        m = evaluate(y[n:], out.pred[n:], out.raw[n:])
        self.assertGreater(m["roc_auc"], 0.9)


class TestEvaluation(unittest.TestCase):
    def test_known_values(self):
        m = evaluate(np.array([1, 1, 0, 0]), np.array([1, 0, 1, 0]), np.array([0.9, 0.4, 0.6, 0.1]))
        self.assertAlmostEqual(m["precision"], 0.5)
        self.assertAlmostEqual(m["recall"], 0.5)
        self.assertEqual(m["confusion"], {"tp": 1, "fp": 1, "fn": 1, "tn": 1})
        self.assertAlmostEqual(m["roc_auc"], 0.75)

    def test_single_class_gives_none_not_fabricated(self):
        m = evaluate(np.array([0, 0, 0]), np.array([0, 1, 0]), np.array([0.1, 0.9, 0.2]))
        self.assertIsNone(m["roc_auc"])
        self.assertIsNone(m["pr_auc"])


class TestIncidents(unittest.TestCase):
    def _flagged(self):
        t = pd.Timestamp("2024-01-01T00:00:00Z")
        rows = []
        for s in range(0, 60, 10):
            rows.append((t + pd.Timedelta(seconds=s), "db", "ERROR", "connection pool exhausted active=1", "connection pool exhausted active=<NUM>", 0.99))
        for s in range(60, 120, 10):
            rows.append((t + pd.Timedelta(seconds=s), "payment", "ERROR", "timeout calling db", "timeout calling db", 0.97))
        for k in range(3):
            rows.append((t + pd.Timedelta(hours=3, seconds=10 * k), "auth", "WARN", "failed login for user admin", "failed login for user admin", 0.96))
        return pd.DataFrame(rows, columns=["timestamp", "service", "level", "message", "template", "score"])

    def test_groups_and_origin_ranking(self):
        inc = IncidentGrouper(gap_seconds=60, group_gap_seconds=60).group(self._flagged())
        self.assertEqual(len({i.group_id for i in inc}), 2)
        g1 = [i for i in inc if i.group_id == 1]
        self.assertEqual([i.service for i in sorted(g1, key=lambda i: i.rank_in_group)], ["db", "payment"])
        self.assertEqual(g1[0].category, "database")
        self.assertIn("Candidate origin", g1[0].hypothesis)
        self.assertIn("downstream", g1[1].hypothesis)

    def test_empty_and_undated(self):
        self.assertEqual(IncidentGrouper().group(self._flagged().iloc[0:0]), [])
        undated = self._flagged()
        undated["timestamp"] = pd.NaT
        self.assertEqual(IncidentGrouper().group(undated), [])

    def test_isolated_alerts_are_not_incidents(self):
        t = pd.Timestamp("2024-01-01T00:00:00Z")
        rows = [(t + pd.Timedelta(minutes=10 * i), "svc", "ERROR", "m", "m", 0.99) for i in range(5)]
        df = pd.DataFrame(rows, columns=["timestamp", "service", "level", "message", "template", "score"])
        self.assertEqual(IncidentGrouper(gap_seconds=60).group(df), [])
        self.assertEqual(len(IncidentGrouper(gap_seconds=60, min_events=1).group(df)), 5)

    def test_category(self):
        self.assertEqual(infer_category(["no space left on device"]), "resource/disk")
        self.assertEqual(infer_category(["all fine"]), "unclassified")


if __name__ == "__main__":
    unittest.main()
