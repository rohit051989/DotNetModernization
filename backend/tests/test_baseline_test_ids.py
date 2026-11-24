"""Baseline tests keyed by class and method, never by method name alone (the vendored baseline_diff, MODIFIED; the
verifier's reruns and approved removals).

MSTest and NUnit write a TRX result's testName as the bare method name; its class is in the test definition. Three test
projects whose classes share their method names (CloseChecks, Invoices.Tests, RemindersTest, each a ClockTests with
Stamps and StampsATime) are six tests, not two: the measured baseline agrees with its six-test table, a failing test is
rerun as itself, and a passing namesake in another class never stands in for it.

Run from backend/:  python -m unittest tests.test_baseline_test_ids -v
"""
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from app.engine import verifier
from app.engine.verifier import plugin

bd = plugin.baseline_diff
NS = "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"


def trx(results: list[tuple[str, str, str]], qualified: bool = False, class_suffix: str = "") -> str:
    """A TRX file as MSTest writes it: (class, method, outcome) per result, the class only in the test definition (or
    also in testName, as xUnit writes it, when `qualified`)."""
    out, definitions = [], []
    for klass, method, outcome in results:
        test_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{klass}.{method}"))
        name = f"{klass}.{method}" if qualified else method
        out.append(f'<UnitTestResult testId="{test_id}" testName="{name}" outcome="{outcome}"/>')
        definitions.append(f'<UnitTest name="{method}" id="{test_id}"><Execution id="{uuid.uuid4()}"/>'
                           f'<TestMethod codeBase="x.dll" className="{klass}{class_suffix}" name="{method.split("(")[0]}"/></UnitTest>')
    return (f'<?xml version="1.0" encoding="utf-8"?><TestRun xmlns="{NS}"><Results>{"".join(out)}</Results>'
            f'<TestDefinitions>{"".join(definitions)}</TestDefinitions></TestRun>')


PROJECTS = ("CloseChecks", "Invoices.Tests", "RemindersTest")


class Ids(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="trx-ids-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, name: str, text: str) -> str:
        (self.root / name).write_text(text, encoding="utf-8")
        return str(self.root / name)

    def three_projects(self, folder: str, close_stamps: str = "Passed") -> list[str]:
        return [self.write(f"{folder}-{p}.trx", trx([(f"{p}.ClockTests", "Stamps", close_stamps if p == "CloseChecks" else "Passed"),
                                                       (f"{p}.ClockTests", "StampsATime", "Passed")]))
                for p in PROJECTS]

    def test_same_method_names_in_three_projects_are_six_tests(self):
        rep = bd.read_results(self.three_projects("clean"))
        self.assertEqual(sorted(rep["tests"]), sorted(f"{p}.ClockTests#{m}" for p in PROJECTS for m in ("Stamps", "StampsATime")))
        self.assertEqual(rep["classes"]["Invoices.Tests.ClockTests"]["executed"], 2)

    def test_the_measured_baseline_agrees_with_its_six_test_table(self):
        baseline = self.root / "analysis" / "app"
        (baseline / "baseline").mkdir(parents=True)
        for path in self.three_projects("base"):
            shutil.copy(path, baseline / "baseline")
        (baseline / "BASELINE.md").write_text("# Baseline\n\n- **Recorded:** machine-readable per-test results in `baseline/`.\n\n"
                                              "| Totals | Count |\n|---|---|\n| Executed | 6 |\n| Passed | 6 |\n| Failed | 0 |\n"
                                              "| Skipped | 0 |\n", encoding="utf-8")
        report = bd.run(str(baseline / "BASELINE.md"), self.three_projects("clean"))
        assessment = report["baseline"]["assessment"]
        self.assertEqual((assessment["kind"], assessment["measuredTests"], assessment["disagree"]), ("measured", 6, 0))
        self.assertEqual(report["fresh"]["counts"]["pass"], 6)
        # One class's test failing is that test, not its namesakes.
        report = bd.run(str(baseline / "BASELINE.md"), self.three_projects("red", close_stamps="Failed"))
        self.assertEqual([r["id"] for r in report["regressions"]], ["CloseChecks.ClockTests#Stamps"])

    def test_xunit_qualified_names_and_older_class_names_give_the_same_ids(self):
        qualified = bd.read_results([self.write("x.trx", trx([("Ns.Facts", "Valid(x: 1)", "Passed")], qualified=True))])
        self.assertEqual(qualified["tests"], {"Ns.Facts#Valid(x: 1)": "PASS"})
        older = bd.read_results([self.write("o.trx", trx([("Ns.Facts", "Valid", "Failed")],
                                                         class_suffix=", Facts, Version=1.0.0.0, Culture=neutral"))])
        self.assertEqual(older["tests"], {"Ns.Facts#Valid": "FAIL"})
        # A file without definitions reads as before: the class split from a qualified testName, else none.
        bare = bd.read_results([self.write("b.trx", f'<TestRun xmlns="{NS}"><Results><UnitTestResult testName="Ns.K.Good" '
                                                    'outcome="Passed"/><UnitTestResult testName="Lone" outcome="Passed"/>'
                                                    '</Results></TestRun>')])
        self.assertEqual(bare["tests"], {"Ns.K#Good": "PASS", "Lone": "PASS"})


class Reruns(unittest.TestCase):
    def test_a_failing_test_is_rerun_as_itself_and_a_passing_namesake_is_not_taken_for_it(self):
        self.assertEqual(verifier.rerun_filter("CloseChecks.ClockTests#Stamps"), "FullyQualifiedName~CloseChecks.ClockTests.Stamps")
        self.assertEqual(verifier.rerun_filter('Ns.K#Valid ("a","1")~1'), "FullyQualifiedName~Ns.K.Valid")
        self.assertEqual(verifier.rerun_filter("Lone"), "Name=Lone")
        asked = []

        def rerun(worktree, project, trx_path, filter=None):
            # The rerun of CloseChecks: its Stamps fails again; Invoices.Tests' Stamps, a namesake, passes.
            asked.append(filter)
            outcome = "Failed" if project.startswith("CloseChecks") else "Passed"
            klass = f"{Path(project).stem}.ClockTests"
            trx_path.parent.mkdir(parents=True, exist_ok=True)
            trx_path.write_text(trx([(klass, "Stamps", outcome)]), encoding="utf-8")
            return None, None

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(verifier.dotnet, "test", side_effect=rerun):
            flaky, still = verifier.rerun_failing(Path(tmp), ["CloseChecks/CloseChecks.csproj", "Invoices.Tests/Invoices.Tests.csproj"],
                                                  ["CloseChecks.ClockTests#Stamps"], Path(tmp) / "rerun")
        self.assertEqual((flaky, still), ([], ["CloseChecks.ClockTests#Stamps"]))
        self.assertEqual(asked, ["FullyQualifiedName~CloseChecks.ClockTests.Stamps"] * 2)

    def test_an_approval_names_the_test_or_its_method_as_an_earlier_verification_named_it(self):
        approvals = [{"test": "Invoices.Tests.ClockTests#Stamps", "reason": "r", "approvedBy": "A", "at": "t"},
                     {"test": "StampsATime", "reason": "r", "approvedBy": "A", "at": "t"}]
        approved, rest = verifier.approved_removals(["Invoices.Tests.ClockTests#Stamps", "CloseChecks.ClockTests#Stamps",
                                                     "CloseChecks.ClockTests#StampsATime"], approvals)
        self.assertEqual([a["test"] for a in approved], ["Invoices.Tests.ClockTests#Stamps", "CloseChecks.ClockTests#StampsATime"])
        self.assertEqual(rest, ["CloseChecks.ClockTests#Stamps"])

    def test_an_old_bare_name_approval_shared_by_two_classes_approves_neither_and_is_listed_for_reapproval(self):
        # Recorded before tests were keyed by class: "Stamps" and "Totals" by method name alone.
        approvals = [{"test": "Stamps", "reason": "moved to the clock service", "approvedBy": "A", "at": "2026-11-20"},
                     {"test": "Totals", "reason": "duplicated", "approvedBy": "B", "at": "2026-11-20"}]
        missing = ["CloseChecks.ClockTests#Stamps", "Invoices.Tests.ClockTests#Totals"]
        # The repository's tests: Stamps in two classes (one still running), Totals in one.
        tests = missing + ["Invoices.Tests.ClockTests#Stamps", "Invoices.Tests.ClockTests#StampsATime"]
        approved, rest = verifier.approved_removals(missing, approvals, tests)
        self.assertEqual([a["test"] for a in approved], ["Invoices.Tests.ClockTests#Totals"])
        self.assertEqual(rest, ["CloseChecks.ClockTests#Stamps"])
        renew = verifier.to_reapprove(approvals, tests)
        self.assertEqual([(a["test"], a["classes"]) for a in renew],
                         [("Stamps", ["CloseChecks.ClockTests", "Invoices.Tests.ClockTests"])])
        # A full name or a test file is never ambiguous; a data row's method counts as its method.
        self.assertEqual(verifier.to_reapprove([{"test": "CloseChecks.ClockTests#Stamps", "reason": "r", "approvedBy": "A"},
                                                {"test": "Tests/ClockTests.cs", "reason": "r", "approvedBy": "A"}], tests), [])
        self.assertEqual(verifier._classes_named("Valid", ['Ns.K#Valid ("a")', "Ns.L#Valid"]), ["Ns.K", "Ns.L"])
        # VERIFICATION.md lists it, with the classes, under "Approvals to renew".
        md = verifier.markdown(_report(reapprove=renew))
        self.assertIn("## Approvals to renew", md)
        self.assertIn("| `Stamps` | `CloseChecks.ClockTests`, `Invoices.Tests.ClockTests` | moved to the clock service | A |", md)


def _report(**fields) -> dict:
    """The least report markdown() renders (as tests.test_engine_convert's), with `fields`."""
    return {"label": "x", "verdict": "NOT PROVEN", "repository": "r", "base": "b" * 8, "ref": "r", "tip": "t" * 8,
            "verifiedAt": "now", "verifier": {"version": "v", "plugin": "p"}, "reasons": [], "checks": [], "rules": [],
            "forAPerson": [], "rediscovery": {"before": 0, "resolved": [], "remaining": [], "introduced": [], "offTarget": []},
            "impact": {"predictedFiles": 0, "predictedCreates": 0, "changedFiles": 0, "unpredicted": [], "predictedUntouched": []},
            "diff": {"filesTouched": 0, "linesAdded": 0, "linesDeleted": 0, "commits": 0}, "excludedPaths": [],
            "testFiles": {"changed": [], "added": [], "removed": []}, **fields}


if __name__ == "__main__":
    unittest.main()
