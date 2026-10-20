import unittest

import pandas as pd

from logintel.exceptions import NotFoundError
from logintel.parsing import normalize_template
from logintel.storage import Storage


class TestStorage(unittest.TestCase):
    def test_roundtrip_and_cascade_lookup(self):
        st = Storage(":memory:")
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(["2024-01-01T00:00:00Z", None], utc=True),
            "level": ["INFO", "ERROR"], "service": ["a", "b"], "message": ["hi 1", "boom 2"],
            "label": pd.array([0, pd.NA], dtype="Int64")})
        bid = st.create_batch("n", "f.csv", "abc", "csv", df, 0, [], [normalize_template(m) for m in df["message"]])
        back = st.get_logs_df(bid)
        self.assertEqual(len(back), 2)
        self.assertTrue(pd.isna(back["timestamp"].iloc[1]))
        self.assertTrue(pd.isna(back["label"].iloc[1]))
        self.assertEqual(back["template"].iloc[0], "hi <NUM>")
        with self.assertRaises(NotFoundError):
            st.get_batch(999)
        with self.assertRaises(NotFoundError):
            st.get_run(999)


if __name__ == "__main__":
    unittest.main()
