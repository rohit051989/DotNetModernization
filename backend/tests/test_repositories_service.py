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
from tests.support import CommittedTestEngagement
from app.repositories import service as repositories_service
from app.repositories.schemas import RegisterLocalPathRequest


class RepositoryRegistrationTestCase(unittest.TestCase):
    """Base: real DB session, a temp folder per test, cleans up both."""

    def setUp(self):
        self.db = SessionLocal()
        self.tmp = tempfile.TemporaryDirectory()
        self.test_engagement = CommittedTestEngagement(self.db)
        self.engagement = self.test_engagement.engagement
        self.registered_ids: list[uuid.UUID] = []

    def tearDown(self):
        for repo_id in self.registered_ids:
            row = self.db.get(models.Repository, repo_id)
            if row is not None:
                self.db.delete(row)
        self.db.commit()
        self.test_engagement.remove()
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

    def test_git_folder_with_an_origin_but_no_clone_url_is_rejected(self):
        local_path = self._folder("git-no-url")
        import subprocess

        subprocess.run(["git", "-C", str(local_path), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(local_path), "remote", "add", "origin", "git@github.com:example/git-no-url.git"], check=True)

        with self.assertRaises(repositories_service.RegistrationError) as ctx:
            self._register(local_path)

        self.assertEqual(ctx.exception.status_code, 422)
        codes = [e["code"] for e in ctx.exception.errors]
        self.assertIn("CLONE_URL_REQUIRED_FOR_GIT", codes)

    def test_git_folder_with_no_remote_at_all_registers_without_a_url_and_inspection_says_why(self):
        local_path = self._folder("git-no-remote")
        import subprocess

        subprocess.run(["git", "-C", str(local_path), "init", "-q"], check=True)
        inspection = repositories_service.inspect_path(self.db, self.engagement.id, str(local_path))
        self.assertTrue(any("no git remote at all" in w for w in inspection.warnings), inspection.warnings)

        repo = self._register(local_path)
        self.assertEqual((repo.clone_url, repo.source_control_status, repo.clone_url_verification),
                         (None, "NONE", "not_applicable"))
        self.assertTrue(repo.has_git_history)

    def test_an_origin_under_another_name_is_named(self):
        local_path = self._folder("git-upstream-only")
        import subprocess

        subprocess.run(["git", "-C", str(local_path), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(local_path), "remote", "add", "upstream", "https://github.com/example/x.git"], check=True)
        inspection = repositories_service.inspect_path(self.db, self.engagement.id, str(local_path))
        self.assertTrue(any("no remote named origin (it has upstream)" in w for w in inspection.warnings), inspection.warnings)

    def test_ssh_remotes_register_and_verify_against_the_same_repository(self):
        import subprocess

        for name, remote, given in [
            ("scp", "git@github.com:example/scp.git", "git@github.com:example/scp.git"),
            ("ssh", "ssh://git@github.com:22/example/ssh.git", "ssh://git@github.com/example/ssh.git"),
            ("mixed", "git@github.com:example/mixed.git", "https://github.com/example/mixed"),
        ]:
            local_path = self._folder(f"git-{name}")
            subprocess.run(["git", "-C", str(local_path), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(local_path), "remote", "add", "origin", remote], check=True)
            repo = self._register(local_path, clone_url=given)
            self.assertEqual((repo.clone_url_verification, repo.clone_url_normalised, repo.source_control_status),
                             ("verified", f"https://github.com/example/{name}", "GIT"), name)

    def test_git_folder_with_clone_url_still_registers_normally(self):
        local_path = self._folder("git-with-url")
        import subprocess

        subprocess.run(["git", "-C", str(local_path), "init", "-q"], check=True)

        repo = self._register(local_path, clone_url="https://github.com/example/git-with-url.git")

        self.assertEqual(repo.source_control_status, "GIT")
        self.assertEqual(repo.clone_url, "https://github.com/example/git-with-url.git")


class OneCheckoutOneEngagementTests(RepositoryRegistrationTestCase):
    """A checkout's conversion branches live in its git, so it serves one engagement (docs/VDI-SETUP.md: More than one person)."""

    def setUp(self):
        super().setUp()
        from app.engagements import service as engagements

        self.other = engagements.create(self.db, f"test-other-{uuid.uuid4().hex[:8]}", "Other client", "net10.0")
        self.db.commit()

    def tearDown(self):
        for repo in self.db.query(models.Repository).filter_by(engagement_id=self.other.id):
            self.db.delete(repo)
        self.db.flush()
        self.db.delete(self.db.get(models.Engagement, self.other.id))
        self.db.commit()
        super().tearDown()

    def _git_repo(self, name: str) -> Path:
        import subprocess

        path = self._folder(name)
        g = ["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(g[:3] + ["init", "-q", "-b", "main"], check=True)
        subprocess.run(g + ["add", "-A"], check=True)
        subprocess.run(g + ["commit", "-q", "-m", "first"], check=True)
        return path

    def test_the_same_checkout_in_a_second_engagement_is_refused_and_says_why(self):
        path = self._git_repo("shared-checkout")
        self._register(path)
        with self.assertRaises(repositories_service.RegistrationError) as ctx:
            repositories_service.register_local_path(self.db, self.other, RegisterLocalPathRequest(
                source_type="local_path", local_path=str(path)))
        self.assertEqual(ctx.exception.status_code, 409)
        problem = ctx.exception.errors[0]
        self.assertEqual(problem["code"], "CHECKOUT_IN_OTHER_ENGAGEMENT")
        self.assertIn(f"already registered in engagement '{self.engagement.id}'", problem["message"])
        self.assertIn("clone it again into another folder", problem["message"])
        warnings = repositories_service.inspect_path(self.db, self.other.id, str(path)).warnings
        self.assertTrue(any("already registered in engagement" in w for w in warnings), warnings)

    def test_a_worktree_of_the_same_repository_shares_its_branches_and_is_refused_too(self):
        import subprocess

        path = self._git_repo("main-checkout")
        self._register(path)
        linked = Path(self.tmp.name) / "linked-worktree"
        subprocess.run(["git", "-C", str(path), "worktree", "add", "-q", "-b", "other", str(linked)], check=True)
        with self.assertRaises(repositories_service.RegistrationError) as ctx:
            repositories_service.register_local_path(self.db, self.other, RegisterLocalPathRequest(
                source_type="local_path", local_path=str(linked)))
        self.assertEqual(ctx.exception.errors[0]["code"], "CHECKOUT_IN_OTHER_ENGAGEMENT")

    def test_a_separate_clone_registers_in_the_second_engagement(self):
        import subprocess

        path = self._git_repo("original")
        self._register(path)
        clone = Path(self.tmp.name) / "second-clone"
        subprocess.run(["git", "clone", "-q", str(path), str(clone)], check=True)
        subprocess.run(["git", "-C", str(clone), "remote", "remove", "origin"], check=True)
        repo = repositories_service.register_local_path(self.db, self.other, RegisterLocalPathRequest(
            source_type="local_path", local_path=str(clone)))
        self.db.commit()
        self.assertEqual(repo.engagement_id, self.other.id)

    def test_a_checkout_shared_before_the_rule_is_reported_and_left_working(self):
        """CLAUDE.md rule 15: an installation upgraded from release 1 may already have one checkout in two
        engagements. It is reported, and nothing refuses or changes the existing registrations."""
        import subprocess

        from app.routers.repositories import _existing_data_warnings

        path = self._git_repo("shared-before")
        first = self._register(path)
        # What release 1 allowed: the same folder in a second engagement, written as it wrote it.
        second = models.Repository(**{c.name: getattr(first, c.name) for c in models.Repository.__table__.columns
                                      if c.name not in ("id", "engagement_id", "created_at", "updated_at")},
                                   id=uuid.uuid4(), engagement_id=self.other.id)
        self.db.add(second)
        self.db.commit()
        groups = [g for g in repositories_service.shared_checkouts(self.db) if first.id in {r.id for r in g}]
        self.assertEqual(len(groups), 1)
        self.assertEqual({r.engagement_id for r in groups[0]}, {self.engagement.id, self.other.id})
        self.assertIn("left working", repositories_service.shared_checkout_message(groups[0]))
        self.assertIn(f"also registered in engagement '{self.engagement.id}'",
                      _existing_data_warnings(self.db, second)[0])
        self.assertEqual(subprocess.run(["git", "-C", str(path), "status", "--porcelain"], capture_output=True,
                                        text=True).stdout, "")


class CloneUrlValidationTests(unittest.TestCase):
    def test_accepted_forms(self):
        for url in ["https://github.com/example/repo.git", "git@github.com:example/repo.git",
                    "ssh://git@github.com/example/repo.git", "ssh://github.com:7999/scm/proj/repo.git",
                    "git@ssh.dev.azure.com:v3/org/project/repo"]:
            self.assertEqual(repositories_service.validate_clone_url(url), [], url)

    def test_rejected_forms_say_why(self):
        cases = {
            "http://github.com/example/repo.git": "must be an https URL, git@host:org/repo.git or ssh://host/org/repo.git",
            r"D:\repos\AccountsApi": "is a local folder, not a URL",
            "file:///D:/repos/AccountsApi": "is a local folder, not a URL",
            "https://user:secret@github.com/example/repo.git": "Embedded credentials",
            "ssh://user:secret@github.com/example/repo.git": "Embedded credentials",
        }
        for url, expected in cases.items():
            problems = repositories_service.validate_clone_url(url)
            self.assertEqual(len(problems), 1, url)
            self.assertIn(expected, problems[0]["message"], url)

    def test_ssh_and_https_normalise_to_one_identity(self):
        from app.steps.repository_ingest import normalize_clone_url

        expected = "https://github.com/example/repo"
        for url in ["https://github.com/example/repo.git", "git@github.com:example/repo.git",
                    "ssh://git@GitHub.com:22/example/repo.git", "ssh://github.com/example/repo/"]:
            self.assertEqual(normalize_clone_url(url), expected, url)


if __name__ == "__main__":
    unittest.main()
