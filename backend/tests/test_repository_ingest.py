"""Unit tests for lifecycle step 1 — see 13-STEP-001-REPOSITORY-INGEST.md and
15-REPOSITORY-INGEST-UI.md Parts B/C.

Uses stdlib unittest (no test framework is listed in requirements.txt; see
test_process_adapter.py for the same rationale) and a real database — this
codebase does not mock the DB (see CLAUDE.md's data model and prior test
files). The "folder with .git" / "folder without .git" cases are constructed
at test time via `git init`, not checked in — see 13's "Test fixtures"
section for why.
"""

import json
import os
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from app import models
from app.config import settings
from app.db import SessionLocal
from app.steps import repository_ingest
from app.workflow.contract import StepContext

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _git(cwd: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _init_git_repo(path: Path, origin_url: str | None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(path, "init", "-b", "main")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "initial commit")
    if origin_url:
        _git(path, "remote", "add", "origin", origin_url)


class RepositoryIngestTestCase(unittest.TestCase):
    """Base: creates a `repositories` row pointing at a temp folder, cleans
    up both the row and the folder afterward."""

    def setUp(self):
        self.db = SessionLocal()
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_row_id = None

    def tearDown(self):
        if self.repo_row_id is not None:
            row = self.db.get(models.Repository, self.repo_row_id)
            if row is not None:
                self.db.delete(row)
                self.db.commit()
        self.db.close()
        self.tmp.cleanup()

    def _make_repository_row(self, local_path: Path, clone_url: str | None = None) -> models.Repository:
        row = models.Repository(
            id=uuid.uuid4(),
            engagement_id="client-a-ocp4",
            name="test-repo",
            root_folder_name=local_path.name,
            slug="test-repo-" + uuid.uuid4().hex[:8],
            local_path=str(local_path),
            local_path_normalised=str(local_path).lower(),
            clone_url=clone_url,
            clone_url_normalised=repository_ingest.normalize_clone_url(clone_url) if clone_url else None,
            # Pre-scan state — run() always recomputes this from the folder's
            # actual .git presence, so what's seeded here doesn't matter to
            # any test except as a starting value.
            source_control_status="NONE",
            source_type="local_path",
            ingest_status="registered",
        )
        self.db.add(row)
        self.db.commit()
        self.repo_row_id = row.id
        return row

    def _make_context(self, repository_id: uuid.UUID, output_dir: Path) -> StepContext:
        return StepContext(
            step_name="repository-ingest",
            step_version="1.0.0",
            job_name="phase0-repository-discovery",
            job_execution_id="11111111-1111-1111-1111-111111111111",
            step_execution_id="22222222-2222-2222-2222-222222222222",
            parameters={
                "engagement_id": "client-a-ocp4",
                "repository_id": str(repository_id),
                "ingest_token": str(uuid.uuid4()),
            },
            working_dir=str(output_dir.parent),
            output_dir=str(output_dir),
            database_url=settings.database_url,
        )


class FolderWithGitTests(RepositoryIngestTestCase):
    def test_resolves_git_metadata_and_verifies_matching_clone_url(self):
        local_path = Path(self.tmp.name) / "with-git"
        origin_url = "https://github.com/example/with-git.git"
        _init_git_repo(local_path, origin_url)
        expected_sha = subprocess.run(
            ["git", "-C", str(local_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        repo = self._make_repository_row(local_path, clone_url=origin_url)
        output_dir = Path(self.tmp.name) / "out"
        result = repository_ingest.run(self._make_context(repo.id, output_dir))

        self.assertEqual(result.exit_status, "COMPLETED")
        self.assertEqual(len(result.outputs), 1)

        self.db.refresh(repo)
        self.assertTrue(repo.has_git_history)
        self.assertEqual(repo.ingest_commit_sha, expected_sha)
        self.assertEqual(repo.clone_url_verification, "verified")
        self.assertEqual(repo.detected_clone_url, origin_url)
        self.assertEqual(repo.ingest_status, "scanned")
        self.assertEqual(repo.source_control_status, "GIT")

        artifact_path = Path(output_dir / "repository-inventory.json")
        self.assertTrue(artifact_path.exists())
        inventory = json.loads(artifact_path.read_text(encoding="utf-8"))
        self.assertNotIn("generated_at", inventory)
        self.assertEqual(inventory["ingest_commit_sha"], expected_sha)
        self.assertEqual(result.outputs[0].metadata["generated_at"].endswith("Z"), True)
        self.assertEqual(inventory["artifact_version"], "1.2.0")
        self.assertEqual(inventory["organization"], "example")
        self.assertIsNotNone(inventory["last_commit_date"])
        self.assertIsNone(inventory["source_status"])
        self.assertEqual(inventory["source_control_status"], "GIT")

        self.db.refresh(repo)
        self.assertEqual(repo.organization, "example")
        self.assertIsNotNone(repo.last_commit_date)
        self.assertIsNone(repo.source_status)
        self.assertEqual(repo.primary_languages, [])  # README.md's .md extension isn't a mapped language

    def test_primary_languages_counted_by_extension_excluding_skipped_dirs(self):
        local_path = Path(self.tmp.name) / "with-git-languages"
        _init_git_repo(local_path, "https://github.com/example/with-git-languages.git")
        (local_path / "Program.cs").write_text("// cs\n", encoding="utf-8")
        (local_path / "Other.cs").write_text("// cs\n", encoding="utf-8")
        (local_path / "site.css").write_text("/* css */\n", encoding="utf-8")
        (local_path / "node_modules").mkdir()
        (local_path / "node_modules" / "index.js").write_text("// js\n", encoding="utf-8")

        repo = self._make_repository_row(
            local_path, clone_url="https://github.com/example/with-git-languages.git"
        )
        repository_ingest.run(self._make_context(repo.id, Path(self.tmp.name) / "out"))

        self.db.refresh(repo)
        languages = {entry["language"]: entry for entry in repo.primary_languages}
        self.assertNotIn("JavaScript/TypeScript", languages)  # excluded via node_modules
        self.assertEqual(languages["C#"]["file_count"], 2)
        self.assertEqual(languages["Web"]["file_count"], 1)
        self.assertEqual(languages["C#"]["percentage"], round(2 / 3 * 100, 1))


    def test_mismatched_clone_url_is_a_warning_not_a_failure(self):
        local_path = Path(self.tmp.name) / "with-git-mismatch"
        _init_git_repo(local_path, "https://github.com/example/actual-repo.git")

        repo = self._make_repository_row(
            local_path, clone_url="https://github.com/example/wrong-repo.git"
        )
        output_dir = Path(self.tmp.name) / "out"
        result = repository_ingest.run(self._make_context(repo.id, output_dir))

        self.assertEqual(result.exit_status, "COMPLETED")
        self.db.refresh(repo)
        self.assertEqual(repo.clone_url_verification, "mismatch")
        self.assertEqual(repo.detected_clone_url, "https://github.com/example/actual-repo.git")

    def test_git_status_is_clean_after_a_run(self):
        """Phase 0 must never write into the registered folder."""
        local_path = Path(self.tmp.name) / "with-git-readonly"
        _init_git_repo(local_path, "https://github.com/example/with-git-readonly.git")

        repo = self._make_repository_row(
            local_path, clone_url="https://github.com/example/with-git-readonly.git"
        )
        output_dir = Path(self.tmp.name) / "out"
        repository_ingest.run(self._make_context(repo.id, output_dir))

        status = subprocess.run(
            ["git", "-C", str(local_path), "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        ).stdout
        self.assertEqual(status, "")

    def test_two_runs_over_unchanged_repository_produce_identical_checksums(self):
        local_path = Path(self.tmp.name) / "with-git-determinism"
        _init_git_repo(local_path, "https://github.com/example/with-git-determinism.git")

        repo = self._make_repository_row(
            local_path, clone_url="https://github.com/example/with-git-determinism.git"
        )
        result1 = repository_ingest.run(
            self._make_context(repo.id, Path(self.tmp.name) / "out1")
        )
        result2 = repository_ingest.run(
            self._make_context(repo.id, Path(self.tmp.name) / "out2")
        )

        self.assertEqual(result1.outputs[0].checksum, result2.outputs[0].checksum)

    def test_skips_ignored_directories_in_size_and_file_count(self):
        local_path = Path(self.tmp.name) / "with-git-skips"
        _init_git_repo(local_path, "https://github.com/example/with-git-skips.git")
        (local_path / "node_modules").mkdir()
        (local_path / "node_modules" / "junk.js").write_text("x" * 1000, encoding="utf-8")
        (local_path / "bin").mkdir()
        (local_path / "bin" / "app.dll").write_text("x" * 1000, encoding="utf-8")
        (local_path / "src.cs").write_text("// real file\n", encoding="utf-8")

        repo = self._make_repository_row(
            local_path, clone_url="https://github.com/example/with-git-skips.git"
        )
        repository_ingest.run(self._make_context(repo.id, Path(self.tmp.name) / "out"))

        self.db.refresh(repo)
        # README.md (from _init_git_repo) + src.cs only — node_modules/bin excluded.
        self.assertEqual(repo.file_count, 2)


class FolderWithoutGitTests(RepositoryIngestTestCase):
    def test_no_git_history_with_clone_url_is_unverifiable_not_a_failure(self):
        """A URL supplied on a non-git folder — e.g. a repository being
        migrated into source control (15-REPOSITORY-INGEST-UI.md Part D) —
        is recorded but unverified; source_control_status stays NONE
        regardless, since supplying a URL doesn't make the folder git."""
        local_path = Path(self.tmp.name) / "no-git"
        local_path.mkdir()
        (local_path / "file.txt").write_text("plain folder, no git\n", encoding="utf-8")

        repo = self._make_repository_row(
            local_path, clone_url="https://github.com/example/no-git.git"
        )
        result = repository_ingest.run(
            self._make_context(repo.id, Path(self.tmp.name) / "out")
        )

        self.assertEqual(result.exit_status, "COMPLETED")
        self.db.refresh(repo)
        self.assertFalse(repo.has_git_history)
        self.assertIsNone(repo.ingest_commit_sha)
        self.assertEqual(repo.clone_url_verification, "unverifiable")
        self.assertIsNone(repo.detected_clone_url)
        self.assertEqual(repo.source_control_status, "NONE")

    def test_no_git_history_and_no_clone_url_is_not_applicable(self):
        """The case docs/15 originally made unsatisfiable: a folder that was
        never under source control, with no clone_url at all — not merely
        unverified, but nothing to verify in the first place."""
        local_path = Path(self.tmp.name) / "no-git-no-url"
        local_path.mkdir()
        (local_path / "file.txt").write_text("plain folder, no git, no url\n", encoding="utf-8")

        repo = self._make_repository_row(local_path, clone_url=None)
        result = repository_ingest.run(
            self._make_context(repo.id, Path(self.tmp.name) / "out")
        )

        self.assertEqual(result.exit_status, "COMPLETED")
        self.db.refresh(repo)
        self.assertFalse(repo.has_git_history)
        self.assertIsNone(repo.clone_url)
        self.assertEqual(repo.clone_url_verification, "not_applicable")
        self.assertEqual(repo.source_control_status, "NONE")
        self.assertIsNone(repo.organization)

    def test_git_added_after_registration_backfills_clone_url_on_rescan(self):
        """The "migrating into source control" case, but discovered on
        rescan: registered with no .git and no clone_url, then git is
        initialized in the folder with a remote before the next scan."""
        local_path = Path(self.tmp.name) / "migrated-into-git"
        local_path.mkdir()
        (local_path / "file.txt").write_text("starts as a plain folder\n", encoding="utf-8")

        repo = self._make_repository_row(local_path, clone_url=None)
        first = repository_ingest.run(
            self._make_context(repo.id, Path(self.tmp.name) / "out1")
        )
        self.assertEqual(first.exit_status, "COMPLETED")
        self.db.refresh(repo)
        self.assertEqual(repo.source_control_status, "NONE")
        self.assertIsNone(repo.clone_url)

        _init_git_repo(local_path, "https://github.com/example/migrated-into-git.git")
        second = repository_ingest.run(
            self._make_context(repo.id, Path(self.tmp.name) / "out2")
        )

        self.assertEqual(second.exit_status, "COMPLETED")
        self.db.refresh(repo)
        self.assertEqual(repo.source_control_status, "GIT")
        self.assertEqual(repo.clone_url, "https://github.com/example/migrated-into-git.git")
        self.assertEqual(repo.clone_url_verification, "verified")


class NonExistentPathTests(RepositoryIngestTestCase):
    def test_missing_folder_fails_and_sets_path_missing(self):
        local_path = Path(self.tmp.name) / "does-not-exist"

        repo = self._make_repository_row(
            local_path, clone_url="https://github.com/example/does-not-exist.git"
        )
        result = repository_ingest.run(
            self._make_context(repo.id, Path(self.tmp.name) / "out")
        )

        self.assertEqual(result.exit_status, "FAILED")
        self.assertIn(str(local_path), result.exit_message)
        self.db.refresh(repo)
        self.assertEqual(repo.ingest_status, "path_missing")


class UnknownRepositoryTests(RepositoryIngestTestCase):
    def test_missing_repository_row_fails_cleanly(self):
        context = self._make_context(uuid.uuid4(), Path(self.tmp.name) / "out")
        result = repository_ingest.run(context)
        self.assertEqual(result.exit_status, "FAILED")
        self.assertIn("does not exist", result.exit_message)


if __name__ == "__main__":
    unittest.main()
