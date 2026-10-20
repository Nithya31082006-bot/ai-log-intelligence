"""Regenerate the synthetic sample files in data/ (deterministic)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logintel.synthetic import generate_logs, to_csv, to_text  # noqa: E402

here = Path(__file__).parent
(here / "sample_batch_1.csv").write_text(to_csv(generate_logs(101, minutes=180)))
(here / "sample_batch_2.csv").write_text(to_csv(generate_logs(102, minutes=180)))
(here / "sample_unlabelled.log").write_text(to_text(generate_logs(103, minutes=120)))
print("written")
