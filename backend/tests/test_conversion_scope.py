"""The conversion scope (36-COPILOT-ENHANCED-CONVERSION.md Part O; app.scope) on the synthetic 170-project repository,
with its four solutions sharing projects (tests/fixtures/synthetic_repository.py, `solutions`).

The repository is generated into a scratch folder, committed, registered to a developer on a simulated machine, and
discovered by the real job in this test run's own schema (tests/__init__.py). Saves go through the API as a server
would call it (tests.asgi_client), through the real guard and policy. Preparation is the real one, with the advisory
check and sibling detection stood in for; the verifier's builds, tests and re-discovery are stood in for, its rules
are the real ones. The tests run in order: each builds on the scope the one before saved.

- a repository nobody has scoped converts everything, as before;
- Save is refused while a kept project's dependency is excluded, with every problem listed together, and accepted once
  fixed; Deselect all is refused; a non-owner's save and a save from a stale copy are refused;
- the work list marks the excluded findings and counts them, and deletes none;
- preparation writes the OUT-OF-SCOPE.md notes (never over a file already there) and the solution filters, and the
  package step and the instructions leave the excluded projects out;
- saving a changed scope prepares an unrun conversion again; a conversion already run keeps its scope;
- the verifier builds and tests the filter, and the excluded projects' tests and findings are not counted;
- a rescan keeps the scope, flags a new project, and drops an excluded project that is gone.

Uses stdlib unittest, same rationale as test_repository_ingest.py. About five minutes: two discovery runs.
"""
import contextlib
import json
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from sqlalchemy import text

from app import models
from app.auth import machine, service
from app.config import settings
from app.conversion import gitops, planner
from app.db import SessionLocal
from app.deletion import service as deletion
from app.engine import convert, siblings
from app.main import app
from app.repositories import service as repositories_service
from app.repositories.schemas import RegisterLocalPathRequest
from app.results import store
from app.scope import service as scope
from app.workflow.runtime import service as runtime
from tests.asgi_client import Client
from tests.fixtures import synthetic_repository as synth

ENGAGEMENT = "t-engagement-scope"
PASSWORD = "a-long-enough-password"
PLANTED = "src/Data/SynthCo.Data.01/OUT-OF-SCOPE.md"


def git(folder: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True, text=True).stdout.strip()


@contextlib.contextmanager
def on(host: str, account: str):
    with mock.patch.object(machine, "hostname", return_value=host), \
            mock.patch.object(machine, "windows_account", return_value=account):
        yield


def discover(db, repo) -> models.WfJobExecution:
    with mock.patch.object(settings, "compare_public_nuget_feed", False):
        token = repositories_service.start_rescan(repo)
        db.commit()
        execution = runtime.launch_job(db, "phase0-repository-discovery", {
            "engagement_id": ENGAGEMENT, "repository_id": str(repo.id), "ingest_token": token,
            "lookup_offline": True, "prepare_conversion": False}, triggered_by="manual")
        db.commit()
    return execution


def path(name: str) -> str:
    return synth.path_of(name)


class ConversionScopeAtScale(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name).resolve() / "SynthCo170"
        synth.generate(cls.root, solutions=True)
        # The repository's own note in a project that will be left out: never overwritten.
        (cls.root / PLANTED).write_text("Our own notes about this project.\n", encoding="utf-8")
        git(cls.root, "init", "-q", "-b", "main")
        git(cls.root, "add", "-A")
        git(cls.root, "-c", "user.name=Dev", "-c", "user.email=dev@client-a.example", "commit", "-qm", "base")

        cls.tag = uuid.uuid4().hex[:6]
        cls.ann = (rf"CORP\ann{cls.tag}", f"HOST-A-{cls.tag}", f"ann-{cls.tag}")
        cls.ben = (rf"CORP\ben{cls.tag}", f"HOST-B-{cls.tag}", f"ben-{cls.tag}")
        cls.db = SessionLocal()
        cls.users = {}
        for (account, host, login), name in ((cls.ann, "Ann"), (cls.ben, "Ben")):
            cls.users[login] = service.create_user(cls.db, login=login, name=name, windows_account=account, role="developer",
                                                   host_names=[host], password=PASSWORD, must_change_password=False).id
        cls.db.add(models.Engagement(id=ENGAGEMENT, client_name="Test engagement (scope)",
                                     target_platform="Linux / OpenShift Container Platform 4", default_posture="lift-and-shift"))
        cls.db.commit()
        cls.repo = repositories_service.register_local_path(
            cls.db, cls.db.get(models.Engagement, ENGAGEMENT), RegisterLocalPathRequest(source_type="local_path", local_path=str(cls.root)))
        cls.repo.owner_user_id, cls.repo.registered_host = cls.users[cls.ann[2]], cls.ann[1]
        cls.db.commit()
        cls.discovery = discover(cls.db, cls.repo)
        cls.db.refresh(cls.repo)
        cls.url = f"/api/repositories/{cls.repo.id}/scope"
        cls.projects = scope._projects(cls.db, cls.repo.id)
        cls.all = [p["path"] for p in cls.projects]

    @classmethod
    def tearDownClass(cls):
        cls.db.rollback()
        engagement = cls.db.get(models.Engagement, ENGAGEMENT)
        if engagement is not None:
            deletion.delete(cls.db, deletion.engagement_plan(cls.db, engagement), engagement.client_name, via="test")
        for user_id in cls.users.values():
            cls.db.execute(text("update activity_records set user_id = null where user_id = :u"), {"u": user_id})
            cls.db.execute(text("delete from users where id = :u"), {"u": user_id})
        cls.db.commit()
        cls.db.close()
        cls.tmp.cleanup()

    # ---------- helpers

    def client(self, who) -> Client:
        client = Client(app)
        with on(who[1], who[0]):
            answer = client.post("/api/auth/sign-in", {"login": who[2], "password": PASSWORD})
        self.assertEqual(answer.status, 200, answer.body)
        return client

    def save(self, who, excluded, version, reason=None):
        client = self.client(who)
        with on(who[1], who[0]):
            return client.request("PUT", self.url, {"excluded": sorted(excluded), "reason": reason},
                                  headers={"If-Match": str(version)})

    def tree(self) -> dict:
        self.db.expire_all()
        return scope.tree(self.db, self.db.get(models.Repository, self.repo.id))

    def closure(self, kept: set[str]) -> set[str]:
        """The kept projects and everything they depend on."""
        depends = {p["path"]: p["dependsOn"] for p in self.projects}
        out, stack = set(), list(kept)
        while stack:
            p = stack.pop()
            if p not in out:
                out.add(p)
                stack += depends[p]
        return out

    # The scope test 2 saves: the Web applications and the Workers, with everything they need. Left out: the legacy
    # applications, their data layer and its tests, the databases, and the Web tests.
    def kept(self) -> set[str]:
        return self.closure({path(n) for n in synth.WEB_APPS + synth.WORKERS})

    # ---------- the tests, in order

    def test_1_a_repository_nobody_has_scoped_converts_everything(self):
        self.assertEqual(self.discovery.batch_status, "COMPLETED", self.discovery.exit_message)
        tree = self.tree()
        self.assertEqual((tree["version"], tree["saved"], tree["totals"]["projects"], tree["totals"]["excluded"]), (0, None, 170, 0))
        self.assertEqual(sorted(s["name"] for s in tree["solutions"]),
                         ["SynthCo.Database", "SynthCo.Legacy", "SynthCo.Web", "SynthCo.Workers"])
        shared = next(p for p in tree["projects"] if p["path"] == path(synth.CORE[0]))
        self.assertEqual(len(shared["solutions"]), 3)
        conversion = scope.for_conversion(self.db, self.repo)
        self.assertEqual((conversion["excluded"], conversion["filters"], conversion["kept"]), ([], [], 170))
        from app.engine.inputs.collect import collect
        model = collect(self.db, self.repo)
        self.assertEqual(model["scope"], {"excluded": [], "filter": None, "filters": []})
        self.assertEqual(len(model["projects"]), 170)

    def test_2_save_is_refused_while_a_dependency_is_excluded_with_every_problem_listed_then_accepted(self):
        # Deselect all, then select a few projects: each needs projects that stay excluded.
        few = {path(synth.WEB_APPS[0]), path(synth.WORKERS[0]), path(synth.SERVICES[4])}
        excluded = set(self.all) - few
        expected = scope.problems(self.projects, excluded)
        refused = self.save(self.ann, excluded, 0)
        self.assertEqual(refused.status, 422, refused.body)
        detail = refused.json()["detail"]
        self.assertEqual(len(detail), len(expected))                          # every problem, together
        self.assertGreater(len(detail), 3)
        self.assertEqual({d["code"] for d in detail}, {"SCOPE_INVALID"})
        self.assertEqual({d["project"] for d in detail}, few)                 # each kept project, by its dependencies
        self.assertTrue(all(d["dependency"] in excluded for d in detail))
        self.assertEqual(self.tree()["version"], 0)                           # nothing saved

        # Fixed: everything the kept projects need is kept too.
        fixed = set(self.all) - self.kept()
        self.assertEqual(scope.problems(self.projects, fixed), [])
        saved = self.save(self.ann, fixed, 0, reason="The legacy web estate is retired next year.")
        self.assertEqual(saved.status, 200, saved.body)
        self.assertEqual(saved.json()["version"], 1)
        tree = self.tree()
        self.assertEqual((tree["totals"]["excluded"], tree["saved"]["by"], tree["saved"]["reason"]),
                         (len(fixed), f"Ann ({self.ann[2]})", "The legacy web estate is retired next year."))
        self.assertEqual(tree["saved"]["on"], self.ann[1])

    def test_3_deselect_all_is_refused_and_nothing_changes(self):
        refused = self.save(self.ann, self.all, 1)
        self.assertEqual(refused.status, 422, refused.body)
        self.assertIn("NOTHING_KEPT", {d["problem"] for d in refused.json()["detail"]})
        self.assertEqual(self.tree()["version"], 1)

    def test_4_a_non_owners_save_and_a_save_after_someone_else_saved_are_refused(self):
        tree = self.tree()
        excluded = {p["path"] for p in tree["projects"] if p["excluded"]}
        by_ben = self.save(self.ben, excluded, 1)
        self.assertEqual(by_ben.status, 403, by_ben.body)
        stale = self.save(self.ann, excluded - {path(synth.OTHER[0][0])}, 0)    # made from the copy before test 2's save
        self.assertEqual((stale.status, stale.code), (409, "STALE_COPY"), stale.body)
        self.assertIn("someone else", stale.message)
        self.assertEqual(self.tree()["version"], 1)

    def test_5_the_work_list_marks_excluded_findings_and_counts_them(self):
        artifact = store.latest(self.db, self.repo.id, "item-occurrences")
        client = self.client(self.ann)
        with on(self.ann[1], self.ann[0]):
            rows = client.request("GET", f"/api/results/{artifact.artifact_id}/work-items?limit=500").json()
            totals = client.request("GET", f"/api/results/{artifact.artifact_id}/work-items/totals").json()
        excluded = {p["path"] for p in self.tree()["projects"] if p["excluded"]}
        marked = [r for r in rows["items"] if r["outOfScope"]]
        self.assertTrue(marked, "the excluded projects have findings")
        self.assertEqual({r["project"] for r in marked}, {r["project"] for r in rows["items"]} & excluded)
        self.assertTrue(all(r["project"] not in excluded for r in rows["items"] if not r["outOfScope"]))
        self.assertEqual(rows["total"], rows["matching"])                    # kept visible: nothing filtered out
        found = [r for r in marked if r["state"] == "found" and not (r["fileCount"] and r["possibleCount"] == r["fileCount"])]
        self.assertEqual(totals["out_of_scope_items"], len(found))
        self.assertEqual(totals["out_of_scope_projects"], len(excluded))
        self.assertEqual(self.tree()["totals"]["workItemsOutOfScope"], len(found))

    def test_6_preparation_writes_the_notes_and_filters_and_leaves_the_excluded_projects_out(self):
        excluded = set(self.all) - self.kept()
        with mock.patch.object(convert, "check_advisories", return_value=[]), \
                mock.patch.object(siblings, "detect", return_value=[]):
            done = convert.prepare(self.db, ENGAGEMENT, self.repo.slug, when_run="new", lookups_from_discovery=True)
        self.assertEqual((done["action"], done["number"]), ("prepared", 1))
        record, wt = done["scope"], Path(done["worktree"])
        self.assertEqual(set(record["excluded"]), excluded)
        self.assertEqual(record["decidedBy"], f"Ann ({self.ann[2]})")

        # A solution filter per solution that keeps a project, listing only those; none for Database's, all left out.
        filters = {f["solution"]: f for f in record["filters"]}
        self.assertEqual(sorted(filters), ["SynthCo.Legacy.sln", "SynthCo.Web.sln", "SynthCo.Workers.sln"])
        for solution, members in synth.SOLUTIONS.items():
            if solution not in filters:
                continue
            listed = json.loads((wt / f"{solution[:-4]}.in-scope.slnf").read_text(encoding="utf-8"))["solution"]
            self.assertEqual(listed["path"], solution)
            want = {path(n).replace("/", "\\") for n in members if path(n) not in excluded}
            self.assertEqual(set(listed["projects"]), want)
        # The conversion builds the filter that keeps the most projects: the first solution, Database's, keeps none.
        self.assertEqual((record["filter"], done["solution"]), ("SynthCo.Web.in-scope.slnf", "SynthCo.Web.sln"))

        # An OUT-OF-SCOPE.md in each excluded project's folder, never over the repository's own.
        for p in excluded - {PLANTED.rsplit("/", 1)[0] + "/SynthCo.Data.01.csproj"}:
            note = (wt / p).parent / "OUT-OF-SCOPE.md"
            text_ = note.read_text(encoding="utf-8")
            self.assertIn("outside the scope of this conversion", text_)
            self.assertIn(f"Ann ({self.ann[2]})", text_)
            self.assertIn("The legacy web estate is retired next year.", text_)
            self.assertIn("not part of the converted build", text_)
        self.assertEqual((wt / PLANTED).read_text(encoding="utf-8"), "Our own notes about this project.\n")
        self.assertIn(PLANTED, record["files"]["kept"])
        self.assertEqual(git(wt, "log", "-1", "--format=%ae", "--", "SynthCo.Web.in-scope.slnf"), "platform@modernization.local")

        # The instructions build the filter, name the projects left out, and say nothing else about them.
        instructions = (wt / ".github/copilot-instructions.md").read_text(encoding="utf-8")
        self.assertIn("## Conversion scope", instructions)
        self.assertIn("Build and test with `SynthCo.Web.in-scope.slnf`, never the whole solution", instructions)
        self.assertIn("Never change a project outside the scope", instructions)
        for skill in (wt / ".github/upgrades/skills").glob("*.md"):
            body = skill.read_text(encoding="utf-8")
            leaked = [p for p in excluded if f"({p})" in body or f"`{p}`" in body or f"| {p} |" in body]
            self.assertEqual(leaked, [], skill.name)

        # The package step plans only the kept projects, and builds the filter. Offline, the fixture's packages have
        # no upgrade to plan: one is recorded for a kept project and one for an excluded one.
        kept_one, left_one = path(synth.SERVICES[0]), path(synth.DATA[0])
        ids = dict(self.db.execute(text("SELECT relative_path, id FROM projects WHERE repository_id = :r AND relative_path = ANY(:p)"),
                                   {"r": self.repo.id, "p": [kept_one, left_one]}).all())
        for project in (kept_one, left_one):
            self.db.add(models.PackageAssessment(id=f"scope-test:{project}", repository_id=self.repo.id, project_id=ids[project],
                                                 package_id="Polly", current_version="7.2.4", recommended_version="8.4.0",
                                                 outcome="upgrade_safe", confidence=1))
        self.db.commit()
        try:
            everything, _, _ = planner.package_moves(self.db, self.repo.id, "net8.0", "net10.0", [], drift=[])
            scoped, _, _ = planner.package_moves(self.db, self.repo.id, "net8.0", "net10.0", [], drift=[], excluded_projects=excluded)
        finally:
            self.db.rollback()
            self.db.execute(text("DELETE FROM package_assessments WHERE id LIKE 'scope-test:%'"))
            self.db.commit()
        projects_of = lambda found: {o[1] for p in found.values() for o in p["occurrences"]}     # noqa: E731
        self.assertEqual(projects_of(everything), {kept_one, left_one})
        self.assertEqual(projects_of(scoped), {kept_one})
        # (A unit test project is a kept project the filter lists: Web.01 stands for one here.)
        plan = models.ConversionPlan(ordering={"solution": "SynthCo.Web.sln", "unit_test_projects": [path(synth.WEB_APPS[0])]})
        with mock.patch.object(planner, "create", return_value=plan) as create, mock.patch.object(self.db, "commit"), \
                mock.patch.object(self.db, "query"):
            convert.plan_packages(self.db, ENGAGEMENT, self.repo.slug, "base", "conversion/x", wt, record)
        self.assertEqual(create.call_args.kwargs["excluded_projects"], excluded)
        self.assertEqual((plan.ordering["solution"], plan.ordering["full_solution"]), ("SynthCo.Web.in-scope.slnf", "SynthCo.Web.sln"))
        # A unit test project in scope that the conversion's filter does not hold: no package step, saying why.
        plan = models.ConversionPlan(ordering={"solution": "SynthCo.Web.sln", "unit_test_projects": [path(synth.WORKERS[0])]})
        with mock.patch.object(planner, "create", return_value=plan), mock.patch.object(self.db, "commit"), \
                mock.patch.object(self.db, "query"), self.assertRaisesRegex(LookupError, "does not hold every unit test"):
            convert.plan_packages(self.db, ENGAGEMENT, self.repo.slug, "base", "conversion/x", wt, record)

        # Saving now would prepare it again: it has not been run.
        self.assertEqual(self.client_get()["on_save"]["reprepares"], 1)

    def client_get(self) -> dict:
        client = self.client(self.ann)
        with on(self.ann[1], self.ann[0]):
            return client.request("GET", self.url).json()

    def test_7_saving_a_changed_scope_prepares_an_unrun_conversion_again_and_a_run_one_keeps_its_scope(self):
        launched = []
        back = path(synth.TESTS[0])                                           # re-include one test project
        excluded = {p["path"] for p in self.tree()["projects"] if p["excluded"]} - {back}
        self.assertEqual(scope.problems(self.projects, excluded), [])
        from app.routers import conversion as conversion_router
        with mock.patch.object(conversion_router, "_launch", side_effect=lambda db, bt, job, params: launched.append(params) or "job-1"):
            saved = self.save(self.ann, excluded, 1).json()
        self.assertEqual(saved["reprepare_job_execution_id"], "job-1")
        self.assertEqual(saved["reIncluded"], [back])
        self.assertTrue(launched[0]["prepare_conversion"])
        self.assertNotIn("new_conversion", launched[0])
        # What that discovery run ends with: the unrun conversion refreshed in place, with the new scope.
        with mock.patch.object(convert, "check_advisories", return_value=[]), \
                mock.patch.object(siblings, "detect", return_value=[]):
            done = convert.prepare(self.db, ENGAGEMENT, self.repo.slug, when_run="keep", lookups_from_discovery=True)
        self.assertEqual((done["action"], done["number"]), ("refreshed", 1))
        self.assertNotIn(back, done["scope"]["excluded"])
        self.assertFalse((Path(done["worktree"]) / back).parent.joinpath("OUT-OF-SCOPE.md").exists())

        # Run: someone commits on the branch. A new save keeps conversion 1's scope; it applies to the next one.
        wt = Path(done["worktree"])
        (wt / "src" / "Web" / "converted.txt").write_text("converted\n", encoding="utf-8")
        git(wt, "add", "-A")
        git(wt, "-c", "user.name=Dev", "-c", "user.email=dev@client-a.example", "commit", "-qm", "convert")
        launched.clear()
        with mock.patch.object(conversion_router, "_launch", side_effect=lambda *a: launched.append(a) or "job-2"):
            again = self.save(self.ann, excluded | {back}, 2).json()
        self.assertIsNone(again["reprepare_job_execution_id"])
        self.assertEqual(launched, [])
        self.assertIn("keeps the scope it was prepared with", again["note"])
        self.assertEqual(convert.record(ENGAGEMENT, self.repo.slug, 1)["scope"]["excluded"], done["scope"]["excluded"])

    def test_8_the_verifier_builds_and_tests_the_filter_and_does_not_count_the_excluded_projects(self):
        from app.engine import verifier
        from app.engine.verifier import rediscovery

        rec = convert.record(ENGAGEMENT, self.repo.slug, 1)
        left = rec["scope"]["excluded"]
        kept_test, left_test = path(synth.TESTS[0]), path(synth.TESTS[25])
        self.assertIn(left_test, left)
        kept_lib, left_lib = path(synth.SERVICES[0]), path(synth.DATA[3])

        def model(items):
            return {"items": [{"id": "hardcoded-windows-path", "name": "A Windows path", "occurrences": [
                        {"project": p, "file": p.rsplit("/", 1)[0] + "/Clock.cs", "value": None, "lines": [{"line": 3}]}
                        for p in items], "impact": []}],
                    "projects": [{"path": p, "framework": "net10.0" if p not in left else "net48"} for p in self.all],
                    "deltas": [], "packages": []}

        snaps = iter([{"model": model([kept_lib, left_lib]), "solution": "SynthCo.Web.sln", "unit_test_projects": [kept_test, left_test]},
                      {"model": model([left_lib]), "solution": "SynthCo.Web.sln", "unit_test_projects": [kept_test, left_test]}])
        built = []

        def build_and_test(tree, solution, projects, out):
            built.append((Path(out).name, solution, list(projects)))
            return {"built": True, "buildExit": 0, "projects": {p: {"ran": True, "exit": 0, "total": 4} for p in projects}, "trx": []}

        with mock.patch.object(rediscovery, "snapshot", side_effect=lambda *a, **k: next(snaps)), \
                mock.patch.object(verifier, "build_and_test", side_effect=build_and_test):
            report = convert.verify(self.db, ENGAGEMENT, self.repo.slug, "conversion/1", refresh_baseline=True)

        tip = next(b for b in built if b[0] == "clean")
        self.assertEqual(tip[1], "SynthCo.Web.in-scope.slnf")              # the clean re-run builds the filter
        self.assertEqual(tip[2], [kept_test])                                # and tests only the kept test project
        rd = report["rediscovery"]
        self.assertEqual(rd["resolved"], [[kept_lib, "hardcoded-windows-path"]])
        self.assertEqual(rd["remaining"], [])                                # the excluded finding is not remaining
        self.assertEqual(rd["outOfScope"], [[left_lib, "hardcoded-windows-path"]])
        self.assertFalse(set(rd["offTarget"]) & set(left))                   # left on its framework, not counted
        self.assertEqual(report["scope"]["testProjectsLeftOut"], [left_test])
        self.assertEqual(report["scope"]["built"], "SynthCo.Web.in-scope.slnf")
        written = set(rec["scope"]["files"]["written"])
        self.assertFalse(written & {f["path"] for f in report["diff"].get("files", [])})
        self.assertTrue(written <= set(report["excludedPaths"]))
        md = (planner.RUNS / ENGAGEMENT / self.repo.slug / "verification" / "conversion-1" / "VERIFICATION.md").read_text(encoding="utf-8")
        self.assertIn("## Conversion scope", md)
        self.assertIn(f"{len(left)} project(s) were left out of this conversion's scope", md)

    def test_9_a_rescan_keeps_the_scope_flags_a_new_project_and_drops_one_that_is_gone(self):
        before = {p["path"] for p in self.tree()["projects"] if p["excluded"]}
        gone = path(synth.LEGACY_APPS[9])                                     # excluded, and nothing depends on it
        self.assertIn(gone, before)
        shutil.rmtree(self.root / gone.rsplit("/", 1)[0])
        extra = self.root / "src" / "Extra" / "SynthCo.Extra"
        extra.mkdir(parents=True)
        (extra / "SynthCo.Extra.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup>\n'
                                                    '    <TargetFramework>net8.0</TargetFramework>\n  </PropertyGroup>\n</Project>\n',
                                                    encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "-c", "user.name=Dev", "-c", "user.email=dev@client-a.example", "commit", "-qm", "change projects")
        execution = discover(self.db, self.db.get(models.Repository, self.repo.id))
        self.assertEqual(execution.batch_status, "COMPLETED", execution.exit_message)

        tree = self.tree()
        now = {p["path"] for p in tree["projects"] if p["excluded"]}
        self.assertEqual(now, before - {gone})                               # the scope kept; the gone one dropped out
        self.assertEqual(tree["gone"], [gone])
        new = [p for p in tree["projects"] if p["new"]]
        self.assertEqual([(p["path"], p["excluded"]) for p in new], [("src/Extra/SynthCo.Extra/SynthCo.Extra.csproj", False)])
        self.assertEqual(tree["totals"]["new"], 1)


if __name__ == "__main__":
    unittest.main()
