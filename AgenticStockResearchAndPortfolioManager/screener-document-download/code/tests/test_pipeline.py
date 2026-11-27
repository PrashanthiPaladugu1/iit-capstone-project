import support  # noqa: F401
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import requests

from history import load_history
from models import AuthError
from pipeline import process_symbol
from support import FakeFetcher, FakeResponse, PDF_BYTES, XLSX_BYTES, fixture_text

PAGE = "https://www.screener.in/company/ABC/consolidated/"
STANDALONE = "https://www.screener.in/company/ABC/"
EXPORT = "https://www.screener.in/user/company/export/42/"
ALL = {"Annual_Report", "Transcript", "PPT"}

AR26 = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/ar2026.pdf"
AR13Z = "https://archives.nseindia.com/annual_reports/AR_2013.zip"
AR13B = "https://www.bseindia.com/bseplus/AnnualReport/ar2013b.pdf"
T_OCT = "https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname=t-oct26.pdf"
P_OCT = "https://example.com/Q2%20Fact%20Sheet.pdf"
T_JUL = "https://example.com/t-jul26.pdf"
ALL_URLS = [AR26, AR13Z, AR13B, T_OCT, P_OCT, T_JUL]


def routes(overrides=None, page_html=None):
    r = {("GET", PAGE): FakeResponse(200, text=page_html or fixture_text("company.html")),
         ("POST", EXPORT): FakeResponse(200, content=XLSX_BYTES)}
    for u in ALL_URLS:
        r[("GET", u)] = FakeResponse(200, content=PDF_BYTES if not u.endswith(".zip") else XLSX_BYTES)
    r.update(overrides or {})
    return r


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.out = self.root / "data"
        self.hist_path = self.root / "h.json"
        self.history = {}

    def tearDown(self):
        self._tmp.cleanup()

    def run_symbol(self, fetcher, **kw):
        args = dict(kinds=ALL, dry_run=False)
        args.update(kw)
        return process_symbol("abc", fetcher, self.history, self.out, self.hist_path, **args)

    def files(self):
        d = self.out / "ABC"
        return sorted(p.name for p in d.iterdir()) if d.exists() else []

    def test_stop_event_already_set_does_nothing(self):
        ev = threading.Event()
        ev.set()
        f = FakeFetcher(routes())
        stats = self.run_symbol(f, stop=ev)
        self.assertEqual(stats, {"new": 0, "skipped": 0, "failed": 0})
        self.assertEqual(f.calls, [])

    def test_stop_event_set_mid_symbol_stops_before_next_document(self):
        ev = threading.Event()

        class StopAfterFirstDoc(FakeFetcher):
            def request(self, method, url, **kw):
                resp = super().request(method, url, **kw)
                if url in ALL_URLS:
                    ev.set()
                return resp

        f = StopAfterFirstDoc(routes())
        self.run_symbol(f, excel=False, stop=ev)
        self.assertEqual(len([u for u in f.urls() if u in ALL_URLS]), 1)

    def test_first_run_downloads_everything_into_data_symbol_folder(self):
        stats = self.run_symbol(FakeFetcher(routes()))
        self.assertEqual(stats, {"new": 7, "skipped": 0, "failed": 0})  # 6 docs + excel
        self.assertEqual(self.files(), sorted([
            "Financials_ABC.xlsx", "Annual_Report_2026.pdf", "Annual_Report_2013.zip",
            "Annual_Report_2013.pdf", "Transcript_Oct_2026.pdf", "PPT_Oct_2026.pdf",
            "Transcript_Jul_2026.pdf"]))

    def test_second_run_is_incremental(self):
        self.run_symbol(FakeFetcher(routes()))
        f2 = FakeFetcher(routes())
        stats = self.run_symbol(f2)
        self.assertEqual(stats["new"], 1)       # only the refreshed excel snapshot
        self.assertEqual(stats["skipped"], 6)
        for u in ALL_URLS:
            self.assertNotIn(u, f2.urls())      # no document re-downloaded

    def test_new_filing_downloaded_alone(self):
        self.run_symbol(FakeFetcher(routes()))
        new_url = "https://example.com/new-transcript.pdf"
        html = fixture_text("company.html").replace(
            '<div class="ink-600 nowrap">Oct 2026</div>',
            '<div class="ink-600 nowrap">Nov 2026</div>'
            f'<a class="button-chip" href="{new_url}">Transcript</a></li><li><div>Oct 2026</div>', 1)
        f2 = FakeFetcher(routes({("GET", PAGE): FakeResponse(200, text=html),
                                 ("GET", new_url): FakeResponse(200, content=PDF_BYTES)}))
        self.run_symbol(f2, excel=False)
        self.assertIn(new_url, f2.urls())
        self.assertIn("Transcript_Nov_2026.pdf", self.files())

    def test_history_persisted_with_metadata(self):
        self.run_symbol(FakeFetcher(routes()))
        h = load_history(self.hist_path)["ABC"]
        self.assertEqual(h[AR26]["file"], "Annual_Report_2026.pdf")
        self.assertEqual(h[T_OCT]["type"], "Transcript")
        self.assertIn("downloaded_at", h[AR26])
        self.assertIn("__excel__", h)

    def test_history_is_what_skips_not_just_disk(self):
        self.run_symbol(FakeFetcher(routes()))
        (self.out / "ABC" / "Annual_Report_2026.pdf").unlink()  # user deleted the file
        f2 = FakeFetcher(routes())
        self.run_symbol(f2)
        self.assertNotIn(AR26, f2.urls())  # still in history -> not re-fetched

    def test_file_on_disk_but_not_in_history_is_adopted_not_redownloaded(self):
        d = self.out / "ABC"
        d.mkdir(parents=True)
        (d / "Annual_Report_2026.pdf").write_bytes(PDF_BYTES)
        f = FakeFetcher(routes())
        self.run_symbol(f, excel=False)
        self.assertNotIn(AR26, f.urls())
        self.assertTrue(self.history["ABC"][AR26].get("adopted"))

    def test_failed_download_not_recorded_and_retried_next_run(self):
        f1 = FakeFetcher(routes({("GET", T_JUL): FakeResponse(403)}))
        stats = self.run_symbol(f1)
        self.assertEqual(stats["failed"], 1)
        self.assertNotIn(T_JUL, self.history["ABC"])
        self.assertNotIn("Transcript_Jul_2026.pdf", self.files())
        f2 = FakeFetcher(routes())
        self.run_symbol(f2)
        self.assertIn(T_JUL, f2.urls())
        self.assertIn("Transcript_Jul_2026.pdf", self.files())

    def test_network_exception_on_one_doc_does_not_stop_others(self):
        f = FakeFetcher(routes({("GET", AR26): requests.ConnectionError("down")}))
        stats = self.run_symbol(f)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["new"], 6)

    def test_dry_run_downloads_and_records_nothing(self):
        f = FakeFetcher(routes())
        stats = self.run_symbol(f, dry_run=True)
        self.assertEqual(stats["new"], 7)
        self.assertEqual(self.files(), [])
        self.assertFalse(self.hist_path.exists())
        self.assertEqual(f.urls("POST"), [])
        self.assertEqual(f.urls(), [PAGE])

    def test_kinds_filter(self):
        stats = self.run_symbol(FakeFetcher(routes()), kinds={"Transcript"}, excel=False)
        self.assertEqual(stats["new"], 2)
        self.assertEqual(self.files(), ["Transcript_Jul_2026.pdf", "Transcript_Oct_2026.pdf"])

    def test_no_excel_flag(self):
        f = FakeFetcher(routes())
        self.run_symbol(f, excel=False)
        self.assertEqual(f.urls("POST"), [])
        self.assertNotIn("Financials_ABC.xlsx", self.files())

    def test_excel_failure_counted_but_documents_still_download(self):
        f = FakeFetcher(routes({("POST", EXPORT): FakeResponse(500)}))
        stats = self.run_symbol(f)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["new"], 6)

    def test_excel_refreshed_every_run(self):
        self.run_symbol(FakeFetcher(routes()))
        f2 = FakeFetcher(routes({("POST", EXPORT): FakeResponse(200, content=b"PK\x03\x04NEW")}))
        self.run_symbol(f2)
        self.assertEqual((self.out / "ABC" / "Financials_ABC.xlsx").read_bytes(), b"PK\x03\x04NEW")

    def test_uses_consolidated_by_default_and_standalone_on_request(self):
        f = FakeFetcher(routes())
        self.run_symbol(f, excel=False)
        self.assertEqual(f.urls()[0], PAGE)
        f2 = FakeFetcher(routes({("GET", STANDALONE): FakeResponse(200, text=fixture_text("company.html"))}))
        self.run_symbol(f2, excel=False, standalone=True)
        self.assertEqual(f2.urls()[0], STANDALONE)

    def test_404_company_counts_as_failure(self):
        f = FakeFetcher({("GET", PAGE): FakeResponse(404)})
        self.assertEqual(self.run_symbol(f)["failed"], 1)

    def test_login_redirect_raises_auth_error(self):
        f = FakeFetcher({("GET", PAGE): FakeResponse(200, text="login",
                                                      url="https://www.screener.in/login/?next=/x")})
        with self.assertRaises(AuthError):
            self.run_symbol(f)

    def test_unexpected_status_counts_as_failure(self):
        f = FakeFetcher({("GET", PAGE): FakeResponse(500)})
        self.assertEqual(self.run_symbol(f)["failed"], 1)

    def test_page_without_documents_is_not_an_error(self):
        f = FakeFetcher(routes(page_html="<html></html>"))
        stats = self.run_symbol(f, excel=False)
        self.assertEqual(stats, {"new": 0, "skipped": 0, "failed": 0})

    def test_duplicate_filenames_do_not_overwrite(self):
        self.run_symbol(FakeFetcher(routes()), excel=False)
        self.assertEqual(len([f for f in self.files() if f.startswith("Annual_Report_2013")]), 2)


class ParallelStocksTests(unittest.TestCase):
    """Real pipeline, several stocks on separate threads, one shared history dict + file."""

    def test_parallel_stocks_share_history_without_losing_records(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            hist_path, history, out = root / "h.json", {}, root / "data"
            syms = [f"S{i}" for i in range(8)]

            def routes_for(sym):
                page = f"https://www.screener.in/company/{sym}/consolidated/"
                r = routes()
                r[("GET", page)] = r.pop(("GET", PAGE))
                return r

            errors, results = [], {}

            def work(sym):
                try:
                    results[sym] = process_symbol(sym, FakeFetcher(routes_for(sym)), history, out,
                                                  hist_path, ALL, False)
                except Exception as exc:  # pragma: no cover
                    errors.append(exc)

            threads = [threading.Thread(target=work, args=(s,)) for s in syms]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
            saved = load_history(hist_path)
            self.assertEqual(saved, history)
            for s in syms:
                self.assertEqual(results[s]["new"], 7)
                self.assertEqual(len(saved[s]), 7)          # 6 docs + __excel__
                self.assertEqual(len(list((out / s).iterdir())), 7)


if __name__ == "__main__":
    unittest.main()
