"""The platform in a subfolder of someone else's repository (docs/VDI-SETUP.md Part 1; app.experiment.instrument):
its git checks look only at its own folder, from the repository's real root, and its identity is our source commit
from PLATFORM_SOURCE.json, recorded beside the host repository's commit."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.experiment import instrument

IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@t"]


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *IDENTITY, *args], check=True, capture_output=True, text=True).stdout.strip()


class PlatformInASubfolder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.host = Path(self.tmp.name) / "client-repo"
        (self.host / "src").mkdir(parents=True)
        (self.host / "src" / "App.cs").write_text("class App {}\n")
        git(self.host, "init", "-q", "-b", "main")
        git(self.host, "add", "-A")
        git(self.host, "commit", "-q", "-m", "the client's own history")
        git(self.host, "switch", "-q", "-c", "rohit/platform")
        self.platform = self.host / "modernization-platform"
        (self.platform / "backend").mkdir(parents=True)
        (self.platform / "backend" / "main.py").write_text("print('platform')\n")
        (self.platform / ".gitignore").write_text("backend/.env\n")
        (self.platform / instrument.SOURCE_FILE).write_text(json.dumps(
            {"commit": "a" * 40, "tag": "release-4", "date": "2026-10-19T10:00:00Z"}))
        git(self.host, "add", "-A", "--", "modernization-platform")
        git(self.host, "commit", "-q", "-m", "platform")

    def tearDown(self):
        self.tmp.cleanup()

    def test_identity_is_our_source_commit_beside_the_host_commit(self):
        state = instrument.platform_state(self.platform)
        self.assertEqual((state["commit"], state["dirty"]), ("a" * 40, False))
        self.assertEqual(state["source"]["tag"], "release-4")
        self.assertEqual(state["host"]["folder"], "modernization-platform")
        self.assertEqual(state["host"]["branch"], "rohit/platform")
        self.assertEqual(state["host"]["commit"], git(self.host, "rev-parse", "HEAD"))
        text = instrument.describe(state)
        self.assertIn("platform aaaaaaaaaaaa (release-4)", text)
        self.assertIn("in modernization-platform/ of the host repository", text)

    def test_changes_outside_the_platform_folder_never_make_it_dirty(self):
        (self.host / "src" / "App.cs").write_text("class App { /* someone else's work */ }\n")
        (self.host / "notes.txt").write_text("untracked, outside the platform\n")
        self.assertFalse(instrument.platform_state(self.platform)["dirty"])
        (self.platform / "backend" / ".env").write_text("DB_PASSWORD=x\n")       # ignored by the platform's .gitignore
        self.assertFalse(instrument.platform_state(self.platform)["dirty"])
        (self.platform / "backend" / "main.py").write_text("print('changed')\n")
        self.assertTrue(instrument.platform_state(self.platform)["dirty"])

    def test_the_check_runs_from_the_real_root_even_from_a_nested_folder(self):
        nested = self.platform / "backend"
        self.assertEqual(instrument.location(nested)["folder"], "modernization-platform/backend")
        self.assertEqual(Path(instrument.location(nested)["top"]), self.host.resolve())

    def test_without_platform_source_json_the_source_is_unknown_and_an_experiment_refuses(self):
        (self.platform / instrument.SOURCE_FILE).unlink()
        git(self.host, "commit", "-q", "-am", "no source record")
        state = instrument.platform_state(self.platform)
        self.assertIsNone(state["commit"])
        self.assertIn("platform source unknown", instrument.describe(state))
        from unittest import mock
        with mock.patch.object(instrument, "platform_state", return_value=state):
            with self.assertRaises(RuntimeError) as ctx:
                instrument.require_clean()
        self.assertIn("PLATFORM_SOURCE.json", str(ctx.exception))

    def test_its_own_repository_is_read_from_git(self):
        own = Path(self.tmp.name) / "own"
        own.mkdir()
        (own / "f.txt").write_text("x")
        git(own, "init", "-q", "-b", "main")
        git(own, "add", "-A")
        git(own, "commit", "-q", "-m", "ours")
        git(own, "tag", "release-9")
        state = instrument.platform_state(own)
        self.assertEqual((state["commit"], state["source"]["tag"], state["host"]), (git(own, "rev-parse", "HEAD"), "release-9", None))

    def test_any_tag_on_the_commit_is_named_and_an_untagged_commit_has_none(self):
        own = Path(self.tmp.name) / "own"
        own.mkdir()
        (own / "f.txt").write_text("x")
        git(own, "init", "-q", "-b", "master")
        git(own, "add", "-A")
        git(own, "commit", "-q", "-m", "ours")
        self.assertIsNone(instrument.platform_state(own)["source"]["tag"])      # installations follow master
        git(own, "tag", "milestone-a")
        self.assertEqual(instrument.platform_state(own)["source"]["tag"], "milestone-a")
        (own / "f.txt").write_text("y")
        git(own, "commit", "-q", "-am", "after the milestone")
        self.assertIsNone(instrument.platform_state(own)["source"]["tag"])


if __name__ == "__main__":
    unittest.main()
