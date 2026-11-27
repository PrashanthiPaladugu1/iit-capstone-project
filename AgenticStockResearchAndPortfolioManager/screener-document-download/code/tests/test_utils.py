import support  # noqa: F401
import tempfile
import unittest
from pathlib import Path

from fs_utils import now_iso, sanitize_filename
from models import Doc
from watchlist import read_watchlist


class SanitizeFilenameTests(unittest.TestCase):
    def test_replaces_spaces_and_symbols(self):
        self.assertEqual(sanitize_filename("Annual Report 2026"), "Annual_Report_2026")

    def test_collapses_repeats_and_trims(self):
        self.assertEqual(sanitize_filename("  a//b::c  "), "a_b_c")

    def test_keeps_dash_and_underscore(self):
        self.assertEqual(sanitize_filename("M&M-Fin"), "M_M-Fin")

    def test_empty_falls_back(self):
        self.assertEqual(sanitize_filename("///"), "document")

    def test_blocks_path_traversal(self):
        self.assertNotIn("/", sanitize_filename("../../etc/passwd"))
        self.assertNotIn("..", sanitize_filename("../../etc/passwd"))


class NowIsoTests(unittest.TestCase):
    def test_is_utc_iso(self):
        self.assertTrue(now_iso().endswith("+00:00"))


class DocTests(unittest.TestCase):
    def test_base_name(self):
        self.assertEqual(Doc("Transcript", "Nov_2026", "u").base_name, "Transcript_Nov_2026")
        self.assertEqual(Doc("Annual_Report", "2026", "u").base_name, "Annual_Report_2026")


class WatchlistTests(unittest.TestCase):
    def _read(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "w.txt"
            p.write_text(text, encoding="utf-8")
            return read_watchlist(p)

    def test_ignores_blank_and_comments(self):
        self.assertEqual(self._read("# head\nTCS\n\n   \n#INFY\nMEESHO\n"), ["TCS", "MEESHO"])

    def test_strips_whitespace_and_trailing_comment(self):
        self.assertEqual(self._read("  TCS  # note\n"), ["TCS"])

    def test_dedupes_case_insensitively_preserving_order(self):
        self.assertEqual(self._read("TCS\ntcs\nINFY\n"), ["TCS", "INFY"])

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            read_watchlist(Path("/nonexistent/watchlist.txt"))


if __name__ == "__main__":
    unittest.main()
