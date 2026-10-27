"""scripts/update-platform.ps1 on small repositories (docs/VDI-SETUP.md, "Updating the platform"): a client repository
with its own history and someone else's branch, our source with a change, a delete and a rename. Installations
follow our master. Runs the script as the guide does, with Windows PowerShell, from the platform folder or the
source folder."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@t"]
BRANCH, OTHER, FOLDER = "rohit/platform", "asmith/feature", "mp"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *IDENTITY, *args], check=True, capture_output=True, text=True).stdout.strip()


def ps(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


@unittest.skipUnless(sys.platform == "win32", "update-platform.ps1 is Windows PowerShell")
class UpdatePlatform(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        # Our repository, with the two scripts, and files to change, delete and rename.
        work = root / "ours-work"
        (work / "scripts").mkdir(parents=True)
        for name in ("update-platform.ps1", "write-platform-source.ps1"):
            shutil.copy2(SCRIPTS / name, work / "scripts" / name)
        (work / "changed.txt").write_text("v1\n")
        (work / "deleted.txt").write_text("goes upstream\n")
        (work / "docs").mkdir()
        (work / "docs" / "old-name.md").write_text("renamed upstream\n")
        (work / ".gitignore").write_text("backend/.env\n")
        git(work, "init", "-q", "-b", "master"); git(work, "add", "-A"); git(work, "commit", "-q", "-m", "ours v1")
        self.ours = root / "ours.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(work), str(self.ours)], check=True)
        self.work = root / "ours-dev"
        subprocess.run(["git", "clone", "-q", str(self.ours), str(self.work)], check=True)
        self.source = root / "source"
        subprocess.run(["git", "clone", "-q", str(self.ours), str(self.source)], check=True)
        # The client's repository: unrelated history, main and someone else's branch.
        seed = root / "client-seed"
        seed.mkdir()
        (seed / "README.md").write_text("client\n")
        git(seed, "init", "-q", "-b", "main"); git(seed, "add", "-A"); git(seed, "commit", "-q", "-m", "client")
        git(seed, "switch", "-q", "-c", OTHER); (seed / "x.txt").write_text("asmith\n")
        git(seed, "add", "-A"); git(seed, "commit", "-q", "-m", "asmith")
        self.remote = root / "client.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True)
        git(seed, "push", "-q", str(self.remote), "main", OTHER)
        git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")
        self.client = root / "client"
        subprocess.run(["git", "clone", "-q", str(self.remote), str(self.client)], check=True)
        # Part 1: your branch, the platform folder, the copy, PLATFORM_SOURCE.json, the commit.
        git(self.client, "switch", "-q", "-c", BRANCH, "origin/main")
        self.platform = self.client / FOLDER
        self.platform.mkdir()
        subprocess.run(["robocopy", str(self.source), str(self.platform), "/E", "/XD", ".git", "/NFL", "/NDL", "/NJH", "/NJS"],
                       capture_output=True)
        done = ps(self.platform / "scripts" / "write-platform-source.ps1", "-Source", str(self.source))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        git(self.client, "add", "-A", "--", FOLDER); git(self.client, "commit", "-q", "-m", "platform", "--", FOLDER)
        git(self.client, "push", "-q", "-u", "origin", BRANCH)
        (self.platform / "backend").mkdir()
        (self.platform / "backend" / ".env").write_text("DB_PASSWORD=local\n")          # local: never touched
        self.other_before = git(self.remote, "rev-parse", OTHER)
        self.v1 = git(self.work, "rev-parse", "HEAD")

    def tearDown(self):
        self.tmp.cleanup()

    def update(self, *extra: str, run_from: Path | None = None) -> subprocess.CompletedProcess:
        """Runs the update as the guide does, from the platform folder unless `run_from` names another."""
        return ps((run_from or self.platform) / "scripts" / "update-platform.ps1", "-Source", str(self.source),
                  "-Platform", str(self.platform), "-Branch", BRANCH, *extra)

    def record(self) -> dict:
        return json.loads((self.platform / "PLATFORM_SOURCE.json").read_text(encoding="utf-8"))

    def upstream(self) -> str:
        (self.work / "changed.txt").write_text("v2\n")
        git(self.work, "rm", "-q", "deleted.txt")
        git(self.work, "mv", "docs/old-name.md", "docs/new-name.md")
        git(self.work, "commit", "-q", "-am", "ours v2: change, delete, rename")
        return self.publish()

    def publish(self, force: bool = False) -> str:
        git(self.work, "push", "-q", *(["--force"] if force else []), "origin", "master")
        return git(self.work, "rev-parse", "HEAD")

    def commit_upstream(self, text: str) -> str:
        (self.work / "changed.txt").write_text(text)
        git(self.work, "commit", "-q", "-am", f"ours {text.strip()}")
        return self.publish()

    def test_an_update_copies_removes_records_and_commits_only_the_platform_folder(self):
        new = self.upstream()
        (self.client / "README.md").write_text("someone's uncommitted edit\n")
        head = git(self.client, "rev-parse", "HEAD")
        done = self.update("-Push")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Now run bootstrap", done.stdout)
        self.assertEqual((self.platform / "changed.txt").read_text(), "v2\n")
        self.assertFalse((self.platform / "deleted.txt").exists())
        self.assertFalse((self.platform / "docs" / "old-name.md").exists())
        self.assertTrue((self.platform / "docs" / "new-name.md").exists())
        self.assertEqual((self.platform / "backend" / ".env").read_text(), "DB_PASSWORD=local\n")
        record = self.record()
        self.assertEqual((record["commit"], record["previousCommit"], record["tag"], record["branch"]),
                         (new, self.v1, None, "master"))
        self.assertNotIn("release", record)
        files = git(self.client, "show", "--name-only", "--format=", "HEAD").splitlines()
        self.assertTrue(files and all(f.startswith(FOLDER + "/") for f in files), files)
        message = git(self.client, "log", "-1", "--format=%B")
        self.assertIn(f"Source commit: {new}", message)
        self.assertNotIn("Tag:", message)
        self.assertEqual(git(self.client, "rev-parse", "HEAD~1"), head)
        self.assertEqual(git(self.client, "status", "--porcelain", "--", "README.md"), "M README.md")
        self.assertEqual(git(self.remote, "rev-parse", BRANCH), git(self.client, "rev-parse", "HEAD"))
        self.assertEqual(git(self.remote, "rev-parse", OTHER), self.other_before)

    def test_three_updates_in_a_row_from_the_source_folder_as_each_left_it(self):
        """Each update runs the script in the source folder, which the previous update left at master's tip; the
        source is never touched in between. The second commit happens to carry a tag, which is recorded."""
        expected = []
        for n, text in enumerate(("v2\n", "v3\n", "v4\n"), start=1):
            new = self.upstream() if n == 1 else self.commit_upstream(text)
            if n == 2:
                git(self.work, "tag", "milestone-a"); git(self.work, "push", "-q", "origin", "milestone-a")
            before = self.record()["commit"]
            done = self.update(run_from=self.source)
            self.assertEqual(done.returncode, 0, f"update {n}\n" + done.stdout + done.stderr)
            self.assertEqual((self.platform / "changed.txt").read_text(), text)
            record = self.record()
            self.assertEqual((record["commit"], record["previousCommit"]), (new, before), f"update {n}")
            self.assertEqual(record["tag"], "milestone-a" if n == 2 else None, f"update {n}")
            self.assertEqual(git(self.source, "rev-parse", "HEAD"), new)
            self.assertEqual(git(self.source, "status", "--porcelain"), "")
            self.assertEqual(git(self.source, "rev-parse", "--abbrev-ref", "HEAD"), "master")
            self.assertEqual(git(self.client, "status", "--porcelain", "--", FOLDER), "")
            expected.append(f"Modernization platform: update to {new[:12]}" + (" (milestone-a)" if n == 2 else ""))
        subjects = git(self.client, "log", "-3", "--format=%s").splitlines()
        self.assertEqual(subjects, list(reversed(expected)))
        # A fourth run with nothing new commits nothing.
        done = self.update(run_from=self.source)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Nothing changed in the platform folder", done.stdout)

    def test_a_rewritten_history_is_refused_and_both_folders_are_left_as_they_were(self):
        self.upstream()
        installed = self.commit_upstream("v3\n")
        self.assertEqual(self.update().returncode, 0)
        # Our master is rewritten: v3 replaced by another commit on top of v2.
        git(self.work, "reset", "-q", "--hard", "HEAD~1")
        (self.work / "changed.txt").write_text("v3, rewritten\n")
        git(self.work, "commit", "-q", "-am", "ours v3 rewritten")
        rewritten = self.publish(force=True)
        head = git(self.client, "rev-parse", "HEAD")
        done = self.update()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn(f"does not descend from the installed commit {installed[:12]}", done.stdout)
        self.assertIn("history was rewritten", done.stdout)
        self.assertIn("ours v3", done.stdout)                                   # what would be lost
        self.assertIn("-AllowDowngrade", done.stdout)
        self.assertEqual(git(self.source, "rev-parse", "HEAD"), installed)
        self.assertEqual(git(self.client, "rev-parse", "HEAD"), head)
        self.assertEqual(self.record()["commit"], installed)
        # -AllowDowngrade installs it, saying what is lost.
        done = self.update("-AllowDowngrade")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Going backwards (-AllowDowngrade)", done.stdout)
        self.assertIn("These will be lost from the platform folder", done.stdout)
        self.assertEqual(self.record()["commit"], rewritten)
        self.assertEqual(git(self.source, "rev-parse", "HEAD"), rewritten)
        self.assertEqual((self.platform / "changed.txt").read_text(), "v3, rewritten\n")

    def test_a_platform_installed_from_another_branch_is_refused(self):
        # The platform holds a commit of another branch of ours, which master does not contain.
        git(self.work, "switch", "-q", "-c", "experiment")
        (self.work / "changed.txt").write_text("experiment\n")
        git(self.work, "commit", "-q", "-am", "ours experiment")
        git(self.work, "push", "-q", "origin", "experiment")
        experiment = git(self.work, "rev-parse", "HEAD")
        git(self.work, "switch", "-q", "master")
        record = self.record()
        record["commit"] = experiment
        (self.platform / "PLATFORM_SOURCE.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        git(self.client, "commit", "-q", "-m", "platform from experiment", "--", FOLDER)
        self.upstream()
        git(self.source, "fetch", "-q", "origin")                               # the source has seen the branch
        done = self.update()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("installed from another branch", done.stdout)
        self.assertIn("ours experiment", done.stdout)
        self.assertEqual((self.platform / "changed.txt").read_text(), "v1\n")
        done = self.update("-AllowDowngrade")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((self.platform / "changed.txt").read_text(), "v2\n")

    def test_the_clients_own_files_in_the_platform_folder_are_kept_and_listed(self):
        """Only files in the installed commit and not in the new one are removed; a file the client committed in the
        platform folder is in neither, so it stays, and is listed. The client's commit was never imported: the
        delivery warns about it, and carries on."""
        (self.platform / "client-notes.md").write_text("ours, not the platform's\n")
        (self.platform / "docs" / "client-runbook.md").write_text("also ours\n")
        git(self.client, "add", "-A", "--", FOLDER); git(self.client, "commit", "-q", "-m", "client files", "--", FOLDER)
        self.upstream()
        for run_from in (self.platform, self.source):
            done = self.update(run_from=run_from)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            if run_from == self.platform:
                self.assertIn("Warning: the client's branch has 1 commit(s) in the platform folder that our repository has not imported", done.stdout)
                self.assertIn("client files", done.stdout)
            else:
                # Delivered over once, with a warning: only commits since the latest delivery are listed again.
                self.assertNotIn("Warning: the client's branch", done.stdout)
            self.assertEqual((self.platform / "client-notes.md").read_text(), "ours, not the platform's\n")
            self.assertEqual((self.platform / "docs" / "client-runbook.md").read_text(), "also ours\n")
            self.assertIn("Kept, not part of the platform (2):", done.stdout)
            self.assertIn("client-notes.md", done.stdout)
            self.assertIn("docs/client-runbook.md", done.stdout)
            self.commit_upstream("v3\n" if run_from == self.platform else "v4\n")
        # The deletion and the rename upstream were applied all the same.
        self.assertFalse((self.platform / "deleted.txt").exists())
        self.assertFalse((self.platform / "docs" / "old-name.md").exists())
        self.assertTrue((self.platform / "docs" / "new-name.md").exists())
        self.assertIn("client-notes.md", git(self.client, "ls-files", "--", FOLDER))

    def assert_refused_and_unchanged(self, done: subprocess.CompletedProcess, *said: str):
        self.assertEqual(done.returncode, 1, done.stdout)
        for text in said:
            self.assertIn(text, done.stdout)
        self.assertIn("Nothing was committed", done.stdout)
        self.assertEqual(git(self.client, "rev-parse", "HEAD"), self.head)
        self.assertEqual(git(self.client, "status", "--porcelain", "--", FOLDER), "")
        self.assertEqual(git(self.source, "rev-parse", "HEAD"), self.v1)
        self.assertEqual((self.platform / "changed.txt").read_text(), "v1\n")
        self.assertTrue((self.platform / "deleted.txt").exists())

    def test_an_installed_platform_without_platform_source_json_is_refused_changing_nothing(self):
        git(self.client, "rm", "-q", "--", f"{FOLDER}/PLATFORM_SOURCE.json")
        git(self.client, "commit", "-q", "-m", "no record", "--", FOLDER)
        self.head = git(self.client, "rev-parse", "HEAD")
        self.upstream()
        self.assert_refused_and_unchanged(self.update(run_from=self.source), "no PLATFORM_SOURCE.json",
                                          "write-platform-source.ps1")

    def test_an_installed_commit_the_source_folder_lacks_is_refused_changing_nothing(self):
        record = self.record()
        record["commit"] = "0123456789abcdef0123456789abcdef01234567"
        (self.platform / "PLATFORM_SOURCE.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        git(self.client, "commit", "-q", "-m", "platform from elsewhere", "--", FOLDER)
        self.head = git(self.client, "rev-parse", "HEAD")
        self.upstream()
        self.assert_refused_and_unchanged(self.update(), "which the source folder does not contain")
        # -AllowDowngrade does not get past it: deletions cannot be worked out without the commit.
        self.assert_refused_and_unchanged(self.update("-AllowDowngrade"), "which the source folder does not contain")

    def test_a_first_install_into_an_empty_folder_needs_no_installed_commit(self):
        empty = self.client / "mp2"
        empty.mkdir()
        new = self.upstream()
        done = ps(self.source / "scripts" / "update-platform.ps1", "-Source", str(self.source), "-Platform", str(empty),
                  "-Branch", BRANCH)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("nothing installed", done.stdout)
        record = json.loads((empty / "PLATFORM_SOURCE.json").read_text(encoding="utf-8"))
        self.assertEqual((record["commit"], record["previousCommit"]), (new, None))
        self.assertEqual((empty / "changed.txt").read_text(), "v2\n")
        self.assertIn("Previous source commit: none (first install)", git(self.client, "log", "-1", "--format=%B"))

    def test_a_source_folder_left_at_a_tag_by_an_older_script_is_refused_with_the_way_back(self):
        """An older update-platform.ps1 checked out a release tag; the first update after the change to master is
        run from the source folder, once it is back on master (docs/VDI-SETUP.md, "Upgrade notes")."""
        new = self.upstream()
        git(self.work, "tag", "release-1", self.v1); git(self.work, "push", "-q", "origin", "release-1")
        git(self.source, "fetch", "-q", "--tags", "origin")
        git(self.source, "switch", "-q", "--detach", "release-1")
        done = self.update()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("a commit of its own (release-1), not master", done.stdout)
        self.assertIn("switch master", done.stdout)
        git(self.source, "switch", "-q", "master")
        done = self.update(run_from=self.source)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.record()["commit"], new)

    def test_it_stops_on_the_wrong_branch(self):
        # Another branch that carries the platform folder: the script is there, and stops naming the branch.
        git(self.client, "switch", "-q", "-c", "rohit/older-work")
        done = self.update()
        self.assertEqual(done.returncode, 1)
        self.assertIn(f"is on branch 'rohit/older-work', not '{BRANCH}'", done.stdout)
        self.assertIn("Nothing was committed", done.stdout)
        # A branch without the platform folder (the client's main): the script itself is not there to run, which
        # the guide's troubleshooting explains; run it from the source folder instead.
        git(self.client, "switch", "-q", "main")
        self.assertFalse((self.platform / "scripts" / "update-platform.ps1").exists())

    def test_it_stops_on_uncommitted_changes_in_the_platform_folder_and_names_them(self):
        (self.platform / "changed.txt").write_text("edited here\n")
        head = git(self.client, "rev-parse", "HEAD")
        done = self.update()
        self.assertEqual(done.returncode, 1)
        self.assertIn("the platform folder has uncommitted changes", done.stdout)
        self.assertIn("mp/changed.txt", done.stdout)
        self.assertEqual(git(self.client, "rev-parse", "HEAD"), head)

    def test_delivery_pushes_files_only_never_our_history_or_tags(self):
        """Delivery from our machine (docs/VDI-SETUP.md, "Delivering to a client from our machine"): after -Push,
        the client's repository holds the platform folder's files, and none of our commits or tags."""
        git(self.work, "tag", "milestone-a"); git(self.work, "push", "-q", "origin", "milestone-a")
        ours = [self.v1, self.upstream()]
        done = self.update("-Push")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(git(self.remote, "tag", "--list"), "")
        refs = git(self.remote, "for-each-ref", "--format=%(refname)").splitlines()
        self.assertEqual(sorted(refs), sorted(["refs/heads/main", f"refs/heads/{OTHER}", f"refs/heads/{BRANCH}"]))
        for commit in ours:
            missing = subprocess.run(["git", "-C", str(self.remote), "cat-file", "-e", f"{commit}^{{commit}}"], capture_output=True)
            self.assertNotEqual(missing.returncode, 0, f"our commit {commit} reached the client")
        # The client branch's history is the client's own commits and the platform commits, nothing of ours.
        subjects = git(self.remote, "log", "--format=%s", BRANCH).splitlines()
        self.assertFalse([s for s in subjects if s.startswith("ours ")], subjects)

    def test_a_working_repository_as_the_source_is_refused(self):
        self.upstream()
        (self.source / "changed.txt").write_text("work in progress\n")
        done = self.update()
        self.assertEqual(done.returncode, 1)
        self.assertIn("the source folder has changes", done.stdout)
        git(self.source, "commit", "-q", "-am", "local work")
        done = self.update()
        self.assertEqual(done.returncode, 1)
        self.assertIn("commit(s) not on origin: it is a working repository", done.stdout)
        git(self.source, "switch", "-q", "-c", "my-feature")
        done = self.update()
        self.assertIn("branch 'my-feature', not master", done.stdout)
        git(self.source, "switch", "-q", "master"); git(self.source, "reset", "-q", "--hard", "origin/master")
        git(self.source, "branch", "-q", "--unset-upstream")
        done = self.update()
        self.assertIn("follows nothing, not origin/master", done.stdout)


@unittest.skipUnless(sys.platform == "win32", "update-platform.ps1 is Windows PowerShell")
class UpdatePlatformAtRoot(unittest.TestCase):
    """The platform at the root of a repository dedicated to it, laid out exactly as ours: the whole repository is the
    platform. The client's repository was created by its git host, with a README.md and .gitignore of its own."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        work = root / "ours-work"
        (work / "scripts").mkdir(parents=True)
        for name in ("update-platform.ps1", "write-platform-source.ps1"):
            shutil.copy2(SCRIPTS / name, work / "scripts" / name)
        (work / "README.md").write_text("# Modernization Platform\n")
        (work / ".gitignore").write_text("backend/.env\n.env\n")
        (work / ".gitattributes").write_text("*.yaml text eol=lf\n")
        (work / "changed.txt").write_text("v1\n")
        (work / "deleted.txt").write_text("goes upstream\n")
        (work / "docs").mkdir()
        (work / "docs" / "old-name.md").write_text("renamed upstream\n")
        git(work, "init", "-q", "-b", "master"); git(work, "add", "-A"); git(work, "commit", "-q", "-m", "ours v1")
        self.ours = root / "ours.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(work), str(self.ours)], check=True)
        self.work = root / "ours-dev"
        subprocess.run(["git", "clone", "-q", str(self.ours), str(self.work)], check=True)
        self.source = root / "source"
        subprocess.run(["git", "clone", "-q", str(self.ours), str(self.source)], check=True)
        # As the git host creates a repository: one commit with its own README.md and .gitignore.
        seed = root / "client-seed"
        seed.mkdir()
        (seed / "README.md").write_text("# platform-repository\nCreated by the git host.\n")
        (seed / ".gitignore").write_text("*.log\n")
        git(seed, "init", "-q", "-b", "main"); git(seed, "add", "-A"); git(seed, "commit", "-q", "-m", "Initial commit")
        self.remote = root / "client.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True)
        git(seed, "push", "-q", str(self.remote), "main")
        git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")
        self.client = root / "client"
        subprocess.run(["git", "clone", "-q", str(self.remote), str(self.client)], check=True)
        self.initial = git(self.client, "rev-parse", "HEAD")

    def tearDown(self):
        self.tmp.cleanup()

    def update(self, *extra: str) -> subprocess.CompletedProcess:
        return ps(self.source / "scripts" / "update-platform.ps1", "-Source", str(self.source), "-Platform",
                  str(self.client), "-Branch", "main", *extra)

    def record(self) -> dict:
        return json.loads((self.client / "PLATFORM_SOURCE.json").read_text(encoding="utf-8"))

    def upstream(self) -> str:
        (self.work / "changed.txt").write_text("v2\n")
        git(self.work, "rm", "-q", "deleted.txt")
        git(self.work, "mv", "docs/old-name.md", "docs/new-name.md")
        git(self.work, "commit", "-q", "-am", "ours v2: change, delete, rename")
        git(self.work, "push", "-q", "origin", "master")
        return git(self.work, "rev-parse", "HEAD")

    def test_a_first_delivery_replaces_the_hosts_readme_and_gitignore_and_lists_them(self):
        done = self.update("-Push")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("platform at the repository root", done.stdout)
        self.assertIn("Replaced with ours, the client's own file of the same name (2):", done.stdout)
        self.assertIn("  .gitignore", done.stdout)
        self.assertIn("  README.md", done.stdout)
        self.assertEqual((self.client / "README.md").read_text(), "# Modernization Platform\n")
        self.assertEqual((self.client / ".gitignore").read_text(), "backend/.env\n.env\n")
        self.assertEqual((self.client / ".gitattributes").read_text(), "*.yaml text eol=lf\n")
        self.assertEqual(self.record()["commit"], git(self.work, "rev-parse", "HEAD"))
        # One commit over the whole repository, on top of the host's own history, which .git keeps.
        self.assertEqual(git(self.client, "rev-parse", "HEAD~1"), self.initial)
        self.assertEqual(git(self.client, "status", "--porcelain"), "")
        self.assertEqual(git(self.remote, "rev-parse", "main"), git(self.client, "rev-parse", "HEAD"))
        self.assertIn("PLATFORM_SOURCE.json", git(self.client, "show", "--name-only", "--format=", "HEAD").splitlines())

    def test_a_clients_own_file_and_env_at_the_root_are_kept_through_an_update(self):
        self.assertEqual(self.update().returncode, 0)
        (self.client / "OPERATIONS.md").write_text("the client's own runbook\n")
        git(self.client, "add", "OPERATIONS.md"); git(self.client, "commit", "-q", "-m", "Client runbook")
        (self.client / ".env").write_text("SECRET=local\n")                         # local, ignored
        self.upstream()
        done = self.update()                                                       # the runbook was never imported
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Warning: the client's branch has 1 commit(s) in the platform folder that our repository has not imported", done.stdout)
        self.assertIn("Client runbook", done.stdout)
        self.assertIn("Kept, not part of the platform (1):\n  OPERATIONS.md", done.stdout)
        self.assertNotIn("Replaced with ours", done.stdout)
        self.assertEqual((self.client / "OPERATIONS.md").read_text(), "the client's own runbook\n")
        self.assertEqual((self.client / ".env").read_text(), "SECRET=local\n")
        self.assertEqual((self.client / "changed.txt").read_text(), "v2\n")

    def test_an_update_at_the_root_applies_a_deletion_and_a_rename(self):
        first = self.update()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        new = self.upstream()
        done = self.update()                    # the host's "Initial commit" predates the platform: not a client change
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Removed 2 file(s) we deleted or renamed", done.stdout)
        self.assertFalse((self.client / "deleted.txt").exists())
        self.assertFalse((self.client / "docs" / "old-name.md").exists())
        self.assertTrue((self.client / "docs" / "new-name.md").exists())
        self.assertEqual((self.client / "changed.txt").read_text(), "v2\n")
        self.assertEqual(self.record()["commit"], new)
        self.assertEqual(git(self.client, "status", "--porcelain"), "")

    def test_uncommitted_changes_anywhere_in_the_repository_stop_it_at_the_root(self):
        self.assertEqual(self.update().returncode, 0)
        (self.client / "README.md").write_text("edited\n")
        done = self.update()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("the platform folder has uncommitted changes", done.stdout)
        self.assertIn("README.md", done.stdout)

    def test_an_installed_root_without_platform_source_json_is_refused(self):
        self.assertEqual(self.update().returncode, 0)
        git(self.client, "rm", "-q", "PLATFORM_SOURCE.json"); git(self.client, "commit", "-q", "-m", "no record")
        self.upstream()
        done = self.update()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("no PLATFORM_SOURCE.json", done.stdout)


if __name__ == "__main__":
    unittest.main()
