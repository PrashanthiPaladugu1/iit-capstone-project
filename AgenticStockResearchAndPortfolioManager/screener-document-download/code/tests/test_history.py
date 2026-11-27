import support  # noqa: F401
import json
import tempfile
import threading
import unittest
from pathlib import Path

from history import load_history, record_entry, save_history


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "sub" / "h.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_returns_empty(self):
        self.assertEqual(load_history(self.path), {})

    def test_roundtrip_and_creates_parent(self):
        data = {"TCS": {"http://x/a.pdf": {"file": "a.pdf"}}}
        save_history(self.path, data)
        self.assertEqual(load_history(self.path), data)

    def test_save_leaves_no_temp_files(self):
        save_history(self.path, {"A": {}})
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["h.json"])

    def test_corrupt_file_is_preserved_not_lost(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(load_history(self.path), {})
        backup = self.path.with_suffix(".json.corrupt")
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_text(encoding="utf-8"), "{not json")

    def test_non_dict_json_returns_empty(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps([1, 2]), encoding="utf-8")
        self.assertEqual(load_history(self.path), {})


class RecordEntryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "h.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_record_entry_sets_in_memory_and_saves(self):
        h = {}
        record_entry(h, self.path, "TCS", "http://x/a.pdf", {"file": "a.pdf"})
        self.assertEqual(h, {"TCS": {"http://x/a.pdf": {"file": "a.pdf"}}})
        self.assertEqual(load_history(self.path), h)

    def test_concurrent_records_from_many_threads_all_persist(self):
        h, errors = {}, []

        def work(n):
            try:
                for j in range(25):
                    record_entry(h, self.path, f"S{n}", f"http://x/{n}/{j}", {"file": f"{j}.pdf"})
            except Exception as exc:  # pragma: no cover - only on a race
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        saved = load_history(self.path)
        self.assertEqual(saved, h)
        self.assertEqual(sum(len(v) for v in saved.values()), 8 * 25)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["h.json"])


if __name__ == "__main__":
    unittest.main()
