"""Unit tests for repository registration business logic — see
15-REPOSITORY-INGEST-UI.md Parts C, D and E, specifically the fix for a
folder that was never under source control (Part D's clone URL
verification table and its "not a real edge case" note).

Uses stdlib unittest, same rationale as test_repository_ingest.py.
"""

import tempfile
import unittest
import uuid
from pathlib import Path

from app import models
from app.db import SessionLocal
from app.repositories import service as repositories_service
from app.repositories.schemas import RegisterLocalPathRequest


class RepositoryRegistrationTestCase(unittest.TestCase):
    """Base: real DB session, a temp folder per test, cleans up both."""

    def setUp(self):
        self.db = SessionLocal()
        self.tmp = tempfile.TemporaryDirectory()
        self.engagement = self.db.get(models.Engagement, "client-a-ocp4")
        self.registered_ids: list[uuid.UUID] = []

    def tearDown(self):
        for repo_id in self.registered_ids:
            row = self.db.get(models.Repository, repo_id)
            if row is not None:
                self.db.delete(row)
        self.db.commit()
        self.db.close()
        self.tmp.cleanup()

    def _folder(self, name: str) -> Path:
        path = Path(self.tmp.name) / name
        path.mkdir()
        (path / "file.txt").write_text("content\n", encoding="utf-8")
        return path

    def _register(self, local_path: Path, **overrides) -> models.Repository:
        payload = RegisterLocalPathRequest(
            source_type="local_path",
            local_path=str(local_path),
            **overrides,
        )
        repo = repositories_service.register_local_path(self.db, self.engagement, payload)
        self.db.commit()
        self.registered_ids.append(repo.id)
        return repo


class NoGitRegistrationTests(RepositoryRegistrationTestCase):
    """The scenario docs/15 originally made unsatisfiable: a folder that
    was never under source control has no canonical URL to assert."""

    def test_registers_with_no_clone_url_at_all(self):
        local_path = self._folder("no-git-no-url")

        repo = self._register(local_path)

        self.assertIsNone(repo.clone_url)
        self.assertIsNone(repo.clone_url_normalised)
        self.assertEqual(repo.source_control_status, "NONE")
        self.assertEqual(repo.clone_url_verification, "not_applicable")
        self.assertIsNone(repo.provider)

    def test_clone_url_supplied_on_non_git_folder_is_recorded_unverified(self):
        """The "repository being migrated into source control" case —
        supplying a URL does not retroactively make the folder git-tracked."""
        local_path = self._folder("no-git-with-url")

        repo = self._register(local_path, clone_url="https://github.com/example/no-git-with-url.git")

        self.assertEqual(repo.clone_url, "https://github.com/example/no-git-with-url.git")
        self.assertEqual(repo.source_control_status, "NONE")
        self.assertEqual(repo.clone_url_verification, "unverifiable")

    def test_two_no_url_folders_do_not_collide_on_the_clone_url_check(self):
        """The clone_url_normalised partial unique index must not apply
        where clone_url is null — root_folder_name and local_path remain
        the identity checks for non-git folders."""
        first = self._register(self._folder("no-git-a"))
        second = self._register(self._folder("no-git-b"))

        self.assertIsNone(first.clone_url)
        self.assertIsNone(second.clone_url)
        self.assertNotEqual(first.id, second.id)


class GitRegistrationStillRequiresCloneUrlTests(RepositoryRegistrationTestCase):
    """The fix must not weaken the existing rule for a folder that *is*
    under git — only lift it for folders that aren't."""

    def test_git_folder_without_clone_url_is_rejected(self):
        local_path = self._folder("git-no-url")
        import subprocess

        subprocess.run(["git", "-C", str(local_path), "init", "-q"], check=True)

        with self.assertRaises(repositories_service.RegistrationError) as ctx:
            self._register(local_path)

        self.assertEqual(ctx.exception.status_code, 422)
        codes = [e["code"] for e in ctx.exception.errors]
        self.assertIn("CLONE_URL_REQUIRED_FOR_GIT", codes)

    def test_git_folder_with_clone_url_still_registers_normally(self):
        local_path = self._folder("git-with-url")
        import subprocess

        subprocess.run(["git", "-C", str(local_path), "init", "-q"], check=True)

        repo = self._register(local_path, clone_url="https://github.com/example/git-with-url.git")

        self.assertEqual(repo.source_control_status, "GIT")
        self.assertEqual(repo.clone_url, "https://github.com/example/git-with-url.git")


if __name__ == "__main__":
    unittest.main()
