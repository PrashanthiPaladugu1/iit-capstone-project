import support  # noqa: F401
import tempfile
import unittest
from pathlib import Path

from symbols_csv import read_symbols_from_csv

HEADER = "Name,BSE Code,NSE Code,ISIN Code,Industry\n"


class SymbolsCsvTests(unittest.TestCase):
    def _read(self, body, header=HEADER, **kw):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.csv"
            p.write_text(header + body, encoding="utf-8")
            return read_symbols_from_csv(p, **kw)

    def test_prefers_nse_code(self):
        self.assertEqual(self._read("20 Microns,533022,20MICRONS,INE1,x\n"), ["20MICRONS"])

    def test_falls_back_to_bse_code_when_no_nse(self):
        self.assertEqual(self._read("3B Films,544412,,INE2,x\n"), ["544412"])

    def test_skips_rows_with_no_code(self):
        self.assertEqual(self._read("Ghost,,,INE3,x\nA,1,AAA,INE4,x\n"), ["AAA"])

    def test_preserves_order_and_dedupes(self):
        body = "A,1,AAA,i,x\nB,2,BBB,i,x\nA2,1,AAA,i,x\n"
        self.assertEqual(self._read(body), ["AAA", "BBB"])

    def test_strips_whitespace_and_handles_bom(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.csv"
            p.write_bytes(b"\xef\xbb\xbf" + (HEADER + "A, 1 , AAA ,i,x\n").encode())
            self.assertEqual(read_symbols_from_csv(p), ["AAA"])

    def test_start_and_limit_for_batching(self):
        body = "".join(f"S{i},{i},SYM{i},i,x\n" for i in range(10))
        self.assertEqual(self._read(body, start=3, limit=2), ["SYM3", "SYM4"])
        self.assertEqual(self._read(body, start=8), ["SYM8", "SYM9"])
        self.assertEqual(len(self._read(body, limit=4)), 4)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            read_symbols_from_csv(Path("/nonexistent/x.csv"))

    def test_missing_columns_raises_clear_error(self):
        with self.assertRaises(ValueError) as cm:
            self._read("A,1\n", header="Name,Foo\n")
        self.assertIn("NSE Code", str(cm.exception))

    def test_real_file_if_present(self):
        from config import PROJECT_ROOT
        files = sorted(PROJECT_ROOT.glob("equitydata-screener-all-stocks-*.csv"))
        if not files:
            self.skipTest("no real CSV in project root")
        syms = read_symbols_from_csv(files[-1])
        self.assertGreater(len(syms), 1000)
        self.assertEqual(len(syms), len(set(syms)))
        self.assertTrue(all(s and s == s.strip() for s in syms))


if __name__ == "__main__":
    unittest.main()
