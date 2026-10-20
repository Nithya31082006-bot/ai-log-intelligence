import unittest

import pandas as pd

from logintel.exceptions import ValidationError
from logintel.parsing import LogParser, normalize_level, normalize_template


class TestTemplates(unittest.TestCase):
    def test_masks_variable_parts(self):
        t = normalize_template("user user_42 from 10.0.0.1:8080 took 250ms id 123e4567-e89b-12d3-a456-426614174000 at 0xFF")
        self.assertEqual(t, "user <ID> from <IP> took <NUM>ms id <UUID> at <HEX>")

    def test_same_template_for_different_values(self):
        self.assertEqual(normalize_template("timeout after 30 s"), normalize_template("timeout after 45 s"))

    def test_level_aliases(self):
        self.assertEqual(normalize_level("warning"), "WARN")
        self.assertEqual(normalize_level("Critical"), "FATAL")
        self.assertEqual(normalize_level("weird"), "UNKNOWN")
        self.assertEqual(normalize_level(None), "UNKNOWN")


class TestCsv(unittest.TestCase):
    def test_alias_columns_and_labels(self):
        csv = ("Time,Severity,Component,Msg,is_anomaly\n"
               "2024-01-01T00:00:00Z,error,db,connection lost,1\n"
               "2024-01-01T00:00:01Z,INFO,api,ok,0\n"
               "2024-01-01T00:00:02Z,INFO,api,ok,maybe\n")
        r = LogParser().parse_bytes(csv.encode(), "x.csv")
        df = r.df
        self.assertEqual(list(df["level"]), ["ERROR", "INFO", "INFO"])
        self.assertEqual(df["label"].tolist()[:2], [1, 0])
        self.assertTrue(pd.isna(df["label"].iloc[2]))
        self.assertEqual(str(df["timestamp"].dt.tz), "UTC")

    def test_missing_message_column_rejected(self):
        with self.assertRaises(ValidationError):
            LogParser().parse_bytes(b"a,b\n1,2\n", "x.csv")

    def test_empty_rejected(self):
        with self.assertRaises(ValidationError):
            LogParser().parse_bytes(b"   \n", "x.csv")

    def test_no_timestamp_warns(self):
        r = LogParser().parse_bytes(b"message\nhello\nworld\n", "x.csv")
        self.assertTrue(any("timestamp" in w.lower() for w in r.warnings))
        self.assertTrue(r.df["timestamp"].isna().all())

    def test_epoch_seconds(self):
        r = LogParser().parse_bytes(b"ts,msg\n1700000000,a\n1700000060,b\n", "x.csv")
        self.assertEqual(r.df["timestamp"].iloc[0].year, 2023)

    def test_empty_messages_dropped(self):
        r = LogParser().parse_bytes(b"message\nhello\n\nworld\n", "x.csv")
        self.assertEqual(len(r.df), 2)

    def test_row_limit(self):
        body = "message\n" + "\n".join(f"m{i}" for i in range(20))
        with self.assertRaises(ValidationError):
            LogParser(max_rows=10).parse_bytes(body.encode(), "x.csv")


class TestText(unittest.TestCase):
    def test_parse_with_continuation_and_malformed(self):
        txt = ("2024-03-01 08:00:00,123 INFO [auth] user logged in\n"
               "2024-03-01 08:00:01,000 ERROR [db] boom\n"
               "    at com.example.Foo.bar(Foo.java:1)\n"
               "garbage line\n"
               "2024-03-01 08:00:02 WARNING service=pay slow call\n")
        r = LogParser().parse_bytes(txt.encode(), "x.log")
        df = r.df
        self.assertEqual(len(df), 3)
        self.assertIn("Foo.java", df["message"].iloc[1])
        self.assertEqual(df["service"].tolist(), ["auth", "db", "pay"])
        self.assertEqual(df["level"].iloc[2], "WARN")
        self.assertEqual(r.n_malformed, 1)
        self.assertEqual(df["timestamp"].iloc[0].microsecond, 123000)

    def test_unrecognised_text_rejected(self):
        with self.assertRaises(ValidationError):
            LogParser().parse_bytes(b"hello\nthis is not a log\nnor this\n", "x.log")


if __name__ == "__main__":
    unittest.main()
