import support  # noqa: F401
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import requests

import nse_bhavcopy as bhav
from config import PROJECT_ROOT

CSV = b"SYMBOL, SERIES, DATE1, PREV_CLOSE\nTCS, EQ, 13-Nov-2026, 3000.0\n"
HTML_404 = b"<!DOCTYPE html><html><body>Not found</body></html>"


class Resp:
    def __init__(self, status=200, content=CSV):
        self.status_code = status
        self.content = content


class FakeSession:
    """routes: {DDMMYYYY: Resp | [Resp, ...] (consumed in order) | Exception}. Unlisted dates -> 404."""

    def __init__(self, routes=None):
        self.headers = {}
        self.routes = routes or {}
        self.calls = []

    def get(self, url, **kw):
        stamp = url.rsplit("_", 1)[1].replace(".csv", "")
        self.calls.append(stamp)
        r = self.routes.get(stamp, Resp(404, HTML_404))
        if isinstance(r, list):
            r = r.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class DateTests(unittest.TestCase):
    def test_weekdays_skip_saturday_and_sunday_newest_first(self):
        # Mon 16 Nov 2026 back through Fri 13 Nov (Sat 14 and Sun 15 skipped)
        days = bhav.trading_days(date(2026, 11, 16), 4)
        self.assertEqual(days, [date(2026, 11, 16), date(2026, 11, 13)])

    def test_days_counts_calendar_days_back_like_the_notebook(self):
        self.assertEqual(len(bhav.trading_days(date(2026, 11, 13), 1700)), 1215)

    def test_filename_and_url(self):
        self.assertEqual(bhav.filename(date(2026, 1, 5)), "sec_bhavdata_full_05012026.csv")
        self.assertTrue(bhav.url_for(date(2026, 1, 5)).endswith("/sec_bhavdata_full_05012026.csv"))
        self.assertTrue(bhav.url_for(date(2026, 1, 5)).startswith("https://nsearchives.nseindia.com/"))

    def test_looks_like_bhavcopy(self):
        self.assertTrue(bhav.is_bhavcopy(CSV))
        self.assertFalse(bhav.is_bhavcopy(HTML_404))
        self.assertFalse(bhav.is_bhavcopy(b""))


class RunTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name) / "bhav"
        self.end = date(2026, 11, 13)   # Friday

    def tearDown(self):
        self._tmp.cleanup()

    def run_it(self, session, days=3, **kw):
        return bhav.run(session, self.out, days, self.end, sleep=lambda _s: None, **kw)

    def names(self):
        return sorted(p.name for p in self.out.iterdir()) if self.out.exists() else []

    def test_downloads_trading_days_and_counts_holiday_as_missing(self):
        s = FakeSession({"13112026": Resp(), "12112026": Resp(), "11112026": Resp(404, HTML_404)})
        stats = self.run_it(s, days=3)
        self.assertEqual(stats, {"new": 2, "skipped": 0, "missing": 1, "failed": 0})
        self.assertEqual(self.names(), ["sec_bhavdata_full_12112026.csv", "sec_bhavdata_full_13112026.csv"])

    def test_a_404_page_is_never_saved_as_a_csv(self):
        self.run_it(FakeSession(), days=3)
        self.assertEqual(self.names(), [])

    def test_html_with_status_200_is_rejected_not_saved(self):
        s = FakeSession({"13112026": [Resp(200, HTML_404)] * bhav.MAX_RETRIES})
        stats = self.run_it(s, days=1)
        self.assertEqual((stats["new"], stats["failed"]), (0, 1))
        self.assertEqual(self.names(), [])

    def test_existing_file_is_skipped_without_a_request(self):
        self.out.mkdir(parents=True)
        (self.out / "sec_bhavdata_full_13112026.csv").write_bytes(CSV)
        s = FakeSession()
        stats = self.run_it(s, days=1)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(s.calls, [])

    def test_bad_file_from_the_old_notebook_is_replaced(self):
        self.out.mkdir(parents=True)
        bad = self.out / "sec_bhavdata_full_13112026.csv"
        bad.write_bytes(HTML_404)
        stats = self.run_it(FakeSession({"13112026": Resp()}), days=1)
        self.assertEqual(stats["new"], 1)
        self.assertEqual(bad.read_bytes(), CSV)

    def test_empty_file_is_replaced(self):
        self.out.mkdir(parents=True)
        (self.out / "sec_bhavdata_full_13112026.csv").write_bytes(b"")
        self.assertEqual(self.run_it(FakeSession({"13112026": Resp()}), days=1)["new"], 1)

    def test_force_downloads_again(self):
        self.run_it(FakeSession({"13112026": Resp()}), days=1)
        s2 = FakeSession({"13112026": Resp()})
        self.assertEqual(self.run_it(s2, days=1, force=True)["new"], 1)
        self.assertEqual(s2.calls, ["13112026"])

    def test_server_error_is_retried_then_succeeds(self):
        s = FakeSession({"13112026": [Resp(503, b"x"), Resp(200)]})
        stats = self.run_it(s, days=1)
        self.assertEqual((stats["new"], stats["failed"]), (1, 0))
        self.assertEqual(s.calls, ["13112026", "13112026"])

    def test_network_error_after_retries_is_failed_and_run_continues(self):
        s = FakeSession({"13112026": requests.ConnectionError("down"), "12112026": Resp()})
        stats = self.run_it(s, days=2)
        self.assertEqual((stats["new"], stats["failed"]), (1, 1))
        self.assertEqual(s.calls.count("13112026"), bhav.MAX_RETRIES)

    def test_no_part_files_left_behind(self):
        self.run_it(FakeSession({"13112026": Resp()}), days=1)
        self.assertFalse([n for n in self.names() if n.endswith(".part")])


class MainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name) / "bhav"

    def tearDown(self):
        self._tmp.cleanup()

    def main(self, session, extra=()):
        with mock.patch("nse_bhavcopy.make_session", return_value=session), \
             mock.patch("nse_bhavcopy.setup_logging"), mock.patch("nse_bhavcopy.time.sleep"):
            return bhav.main(["--out", str(self.out), "--end-date", "2026-11-13", *extra])

    def test_defaults(self):
        a = bhav.parse_args([])
        self.assertEqual(a.out, PROJECT_ROOT / "data_stock_bhavcopy")
        self.assertEqual(a.days, 1700)
        self.assertFalse(a.force)

    def test_bad_days_rejected(self):
        with self.assertRaises(SystemExit):
            bhav.parse_args(["--days", "0"])

    def test_bad_end_date_rejected(self):
        with self.assertRaises(SystemExit):
            bhav.parse_args(["--end-date", "13-11-2026"])

    def test_exit_0_when_everything_downloaded_or_holiday(self):
        self.assertEqual(self.main(FakeSession({"13112026": Resp()}), ["--days", "2"]), 0)

    def test_exit_1_when_a_download_failed(self):
        s = FakeSession({"13112026": [Resp(500)] * bhav.MAX_RETRIES})
        self.assertEqual(self.main(s, ["--days", "1"]), 1)


if __name__ == "__main__":
    unittest.main()
