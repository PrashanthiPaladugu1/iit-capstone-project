import support  # noqa: F401
import tempfile
import unittest
from datetime import date
from pathlib import Path

import bhavcopy_index_filter as bf

HDR = "SYMBOL, SERIES, DATE1, CLOSE_PRICE"
DAY1 = HDR + "\nAAA, EQ, 01-Jan-2024, 10\nAAA, N1, 01-Jan-2024, 99\nBBB, EQ, 01-Jan-2024, 20\nZZZ, EQ, 01-Jan-2024, 30\n"
DAY2 = HDR + "\nAAA, EQ, 02-Jan-2024, 11\nZZZ, EQ, 02-Jan-2024, 31\n"
DAY0 = HDR + "\nAAA, EQ, 29-Dec-2023, 9\n"


class IndexFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_latest_dated_folder_is_used(self):
        for d in ("20260101", "20260301", "notes"):
            (self.root / d).mkdir()
            (self.root / d / "NIFTY_50.csv").write_text("symbol\nX\n")
        self.assertEqual(bf.find_index_file(self.root, "NIFTY_50").parent.name, "20260301")

    def test_missing_index_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            bf.find_index_file(self.root, "NIFTY_50")

    def test_symbols_skip_index_row_and_duplicates(self):
        p = self.root / "i.csv"
        p.write_text("symbol,open\nNIFTY 50,1\nM&M,2\nBAJAJ-AUTO,3\nm&m,4\n")
        self.assertEqual(bf.read_index_symbols(p), ["M&M", "BAJAJ-AUTO"])

    def test_bad_header_rejected(self):
        p = self.root / "i.csv"
        p.write_text("name,open\nA,1\n")
        with self.assertRaises(ValueError):
            bf.read_index_symbols(p)


class FileOrderTests(unittest.TestCase):
    def test_file_date_parsed_from_name(self):
        self.assertEqual(bf.file_date(Path("sec_bhavdata_full_22062022.csv")), date(2022, 6, 22))
        self.assertIsNone(bf.file_date(Path("sec_bhavdata_full_bad.csv")))

    def test_daily_files_sorted_by_date_not_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for n in ("sec_bhavdata_full_01022024.csv", "sec_bhavdata_full_31122023.csv",
                      "sec_bhavdata_full_junk.csv"):
                (d / n).write_text(HDR + "\n")
            self.assertEqual([p.name for p in bf.daily_files(d)],
                             ["sec_bhavdata_full_31122023.csv", "sec_bhavdata_full_01022024.csv"])


class RunTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.src, self.out = root / "src", root / "out"
        self.src.mkdir()
        # file names sort differently from dates on purpose (01/02/2024 < 29/12/2023 as text)
        (self.src / "sec_bhavdata_full_01012024.csv").write_text(DAY1)
        (self.src / "sec_bhavdata_full_02012024.csv").write_text(DAY2)
        (self.src / "sec_bhavdata_full_29122023.csv").write_text(DAY0)

    def tearDown(self):
        self._tmp.cleanup()

    def test_one_file_per_symbol_oldest_first(self):
        stats, missing = bf.run(self.src, self.out, ["AAA", "BBB"], {"EQ"})
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["AAA.csv", "BBB.csv"])
        self.assertEqual((self.out / "AAA.csv").read_text(),
                         HDR + "\nAAA, EQ, 29-Dec-2023, 9\nAAA, EQ, 01-Jan-2024, 10\nAAA, EQ, 02-Jan-2024, 11\n")
        self.assertEqual((self.out / "BBB.csv").read_text(), HDR + "\nBBB, EQ, 01-Jan-2024, 20\n")
        self.assertEqual((stats["new"], stats["rows"], stats["days"], missing), (2, 4, 3, []))

    def test_series_filter_and_all(self):
        bf.run(self.src, self.out, ["AAA"], None)
        self.assertIn("N1", (self.out / "AAA.csv").read_text())
        bf.run(self.src, self.out, ["AAA"], {"EQ"})
        self.assertNotIn("N1", (self.out / "AAA.csv").read_text())

    def test_symbol_without_rows_reported_and_not_written(self):
        stats, missing = bf.run(self.src, self.out, ["AAA", "QQQ"], {"EQ"})
        self.assertEqual(missing, ["QQQ"])
        self.assertFalse((self.out / "QQQ.csv").exists())

    def test_rerun_unchanged_then_updated_then_stale_removed(self):
        bf.run(self.src, self.out, ["AAA", "BBB"], {"EQ"})
        stats, _ = bf.run(self.src, self.out, ["AAA", "BBB"], {"EQ"})
        self.assertEqual((stats["new"], stats["updated"], stats["unchanged"]), (0, 0, 2))

        (self.src / "sec_bhavdata_full_03012024.csv").write_text(HDR + "\nAAA, EQ, 03-Jan-2024, 12\n")
        stats, _ = bf.run(self.src, self.out, ["AAA", "BBB"], {"EQ"})
        self.assertEqual((stats["updated"], stats["unchanged"]), (1, 1))

        stats, _ = bf.run(self.src, self.out, ["AAA"], {"EQ"})  # BBB left the index
        self.assertEqual(stats["removed"], 1)
        self.assertFalse((self.out / "BBB.csv").exists())

    def test_missing_or_empty_source_raises(self):
        with self.assertRaises(FileNotFoundError):
            bf.run(self.src / "nope", self.out, ["AAA"], None)
        empty = self.src.parent / "empty"
        empty.mkdir()
        with self.assertRaises(FileNotFoundError):
            bf.run(empty, self.out, ["AAA"], None)


if __name__ == "__main__":
    unittest.main()
