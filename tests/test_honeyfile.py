import tempfile
import unittest
from pathlib import Path

from honeyfile import compare, default_state, inspect, main


class HoneyfileTests(unittest.TestCase):
    def test_compare_detects_delete_and_change(self):
        self.assertEqual(compare({"exists": True}, {"exists": False}), ["deleted"])
        events = compare({"exists": True, "file_id": "1", "sha256": "a", "mtime_ns": 1}, {"exists": True, "file_id": "1", "sha256": "b", "mtime_ns": 2})
        self.assertEqual(events, ["content_changed"])

    def test_create_and_detect_change(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "canary.txt"
            self.assertEqual(main(["create", str(target)]), 0)
            self.assertEqual(inspect(target, default_state(target))[0], [])
            target.write_text("changed", encoding="utf-8")
            self.assertIn("content_changed", inspect(target, default_state(target))[0])


if __name__ == "__main__":
    unittest.main()
