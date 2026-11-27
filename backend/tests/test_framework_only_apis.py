"""Framework-only APIs in class libraries (hand-off of 2026-11-26), proved on a made-up repository
(tests/fixtures/framework_only_repository.py) scanned by the real discovery job:

- LINQ to SQL, System.Web, WIF and Windows Workflow in a library are each detected, and each work item is in both
  engines' inputs before the same library's bridge or retarget (phase 2 before phase 3), whose Prerequisites name it;
  the EF Core rewrite, which needs the target framework, is one task with the direct retarget; the rewrites are under
  the design questions, and preparation reports nothing incomplete for them;
- a library whose consumers all move gets the direct retarget recommended (and, with no decision, applied); one with a
  consumer left on .NET Framework the bridge; a recorded decision is never overridden; EF Core with the bridge warns;
- a library using System.Web is never the classic MVC / Web API application item (gap 2);
- the identity-claims work item changes the signed-in user's checks, each listed once, and lists the directory lookups
  of other users to leave unchanged (gap 3);
- a package built only for .NET Framework is reported as loading only through .NET Framework fallback (NU1701), and
  replaced (gap 4);
- a .NET Framework service whose conversion lands it in a container gets the image and manifest work items after its
  conversion; one that stays on Windows does not (gap 5);
- a claim-type URI is not an unqualified hostname (gap 6).

Runs in this run's own schema. Run from backend/:  python -m unittest tests.test_framework_only_apis -v
"""
import datetime
import re
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from sqlalchemy import text

from app import models
from app.config import settings
from app.conversion import frameworks
from app.db import SessionLocal
from app.engine import engines, inputs, paths
from app.engine.inputs import claude, collect, render
from tests.fixtures import framework_only_repository as fixture

DIRECT = "applying-net10-class-library"
BRIDGE = "applying-netstandard20-bridge"
EF_CORE = "applying-rewrite-to-ef-core"
REWRITES = ("applying-rewrite-to-ef-core", "applying-move-to-aspnetcore-authentication", "applying-rewrite-as-plain-code")
REMOVAL_ITEMS = {"applying-compile-against-system-web-adapters": "WebKit/WebKit.csproj",
                 "applying-move-to-aspnetcore-authentication": "Identity/Identity.csproj",
                 "applying-rewrite-as-plain-code": "Flow/Flow.csproj"}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@client-a.example", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def _flat(text_: str) -> str:
    return " ".join(text_.split())


class FrameworkSupportRule(unittest.TestCase):
    """Gap 4's rule on its own: lib/net45 only is not support for a .NET target, whatever the dependency list says."""

    def test_only_framework_assets_load_through_fallback_only(self):
        found = frameworks.supports(fixture.ENTLIB["6.0.1304"], "net10.0")
        self.assertFalse(found.supported)
        self.assertTrue(found.fallback_only)
        self.assertIn("NU1701", found.basis)

    def test_dependencies_without_groups_say_nothing_of_the_assemblies(self):
        self.assertIsNone(frameworks.supports({"dependencyFrameworks": ["any"]}, "net10.0").supported)
        self.assertTrue(frameworks.supports({"dependencyFrameworks": ["any"], "libFrameworks": ["netstandard2.0"]},
                                            "net10.0").supported)
        self.assertTrue(frameworks.supports({"dependencyFrameworks": ["any"], "libFrameworks": ["net45"]}, "net472").supported)


class FrameworkOnlyApisOnAScannedRepository(unittest.TestCase):
    TAG = uuid.uuid4().hex[:6]
    ENGAGEMENT = f"t-fwonly-{TAG}"
    FEED = f"https://feed-{TAG}.client-a.example/v3/index.json"

    @classmethod
    def setUpClass(cls):
        from app.repositories import service as repositories_service
        from app.repositories.schemas import RegisterLocalPathRequest
        from app.workflow.runtime import service as runtime

        cls.tmp = Path(tempfile.mkdtemp(prefix="fwonly-"))
        cls.root = cls.tmp / "order-services"
        fixture.write(cls.root)
        _git(cls.root, "init", "-q", "-b", "main")
        _git(cls.root, "add", "-A", "-f")
        _git(cls.root, "commit", "-qm", "a made-up set of .NET Framework libraries and a service")
        cls.db = SessionLocal()
        cls.db.add(models.PackageLookupCache(feed_url_normalised=cls.FEED, package_id="EnterpriseLibrary.Data",
                                             versions=list(fixture.ENTLIB), metadata_=fixture.ENTLIB,
                                             fetched_at=datetime.datetime.now(datetime.timezone.utc), lookup_rule=2))
        cls.db.add(models.Engagement(id=cls.ENGAGEMENT, client_name="Test engagement (framework-only APIs)",
                                     target_platform="Linux / OpenShift Container Platform 4", default_posture="lift-and-shift"))
        cls.db.commit()
        cls.repo = repositories_service.register_local_path(cls.db, cls.db.get(models.Engagement, cls.ENGAGEMENT),
                                                            RegisterLocalPathRequest(source_type="local_path", local_path=str(cls.root)))
        cls.db.commit()
        with mock.patch.object(settings, "compare_public_nuget_feed", False):
            token = repositories_service.start_rescan(cls.repo)
            cls.db.commit()
            cls.execution = runtime.launch_job(cls.db, "phase0-repository-discovery", {
                "engagement_id": cls.ENGAGEMENT, "repository_id": str(cls.repo.id), "ingest_token": token,
                "lookup_offline": True, "prepare_conversion": False}, triggered_by="manual")
            cls.db.commit()
        cls.db.refresh(cls.repo)

    @classmethod
    def tearDownClass(cls):
        from app.deletion import service as deletion

        cls.db.rollback()
        cls.db.execute(text("delete from package_lookup_cache where feed_url_normalised = :f"), {"f": cls.FEED})
        cls.db.commit()
        engagement = cls.db.get(models.Engagement, cls.ENGAGEMENT)
        if engagement is not None:
            with mock.patch.object(deletion, "_remove_files", return_value={"worktrees": [], "branches": [], "folders": []}):
                deletion.delete(cls.db, deletion.engagement_plan(cls.db, engagement), engagement.client_name, via="test")
        cls.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- helpers

    def setUp(self):
        self.decide({})
        self.scope([])

    def decide(self, choices: dict[str, str]) -> None:
        self.db.query(models.EngagementDecision).filter_by(engagement_id=self.ENGAGEMENT).delete()
        for item_id, resolution_id in choices.items():
            self.db.add(models.EngagementDecision(engagement_id=self.ENGAGEMENT, item_id=item_id, resolution_id=resolution_id,
                                                  status="approved", approver_name="Test", rationale="chosen for the test"))
        self.db.commit()

    def scope(self, excluded: list[str]) -> None:
        """The conversion's scope: `excluded` left out (app.scope), the rest in."""
        self.db.query(models.ConversionScope).filter_by(repository_id=self.repo.id).delete()
        if excluded:
            self.db.add(models.ConversionScope(repository_id=self.repo.id, excluded_projects=excluded,
                                               known_projects=sorted({p for p in fixture.FILES if p.endswith(".csproj")}),
                                               saved_by_name="Test", reason="the tool stays on .NET Framework"))
        self.db.commit()

    def both(self, model: dict) -> dict[str, dict[str, str]]:
        return {engine: inputs.build(model, Path(self.repo.local_path), [], engine) for engine in engines.ENGINES}

    @staticmethod
    def skill(files: dict[str, str], engine: str, name: str) -> str:
        return files[f".github/upgrades/skills/{name}.md"] if engine == engines.COPILOT else files[claude.skill_path(name)]

    @staticmethod
    def sheet(files: dict[str, str]) -> str:
        return next(t for p, t in files.items() if p.endswith("decision-sheet.md"))

    # ---- the tests

    def test_1_each_item_is_detected_on_its_project_and_a_library_is_never_the_mvc_application(self):
        self.assertEqual(self.execution.batch_status, "COMPLETED", self.execution.exit_message)
        found = {(o.item_id, p) for o, p in self.db.query(models.ItemOccurrence, models.Project.relative_path)
                 .join(models.Project, models.Project.id == models.ItemOccurrence.project_id)
                 .filter(models.ItemOccurrence.repository_id == self.repo.id, models.ItemOccurrence.detection_state == "found")}
        missing = sorted(f"{i} on {p}" for i, ps in fixture.EXPECTED.items() for p in ps if (i, p) not in found)
        self.assertEqual(missing, [], sorted(found))
        # Gap 2: the System.Web.Http exception handler in a library is not the classic MVC / Web API application.
        self.assertNotIn(("fx-aspnet-mvc", "WebKit/WebKit.csproj"), found)
        # Gap 6: the claim-type constant is no hostname; the endpoint on an unqualified host still is.
        hosts = {o.file_path for o in self.db.query(models.ItemOccurrence).filter_by(
            repository_id=self.repo.id, item_id="unqualified-hostname", detection_state="found")}
        self.assertEqual(hosts, {"Identity/Endpoints.cs"})
        # Each library's own files locate its item: the .dbml and the workflow definition included.
        places = {(o.item_id, o.file_path) for o in self.db.query(models.ItemOccurrence).filter_by(
            repository_id=self.repo.id, detection_state="found")}
        for expected in [("linq-to-sql-usage", "Data/Orders.dbml"), ("linq-to-sql-usage", "Data/OrdersContext.cs"),
                         ("linq-to-sql-usage", "Data/OrderRepository.cs"), ("system-web-in-library", "WebKit/AuditModule.cs"),
                         ("system-web-in-library", "WebKit/RequestInfo.cs"), ("wif-usage", "Identity/SignIn.cs"),
                         ("windows-workflow-usage", "Flow/Approval.xaml"), ("windows-workflow-usage", "Flow/ApproveOrder.cs")]:
            self.assertIn(expected, places)

    def test_2_each_removal_comes_before_its_librarys_retarget_in_both_engines_and_prerequisites_name_it(self):
        model = collect.collect(self.db, self.repo)
        plan = render.work_items(model)
        names = [w["name"] for w in plan]
        # Every consumer moves, and nobody decided: the direct retarget, with EF Core in its task.
        self.assertIn(DIRECT, names)
        self.assertNotIn(BRIDGE, names)
        ef = next(w for w in plan if w["name"] == EF_CORE)
        self.assertEqual(ef["together_with"], DIRECT)
        for removal in REMOVAL_ITEMS:
            self.assertLess(names.index(removal), names.index(DIRECT), names)
            self.assertEqual(next(w for w in plan if w["name"] == removal)["phase"], 2)
        files = self.both(model)
        for engine, text_ in files.items():
            retarget = _flat(self.skill(text_, engine, DIRECT))
            for removal in REMOVAL_ITEMS:
                self.assertRegex(retarget, rf"Apply after `{removal}` \([^`]*\): it changes the same project first\.",
                                 (engine, removal))
            self.assertIn(f"together with `{DIRECT}`", _flat(self.skill(text_, engine, EF_CORE)).replace("**", ""))
            ordering = re.findall(r"`(applying-[^`]+)`", self.sheet(text_).split("## Ordering", 1)[1].split("\n## ", 1)[0])
            for removal in REMOVAL_ITEMS:
                self.assertLess(ordering.index(removal), ordering.index(DIRECT), (engine, ordering))
        claude_plan = files[engines.CLAUDE][claude.instructions_path(model)].split("## How to run this conversion", 1)[1]
        listed = re.findall(r"`(applying-[^`]+)`", claude_plan.split("\n## ", 1)[0])
        for removal in REMOVAL_ITEMS:
            self.assertLess(listed.index(removal), listed.index(DIRECT), listed)

        # The ADO.NET rewrite builds for both frameworks: it is a removal like the others, before the retarget.
        self.decide({"linq-to-sql-usage": "rewrite-to-ado-or-dapper"})
        model = collect.collect(self.db, self.repo)
        names = [w["name"] for w in render.work_items(model)]
        self.assertLess(names.index("applying-rewrite-to-ado-or-dapper"), names.index(DIRECT), names)

    def test_3_the_rewrites_are_design_questions_and_nothing_is_incomplete_for_them(self):
        model = collect.collect(self.db, self.repo)
        files = self.both(model)
        for engine, text_ in files.items():
            instructions = text_[paths.COPILOT_INSTRUCTIONS if engine == engines.COPILOT else claude.instructions_path(model)]
            design = instructions.split(render.DESIGN_HEADING, 1)[1].split("\n## ", 1)[0]
            for rewrite in REWRITES:
                self.assertIn(f"`{rewrite}`", design, engine)
        new_items = set(fixture.REMOVALS)
        self.assertEqual([m for m in render.without_guidance(model) if m["item"] in new_items], [])

    def test_4_the_recommendation_follows_the_consumers_and_never_overrides_a_decision(self):
        model = collect.collect(self.db, self.repo)
        recommended = {lib["project"]: lib["recommended"] for lib in model["class_libraries"]}
        self.assertEqual(recommended, {lib: "net10-class-library" for lib in fixture.LIBRARIES})
        sheet = self.sheet(self.both(model)[engines.COPILOT])
        libraries = sheet.split("## Class libraries: bridge or direct retarget", 1)[1].split("\n## ", 1)[0]
        self.assertIn("No decision recorded: the conversion follows the recommendation", libraries)
        self.assertIn("all 1 consumer(s) are in this conversion's scope and move to the target framework", libraries)
        self.assertEqual(render.plan_warnings(model), [])

        # The tool stays on .NET Framework: Flow, which it references, keeps building for .NET Framework: the bridge.
        self.scope(["Tool/Tool.csproj"])
        model = collect.collect(self.db, self.repo)
        by_lib = {lib["project"]: lib for lib in model["class_libraries"]}
        self.assertEqual(by_lib["Flow/Flow.csproj"]["recommended"], "netstandard20-bridge")
        self.assertIn("Tool/Tool.csproj", by_lib["Flow/Flow.csproj"]["reason"])
        self.assertEqual(by_lib["Data/Data.csproj"]["recommended"], "net10-class-library")
        library = next(i for i in model["items"] if i["id"] == "fx47-class-library")
        self.assertEqual(library["resolution"]["id"], "netstandard20-bridge")     # every consumer builds against it
        # EF Core with the bridge warns: in the decision sheet and in preparation's incomplete inputs.
        warnings = render.plan_warnings(model)
        self.assertEqual(len(warnings), 1)
        self.assertIn("Data/Data.csproj", warnings[0])
        self.assertIn("Current EF Core does not build for .NET Framework or .NET Standard 2.0", warnings[0])
        incomplete = render.incomplete(model)
        self.assertIn(warnings[0], incomplete["details"])
        for engine, text_ in self.both(model).items():
            self.assertIn("## Warnings", self.sheet(text_), engine)

        # A recorded decision stands: the direct retarget, though Flow's recommendation is the bridge.
        self.decide({"fx47-class-library": "net10-class-library"})
        model = collect.collect(self.db, self.repo)
        library = next(i for i in model["items"] if i["id"] == "fx47-class-library")
        self.assertEqual(library["resolution"]["id"], "net10-class-library")
        sheet = self.sheet(self.both(model)[engines.COPILOT])
        self.assertIn("The recommendation does not override a recorded decision.", sheet)
        self.assertIn("(differs from the recommendation)", sheet)
        self.assertEqual(render.plan_warnings(model), [])

    def test_5_a_package_built_only_for_dotnet_framework_is_fallback_only_and_replaced(self):
        model = collect.collect(self.db, self.repo)
        entlib = next(a for a in model["assembly_references"] if a["package"] and a["package"]["id"] == "EnterpriseLibrary.Data")
        self.assertEqual(entlib["verdict"], "fallback-only")
        files = self.both(model)
        for engine, text_ in files.items():
            addendum = _flat(next(t for p, t in text_.items() if p.endswith("assessment-addendum.md")))
            self.assertIn("loads on the target framework only through .NET Framework fallback (NU1701)", addendum, engine)
            self.assertNotIn("is the newest version known to support", addendum.split("EnterpriseLibrary.Data")[1][:400])
            work = _flat(self.skill(text_, engine, "applying-package-replacement-publisher-suggested"))
            self.assertIn("EnterpriseLibrary.Data 6.0.1304: loads only through .NET Framework fallback (NU1701); "
                          "replacement Microsoft.Data.SqlClient (plain ADO.NET)", work, engine)

    def test_6_a_framework_service_moving_to_a_container_gets_its_image_and_manifests_after_its_conversion(self):
        model = collect.collect(self.db, self.repo)
        plan = render.work_items(model)
        by_item = {w["item"]["id"]: w for w in plan}
        order = [w["item"]["id"] for w in plan]
        for item in ("missing-dockerfile", "missing-ocp4-manifests"):
            self.assertIn(item, by_item)
            # The service, and the console tool whose default is a CronJob container: both move to a container.
            self.assertEqual({o["project"] for o in by_item[item]["item"]["occurrences"]},
                             {"Web/Web.csproj", "Tool/Tool.csproj"})
            self.assertGreater(by_item[item]["phase"], by_item["wcf-service"]["phase"])
            self.assertLess(order.index("wcf-service"), order.index(item))
            self.assertLess(order.index("console-batch-job"), order.index(item))
        # The health endpoint: the web service only (the console tool has no HTTP endpoint), after its conversion; the
        # manifests' probes call the paths it creates.
        health = by_item["missing-health-endpoint"]
        self.assertEqual({o["project"] for o in health["item"]["occurrences"]}, {"Web/Web.csproj"})
        self.assertLess(order.index("wcf-service"), order.index("missing-health-endpoint"))
        for engine, text_ in self.both(model).items():
            self.assertIn("Web/Web.csproj", self.skill(text_, engine, "applying-multistage-dockerfile"), engine)
            manifests = _flat(self.skill(text_, engine, "applying-plain-manifests"))
            self.assertIn("Web/Web.csproj", manifests, engine)
            self.assertIn("the liveness probe `/health/live` and the readiness probe `/health/ready`, on port 8080", manifests)
            self.assertIn("`/health/live`", self.skill(text_, engine, "applying-aspnetcore-health-checks"), engine)
        # The service stays on Windows: no image, no manifests for it; the tool still moves.
        self.decide({"wcf-service": "wcf-service-remain-windows-hosted", "wcf-service-host": "wcf-host-remain-windows-hosted"})
        model = collect.collect(self.db, self.repo)
        for item in model["items"]:
            if item["id"] in ("missing-dockerfile", "missing-ocp4-manifests"):
                self.assertEqual({o["project"] for o in item["occurrences"]}, {"Tool/Tool.csproj"}, item["id"])
        self.assertNotIn("missing-health-endpoint", {i["id"] for i in model["items"]})

    def test_7_the_identity_claims_work_item_changes_the_signed_in_users_checks_only_each_once(self):
        self.decide({"directory-services-usage": "identity-provider-claims"})
        model = collect.collect(self.db, self.repo)
        for engine, text_ in self.both(model).items():
            work = self.skill(text_, engine, "applying-identity-provider-claims")
            places = work.split("## Places", 1)[1].split("\n## ", 1)[0]
            listed = re.findall(r"^- `([^`]+)`", places, re.MULTILINE)
            self.assertTrue(listed, engine)
            self.assertEqual(len(listed), len(set(listed)), (engine, listed))
            self.assertEqual({p.split(":")[0] for p in listed}, {"Identity/Access.cs"}, (engine, listed))
            left = work.split("## Leave unchanged", 1)[1].split("\n## ", 1)[0]
            kept = re.findall(r"^- `([^`]+)`", left, re.MULTILINE)
            self.assertEqual({p.split(":")[0] for p in kept}, {"Identity/People.cs"}, (engine, kept))
            self.assertEqual(len(kept), len(set(kept)), (engine, kept))
            self.assertIn("a directory query for other users or groups", _flat(left))


if __name__ == "__main__":
    unittest.main()
