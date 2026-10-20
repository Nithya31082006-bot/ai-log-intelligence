import json
import tempfile
import unittest
from pathlib import Path

from logintel.exceptions import AnalysisError, NotFoundError, ValidationError
from logintel.service import AnalysisService
from logintel.synthetic import generate_logs, to_csv, to_text


class TestService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.svc = AnalysisService(Path(cls.tmp.name) / "t.db")
        cls.csv1 = to_csv(generate_logs(1, minutes=120)).encode()
        cls.csv2 = to_csv(generate_logs(2, minutes=120)).encode()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_01_ingest_and_analyze_with_metrics(self):
        b = self.svc.ingest_bytes(self.csv1, "b1.csv", "first")
        self.assertTrue(b["has_labels"])
        run = self.svc.analyze(b["id"], "pca_reconstruction")
        self.assertEqual(run["status"], "completed")
        self.assertIsNotNone(run["metrics"])
        self.assertIn("chronological", run["metrics"]["protocol"])
        findings = self.svc.storage.get_findings(run["id"], limit=5)
        self.assertTrue(findings)
        self.assertIn("top_features", findings[0]["evidence"])
        self.assertEqual(self.svc.storage.count_findings(run["id"]), run["n_anomalies"])
        self.assertTrue(self.svc.storage.get_incidents(run["id"]))

    def test_02_repeat_upload_flags_duplicate_and_history(self):
        b1 = self.svc.ingest_bytes(self.csv1, "b1.csv")
        self.assertTrue(any("already uploaded" in w for w in b1["warnings"]))
        b2 = self.svc.ingest_bytes(self.csv2, "b2.csv")
        run_a = self.svc.analyze(b1["id"], "pca_reconstruction")
        run_b = self.svc.analyze(b2["id"], "pca_reconstruction")
        h = self.svc.history_comparison(run_b["id"])
        self.assertGreaterEqual(h["n_prior_runs"], 1)
        self.assertIsNotNone(h["rate_delta"])
        self.assertIn(run_a["id"], [r["run_id"] for r in h["prior_runs"]])
        self.assertTrue(h["recurring_patterns"])  # same synthetic failure templates recur

    def test_03_reference_batch_training(self):
        b1 = self.svc.ingest_bytes(self.csv1, "b1.csv")
        b2 = self.svc.ingest_bytes(self.csv2, "b2.csv")
        run = self.svc.analyze(b2["id"], "logistic_regression", train_batch_id=b1["id"])
        self.assertIn("reference batch", run["metrics"]["protocol"])
        self.assertEqual(run["n_scored"], b2["n_rows"])

    def test_04_unlabelled_text_has_no_metrics_and_supervised_fails_cleanly(self):
        txt = to_text(generate_logs(5, minutes=60)).encode()
        b = self.svc.ingest_bytes(txt, "u.log")
        self.assertFalse(b["has_labels"])
        run = self.svc.analyze(b["id"], "isolation_forest")
        self.assertIsNone(run["metrics"])
        with self.assertRaises(AnalysisError):
            self.svc.analyze(b["id"], "logistic_regression")
        failed = [r for r in self.svc.storage.list_runs(b["id"]) if r["status"] == "failed"]
        self.assertTrue(failed)

    def test_05_compare_detectors(self):
        b = self.svc.ingest_bytes(self.csv1, "b1.csv")
        res = self.svc.compare_detectors(b["id"])
        self.assertEqual({r["detector"] for r in res}, {"isolation_forest", "pca_reconstruction", "logistic_regression", "level_baseline"})
        self.assertTrue(all(r.get("status") == "completed" for r in res))

    def test_06_validation_errors(self):
        b = self.svc.ingest_bytes(self.csv1, "b1.csv")
        with self.assertRaises(NotFoundError):
            self.svc.analyze(99999)
        with self.assertRaises(AnalysisError):
            self.svc.analyze(b["id"], "bogus")
        with self.assertRaises(ValidationError):
            self.svc.analyze(b["id"], train_fraction=0.99)
        with self.assertRaises(ValidationError):
            self.svc.analyze(b["id"], train_batch_id=b["id"])
        with self.assertRaises(ValidationError):
            self.svc.ingest_bytes(b"", "e.csv")
        tiny = self.svc.ingest_bytes(b"message\n" + b"\n".join(b"m%d" % i for i in range(5)), "t.csv")
        with self.assertRaises(ValidationError):
            self.svc.analyze(tiny["id"])

    def test_07_reports(self):
        b = self.svc.ingest_bytes(self.csv1, "b1.csv")
        run = self.svc.analyze(b["id"], "pca_reconstruction")
        js, mt = self.svc.report(run["id"], "json")
        self.assertEqual(mt, "application/json")
        self.assertEqual(json.loads(js)["run"]["id"], run["id"])
        self.assertIn("log_id", self.svc.report(run["id"], "csv")[0])
        self.assertIn("# Log analysis report", self.svc.report(run["id"], "md")[0])
        with self.assertRaises(ValidationError):
            self.svc.report(run["id"], "pdf")


if __name__ == "__main__":
    unittest.main()
