"""Registering a repository by its git URL (docs/VDI-SETUP.md: Registering a client repository; app/repositories/git_source.py): the clone,
the target folder rules, a sign-in failing at once instead of waiting, and the fetch and fast-forward before a rescan.

Uses stdlib unittest, as the other tests do. The "remote" is a bare repository in a temporary folder, cloned through a
file:/// URL; the sign-in case is a local HTTP server that only ever answers 401.
"""
import http.server
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from app import models
from app.config import settings
from app.db import SessionLocal
from app.repositories import git_source
from app.repositories import service as repositories_service
from app.repositories.schemas import RegisterGitCloneRequest
from tests.support import CommittedTestEngagement

IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@t"]


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *IDENTITY, *args], check=True, capture_output=True,
                          text=True).stdout.strip()


class Upstream:
    """A bare repository with one commit on main, and a working clone to push new commits from."""

    def __init__(self, root: Path):
        self.bare = root / "upstream" / "Orders.git"
        self.bare.mkdir(parents=True)
        git(self.bare, "init", "-q", "--bare", "-b", "main")
        self.work = root / "upstream-work"
        subprocess.run(["git", "clone", "-q", str(self.bare), str(self.work)], check=True, capture_output=True)
        self.commit("Program.cs", "class Program {}\n", "first")
        self.url = self.bare.as_uri()

    def commit(self, name: str, text: str, message: str) -> str:
        (self.work / name).write_text(text, encoding="utf-8")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", message)
        git(self.work, "push", "-q", "origin", "HEAD:main")
        return git(self.work, "rev-parse", "HEAD")


class GitSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.upstream = Upstream(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_full_clone_with_long_paths_and_its_progress(self):
        folder = self.root / "repos" / "Orders"
        lines = []
        git_source.clone(self.upstream.url, None, folder, lines.append)
        self.assertEqual(git(folder, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertEqual(git(folder, "config", "core.longpaths"), "true")
        self.assertEqual(git(folder, "rev-parse", "--is-shallow-repository"), "false")
        self.assertTrue(git_source.is_clone_of(folder, self.upstream.url))

    def test_the_target_folder_rules(self):
        self.assertEqual(git_source.target_state(self.root / "new", self.upstream.url), ("clone", None))
        (self.root / "empty").mkdir()
        self.assertEqual(git_source.target_state(self.root / "empty", self.upstream.url), ("clone", None))
        busy = self.root / "busy"
        busy.mkdir()
        (busy / "notes.txt").write_text("x")
        action, why = git_source.target_state(busy, self.upstream.url)
        self.assertEqual(action, "refuse")
        self.assertIn("exists and is not empty", why)
        git_source.clone(self.upstream.url, None, self.root / "clone")
        self.assertEqual(git_source.target_state(self.root / "clone", self.upstream.url), ("reuse", None))
        other = Upstream(self.root / "other")
        action, why = git_source.target_state(self.root / "clone", other.url)
        self.assertEqual(action, "refuse")
        self.assertIn("already a clone of another repository", why)

    def test_update_fast_forwards_and_refuses_local_changes_or_divergence(self):
        folder = self.root / "clone"
        git_source.clone(self.upstream.url, None, folder)
        self.assertIn("already up to date", git_source.update(folder, self.upstream.url, "main"))
        new = self.upstream.commit("Orders.cs", "class Orders {}\n", "second")
        self.assertIn("fast-forwarded", git_source.update(folder, self.upstream.url, "main"))
        self.assertEqual(git(folder, "rev-parse", "HEAD"), new)

        (folder / "Program.cs").write_text("changed\n", encoding="utf-8")
        with self.assertRaises(git_source.GitSourceError) as ctx:
            git_source.update(folder, self.upstream.url, "main")
        self.assertIn("has local changes (Program.cs)", str(ctx.exception))
        git(folder, "checkout", "--", "Program.cs")

        git(folder, "commit", "-q", "--allow-empty", "-m", "local only")
        self.upstream.commit("Third.cs", "x\n", "third")
        with self.assertRaises(git_source.GitSourceError) as ctx:
            git_source.update(folder, self.upstream.url, "main")
        self.assertIn("cannot be fast-forwarded", str(ctx.exception))

    def test_a_host_that_needs_a_sign_in_fails_at_once_and_says_how_to_sign_in(self):
        class AlwaysUnauthorized(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="git"')
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), AlwaysUnauthorized)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/team/Orders.git"
            started = time.monotonic()
            with self.assertRaises(git_source.GitSourceError) as ctx:
                git_source.clone(url, None, self.root / "never")
            self.assertLess(time.monotonic() - started, 30)
        finally:
            server.shutdown()
        self.assertIn("needs a sign-in the platform cannot give", str(ctx.exception))
        self.assertFalse((self.root / "never").exists())

    def test_no_prompt_can_reach_the_person(self):
        with mock.patch.dict("os.environ", {"GIT_ASKPASS": "C:\\askpass.exe", "SSH_ASKPASS": "x"}):
            env = git_source.git_environment()
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(env["GCM_INTERACTIVE"], "never")
        self.assertNotIn("GIT_ASKPASS", env)
        self.assertNotIn("SSH_ASKPASS", env)


class RegisterByUrlTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.upstream = Upstream(self.root)
        self.test_engagement = CommittedTestEngagement(self.db)
        self.engagement = self.test_engagement.engagement

    def tearDown(self):
        for repo in self.db.query(models.Repository).filter_by(engagement_id=self.engagement.id):
            self.db.delete(repo)
        self.db.commit()
        self.test_engagement.remove()
        self.db.close()
        self.tmp.cleanup()

    def _register(self, **fields) -> models.Repository:
        repo = repositories_service.register_git_clone(self.db, self.engagement, RegisterGitCloneRequest(
            source_type="git_clone", clone_url=self.upstream.url, **fields))
        self.db.commit()
        return repo

    def test_the_default_folder_is_under_repos_dir(self):
        with mock.patch.object(settings, "repos_dir", str(self.root / "repos")):
            repo = self._register()
        self.assertEqual(Path(repo.local_path), self.root / "repos" / self.engagement.id / "Orders")
        self.assertEqual((repo.source_type, repo.name, repo.ingest_status), ("git_clone", "Orders", "registered"))

    def test_without_repos_dir_the_target_folder_is_required(self):
        with mock.patch.object(settings, "repos_dir", ""):
            with self.assertRaises(repositories_service.RegistrationError) as ctx:
                self._register()
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("REPOS_DIR is not set", str(ctx.exception))
            repo = self._register(target_folder=str(self.root / "mine" / "Orders"))
        self.assertEqual(Path(repo.local_path), self.root / "mine" / "Orders")

    def test_a_folder_that_is_not_empty_is_refused_unless_it_is_a_clone_of_the_same_url(self):
        busy = self.root / "busy"
        busy.mkdir()
        (busy / "x.txt").write_text("x")
        with self.assertRaises(repositories_service.RegistrationError) as ctx:
            self._register(target_folder=str(busy))
        self.assertEqual(ctx.exception.errors[0]["code"], "TARGET_FOLDER_NOT_EMPTY")
        clone = self.root / "existing"
        git_source.clone(self.upstream.url, None, clone)
        inspected = repositories_service.inspect_url(self.db, self.engagement.id, self.upstream.url, str(clone))
        self.assertEqual(inspected.target_action, "reuse")
        self.assertEqual(Path(self._register(target_folder=str(clone)).local_path), clone)

    def test_a_folder_inside_the_platform_or_runs_dir_is_refused(self):
        for inside in (Path(settings.platform_root) / "clones" / "Orders", settings.runs_path / "Orders"):
            with self.assertRaises(repositories_service.RegistrationError) as ctx:
                self._register(target_folder=str(inside))
            self.assertEqual(ctx.exception.errors[0]["code"], "INVALID_TARGET_FOLDER")

    def test_a_credential_in_the_url_is_refused(self):
        with self.assertRaises(repositories_service.RegistrationError):
            repositories_service.register_git_clone(self.db, self.engagement, RegisterGitCloneRequest(
                source_type="git_clone", clone_url="https://jdoe:secret@git.client-a.example/team/Orders.git",
                target_folder=str(self.root / "x")))


if __name__ == "__main__":
    unittest.main()
