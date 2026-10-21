import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from honeyfile import build_parser, compare, default_state, inspect, main, snapshot


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

    def test_every_command_and_option_has_help(self):
        parser = build_parser()
        commands = next(action for action in parser._actions if action.dest == "command")
        for choice in commands._choices_actions:
            self.assertTrue(choice.help, choice.dest)
        for name, subparser in commands.choices.items():
            for action in subparser._actions:
                if action.dest != "help":
                    self.assertTrue(action.help, f"{name} {action.dest}")

    def test_snapshot_treats_mid_read_deletion_as_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "canary.txt"
            target.write_text("canary", encoding="utf-8")
            with mock.patch("honeyfile.hash_file", side_effect=FileNotFoundError):
                self.assertEqual(snapshot(target), {"exists": False})

    def test_watch_rejects_missing_state(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "canary.txt"
            target.write_text("canary", encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(main(["watch", str(target)]), 2)
            self.assertIn("Cannot read canary state", stderr.getvalue())

    def test_watch_keeps_running_after_read_error(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "canary.txt"
            with redirect_stdout(io.StringIO()):
                main(["create", str(target)])
            real_inspect = inspect
            results = iter([None, PermissionError("locked"), None])

            def flaky_inspect(*args):
                result = next(results)
                if isinstance(result, Exception):
                    raise result
                return real_inspect(*args)

            target.write_text("changed", encoding="utf-8")
            stdout, stderr = io.StringIO(), io.StringIO()
            sleeps = mock.Mock(side_effect=[None, KeyboardInterrupt])
            with mock.patch("honeyfile.inspect", flaky_inspect), mock.patch("honeyfile.time.sleep", sleeps), redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(main(["watch", str(target), "--interval", "0"]), 0)
            self.assertIn("Cannot inspect canary: locked", stderr.getvalue())
            self.assertIn("content_changed", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
