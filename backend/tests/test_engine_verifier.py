"""The verifier's fixed rules and comparisons (36-COPILOT-ENHANCED-CONVERSION Part E), without .NET or a database.
The end-to-end calibration on eShopOnWeb is run by hand (`python -m app.experiment.calibrate`, which writes CALIBRATION.md).

Run: python -m unittest tests.test_engine_verifier
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

from app import engine  # noqa: F401
from app.engine import verifier
from app.engine.verifier import plugin, rediscovery


def _c(state, cid="x"):
    return {"id": cid, "label": cid, "state": state, "detail": f"{cid} {state}"}


def _model(items):
    return {"items": items, "deltas": [], "projects": []}


def _item(item_id, project, file, line=5, impact=()):
    return {"id": item_id, "name": item_id, "occurrences": [{"project": project, "file": file, "value": None,
                                                              "lines": [{"line": line, "value": "v"}]}],
            "impact": list(impact)}


class Verdict(unittest.TestCase):
    def test_any_fail_is_not_proven_any_gap_is_partly_else_proven(self):
        self.assertEqual(verifier.verdict([_c("pass"), _c("na"), _c("info")])[0], "PROVEN")
        self.assertEqual(verifier.verdict([_c("pass"), _c("gap")])[0], "PARTLY PROVEN")
        self.assertEqual(verifier.verdict([_c("gap"), _c("fail"), _c("pass")])[0], "NOT PROVEN")

    def test_every_reason_is_given_fails_first(self):
        _, reasons = verifier.verdict([_c("gap", "kept"), _c("fail", "clean"), _c("pass", "diff")])
        self.assertEqual(reasons, ["clean: clean fail", "kept: kept gap"])

    def test_the_rules_are_written_into_the_output(self):
        self.assertTrue(any(r.startswith("NOT PROVEN when") for r in verifier.RULES))
        self.assertTrue(any("never judged" in r for r in verifier.RULES))
        self.assertTrue(any(".github/upgrades/" in r for r in verifier.RULES))


class Diff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        git = lambda *a: subprocess.run(["git", "-C", str(self.root), *a], check=True, capture_output=True)  # noqa: E731
        git("init", "-q")
        (self.root / "src").mkdir()
        (self.root / "src" / "A.cs").write_text("a\n", encoding="utf-8")
        git("add", ".")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
        self.base = subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.git = git

    def commit(self, files):
        for rel, text in files.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text, encoding="utf-8")
        self.git("add", ".")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "change")
        return subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

    def test_engine_state_and_generated_inputs_are_excluded(self):
        tip = self.commit({".github/upgrades/dotnet-version-upgrade/plan.md": "plan\n",
                           ".github/upgrades/skills/applying-x.md": "x\n", ".github/skills/s.md": "s\n",
                           ".github/copilot-instructions.md": "g\n", ".github/platform-inputs/decision-sheet.md": "d\n"})
        d = verifier.diff(self.root, self.base, tip)
        self.assertEqual(d["files"], [])                     # nothing converted
        self.assertEqual(len(d["excluded"]), 5)

    def test_conversion_is_counted(self):
        tip = self.commit({"src/A.cs": "b\nc\n", ".github/workflows/ci.yml": "on: push\n", ".github/upgrades/x/tasks.md": "t\n"})
        d = verifier.diff(self.root, self.base, tip)
        self.assertEqual(sorted(f["path"] for f in d["files"]), [".github/workflows/ci.yml", "src/A.cs"])
        self.assertEqual((d["filesTouched"], d["commits"]), (2, 1))
        self.assertEqual((d["linesAdded"], d["linesDeleted"]), (3, 1))


class ImpactComparison(unittest.TestCase):
    def test_unpredicted_and_untouched_are_reported(self):
        model = _model([
            _item("datetime-now-usage", "src/A/A.csproj", "src/A/Order.cs", impact=[
                {"action": "update", "file": "src/A/Order.cs", "proposed": None},
                {"action": "update", "file": "src/A/Other.cs", "proposed": None}]),
            _item("missing-ocp4-manifests", "src/A/A.csproj", None, impact=[
                {"action": "create", "file": None, "proposed": "deploy/openshift/"},
                {"action": "review", "file": "src/A/Program.cs", "proposed": None}]),
        ])
        changed = [{"path": "src/A/Order.cs", "change": "M"}, {"path": "src/A/Program.cs", "change": "M"},
                   {"path": "deploy/openshift/deployment.yaml", "change": "A"}, {"path": "src/B/Surprise.cs", "change": "M"}]
        got = verifier.impact_comparison(model, changed)
        self.assertEqual(got["unpredicted"], ["src/B/Surprise.cs"])
        self.assertEqual(got["predictedUntouched"], ["src/A/Other.cs"])
        self.assertEqual(got["createsMade"], 1)
        self.assertEqual(got["reviewTouched"], ["src/A/Program.cs"])


class WorkItems(unittest.TestCase):
    def test_a_work_item_is_a_found_project_and_item(self):
        model = _model([_item("datetime-now-usage", "src/A/A.csproj", "src/A/Order.cs", 23),
                        _item("package-upgrade-safe", "src/B/B.csproj", "src/B/B.csproj", 13)])
        got = rediscovery.work_items(model)
        self.assertEqual(sorted(got), [("src/A/A.csproj", "datetime-now-usage"), ("src/B/B.csproj", "package-upgrade-safe")])
        self.assertEqual(got[("src/A/A.csproj", "datetime-now-usage")]["places"], ["src/A/Order.cs:23"])


class DeltaCatalog(unittest.TestCase):
    def test_the_plugin_reads_the_silent_deltas_the_verifier_writes(self):
        model = _model([_item("datetime-now-usage", "src/A/A.csproj", "src/A/Order.cs", 23)])
        model["deltas"] = [{"id": "net10-public-top-level-program", "sites": {"src/Web/Program.cs": ["tests/X.cs"]}}]
        deltas = plugin.uplift_checks.parse_deltas(verifier.delta_catalog(model))
        silent = [d for d in deltas if plugin.uplift_checks.SILENT.search(d["category"])]
        self.assertEqual(len(silent), 1)
        self.assertEqual(silent[0]["sites"][0]["path"], "src/A/Order.cs")
        self.assertEqual(len(deltas), 2)


    def test_an_empty_catalog_has_no_rows_for_the_plugin_to_misread(self):
        self.assertNotIn("| D-", verifier.delta_catalog(_model([])))


class Checkout(unittest.TestCase):
    def test_a_scratch_worktree_is_absolute_and_never_inside_the_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp) / "repo"
            with self.assertRaises(ValueError):
                verifier._outside(checkout, Path("runs/x"))
            with self.assertRaises(ValueError):
                verifier._outside(checkout, checkout / "runs" / "x")
            verifier._outside(checkout, Path(tmp) / "elsewhere" / "x")


class Isolation(unittest.TestCase):
    def test_the_rediscovery_worker_refuses_any_database_but_a_verifier_scratch_one(self):
        backend = Path(__file__).resolve().parents[1]
        done = subprocess.run([str(backend / ".venv" / "Scripts" / "python.exe"), "-m", "app.engine.verifier.rediscovery", "--worker",
                               "--engagement", "x", "--path", "x", "--name", "x", "--out", "x"],
                              cwd=backend, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 2)
        self.assertIn("runs only in a verifier scratch schema", done.stderr)

    def test_the_engagement_rows_copied_are_the_engagements_own(self):
        self.assertEqual([t for t, column in rediscovery.ENGAGEMENT_ROWS if column is None], ["package_lookup_cache"])
        self.assertEqual(rediscovery.ENGAGEMENT_ROWS[0], ("engagements", "id"))


class Siblings(unittest.TestCase):
    def test_a_junction_beside_the_worktree_is_removed_without_touching_its_target(self):
        from app.engine import siblings

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "apps" / "App").mkdir(parents=True)
            (root / "apps" / "Feed").mkdir()
            (root / "apps" / "Feed" / "pkg.nupkg").write_text("x", encoding="utf-8")
            worktree = root / "runs" / "exp" / "arm1-run1"
            worktree.mkdir(parents=True)
            made = siblings.link(worktree, root / "apps" / "App", ["Feed"])
            self.assertEqual(made, [worktree.parent / "Feed"])
            self.assertTrue((worktree.parent / "Feed" / "pkg.nupkg").exists())
            self.assertEqual(siblings.link(worktree, root / "apps" / "App", ["Feed"]), [])   # idempotent
            siblings.remove(worktree.parent, ["Feed"])
            self.assertFalse((worktree.parent / "Feed").exists())
            self.assertTrue((root / "apps" / "Feed" / "pkg.nupkg").exists())


if __name__ == "__main__":
    unittest.main()
