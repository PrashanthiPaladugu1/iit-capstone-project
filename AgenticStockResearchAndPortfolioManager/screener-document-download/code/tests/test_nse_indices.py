import support  # noqa: F401
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

import nse_indices as nse
from config import PROJECT_ROOT

HEADER = ["symbol", "open", "high", "low", "ltP", "ptsC30d", "volume", "value_crores", "yHigh", "yLow", "pChange"]

ALL_INDICES = {"data": [{"index": "NIFTY 50", "last": 1}, {"index": " NIFTY BANK ", "last": 2},
                        {"index": None}, {"index": "NIFTY MIDCAP & SMALL"}]}
STOCK = {"symbol": "HDFCBANK", "open": 808.0, "dayHigh": 808.8, "dayLow": 798.0, "lastPrice": 804.0,
         "perChange30d": 12.61, "totalTradedVolume": 23442886, "totalTradedValue": 1.8e10,
         "yearHigh": 1017.5, "yearLow": 669.2, "pChange": -1.02}


def payload(*stocks):
    return {"data": list(stocks) or [STOCK], "timestamp": "x"}


class Resp:
    def __init__(self, status=200, body=None, text=None):
        self.status_code = status
        self._body = body
        self.text = text if text is not None else json.dumps(body)

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """routes: {url: Resp | [Resp, ...] (consumed in order) | Exception}. Params are matched by index name."""

    def __init__(self, indices=("NIFTY 50", "NIFTY BANK"), overrides=None, symbols=None):
        """symbols: {display name: indexSymbol} - NSE wants the short indexSymbol in the request."""
        symbols = symbols or {}
        self.headers = {}
        self.calls = []
        rows = [{"index": i, **({"indexSymbol": symbols[i]} if i in symbols else {})} for i in (indices or [])]
        self.routes = {nse.INDICES_URL: Resp(body=ALL_INDICES if indices is None else {"data": rows})}
        self.index_routes = {symbols.get(i, i): Resp(body=payload()) for i in (indices or [])}
        self.index_routes.update(overrides or {})

    def get(self, url, params=None, **kw):
        self.calls.append((url, params))
        if url == nse.INDICES_URL:
            r = self.routes[url]
        elif url == nse.INDEX_URL:
            r = self.index_routes[params["index"]]
        else:  # homepage priming
            return Resp(200, text="home")
        if isinstance(r, list):
            r = r.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def index_calls(self, name=None):
        return [p["index"] for u, p in self.calls if u == nse.INDEX_URL and (name is None or p["index"] == name)]


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.reader(fh))


class HelperTests(unittest.TestCase):
    def test_filename_matches_the_notebook_style(self):
        self.assertEqual(nse.index_filename("NIFTY 50"), "NIFTY_50.csv")
        self.assertEqual(nse.index_filename("NIFTY MIDCAP & SMALL"), "NIFTY_MIDCAP_and_SMALL.csv")
        self.assertEqual(nse.index_filename("A/B: C"), "A_B__C.csv")

    def test_stock_row_uses_the_real_nse_keys(self):
        row = nse.stock_row(STOCK)
        self.assertEqual(row, ["HDFCBANK", 808.0, 808.8, 798.0, 804.0, 12.61, 23442886, 1.8e10,
                               1017.5, 669.2, -1.02])

    def test_missing_fields_become_dash(self):
        self.assertEqual(nse.stock_row({"symbol": "X"}), ["X"] + ["-"] * 10)

    def test_write_index_csv_header_rows_and_no_part_file_left(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "NIFTY_50.csv"
            nse.write_index_csv(p, payload(STOCK, {"symbol": "Y"})["data"])
            rows = read_csv(p)
            self.assertEqual(rows[0], HEADER)
            self.assertEqual([r[0] for r in rows[1:]], ["HDFCBANK", "Y"])
            self.assertEqual([x.name for x in p.parent.iterdir()], ["NIFTY_50.csv"])

    def test_write_master_csv_covers_all_columns(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "m.csv"
            nse.write_master_csv(p, [{"index": "A", "last": 1}, {"index": "B", "extra": 2}])
            rows = read_csv(p)
            self.assertEqual(rows[0], ["index", "last", "extra"])
            self.assertEqual(rows[2], ["B", "", "2"])


class FetchTests(unittest.TestCase):
    def test_list_indices_strips_and_drops_blank(self):
        s = FakeSession(indices=None)
        targets, rows = nse.list_indices(s, sleep=lambda _s: None)
        # no indexSymbol in these rows -> the display name is used for the request
        self.assertEqual(targets, [("NIFTY 50", "NIFTY 50"), ("NIFTY BANK", "NIFTY BANK"),
                                   ("NIFTY MIDCAP & SMALL", "NIFTY MIDCAP & SMALL")])
        self.assertEqual(len(rows), 4)

    def test_list_indices_pairs_display_name_with_index_symbol(self):
        s = FakeSession(indices=["NIFTY FINANCIAL SERVICES"],
                        symbols={"NIFTY FINANCIAL SERVICES": "NIFTY FIN SERVICE"})
        targets, _ = nse.list_indices(s, sleep=lambda _s: None)
        self.assertEqual(targets, [("NIFTY FINANCIAL SERVICES", "NIFTY FIN SERVICE")])

    def test_fetch_retries_after_401_and_reprimes_session(self):
        s = FakeSession(overrides={"NIFTY 50": [Resp(401, text="denied"), Resp(body=payload())]})
        data = nse.fetch_index(s, "NIFTY 50", sleep=lambda _s: None)
        self.assertEqual(len(data), 1)
        self.assertEqual(s.index_calls("NIFTY 50"), ["NIFTY 50", "NIFTY 50"])
        self.assertIn(nse.HOME_URL, [u for u, _ in s.calls])

    def test_fetch_retries_on_html_instead_of_json(self):
        s = FakeSession(overrides={"NIFTY 50": [Resp(200, text="<html>blocked</html>"), Resp(body=payload())]})
        self.assertEqual(len(nse.fetch_index(s, "NIFTY 50", sleep=lambda _s: None)), 1)

    def test_fetch_gives_up_after_max_retries(self):
        s = FakeSession(overrides={"NIFTY 50": [Resp(500)] * nse.MAX_RETRIES})
        with self.assertRaises(RuntimeError):
            nse.fetch_index(s, "NIFTY 50", sleep=lambda _s: None)
        self.assertEqual(len(s.index_calls("NIFTY 50")), nse.MAX_RETRIES)

    def test_payload_without_data_is_an_error(self):
        s = FakeSession(overrides={"NIFTY 50": [Resp(body={"oops": 1})] * nse.MAX_RETRIES})
        with self.assertRaises(RuntimeError):
            nse.fetch_index(s, "NIFTY 50", sleep=lambda _s: None)


class RunTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name) / "nse" / "all-index-data"

    def tearDown(self):
        self._tmp.cleanup()

    def run_it(self, session, **kw):
        kw.setdefault("run_date", "20261114")
        return nse.run(session, self.out, sleep=lambda _s: None, **kw)

    def day(self):
        return self.out / "20261114"

    def test_downloads_every_index_into_dated_folder_with_master_file(self):
        stats = self.run_it(FakeSession())
        self.assertEqual(stats, {"new": 2, "skipped": 0, "failed": 0, "empty": 0})
        names = sorted(p.name for p in self.day().iterdir())
        self.assertEqual(names[:2], ["NIFTY_50.csv", "NIFTY_BANK.csv"])
        self.assertTrue(any(n.startswith("NSE_ALL_INDICES_") and n.endswith(".csv") for n in names))
        self.assertEqual(read_csv(self.day() / "NIFTY_50.csv")[0], HEADER)

    def test_rerun_same_day_skips_finished_files(self):
        self.run_it(FakeSession())
        s2 = FakeSession()
        stats = self.run_it(s2)
        self.assertEqual(stats, {"new": 0, "skipped": 2, "failed": 0, "empty": 0})
        self.assertEqual(s2.index_calls(), [])          # nothing re-fetched

    def test_request_uses_index_symbol_but_file_uses_display_name(self):
        s = FakeSession(indices=["NIFTY FINANCIAL SERVICES"],
                        symbols={"NIFTY FINANCIAL SERVICES": "NIFTY FIN SERVICE"})
        stats = self.run_it(s)
        self.assertEqual(stats["new"], 1)
        self.assertEqual(s.index_calls(), ["NIFTY FIN SERVICE"])
        self.assertTrue((self.day() / "NIFTY_FINANCIAL_SERVICES.csv").exists())

    def test_index_with_no_constituents_is_counted_empty_and_no_file_written(self):
        s = FakeSession(overrides={"NIFTY 50": Resp(body={"data": []})})
        stats = self.run_it(s)
        self.assertEqual(stats, {"new": 1, "skipped": 0, "failed": 0, "empty": 1})
        self.assertFalse((self.day() / "NIFTY_50.csv").exists())

    def test_header_only_file_from_an_earlier_bad_run_is_redownloaded(self):
        self.day().mkdir(parents=True)
        (self.day() / "NIFTY_50.csv").write_text(",".join(nse.HEADER) + "\n")
        s = FakeSession()
        stats = self.run_it(s)
        self.assertEqual(stats["new"], 2)
        self.assertIn("NIFTY 50", s.index_calls())

    def test_force_downloads_again(self):
        self.run_it(FakeSession())
        s2 = FakeSession()
        stats = self.run_it(s2, force=True)
        self.assertEqual(stats["new"], 2)
        self.assertEqual(sorted(s2.index_calls()), ["NIFTY 50", "NIFTY BANK"])

    def test_empty_file_is_not_treated_as_done(self):
        self.day().mkdir(parents=True)
        (self.day() / "NIFTY_50.csv").write_text("")
        stats = self.run_it(FakeSession())
        self.assertEqual(stats["new"], 2)

    def test_one_failing_index_does_not_stop_the_rest(self):
        s = FakeSession(overrides={"NIFTY 50": [Resp(500)] * nse.MAX_RETRIES})
        stats = self.run_it(s)
        self.assertEqual(stats, {"new": 1, "skipped": 0, "failed": 1, "empty": 0})
        self.assertTrue((self.day() / "NIFTY_BANK.csv").exists())
        self.assertFalse((self.day() / "NIFTY_50.csv").exists())

    def test_new_day_gets_its_own_folder(self):
        self.run_it(FakeSession(), run_date="20261114")
        stats = self.run_it(FakeSession(), run_date="20261115")
        self.assertEqual(stats["new"], 2)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["20261114", "20261115"])


class MainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name) / "all-index-data"

    def tearDown(self):
        self._tmp.cleanup()

    def main(self, session, extra=()):
        with mock.patch("nse_indices.make_session", return_value=session), \
             mock.patch("nse_indices.setup_logging"), mock.patch("nse_indices.time.sleep"):
            return nse.main(["--out", str(self.out), *extra])

    def test_default_output_is_data_nse_index(self):
        self.assertEqual(nse.parse_args([]).out, PROJECT_ROOT / "data_nse_index")

    def test_exit_0_on_success(self):
        self.assertEqual(self.main(FakeSession()), 0)

    def test_exit_1_when_any_index_failed(self):
        s = FakeSession(overrides={"NIFTY 50": [Resp(500)] * nse.MAX_RETRIES})
        self.assertEqual(self.main(s), 1)

    def test_exit_2_when_index_list_unavailable(self):
        s = FakeSession()
        s.routes[nse.INDICES_URL] = [Resp(503)] * nse.MAX_RETRIES
        self.assertEqual(self.main(s), 2)

    def test_force_flag_is_passed_through(self):
        self.main(FakeSession())
        s2 = FakeSession()
        self.main(s2, ["--force"])
        self.assertEqual(len(s2.index_calls()), 2)


if __name__ == "__main__":
    unittest.main()
