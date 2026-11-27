import support  # noqa: F401
import tempfile
import threading
import unittest
from pathlib import Path

from tracker import load_tracker, mark_done


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "sub" / "download_tracker.txt"

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_is_empty_set(self):
        self.assertEqual(load_tracker(self.path), set())

    def test_mark_done_writes_one_uppercase_symbol_per_line_and_creates_parent(self):
        mark_done(self.path, "tcs")
        mark_done(self.path, "INFY")
        self.assertEqual(self.path.read_text().splitlines(), ["TCS", "INFY"])
        self.assertEqual(load_tracker(self.path), {"TCS", "INFY"})

    def test_mark_done_twice_does_not_duplicate(self):
        mark_done(self.path, "TCS")
        mark_done(self.path, "tcs")
        self.assertEqual(self.path.read_text().splitlines(), ["TCS"])

    def test_load_ignores_blank_lines_comments_and_case(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("# my notes\n\n  tcs  \nInfy\n#MEESHO\n", encoding="utf-8")
        self.assertEqual(load_tracker(self.path), {"TCS", "INFY"})

    def test_concurrent_marks_all_persist_without_corruption(self):
        syms = [f"S{i}" for i in range(200)]
        threads = [threading.Thread(target=lambda chunk=syms[i::8]: [mark_done(self.path, s) for s in chunk])
                   for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        lines = self.path.read_text().splitlines()
        self.assertEqual(len(lines), 200)
        self.assertEqual(set(lines), set(syms))


if __name__ == "__main__":
    unittest.main()
