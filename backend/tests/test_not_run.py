"""When a conversion counts as run, and what a refresh may touch (36-COPILOT-ENHANCED-CONVERSION Part N and Q).

- One check (app.engine.convert.not_run_because) for status() and preparation: not run means the branch is the
  baseline plus only the platform's commits, and no tracked file is modified or staged. An untracked file does not
  count, ignored or not; status() says "prepared" exactly when unrun() is True, in every worktree state.
- A conversion prepared for one engine, with a person's untracked file in its worktree, is refreshed at a rescan with
  both engines' inputs; the untracked file is still there, uncommitted, and the platform's commit holds only the inputs.
- An untracked file where the new inputs would be written is never overwritten: the refresh is refused before anything
  changes, naming it (kept at a rescan, FilesInTheWay from the command line).
- A kept conversion says its real cause, in the result and in last-prepare.json: commits beyond its inputs, or
  uncommitted changes to tracked files (named), or the collision (named).
- A backend starting starts no discovery run.

The branch, worktree and record are real; the package step, the inputs' content and the advisories are stood in for.
Run from backend/:  python -m unittest tests.test_not_run -v
"""
import asyncio
import importlib
import json
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from app.conversion import gitops
from app.engine import convert, engines, siblings
from app.engine import inputs as engine_inputs
from tests.tiers import slow

COPILOT_FILES = {".github/copilot-instructions.md": "# Conversion instructions\n",
                 ".github/upgrades/skills/applying-utc.md": "# applying-utc\n"}
CLAUDE_FILES = {".claude/CLAUDE.md": "# Conversion instructions\n", ".claude/settings.json": "{}\n",
                ".claude/skills/applying-utc/SKILL.md": "# applying-utc\n"}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@client-a.example", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def _platform_commit(repo: Path, name: str) -> None:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(name, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "--", name], check=True)
    subprocess.run(["git", "-C", str(repo), *gitops.PLATFORM_IDENTITY, "commit", "-qm", name], check=True)


class OneCheck(unittest.TestCase):
    """unrun() and status() in every worktree state, from one check."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        _git(self.repo, "init", "-q")
        (self.repo / "a.txt").write_text("a", encoding="utf-8")
        (self.repo / ".gitignore").write_text("bin/\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "base")
        self.base = _git(self.repo, "rev-parse", "HEAD")
        _platform_commit(self.repo, "package.csproj")               # the package step, then the inputs: the platform's
        _platform_commit(self.repo, ".github/copilot-instructions.md")
        self.head = _git(self.repo, "rev-parse", "HEAD")

    def record(self, worktree: Path | None = None) -> dict:
        return {"worktree": str(worktree or self.repo), "baseline": self.base, "head": self.head,
                "engagement": f"t-none-{uuid.uuid4().hex[:6]}", "repository": "r", "branch": "conversion/1"}

    def check(self, expected: bool, worktree: Path | None = None) -> str | None:
        wt = worktree or self.repo
        self.assertEqual(convert.unrun(wt, self.base), expected)
        status = convert.status(self.record(wt))
        self.assertEqual(status["state"] == "prepared", expected, status)        # the tab and preparation agree
        self.assertEqual(status["runBecause"] is None, expected)
        return status["runBecause"]

    def test_every_worktree_state(self):
        self.check(True)                                                          # clean, only the platform's commits
        (self.repo / ".goal-workflow.md").write_text("a tool's config\n", encoding="utf-8")
        self.check(True)                                                          # untracked: does not count
        self.assertEqual(convert.status(self.record())["untracked"], [".goal-workflow.md"])
        (self.repo / "bin").mkdir()
        (self.repo / "bin" / "x.dll").write_text("x", encoding="utf-8")
        self.check(True)                                                          # ignored: does not count
        self.assertEqual(convert.status(self.record())["untracked"], [".goal-workflow.md"])

        (self.repo / "a.txt").write_text("changed", encoding="utf-8")
        self.assertIn("uncommitted changes to 1 tracked file(s) (a.txt)", self.check(False))     # modified
        _git(self.repo, "add", "a.txt")
        self.assertIn("(a.txt)", self.check(False))                              # staged
        _git(self.repo, "reset", "-q", "--hard")
        self.check(True)                                                          # discarded: not run again
        (self.repo / "new.cs").write_text("class N {}", encoding="utf-8")
        _git(self.repo, "add", "new.cs")
        self.assertIn("(new.cs)", self.check(False))                             # a new file, staged
        _git(self.repo, "commit", "-qm", "a person's change")
        self.assertIn("1 commit(s) beyond its inputs that are not the platform's", self.check(False))
        self.assertEqual(self.check(False, self.repo / "missing"), "its worktree does not exist")

    def test_a_branch_that_no_longer_starts_from_its_baseline_counts_as_run(self):
        _git(self.repo, "checkout", "-q", "--orphan", "other")
        _git(self.repo, "commit", "-qm", "unrelated")
        self.assertEqual(self.check(False), "its branch no longer starts from its baseline")


@slow
class Refresh(unittest.TestCase):
    """A rescan's preparation on a real repository, worktree and record; the inputs' content stood in for."""

    def setUp(self):
        from app import models
        from app.db import SessionLocal
        from tests.support import TEST_ENGAGEMENT_ID, CommittedTestEngagement

        self.db = SessionLocal()
        self.addCleanup(self.db.close)
        self.engagement = CommittedTestEngagement(self.db)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve() / "App"
        self.root.mkdir()
        _git(self.root, "init", "-q", "-b", "main")
        (self.root / "a.txt").write_text("a", encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-qm", "base")
        name = f"NotRun-{uuid.uuid4().hex[:6]}"
        self.repo = models.Repository(engagement_id=TEST_ENGAGEMENT_ID, name=name, slug=name.lower(), source_type="local_path",
                                      local_path=str(self.root), local_path_normalised=str(self.root).lower(),
                                      root_folder_name=name, ingest_status="scanned",
                                      ingest_commit_sha=_git(self.root, "rev-parse", "HEAD"))
        self.db.add(self.repo)
        self.db.commit()
        self.home = convert.conversions_dir(TEST_ENGAGEMENT_ID, self.repo.slug)
        self.addCleanup(self.engagement.remove)
        self.addCleanup(lambda: (self.db.rollback(), self.db.query(models.ConversionPlan).filter_by(repository_id=self.repo.id).delete(),
                                 self.db.query(models.Repository).filter_by(id=self.repo.id).delete(), self.db.commit()))
        self.addCleanup(lambda: [gitops.remove(self.root, Path(r["worktree"])) for r in convert.records(TEST_ENGAGEMENT_ID, self.repo.slug)])
        self.addCleanup(lambda: shutil.rmtree(self.home, ignore_errors=True))
        self.both = True

        def files() -> dict:
            return {engines.COPILOT: dict(COPILOT_FILES), **({engines.CLAUDE: dict(CLAUDE_FILES)} if self.both else {})}

        def generate_both(db, engagement_id, slug, out, applied=None, warnings=None, unguided=None):
            made = files()
            for engine_files in made.values():
                engine_inputs.write(engine_files, out)
            return made, ({} if self.both else {engines.CLAUDE: "not prepared"})

        def planned(db, engagement_id, slug, base, branch, worktree, scope=None):
            plan = models.ConversionPlan(repository_id=self.repo.id, engagement_id=engagement_id, legacy_commit=base,
                                         target_layout="in_place", target_framework="net10.0", recipes=[], branch=branch,
                                         worktree_path=str(worktree))
            db.add(plan)
            db.commit()
            return plan, []

        stand_ins = ((convert, {"plan_packages": planned, "check_advisories": lambda *a, **k: [],
                                "run_packages": lambda *a: ([], {"seconds": 0, "cycles": 0, "flaky": []}),
                                "left_for_agent": lambda *a: {}, "generate": lambda *a, **k: {}}),
                     (siblings, {"detect": lambda root: []}),
                     (engine_inputs, {"generate_both": generate_both, "model_for": lambda *a: ({}, self.repo),
                                      "build_both": lambda *a, **k: (files(), {})}))
        for target, kwargs in stand_ins:
            for attr, stand_in in kwargs.items():
                patcher = mock.patch.object(target, attr, side_effect=stand_in)
                patcher.start()
                self.addCleanup(patcher.stop)

    def prepare(self, when_run: str = "keep") -> dict:
        return convert.prepare(self.db, self.repo.engagement_id, self.repo.slug, when_run=when_run, lookups_from_discovery=True)

    def prepared_for_copilot_only(self) -> tuple[dict, Path]:
        """Conversion 1 as one prepared before every conversion got both engines' inputs: GitHub Copilot's alone, and a
        record with no `engines`."""
        self.both = False
        done = self.prepare("new")
        self.both = True
        record = convert.record(self.repo.engagement_id, self.repo.slug, 1)
        record.pop("engines")
        record.pop("untracked", None)
        convert._write_record(record)
        return record, Path(done["worktree"])

    def test_an_untracked_file_does_not_stop_a_refresh_and_survives_it_uncommitted(self):
        before, wt = self.prepared_for_copilot_only()
        self.assertFalse((wt / ".claude").exists())
        (wt / ".goal-workflow.md").write_text("a tool's config\n", encoding="utf-8")
        (wt / ".claude").mkdir()
        (wt / ".claude" / "notes.md").write_text("a person's notes\n", encoding="utf-8")   # beside the inputs, not one

        done = self.prepare("keep")                                               # a rescan
        self.assertEqual((done["action"], done["number"]), ("refreshed", 1))
        record = convert.record(self.repo.engagement_id, self.repo.slug, 1)
        self.assertEqual({e: s["prepared"] for e, s in record["engines"].items()},
                         {engines.COPILOT: True, engines.CLAUDE: True})
        for path in (*COPILOT_FILES, *CLAUDE_FILES):
            self.assertTrue((wt / path).is_file(), path)
        self.assertIn("## B. Claude Code", Path(record["runbook"]).read_text(encoding="utf-8"))
        # The person's files: still there, unchanged and uncommitted, listed in the record, and in no platform commit.
        self.assertEqual((wt / ".goal-workflow.md").read_text(encoding="utf-8"), "a tool's config\n")
        self.assertEqual(sorted(record["untracked"]), [".claude/notes.md", ".goal-workflow.md"])
        status = _git(wt, "status", "--porcelain", "--untracked-files=all").splitlines()
        self.assertEqual(sorted(status), ["?? .claude/notes.md", "?? .goal-workflow.md"])
        committed = _git(wt, "log", "--name-only", "--format=", f"{record['baseline']}..HEAD").split()
        self.assertNotIn(".goal-workflow.md", committed)
        self.assertNotIn(".claude/notes.md", committed)
        inputs_commit = _git(wt, "show", "--name-only", "--format=", "HEAD").split()
        self.assertEqual(sorted(inputs_commit), sorted({*COPILOT_FILES, *CLAUDE_FILES}))
        self.assertEqual(convert.status(record)["state"], "prepared")
        self.assertNotEqual(before["preparedAt"] + before["head"], record["preparedAt"] + record["head"])

    def test_an_untracked_file_where_an_input_goes_is_refused_and_nothing_changes(self):
        from app import models

        before, wt = self.prepared_for_copilot_only()
        (wt / ".claude").mkdir()
        (wt / ".claude" / "CLAUDE.md").write_text("# A person's own instructions\n", encoding="utf-8")
        head, plans = _git(wt, "rev-parse", "HEAD"), self.db.query(models.ConversionPlan).filter_by(repository_id=self.repo.id).count()
        record_text = (self.home / "1" / convert.RECORD).read_text(encoding="utf-8")
        runbook_text = Path(before["runbook"]).read_text(encoding="utf-8")

        done = self.prepare("keep")
        self.assertEqual((done["action"], done["keptBecause"], done["reasonDetails"]), ("kept", "collision", [".claude/CLAUDE.md"]))
        self.assertIn("1 untracked file(s) in its worktree sit where the new inputs would be written (.claude/CLAUDE.md)",
                      done["reason"])
        with self.assertRaises(convert.FilesInTheWay) as raised:                 # the command line: refused
            self.prepare("new")
        self.assertEqual(raised.exception.files, [".claude/CLAUDE.md"])
        # Nothing changed: the branch, the person's file, the record, the runbook, the plans.
        self.assertEqual(_git(wt, "rev-parse", "HEAD"), head)
        self.assertEqual((wt / ".claude" / "CLAUDE.md").read_text(encoding="utf-8"), "# A person's own instructions\n")
        self.assertFalse((wt / ".claude" / "settings.json").exists())
        self.assertEqual((self.home / "1" / convert.RECORD).read_text(encoding="utf-8"), record_text)
        self.assertEqual(Path(before["runbook"]).read_text(encoding="utf-8"), runbook_text)
        self.assertEqual(self.db.query(models.ConversionPlan).filter_by(repository_id=self.repo.id).count(), plans)
        self.assertEqual(len(convert.records(self.repo.engagement_id, self.repo.slug)), 1)

    def test_a_file_the_platform_wrote_earlier_is_not_in_the_way(self):
        _, wt = self.prepared_for_copilot_only()
        (wt / ".claude").mkdir()
        (wt / ".claude" / "settings.json").write_text(CLAUDE_FILES[".claude/settings.json"], encoding="utf-8")
        self.assertEqual(self.prepare("keep")["action"], "refreshed")             # the same text it writes: not a person's

    def test_a_kept_conversion_says_its_real_cause(self):
        _, wt = self.prepared_for_copilot_only()
        (wt / "a.txt").write_text("changed by hand\n", encoding="utf-8")
        done = self.prepare("keep")
        self.assertEqual((done["action"], done["keptBecause"], done["reasonDetails"]), ("kept", "tracked changes", ["a.txt"]))
        self.assertIn("uncommitted changes to 1 tracked file(s) (a.txt): commit them on the branch, or discard them",
                      done["reason"])
        self.assertNotIn("has been run", done["reason"])
        _git(wt, "commit", "-qam", "a person's change")
        done = self.prepare("keep")
        self.assertEqual((done["action"], done["keptBecause"]), ("kept", "run"))
        self.assertIn("1 commit(s) beyond its inputs that are not the platform's", done["reason"])
        self.assertIn("start the next conversion from the UI", done["reason"])

    def test_the_preparation_step_records_the_cause_and_the_files_for_the_tab(self):
        from app.config import settings
        from app.steps import conversion_preparation
        from app.workflow.contract import StepContext

        _, wt = self.prepared_for_copilot_only()
        (wt / ".claude").mkdir()
        (wt / ".claude" / "CLAUDE.md").write_text("# A person's own instructions\n", encoding="utf-8")
        result = conversion_preparation.run(StepContext(
            step_name="conversion-preparation", step_version="1.0.0", job_name="phase0-repository-discovery",
            job_execution_id=str(uuid.uuid4()), step_execution_id=str(uuid.uuid4()),
            parameters={"repository_id": str(self.repo.id)}, working_dir=".", output_dir=".",
            database_url=settings.database_url))
        self.assertEqual(result.exit_status, "COMPLETED")
        last = json.loads((self.home / conversion_preparation.LAST_PREPARE).read_text(encoding="utf-8"))
        self.assertEqual((last["status"], last["keptBecause"], last["details"]), ("kept", "collision", [".claude/CLAUDE.md"]))
        self.assertIn(".claude/CLAUDE.md", last["message"])

    def test_the_tab_says_prepared_for_one_engine_only_and_how_to_add_the_other(self):
        from app.results import conversions as shared

        _, wt = self.prepared_for_copilot_only()
        entry = shared.local_snapshot(self.repo)["entries"][0]
        self.assertEqual(entry["one_engine"]["engine"], engines.COPILOT)
        self.assertIn("rescan the repository", entry["one_engine"]["how"])
        self.assertIn("Claude Code's inputs", entry["one_engine"]["how"])
        _git(wt, "commit", "--allow-empty", "-qm", "a person's change")
        entry = shared.local_snapshot(self.repo)["entries"][0]
        self.assertIn("start the next conversion", entry["one_engine"]["how"])


class NoRunAtStart(unittest.TestCase):
    def test_a_backend_starting_starts_no_discovery_run(self):
        from app import main

        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("app.engine.both_engines")
        started = []
        with mock.patch.object(main, "Heartbeat"), mock.patch.object(main.platform_version, "Watch"), \
                mock.patch.object(main.platform_version, "check_at_start", return_value=None), \
                mock.patch("app.workflow.runtime.service.create_execution", side_effect=lambda *a, **k: started.append(a)), \
                mock.patch("app.workflow.runtime.service.launch_job", side_effect=lambda *a, **k: started.append(a)), \
                mock.patch("app.workflow.runtime.service.run_execution_in_background",
                           side_effect=lambda *a, **k: started.append(a)):
            async def start_and_stop():
                async with main.lifespan(main.app):
                    pass
            asyncio.run(start_and_stop())
        self.assertEqual(started, [])


if __name__ == "__main__":
    unittest.main()
