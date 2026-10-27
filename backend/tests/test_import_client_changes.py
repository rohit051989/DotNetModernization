"""scripts/import-client-changes.ps1 on small repositories (docs/VDI-SETUP.md, "Importing a client's changes"): our
repository with a feature the client never received, a client repository that received the platform through
update-platform.ps1 and changed it, on main and on a release branch. Runs both scripts as the guide does, with
Windows PowerShell. The suites the import runs on master are a stand-in here (scripts/run-suites.ps1 in the scratch
repository), passing or failing as each test sets."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@t"]
FOLDER = "mp"
TERM = "zebracorp"        # an invented term standing for a client's name in the deny-list

SUITES = """if ($env:MP_TEST_SUITES -eq 'fail') { Write-Host 'stand-in suites: FAILED'; exit 1 }
Write-Host 'stand-in suites: passed'
exit 0
"""


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *IDENTITY, *args], check=True, capture_output=True, text=True).stdout.strip()


def ps(script: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, **(env or {})})


@unittest.skipUnless(sys.platform == "win32", "the scripts are Windows PowerShell")
class ImportClientChanges(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        # Ours: the scripts, files the client will change, delete and leave alone.
        seed = root / "ours-seed"
        (seed / "scripts").mkdir(parents=True)
        for name in ("update-platform.ps1", "write-platform-source.ps1", "import-client-changes.ps1"):
            shutil.copy2(SCRIPTS / name, seed / "scripts" / name)
        (seed / "scripts" / "run-suites.ps1").write_text(SUITES)
        (seed / "app.txt").write_text("one\ntwo\nthree\n")
        (seed / "gone.txt").write_text("the client deletes this\n")
        (seed / "kept.txt").write_text("nobody changes this\n")
        (seed / ".gitignore").write_text("backend/.env\n")
        git(seed, "init", "-q", "-b", "master"); git(seed, "add", "-A"); git(seed, "commit", "-q", "-m", "ours v1")
        self.ours = root / "ours.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(self.ours)], check=True)
        self.work = root / "ours-dev"                       # our working repository
        subprocess.run(["git", "clone", "-q", str(self.ours), str(self.work)], check=True)
        git(self.work, "config", "user.name", "t"); git(self.work, "config", "user.email", "t@t")
        self.source = root / "source"
        subprocess.run(["git", "clone", "-q", str(self.ours), str(self.source)], check=True)
        # The client's repository, on main, with the platform delivered into mp by update-platform.ps1.
        client_seed = root / "client-seed"
        client_seed.mkdir()
        (client_seed / "README.md").write_text("client\n")
        git(client_seed, "init", "-q", "-b", "main"); git(client_seed, "add", "-A"); git(client_seed, "commit", "-q", "-m", "client")
        self.remote = root / "client.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True)
        git(client_seed, "push", "-q", str(self.remote), "main")
        git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")
        self.client = root / "client"
        subprocess.run(["git", "clone", "-q", str(self.remote), str(self.client)], check=True)
        git(self.client, "config", "user.name", "client"); git(self.client, "config", "user.email", "client@client-a.example")
        self.platform = self.client / FOLDER
        self.platform.mkdir()
        self.deliver_and_check()
        self.received = self.record()["commit"]
        # A local .env on the client's machine, ignored by git: never imported.
        (self.platform / "backend").mkdir(exist_ok=True)
        (self.platform / "backend" / ".env").write_text("DB_PASSWORD=local-only-value\n")
        # Our master moves on with a feature the client never received.
        (self.work / "feature.txt").write_text("built for another installation\n")
        git(self.work, "add", "-A"); git(self.work, "commit", "-q", "-m", "ours: a feature for another installation")
        git(self.work, "push", "-q", "origin", "master")
        self.deny = root / "deny-list.txt"                  # outside every repository
        self.deny.write_text(f"# client names and hosts\n{TERM}\n")

    def tearDown(self):
        self.tmp.cleanup()

    def record(self) -> dict:
        return json.loads((self.platform / "PLATFORM_SOURCE.json").read_text(encoding="utf-8"))

    def deliver(self, *extra: str) -> subprocess.CompletedProcess:
        branch = git(self.client, "rev-parse", "--abbrev-ref", "HEAD")
        return ps(self.source / "scripts" / "update-platform.ps1", "-Source", str(self.source), "-Platform",
                  str(self.platform), "-Branch", branch, "-Push", *extra)

    def deliver_and_check(self):
        done = self.deliver()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def client_commit(self, message: str, files: dict[str, str | None], push: bool = True):
        """Writes (or, for None, deletes) files in the client's platform folder, commits and pushes."""
        for name, text in files.items():
            path = self.platform / name
            if text is None:
                git(self.client, "rm", "-q", "--", f"{FOLDER}/{name}")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
        git(self.client, "add", "-A", "--", FOLDER)
        git(self.client, "commit", "-q", "-m", message, "--", FOLDER)
        if push:
            git(self.client, "push", "-q", "-u", "origin", "HEAD")

    def import_(self, *extra: str, suites: str = "pass") -> subprocess.CompletedProcess:
        return ps(self.work / "scripts" / "import-client-changes.ps1", "-Platform", str(self.platform), "-Repository",
                  str(self.work), "-DenyList", str(self.deny), "-Push", *extra, env={"MP_TEST_SUITES": suites})

    def ours_file(self, ref: str, name: str) -> str | None:
        done = subprocess.run(["git", "-C", str(self.ours), "show", f"{ref}:{name}"], capture_output=True, text=True)
        return done.stdout if done.returncode == 0 else None

    def assert_refused(self, done: subprocess.CompletedProcess, *said: str):
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("Nothing was imported", done.stdout)
        for text in said:
            self.assertIn(text, done.stdout)
        self.assertEqual(git(self.ours, "rev-parse", "master"), self.ours_master)
        self.assertEqual(git(self.work, "rev-parse", "master"), self.ours_master)
        self.assertEqual(git(self.work, "status", "--porcelain"), "")
        self.assertFalse([b for b in git(self.work, "branch", "--list").split() if b.startswith("platform-import")])

    # ---- main into master

    def test_main_merges_exactly_the_clients_changes_into_master_and_our_feature_survives(self):
        self.client_commit("Client: notes for operators", {"notes.md": "how we run it\n"})
        self.client_commit("Client: tune the app, drop an unused file", {"app.txt": "one\nTWO, tuned\nthree\n", "gone.txt": None})
        head = git(self.client, "rev-parse", "HEAD")
        done = self.import_()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.ours_file("master", "app.txt"), "one\nTWO, tuned\nthree\n")
        self.assertEqual(self.ours_file("master", "notes.md"), "how we run it\n")
        self.assertIsNone(self.ours_file("master", "gone.txt"))
        self.assertEqual(self.ours_file("master", "feature.txt"), "built for another installation\n")
        self.assertEqual(self.ours_file("master", "kept.txt"), "nobody changes this\n")
        self.assertIsNone(self.ours_file("master", "PLATFORM_SOURCE.json"))
        self.assertIsNone(self.ours_file("master", "backend/.env"))           # the local .env never comes in
        message = git(self.ours, "log", "-1", "--format=%B", "master")
        self.assertEqual(message.splitlines()[0], "Client: tune the app, drop an unused file")
        self.assertIn("- Client: notes for operators", message)
        self.assertIn(f"Client-Commit: {head}", message)
        self.assertIn("Added (1):\n  notes.md", done.stdout)
        self.assertIn("Changed (1):\n  app.txt", done.stdout)
        self.assertIn("Deleted (1):\n  gone.txt", done.stdout)
        self.assertIn("stand-in suites: passed", done.stdout)
        self.assertIn("Pushed our master", done.stdout)
        # Our history is only added to: the feature commit is still an ancestor.
        self.assertIn("ours: a feature for another installation", git(self.ours, "log", "--format=%s", "master"))
        # Again: nothing new.
        self.ours_master = git(self.ours, "rev-parse", "master")
        again = self.import_()
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertIn("Nothing new to import", again.stdout)
        self.assertEqual(git(self.ours, "rev-parse", "master"), self.ours_master)

    def test_a_conflict_is_won_by_the_client_and_reported(self):
        (self.work / "app.txt").write_text("one\ntwo, ours\nthree\n")
        git(self.work, "commit", "-q", "-am", "ours: change line two"); git(self.work, "push", "-q", "origin", "master")
        self.client_commit("Client: change line two", {"app.txt": "one\ntwo, the client's\nthree\n"})
        done = self.import_()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.ours_file("master", "app.txt"), "one\ntwo, the client's\nthree\n")
        self.assertIn("The client's version won where both sides changed the same lines (1):\n  app.txt", done.stdout)
        self.assertIn("the client's version was kept:\n- app.txt", git(self.ours, "log", "-1", "--format=%B", "master"))

    # ---- a release branch

    def test_a_release_branch_is_created_by_the_first_import_and_merged_into_by_the_second(self):
        git(self.client, "switch", "-q", "-c", "release/feature-x")
        self.client_commit("Client: feature x, first part", {"feature-x.txt": "part one\n"})
        done = self.import_()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Target: our release/feature-x (new", done.stdout)
        self.assertNotIn("stand-in suites", done.stdout)                      # only master runs the suites
        self.assertEqual(self.ours_file("release/feature-x", "feature-x.txt"), "part one\n")
        self.assertIsNone(self.ours_file("master", "feature-x.txt"))
        self.assertIn(self.received, git(self.ours, "rev-list", "release/feature-x"))   # built on what the client received
        first = git(self.ours, "rev-parse", "release/feature-x")
        self.client_commit("Client: feature x, second part", {"feature-x.txt": "part one\npart two\n"})
        done = self.import_()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.ours_file("release/feature-x", "feature-x.txt"), "part one\npart two\n")
        self.assertIn(first, git(self.ours, "rev-list", "release/feature-x"))
        self.assertNotIn("version won", done.stdout)          # only what changed since the first import came in
        self.assertIn("Changed (1):\n  feature-x.txt", done.stdout)
        message = git(self.ours, "log", "-1", "--format=%B", "release/feature-x")
        self.assertEqual(message.splitlines()[0], "Client: feature x, second part")
        self.assertNotIn("first part", message)                              # since the previous import only

    # ---- the scan

    def refuse_setup(self):
        self.ours_master = git(self.ours, "rev-parse", "master")

    def test_a_deny_listed_term_in_code_is_refused_with_file_and_line(self):
        self.refuse_setup()
        self.client_commit("Client: endpoint", {"app.txt": "one\ntwo\nthree\nendpoint for ZebraCorp\n"})
        self.assert_refused(self.import_(), "app.txt:4: deny-listed term 'zebracorp'")

    def test_a_deny_listed_term_in_a_commit_message_is_refused(self):
        self.refuse_setup()
        self.client_commit(f"Client: fix for the {TERM} team", {"app.txt": "one\ntwo!\nthree\n"})
        self.assert_refused(self.import_(), "message, line 1: deny-listed term 'zebracorp'")

    def test_a_deny_listed_term_in_a_file_name_is_refused(self):
        self.refuse_setup()
        self.client_commit("Client: a runbook", {f"docs/{TERM}-runbook.md": "steps\n"})
        self.assert_refused(self.import_(), f"docs/{TERM}-runbook.md: deny-listed term 'zebracorp' in the file name")

    def test_a_deny_listed_term_in_the_branch_name_is_refused(self):
        self.refuse_setup()
        git(self.client, "switch", "-q", "-c", f"release/{TERM}-portal")
        self.client_commit("Client: portal", {"portal.txt": "portal\n"})
        self.assert_refused(self.import_(), f"branch name 'release/{TERM}-portal': deny-listed term 'zebracorp'")
        self.assertNotIn(TERM, git(self.ours, "branch", "--list"))

    def test_a_secret_is_refused_with_file_and_line(self):
        self.refuse_setup()
        self.client_commit("Client: settings", {
            "appsettings.json": '{\n  "Logging": "Information",\n  "Password": "Hunter2-Secret"\n}\n',
            "db.config": 'ConnectionString = "Server=db01;Database=shop;User Id=app;Password=pa55w0rd!"\n',
        })
        done = self.import_()
        self.assert_refused(done, "appsettings.json:3: a value for Password (Hu...)",
                            "db.config:1: a connection string with a password (pa...)")
        self.assertNotIn("Hunter2-Secret", done.stdout)                      # findings never repeat the secret

    def test_a_committed_env_file_is_refused_and_never_imported(self):
        self.refuse_setup()
        git(self.client, "add", "-f", "--", f"{FOLDER}/backend/.env")
        git(self.client, "commit", "-q", "-m", "Client: settings file", "--", FOLDER)
        git(self.client, "push", "-q", "origin", "HEAD")
        self.assert_refused(self.import_(), "backend/.env: a .env file, committed in the platform folder: never imported")

    # ---- master stays deployable

    def test_master_is_pushed_only_when_the_suites_pass(self):
        self.ours_master = git(self.ours, "rev-parse", "master")
        self.client_commit("Client: a change", {"app.txt": "one\ntwo\nthree\nfour\n"})
        done = self.import_(suites="fail")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("stand-in suites: FAILED", done.stdout)
        self.assertIn("Not pushed: master stays deployable", done.stdout)
        self.assertEqual(git(self.ours, "rev-parse", "master"), self.ours_master)          # not pushed
        self.assertIn("four", (self.work / "app.txt").read_text())                         # merged locally only

    # ---- the delivery waits for the import

    def test_a_delivery_is_refused_while_client_commits_are_unimported_and_accepted_after_the_import(self):
        self.client_commit("Client: hotfix in the app", {"app.txt": "one\ntwo, hot-fixed\nthree\n"})
        refused = self.deliver()
        self.assertEqual(refused.returncode, 1, refused.stdout)
        self.assertIn("has 1 commit(s) in the platform folder that our repository has not imported", refused.stdout)
        self.assertIn("Client: hotfix in the app", refused.stdout)
        self.assertEqual((self.platform / "app.txt").read_text(), "one\ntwo, hot-fixed\nthree\n")
        done = self.import_()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        delivered = self.deliver()
        self.assertEqual(delivered.returncode, 0, delivered.stdout + delivered.stderr)
        # The delivery brings back the client's fix and our feature together.
        self.assertEqual((self.platform / "app.txt").read_text(), "one\ntwo, hot-fixed\nthree\n")
        self.assertEqual((self.platform / "feature.txt").read_text(), "built for another installation\n")
        self.assertEqual(self.record()["commit"], git(self.ours, "rev-parse", "master"))

    def test_force_delivers_anyway_listing_what_is_lost(self):
        self.client_commit("Client: hotfix in the app", {"app.txt": "one\ntwo, hot-fixed\nthree\n"})
        (self.work / "app.txt").write_text("one\ntwo\nthree\nours\n")
        git(self.work, "commit", "-q", "-am", "ours: app"); git(self.work, "push", "-q", "origin", "master")
        done = self.deliver("-Force")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Delivering anyway (-Force)", done.stdout)
        self.assertIn("Client: hotfix in the app", done.stdout)

    # ---- refusals before anything happens

    def test_uncommitted_changes_in_our_repository_are_refused(self):
        self.ours_master = git(self.ours, "rev-parse", "master")
        self.client_commit("Client: a change", {"app.txt": "x\n"})
        (self.work / "kept.txt").write_text("edited in our working repository\n")
        done = self.import_()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("our working repository has uncommitted changes", done.stdout)

    def test_a_client_branch_behind_its_remote_is_refused(self):
        self.ours_master = git(self.ours, "rev-parse", "master")
        self.client_commit("Client: a change", {"app.txt": "x\n"})
        git(self.client, "reset", "-q", "--hard", "HEAD~1")
        done = self.import_()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("does not match origin/main", done.stdout)

    def test_a_received_commit_our_repository_lacks_is_refused(self):
        self.ours_master = git(self.ours, "rev-parse", "master")
        record = self.record()
        record["commit"] = "0123456789abcdef0123456789abcdef01234567"
        (self.platform / "PLATFORM_SOURCE.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        self.client_commit("Client: a change", {"app.txt": "x\n"})
        self.assert_refused(self.import_(), "which our repository does not have")


if __name__ == "__main__":
    unittest.main()
