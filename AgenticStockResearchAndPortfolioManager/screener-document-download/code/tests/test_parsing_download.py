import support
import tempfile
import unittest
from pathlib import Path

import requests

from excel_export import export_excel
from file_downloader import download_file, pick_filename, url_extension
from html_parser import parse_documents
from models import Doc
from support import FakeFetcher, FakeResponse, PDF_BYTES, XLSX_BYTES, fixture_text


class ParseDocumentsTests(unittest.TestCase):
    def setUp(self):
        self.docs = parse_documents(fixture_text("company.html"))

    def _by(self, kind):
        return [d for d in self.docs if d.kind == kind]

    def test_annual_reports_found_with_year_labels(self):
        self.assertEqual([d.label for d in self._by("Annual_Report")], ["2026", "2013", "2013"])

    def test_transcripts_and_ppts(self):
        self.assertEqual([(d.label) for d in self._by("Transcript")], ["Oct_2026", "Jul_2026"])
        self.assertEqual([(d.label) for d in self._by("PPT")], ["Oct_2026"])

    def test_ppt_without_link_is_skipped(self):
        self.assertNotIn("Jul_2026", [d.label for d in self._by("PPT")])

    def test_rec_and_ai_summary_excluded(self):
        urls = " ".join(d.url for d in self.docs)
        self.assertNotIn("call.mp3", urls)
        self.assertEqual({d.kind for d in self.docs}, {"Annual_Report", "Transcript", "PPT"})

    def test_announcements_excluded(self):
        self.assertNotIn("ann.pdf", " ".join(d.url for d in self.docs))

    def test_row_without_parsable_date_skipped(self):
        self.assertNotIn("ignored.pdf", " ".join(d.url for d in self.docs))

    def test_urls_are_absolute_and_unique(self):
        urls = [d.url for d in self.docs]
        self.assertTrue(all(u.startswith("http") for u in urls))
        self.assertEqual(len(urls), len(set(urls)))

    def test_no_documents_section(self):
        self.assertEqual(parse_documents("<html><body>nothing</body></html>"), [])

    def test_relative_href_made_absolute(self):
        html = ('<section id="documents"><div class="annual-reports"><ul class="list-links">'
                '<li><a href="/x/ar.pdf">Annual Report 2020</a></li></ul></div></section>')
        self.assertEqual(parse_documents(html)[0].url, "https://www.screener.in/x/ar.pdf")


class FilenameTests(unittest.TestCase):
    def test_url_extension(self):
        self.assertEqual(url_extension("https://a/b/c.PDF"), ".pdf")
        self.assertEqual(url_extension("https://a/b/c.zip"), ".zip")
        self.assertEqual(url_extension("https://a/AnnPdfOpen.aspx?Pname=x.pdf"), ".pdf")
        self.assertEqual(url_extension("https://a/file.exe"), ".pdf")

    def test_pick_filename_and_collisions(self):
        d = Doc("Annual_Report", "2013", "https://a/x.pdf")
        self.assertEqual(pick_filename(d, set()), "Annual_Report_2013.pdf")
        self.assertEqual(pick_filename(d, {"Annual_Report_2013.pdf"}), "Annual_Report_2013_2.pdf")
        self.assertEqual(pick_filename(d, {"Annual_Report_2013.pdf", "Annual_Report_2013_2.pdf"}),
                         "Annual_Report_2013_3.pdf")

    def test_zip_keeps_extension(self):
        d = Doc("Annual_Report", "2013", "https://a/AR.zip")
        self.assertEqual(pick_filename(d, set()), "Annual_Report_2013.zip")


class DownloadFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self._tmp.name) / "a.pdf"

    def tearDown(self):
        self._tmp.cleanup()

    def _dl(self, resp):
        f = FakeFetcher({("GET", "http://x/a.pdf"): resp})
        download_file(f, "http://x/a.pdf", self.dest)

    def test_saves_valid_pdf(self):
        self._dl(FakeResponse(200, content=PDF_BYTES))
        self.assertEqual(self.dest.read_bytes(), PDF_BYTES)
        self.assertFalse(Path(str(self.dest) + ".part").exists())

    def test_http_error_raises_and_writes_nothing(self):
        with self.assertRaises(requests.HTTPError):
            self._dl(FakeResponse(403))
        self.assertFalse(self.dest.exists())

    def test_html_instead_of_pdf_rejected_and_cleaned(self):
        with self.assertRaises(ValueError):
            self._dl(FakeResponse(200, content=b"<html>blocked</html>"))
        self.assertFalse(self.dest.exists())
        self.assertFalse(Path(str(self.dest) + ".part").exists())

    def test_empty_body_rejected(self):
        with self.assertRaises(ValueError):
            self._dl(FakeResponse(200, content=b""))
        self.assertFalse(self.dest.exists())

    def test_zip_not_pdf_checked(self):
        self.dest = Path(self._tmp.name) / "a.zip"
        f = FakeFetcher({("GET", "http://x/a.pdf"): FakeResponse(200, content=XLSX_BYTES)})
        download_file(f, "http://x/a.pdf", self.dest)
        self.assertTrue(self.dest.exists())

    def test_response_closed(self):
        r = FakeResponse(200, content=PDF_BYTES)
        self._dl(r)
        self.assertTrue(r.closed)


class ExcelExportTests(unittest.TestCase):
    PAGE = "https://www.screener.in/company/ABC/consolidated/"
    EXPORT = "https://www.screener.in/user/company/export/42/"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self._tmp.name) / "d" / "F.xlsx"

    def tearDown(self):
        self._tmp.cleanup()

    def test_posts_form_with_csrf_and_saves(self):
        f = FakeFetcher({("POST", self.EXPORT): FakeResponse(200, content=XLSX_BYTES)})
        export_excel(f, self.PAGE, fixture_text("company.html"), self.dest)
        self.assertEqual(self.dest.read_bytes(), XLSX_BYTES)
        _, _, kw = f.calls[0]
        self.assertEqual(kw["data"]["csrfmiddlewaretoken"], "TOKEN123")
        self.assertEqual(kw["headers"]["Referer"], self.PAGE)

    def test_button_missing_raises(self):
        with self.assertRaises(ValueError):
            export_excel(FakeFetcher(), self.PAGE, "<html></html>", self.dest)

    def test_non_xlsx_response_rejected(self):
        f = FakeFetcher({("POST", self.EXPORT): FakeResponse(200, content=b"<html>login</html>")})
        with self.assertRaises(ValueError):
            export_excel(f, self.PAGE, fixture_text("company.html"), self.dest)
        self.assertFalse(self.dest.exists())

    def test_http_error_raises(self):
        f = FakeFetcher({("POST", self.EXPORT): FakeResponse(403)})
        with self.assertRaises(requests.HTTPError):
            export_excel(f, self.PAGE, fixture_text("company.html"), self.dest)

    def test_overwrites_existing(self):
        self.dest.parent.mkdir(parents=True)
        self.dest.write_bytes(b"old")
        f = FakeFetcher({("POST", self.EXPORT): FakeResponse(200, content=XLSX_BYTES)})
        export_excel(f, self.PAGE, fixture_text("company.html"), self.dest)
        self.assertEqual(self.dest.read_bytes(), XLSX_BYTES)


if __name__ == "__main__":
    unittest.main()
