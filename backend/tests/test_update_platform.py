"""scripts/update-platform.ps1 on small repositories (docs/VDI-SETUP.md, "Updating the platform"): a client repository
with its own history and someone else's branch, our source with a change, a delete and a rename. Runs the script as
the guide does, with Windows PowerShell."""
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
        git(work, "init", "-q", "-b", "main"); git(work, "add", "-A"); git(work, "commit", "-q", "-m", "ours v1")
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

    def tearDown(self):
        self.tmp.cleanup()

    def update(self, *extra: str) -> subprocess.CompletedProcess:
        return ps(self.platform / "scripts" / "update-platform.ps1", "-Source", str(self.source), "-Platform",
                  str(self.platform), "-Branch", BRANCH, *extra)

    def upstream(self):
        (self.work / "changed.txt").write_text("v2\n")
        git(self.work, "rm", "-q", "deleted.txt")
        git(self.work, "mv", "docs/old-name.md", "docs/new-name.md")
        git(self.work, "commit", "-q", "-am", "ours v2: change, delete, rename")
        git(self.work, "push", "-q", "origin", "main")
        return git(self.work, "rev-parse", "HEAD")

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
        record = json.loads((self.platform / "PLATFORM_SOURCE.json").read_text(encoding="utf-8"))
        self.assertEqual(record["commit"], new)
        self.assertNotEqual(record["previousCommit"], new)
        files = git(self.client, "show", "--name-only", "--format=", "HEAD").splitlines()
        self.assertTrue(files and all(f.startswith(FOLDER + "/") for f in files), files)
        self.assertIn(f"Source commit: {new}", git(self.client, "log", "-1", "--format=%B"))
        self.assertEqual(git(self.client, "rev-parse", "HEAD~1"), head)
        self.assertEqual(git(self.client, "status", "--porcelain", "--", "README.md"), "M README.md")
        self.assertEqual(git(self.remote, "rev-parse", BRANCH), git(self.client, "rev-parse", "HEAD"))
        self.assertEqual(git(self.remote, "rev-parse", OTHER), self.other_before)

    def test_it_stops_on_the_wrong_branch(self):
        # Another branch that carries the platform folder: the script is there, and stops naming the branch.
        git(self.client, "switch", "-q", "-c", "rohit/older-work")
        done = self.update()
        self.assertEqual(done.returncode, 1)
        self.assertIn(f"is on branch 'rohit/older-work', not '{BRANCH}'", done.stdout)
        self.assertIn("Nothing was committed", done.stdout)
        # A branch without the platform folder (the client's main): the script itself is not there to run, which
        # the guide's troubleshooting explains.
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

    def test_a_platform_folder_that_is_its_own_repository_is_refused(self):
        done = ps(self.platform / "scripts" / "update-platform.ps1", "-Source", str(self.source), "-Platform",
                  str(self.client), "-Branch", BRANCH)
        self.assertEqual(done.returncode, 1)
        self.assertIn("is the root of a git repository", done.stdout)


if __name__ == "__main__":
    unittest.main()
