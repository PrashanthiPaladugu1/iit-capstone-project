import support  # noqa: F401
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import cli
from config import DEFAULT_AUTH, DEFAULT_HISTORY, DEFAULT_OUTPUT_DIR, DEFAULT_WATCHLIST, PROJECT_ROOT
from models import AuthError
from tracker import load_tracker


class ArgsTests(unittest.TestCase):
    def test_defaults_are_anchored_to_project_root(self):
        a = cli.parse_args([])
        self.assertEqual(a.output_dir, PROJECT_ROOT / "data")
        self.assertEqual(a.watchlist, PROJECT_ROOT / "watchlist.txt")
        self.assertEqual(a.auth, PROJECT_ROOT / "screener_auth.json")
        self.assertEqual(a.history, PROJECT_ROOT / "downloaded_history.json")
        self.assertEqual((a.min_delay, a.max_delay), (1.0, 2.0))
        self.assertEqual(a.types, ["annual", "transcript", "ppt"])

    def test_flags(self):
        a = cli.parse_args(["-s", "TCS", "INFY", "--types", "ppt", "--dry-run", "--no-excel",
                            "--standalone", "-v"])
        self.assertEqual(a.symbols, ["TCS", "INFY"])
        self.assertEqual(a.types, ["ppt"])
        self.assertTrue(a.dry_run and a.no_excel and a.standalone and a.verbose)

    def test_bad_delay_range_rejected(self):
        with self.assertRaises(SystemExit):
            cli.parse_args(["--min-delay", "3", "--max-delay", "1"])

    def test_bad_type_rejected(self):
        with self.assertRaises(SystemExit):
            cli.parse_args(["--types", "video"])

    def test_workers_default_is_one_and_parsed(self):
        self.assertEqual(cli.parse_args([]).workers, 1)
        self.assertEqual(cli.parse_args(["--workers", "4"]).workers, 4)

    def test_bad_workers_rejected(self):
        for bad in ("0", "-2", "99"):
            with self.assertRaises(SystemExit):
                cli.parse_args(["--workers", bad])

    def test_tracker_default_path_and_force_flag(self):
        a = cli.parse_args([])
        self.assertEqual(a.tracker, PROJECT_ROOT / "download_tracker.txt")
        self.assertFalse(a.force)
        b = cli.parse_args(["--force", "--tracker", "x.txt"])
        self.assertTrue(b.force)
        self.assertEqual(str(b.tracker), "x.txt")


class CsvArgsTests(unittest.TestCase):
    def test_csv_flags_parsed(self):
        a = cli.parse_args(["--csv", "x.csv", "--start", "5", "--limit", "10"])
        self.assertEqual((str(a.csv), a.start, a.limit), ("x.csv", 5, 10))

    def test_csv_defaults_none(self):
        a = cli.parse_args([])
        self.assertEqual((a.csv, a.start, a.limit), (None, 0, None))

    def test_negative_start_or_limit_rejected(self):
        for bad in (["--start", "-1"], ["--limit", "0"]):
            with self.assertRaises(SystemExit):
                cli.parse_args(bad)


class MainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.auth = self.root / "auth.json"
        self.auth.write_text(json.dumps({"cookies": [{"name": "sessionid", "value": "x"}]}))
        self.wl = self.root / "w.txt"
        self.wl.write_text("# c\nTCS\nINFY\n")
        self.logs = self.root / "logs"
        self.tracker = self.root / "download_tracker.txt"
        self.base = ["-a", str(self.auth), "-w", str(self.wl), "--history", str(self.root / "h.json"),
                     "-o", str(self.root / "data"), "--log-dir", str(self.logs),
                     "--tracker", str(self.tracker)]

    def tearDown(self):
        self._tmp.cleanup()

    def _main(self, extra, side_effect=None, return_value=None):
        with mock.patch("cli.process_symbol", side_effect=side_effect, return_value=return_value) as ps, \
             mock.patch("cli.setup_logging"):
            code = cli.main(self.base + extra)
        return code, ps

    def test_success_processes_watchlist_symbols_in_order(self):
        code, ps = self._main([], return_value={"new": 1, "skipped": 0, "failed": 0})
        self.assertEqual(code, 0)
        self.assertEqual([c.args[0] for c in ps.call_args_list], ["TCS", "INFY"])

    def test_symbols_flag_overrides_watchlist(self):
        _, ps = self._main(["-s", "MEESHO"], return_value={"new": 0, "skipped": 0, "failed": 0})
        self.assertEqual([c.args[0] for c in ps.call_args_list], ["MEESHO"])

    def test_stock_flag_single_and_repeated(self):
        _, ps = self._main(["--stock", "INFY"], return_value=self.OK)
        self.assertEqual([c.args[0] for c in ps.call_args_list], ["INFY"])
        _, ps = self._main(["--stock", "AAA", "--stock", "BBB"], return_value=self.OK)
        self.assertEqual([c.args[0] for c in ps.call_args_list], ["AAA", "BBB"])

    def test_exit_1_when_any_failure(self):
        code, _ = self._main([], return_value={"new": 0, "skipped": 0, "failed": 1})
        self.assertEqual(code, 1)

    def test_unexpected_error_in_one_symbol_does_not_stop_run(self):
        good = {"new": 1, "skipped": 0, "failed": 0}
        code, ps = self._main([], side_effect=[RuntimeError("boom"), good])
        self.assertEqual(ps.call_count, 2)
        self.assertEqual(code, 1)

    def test_auth_error_during_run_exits_3_and_stops(self):
        code, ps = self._main([], side_effect=AuthError("expired"))
        self.assertEqual(code, 3)
        self.assertEqual(ps.call_count, 1)

    def test_missing_auth_exits_2(self):
        self.auth.unlink()
        code, ps = self._main([])
        self.assertEqual(code, 2)
        ps.assert_not_called()

    def test_missing_watchlist_exits_2(self):
        self.wl.unlink()
        self.assertEqual(self._main([])[0], 2)

    def test_empty_watchlist_exits_2(self):
        self.wl.write_text("# nothing\n")
        self.assertEqual(self._main([])[0], 2)

    def test_options_forwarded_to_pipeline(self):
        _, ps = self._main(["--types", "transcript", "--dry-run", "--no-excel", "--standalone"],
                           return_value={"new": 0, "skipped": 0, "failed": 0})
        c = ps.call_args
        self.assertEqual(c.args[5], {"Transcript"})
        self.assertTrue(c.args[6])
        self.assertEqual((c.kwargs["excel"], c.kwargs["standalone"]), (False, True))

    def test_csv_source_used_with_batching(self):
        csv_path = self.root / "s.csv"
        csv_path.write_text("Name,BSE Code,NSE Code\nA,1,AAA\nB,2,BBB\nC,3,\nD,4,DDD\n")
        _, ps = self._main(["--csv", str(csv_path), "--start", "1", "--limit", "2"],
                           return_value={"new": 0, "skipped": 0, "failed": 0})
        self.assertEqual([c.args[0] for c in ps.call_args_list], ["BBB", "3"])

    def test_symbols_flag_beats_csv(self):
        csv_path = self.root / "s.csv"
        csv_path.write_text("Name,BSE Code,NSE Code\nA,1,AAA\n")
        _, ps = self._main(["--csv", str(csv_path), "-s", "ZZZ"],
                           return_value={"new": 0, "skipped": 0, "failed": 0})
        self.assertEqual([c.args[0] for c in ps.call_args_list], ["ZZZ"])

    def test_bad_csv_exits_2(self):
        bad = self.root / "bad.csv"
        bad.write_text("Name,Foo\nA,1\n")
        self.assertEqual(self._main(["--csv", str(bad)])[0], 2)
        self.assertEqual(self._main(["--csv", str(self.root / "nope.csv")])[0], 2)

    OK = {"new": 1, "skipped": 0, "failed": 0}

    def test_default_log_dir_is_project_logs(self):
        self.assertEqual(cli.parse_args([]).log_dir, PROJECT_ROOT / "logs")

    def test_run_log_file_created_in_log_dir_by_default(self):
        with mock.patch("cli.process_symbol", return_value=self.OK), \
             mock.patch("cli.setup_logging") as sl:
            cli.main(self.base)
        path = sl.call_args.args[1]
        self.assertEqual(path.parent, self.logs)
        self.assertTrue(path.name.startswith("run_") and path.name.endswith(".log"))

    def test_explicit_log_file_overrides_default(self):
        with mock.patch("cli.process_symbol", return_value=self.OK), \
             mock.patch("cli.setup_logging") as sl:
            cli.main(self.base + ["--log-file", str(self.root / "my.log")])
        self.assertEqual(sl.call_args.args[1], self.root / "my.log")

    def test_summary_json_written_next_to_log(self):
        self._main([], return_value=self.OK)
        files = list(self.logs.glob("run_*.summary.json"))
        self.assertEqual(len(files), 1)
        data = json.loads(files[0].read_text())
        self.assertEqual(data["symbols_total"], 2)
        self.assertEqual(data["symbols_done"], 2)
        self.assertEqual(data["totals"]["new"], 2)
        self.assertFalse(data["interrupted"])

    def test_summary_lists_symbols_with_failures(self):
        bad = {"new": 0, "skipped": 0, "failed": 1}
        self._main([], side_effect=[self.OK, bad])
        data = json.loads(next(self.logs.glob("*.summary.json")).read_text())
        self.assertEqual(data["symbols_with_failures"], ["INFY"])

    def test_progress_logged_for_each_symbol(self):
        with self.assertLogs("screener_downloader", level="INFO") as cm:
            self._main([], return_value=self.OK)
        text = "\n".join(cm.output)
        self.assertIn("[1/2]", text)
        self.assertIn("[2/2]", text)
        self.assertIn("total new=2", text)

    def test_all_flag_uses_latest_csv(self):
        csv_path = self.root / "all.csv"
        csv_path.write_text("Name,BSE Code,NSE Code\nA,1,AAA\nB,2,BBB\n")
        with mock.patch("cli.find_latest_csv", return_value=csv_path):
            _, ps = self._main(["--all"], return_value=self.OK)
        self.assertEqual([c.args[0] for c in ps.call_args_list], ["AAA", "BBB"])

    def test_all_flag_without_csv_exits_2(self):
        with mock.patch("cli.find_latest_csv", return_value=None):
            self.assertEqual(self._main(["--all"])[0], 2)

    def test_index_flag_reads_reference_csv_with_batching(self):
        ref = self.root / "ref"
        ref.mkdir()
        (ref / "nifty-50.csv").write_text("Name,BSE Code,NSE Code\nA,1,AAA\nB,2,BBB\nC,3,CCC\n")
        with mock.patch("cli.REFERENCE_DIR", ref):
            _, ps = self._main(["--index", "Nifty50", "--start", "1", "--limit", "1"],
                               return_value=self.OK)
        self.assertEqual([c.args[0] for c in ps.call_args_list], ["BBB"])

    def test_unknown_index_exits_2(self):
        ref = self.root / "ref"
        ref.mkdir()
        with mock.patch("cli.REFERENCE_DIR", ref):
            self.assertEqual(self._main(["--index", "nope"])[0], 2)

    def test_index_cannot_combine_with_all_or_csv(self):
        for other in (["--all"], ["--csv", "x.csv"]):
            with self.assertRaises(SystemExit):
                cli.parse_args(["--index", "nifty50"] + other)

    def test_interrupt_with_csv_logs_resume_hint_and_marks_summary(self):
        csv_path = self.root / "s.csv"
        csv_path.write_text("Name,BSE Code,NSE Code\nA,1,AAA\nB,2,BBB\nC,3,CCC\n")
        with self.assertLogs("screener_downloader", level="WARNING") as cm:
            code, _ = self._main(["--csv", str(csv_path), "--start", "1"],
                                 side_effect=[self.OK, KeyboardInterrupt])
        self.assertEqual(code, 130)
        self.assertIn("--start 2", "\n".join(cm.output))   # start 1 + 1 finished
        data = json.loads(next(self.logs.glob("*.summary.json")).read_text())
        self.assertTrue(data["interrupted"])
        self.assertEqual(data["symbols_done"], 1)

    def test_auth_error_still_writes_summary(self):
        self._main([], side_effect=AuthError("expired"))
        self.assertEqual(len(list(self.logs.glob("*.summary.json"))), 1)

    def test_keyboard_interrupt_exits_130(self):
        self.assertEqual(self._main([], side_effect=KeyboardInterrupt)[0], 130)

    # -- parallel across stocks (one stock = one worker, end to end)
    def test_workers_process_different_stocks_concurrently(self):
        self.wl.write_text("A\nB\nC\n")
        barrier = threading.Barrier(3, timeout=10)  # only passes if 3 stocks run at the same time

        def fake(symbol, fetcher, *a, **k):
            barrier.wait()
            return self.OK

        code, ps = self._main(["--workers", "3"], side_effect=fake)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(c.args[0] for c in ps.call_args_list), ["A", "B", "C"])

    def test_each_stock_runs_once_on_one_fetcher_and_fetchers_are_not_shared(self):
        self.wl.write_text("\n".join(f"S{i}" for i in range(9)) + "\n")
        lock, active, overlap, sessions = threading.Lock(), set(), [], {}

        def fake(symbol, fetcher, *a, **k):
            with lock:
                if id(fetcher) in active:
                    overlap.append(symbol)
                active.add(id(fetcher))
                sessions[id(fetcher)] = fetcher.session
            time.sleep(0.03)
            with lock:
                active.discard(id(fetcher))
            return self.OK

        code, ps = self._main(["--workers", "3"], side_effect=fake)
        self.assertEqual(code, 0)
        self.assertEqual(overlap, [])                       # a fetcher never serves two stocks at once
        self.assertLessEqual(len(sessions), 3)
        self.assertEqual(len({id(s) for s in sessions.values()}), len(sessions))  # own session each
        self.assertEqual(sorted(c.args[0] for c in ps.call_args_list), sorted(f"S{i}" for i in range(9)))

    def test_parallel_totals_and_summary(self):
        self.wl.write_text("A\nB\nC\nD\n")
        code, _ = self._main(["--workers", "2"], return_value=self.OK)
        data = json.loads(next(self.logs.glob("*.summary.json")).read_text())
        self.assertEqual((data["symbols_total"], data["symbols_done"], data["totals"]["new"]), (4, 4, 4))
        self.assertEqual(code, 0)

    def test_parallel_unexpected_error_in_one_stock_does_not_stop_others(self):
        self.wl.write_text("A\nB\nC\n")

        def fake(symbol, *a, **k):
            if symbol == "B":
                raise RuntimeError("boom")
            return self.OK

        code, ps = self._main(["--workers", "2"], side_effect=fake)
        self.assertEqual(ps.call_count, 3)
        self.assertEqual(code, 1)

    def test_parallel_auth_error_exits_3_and_writes_summary(self):
        self.wl.write_text("\n".join(f"S{i}" for i in range(20)) + "\n")
        code, ps = self._main(["--workers", "3"], side_effect=AuthError("expired"))
        self.assertEqual(code, 3)
        self.assertLess(ps.call_count, 20)                  # pending stocks were cancelled
        self.assertEqual(len(list(self.logs.glob("*.summary.json"))), 1)

    # -- download_tracker.txt: finished symbols are skipped unless --force
    def test_successful_symbols_are_written_to_tracker(self):
        self._main([], return_value=self.OK)
        self.assertEqual(load_tracker(self.tracker), {"TCS", "INFY"})

    def test_symbol_with_failures_is_not_tracked(self):
        bad = {"new": 0, "skipped": 0, "failed": 1}
        self._main([], side_effect=[self.OK, bad])
        self.assertEqual(load_tracker(self.tracker), {"TCS"})

    def test_crashed_symbol_is_not_tracked(self):
        self._main([], side_effect=[RuntimeError("boom"), self.OK])
        self.assertEqual(load_tracker(self.tracker), {"INFY"})

    def test_dry_run_does_not_write_tracker(self):
        self._main(["--dry-run"], return_value=self.OK)
        self.assertFalse(self.tracker.exists())

    def test_auth_error_does_not_track(self):
        self._main([], side_effect=AuthError("expired"))
        self.assertFalse(self.tracker.exists())

    def test_symbol_interrupted_by_stop_is_not_tracked(self):
        def fake(symbol, fetcher, *a, **k):
            k["stop"].set()          # run was told to stop while this stock was in flight
            return self.OK

        self._main(["-s", "TCS"], side_effect=fake)
        self.assertFalse(self.tracker.exists())

    def test_tracked_symbols_are_skipped(self):
        self.tracker.write_text("TCS\n")
        with self.assertLogs("screener_downloader", level="INFO") as cm:
            code, ps = self._main([], return_value=self.OK)
        self.assertEqual([c.args[0] for c in ps.call_args_list], ["INFY"])
        self.assertIn("1 symbol(s) already done", "\n".join(cm.output))
        self.assertEqual(code, 0)

    def test_tracker_match_is_case_insensitive(self):
        self.tracker.write_text("tcs\n")
        _, ps = self._main([], return_value=self.OK)
        self.assertEqual([c.args[0] for c in ps.call_args_list], ["INFY"])

    def test_force_processes_tracked_symbols_again(self):
        self.tracker.write_text("TCS\nINFY\n")
        _, ps = self._main(["--force"], return_value=self.OK)
        self.assertEqual([c.args[0] for c in ps.call_args_list], ["TCS", "INFY"])

    def test_everything_already_done_exits_0_without_work(self):
        self.tracker.write_text("TCS\nINFY\n")
        with self.assertLogs("screener_downloader", level="INFO") as cm:
            code, ps = self._main([])
        self.assertEqual(code, 0)
        ps.assert_not_called()
        self.assertIn("--force", "\n".join(cm.output))

    def test_progress_total_counts_only_remaining_symbols(self):
        self.tracker.write_text("TCS\n")
        self._main([], return_value=self.OK)
        data = json.loads(next(self.logs.glob("*.summary.json")).read_text())
        self.assertEqual((data["symbols_total"], data["symbols_done"]), (1, 1))

    def test_resume_hint_maps_back_to_position_in_full_csv_list(self):
        csv_path = self.root / "s.csv"
        csv_path.write_text("Name,BSE Code,NSE Code\nA,1,AAA\nB,2,BBB\nC,3,CCC\nD,4,DDD\n")
        self.tracker.write_text("AAA\n")        # already done -> run list is BBB, CCC, DDD
        with self.assertLogs("screener_downloader", level="WARNING") as cm:
            self._main(["--csv", str(csv_path)], side_effect=[self.OK, KeyboardInterrupt])
        # BBB finished, CCC interrupted: CCC sits at position 2 of the full list
        self.assertIn("--start 2", "\n".join(cm.output))

    def test_parallel_keyboard_interrupt_exits_130(self):
        self.wl.write_text("A\nB\nC\n")
        code, _ = self._main(["--workers", "2"], side_effect=KeyboardInterrupt)
        self.assertEqual(code, 130)
        data = json.loads(next(self.logs.glob("*.summary.json")).read_text())
        self.assertTrue(data["interrupted"])


if __name__ == "__main__":
    unittest.main()
