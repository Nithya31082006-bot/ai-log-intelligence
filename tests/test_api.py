"""API tests. Skipped automatically when fastapi / httpx are not installed."""
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
    from logintel.api import create_app
    HAVE_API = True
except ImportError:  # pragma: no cover
    HAVE_API = False

from logintel.synthetic import generate_logs, to_csv


@unittest.skipUnless(HAVE_API, "fastapi/httpx not installed")
class TestApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(str(Path(self.tmp.name) / "api.db")))
        self.csv = to_csv(generate_logs(1, minutes=90)).encode()

    def tearDown(self):
        self.tmp.cleanup()

    def test_flow(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        r = self.client.post("/batches", files={"file": ("a.csv", self.csv, "text/csv")}, data={"name": "x"})
        self.assertEqual(r.status_code, 201)
        bid = r.json()["id"]
        r = self.client.post(f"/batches/{bid}/analyze", json={"detector": "pca_reconstruction"})
        self.assertEqual(r.status_code, 201)
        rid = r.json()["id"]
        f = self.client.get(f"/runs/{rid}/findings", params={"limit": 3}).json()
        self.assertLessEqual(len(f["items"]), 3)
        self.assertEqual(self.client.get(f"/runs/{rid}/incidents").status_code, 200)
        self.assertEqual(self.client.get(f"/runs/{rid}/history").status_code, 200)
        self.assertEqual(self.client.get(f"/runs/{rid}/report", params={"format": "md"}).status_code, 200)

    def test_errors(self):
        self.assertEqual(self.client.get("/runs/9999").status_code, 404)
        r = self.client.post("/batches", files={"file": ("a.csv", b"a,b\n1,2\n", "text/csv")})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/batches/1/analyze", json={"contamination": 0.9})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
