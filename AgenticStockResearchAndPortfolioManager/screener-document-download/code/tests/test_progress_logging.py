import support  # noqa: F401
import json
import logging
import re
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

from log_setup import default_log_path, setup_logging
from progress import Progress, fmt_duration
from symbols_csv import find_latest_csv


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FmtDurationTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(fmt_duration(0), "00:00:00")
        self.assertEqual(fmt_duration(80), "00:01:20")
        self.assertEqual(fmt_duration(3661), "01:01:01")
        self.assertEqual(fmt_duration(100 * 3600), "100:00:00")

    def test_none_or_negative(self):
        self.assertEqual(fmt_duration(None), "--:--:--")
        self.assertEqual(fmt_duration(-5), "00:00:00")


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.p = Progress(10, clock=self.clock)

    def test_begin_shows_position_total_percent_and_symbol(self):
        line = self.p.begin("TCS")
        self.assertIn("[1/10]", line)
        self.assertIn("0.0%", line)
        self.assertIn("TCS", line)

    def test_position_advances_after_finish(self):
        self.p.begin("A"); self.p.finish("A", {"new": 1, "skipped": 0, "failed": 0})
        self.assertIn("[2/10]", self.p.begin("B"))
        self.assertIn("10.0%", self.p.begin("B"))

    def test_totals_accumulate(self):
        self.p.finish("A", {"new": 2, "skipped": 3, "failed": 0})
        self.p.finish("B", {"new": 1, "skipped": 0, "failed": 4})
        self.assertEqual(self.p.totals, {"new": 3, "skipped": 3, "failed": 4})
        self.assertEqual(self.p.done, 2)

    def test_finish_line_has_counts_totals_and_eta(self):
        self.clock.t = 20.0
        self.p.finish("A", {"new": 1, "skipped": 0, "failed": 0})
        self.clock.t = 40.0
        line = self.p.finish("B", {"new": 2, "skipped": 1, "failed": 0})
        self.assertIn("B", line)
        self.assertIn("new=2 skipped=1 failed=0", line)
        self.assertIn("2/10", line)
        self.assertIn("total new=3 skipped=1 failed=0", line)
        self.assertIn("elapsed 00:00:40", line)
        self.assertIn("ETA 00:02:40", line)   # 40s for 2 symbols -> 8 left * 20s

    def test_eta_unknown_before_first_symbol_done(self):
        self.assertIn("--:--:--", self.p.begin("A"))

    def test_symbols_with_failures_tracked(self):
        self.p.finish("A", {"new": 1, "skipped": 0, "failed": 0})
        self.p.finish("B", {"new": 0, "skipped": 0, "failed": 2})
        self.assertEqual(self.p.failed_symbols, ["B"])

    def test_summary_dict(self):
        self.clock.t = 5.0
        self.p.finish("B", {"new": 0, "skipped": 0, "failed": 2})
        s = self.p.summary(interrupted=True)
        self.assertEqual(s["symbols_total"], 10)
        self.assertEqual(s["symbols_done"], 1)
        self.assertTrue(s["interrupted"])
        self.assertEqual(s["totals"], {"new": 0, "skipped": 0, "failed": 2})
        self.assertEqual(s["symbols_with_failures"], ["B"])
        self.assertEqual(s["elapsed_seconds"], 5.0)

    def test_write_summary_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "logs" / "run.summary.json"
            self.p.write_summary(path, interrupted=False)
            data = json.loads(path.read_text())
            self.assertEqual(data["symbols_total"], 10)
            self.assertFalse(data["interrupted"])

    def test_zero_total_does_not_divide_by_zero(self):
        p = Progress(0, clock=self.clock)
        self.assertIn("0.0%", p.begin("X"))


class ParallelProgressTests(unittest.TestCase):
    def test_begin_positions_are_unique_across_threads(self):
        p = Progress(100)
        lines = []
        threads = [threading.Thread(target=lambda s=s: lines.append(p.begin(f"S{s}"))) for s in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        positions = {int(re.match(r"\[(\d+)/100\]", ln).group(1)) for ln in lines}
        self.assertEqual(positions, set(range(1, 51)))

    def test_finish_from_many_threads_counts_everything(self):
        p = Progress(200)
        threads = [threading.Thread(target=lambda: p.finish("X", {"new": 1, "skipped": 2, "failed": 0}))
                   for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(p.done, 100)
        self.assertEqual(p.totals, {"new": 100, "skipped": 200, "failed": 0})

    def test_resume_offset_defaults_to_done_without_indexes(self):
        p = Progress(5)
        p.finish("A", {}); p.finish("B", {})
        self.assertEqual(p.resume_offset(), 2)

    def test_resume_offset_is_contiguous_prefix_when_finishing_out_of_order(self):
        p = Progress(5)
        p.finish("C", {}, index=2)
        p.finish("A", {}, index=0)
        self.assertEqual(p.resume_offset(), 1)      # index 1 never finished -> resume from it
        p.finish("B", {}, index=1)
        self.assertEqual(p.resume_offset(), 3)


class LogSetupTests(unittest.TestCase):
    def test_default_log_path_is_timestamped_in_dir(self):
        p = default_log_path(Path("/x/logs"), now=datetime(2026, 11, 14, 19, 45, 3))
        self.assertEqual(p, Path("/x/logs/run_20261114_194503.log"))

    def test_setup_logging_creates_dir_and_writes_file(self):
        root = logging.getLogger()
        saved = (root.handlers[:], root.level)
        try:
            with tempfile.TemporaryDirectory() as d:
                path = Path(d) / "nested" / "logs" / "run.log"
                setup_logging(False, path)
                logging.getLogger("screener_downloader").info("hello-log-file")
                for h in root.handlers:
                    h.flush()
                self.assertIn("hello-log-file", path.read_text())
                for h in root.handlers[:]:
                    h.close()
        finally:
            root.handlers[:] = saved[0]
            root.setLevel(saved[1])


class FindLatestCsvTests(unittest.TestCase):
    def test_picks_newest_by_name(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("equitydata-screener-all-stocks-20261101.csv",
                      "equitydata-screener-all-stocks-20261113.csv", "other.csv"):
                (Path(d) / n).write_text("x")
            self.assertEqual(find_latest_csv(Path(d)).name, "equitydata-screener-all-stocks-20261113.csv")

    def test_none_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(find_latest_csv(Path(d)))


if __name__ == "__main__":
    unittest.main()
