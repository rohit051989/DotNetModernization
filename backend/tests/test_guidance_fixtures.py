"""The engine guidance written on 2026-11-24, proved on a made-up repository (tests/fixtures/guidance_repository.py)
scanned by the real discovery job:

- each item is detected on the project it is meant for, the two project-file items included, and the project-file
  items are not raised for a classic ASP.NET web project (2026-11-25);
- for each resolution with guidance, chosen in turn, both engines' inputs carry the item's and the resolution's text
  in its work item, with the real frameworks in place of the roles the text names, and preparation's warning has no
  entry for it; every generated file passes the self-containedness and secret checks (inputs.build refuses otherwise);
- the decision sheet's Package management answer points to the packages.config instruction instead of reporting
  missing guidance;
- the preparation itself, end to end, with the defaults and then with the other resolutions chosen, reports no gap
  but the undecided Windows-only assemblies (a decision a person makes first, by design);
- (2026-11-25) the SDK-style conversion and the PackageReference move are one task, before every other, for both
  engines; the WCF web project's instruction carries its SDK-style step; a package pinned higher than restore would
  resolve is kept at its version; and choosing a resolution that keeps something unchanged gives no warning.

Runs in this run's own schema. Run from backend/:  python -m unittest tests.test_guidance_fixtures -v
"""
import datetime
import json
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

import yaml

from sqlalchemy import text

from app import models
from app.config import settings
from app.db import SessionLocal
from app.engine import engines, inputs, paths
from app.engine.inputs import claude, collect, render
from app.items import baseline
from app.steps import conversion_preparation
from tests.fixtures import guidance_repository as fixture

GUIDANCE = baseline.engine_guidance()
WRITTEN = {item: sorted((g.get("resolutions") or {}).items()) for item, g in GUIDANCE.items() if item in fixture.EXPECTED}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@client-a.example", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def _first_words(text: str) -> str:
    return " ".join(text.split()[:12])


class GuidanceOnAScannedRepository(unittest.TestCase):
    TAG = uuid.uuid4().hex[:6]
    ENGAGEMENT = f"t-guidance-{TAG}"
    FEED = fixture.FEED.format(tag=TAG)

    @classmethod
    def setUpClass(cls):
        from app.repositories import service as repositories_service
        from app.repositories.schemas import RegisterLocalPathRequest
        from app.workflow.runtime import service as runtime

        cls.tmp = Path(tempfile.mkdtemp(prefix="guidance-"))
        cls.root = cls.tmp / "orders-platform"
        fixture.write(cls.root, cls.TAG)
        _git(cls.root, "init", "-q", "-b", "main")
        _git(cls.root, "add", "-A", "-f")
        _git(cls.root, "commit", "-qm", "a made-up .NET Framework repository")
        cls.db = SessionLocal()
        # What the repository's own feed says about Batch's packages, for the scan's offline lookups.
        now = datetime.datetime.now(datetime.timezone.utc)
        for package_id, versions in fixture.LOOKUPS.items():
            cls.db.add(models.PackageLookupCache(feed_url_normalised=cls.FEED, package_id=package_id, versions=list(versions),
                                                 metadata_=versions, fetched_at=now, lookup_rule=2))
        cls.db.add(models.Engagement(id=cls.ENGAGEMENT, client_name="Test engagement (guidance)",
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
        root = cls.root
        if (root / ".git").exists():                    # the engagement's deletion may have removed it already
            try:
                for line in _git(root, "worktree", "list", "--porcelain").splitlines():
                    if line.startswith("worktree ") and Path(line[9:]).resolve() != root.resolve():
                        _git(root, "worktree", "remove", "--force", line[9:])
            except subprocess.CalledProcessError:
                pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- helpers

    def decide(self, choices: dict[str, str]) -> None:
        """The engagement's decisions: exactly `choices` ({item: resolution}), approved."""
        self.db.query(models.EngagementDecision).filter_by(engagement_id=self.ENGAGEMENT).delete()
        for item_id, resolution_id in choices.items():
            self.db.add(models.EngagementDecision(engagement_id=self.ENGAGEMENT, item_id=item_id, resolution_id=resolution_id,
                                                  status="approved", approver_name="Test", rationale="chosen for the test"))
        self.db.commit()

    def both(self, model: dict) -> dict[str, dict[str, str]]:
        """Both engines' files, through inputs.build: the self-containedness and secret checks refuse otherwise."""
        return {engine: inputs.build(model, Path(self.repo.local_path), [], engine) for engine in engines.ENGINES}

    # ---- the tests

    def test_1_each_item_is_detected_on_its_project(self):
        self.assertEqual(self.execution.batch_status, "COMPLETED", self.execution.exit_message)
        found = {(o.item_id, p) for o, p in self.db.query(models.ItemOccurrence, models.Project.relative_path)
                 .join(models.Project, models.Project.id == models.ItemOccurrence.project_id)
                 .filter(models.ItemOccurrence.repository_id == self.repo.id, models.ItemOccurrence.detection_state == "found")}
        missing = sorted(f"{item} on {project}" for item, projects in fixture.EXPECTED.items() for project in projects
                         if (item, project) not in found)
        self.assertEqual(missing, [], sorted(found))
        wrong = sorted(f"{item} on {project}" for item, projects in fixture.NOT_EXPECTED.items() for project in projects
                       if (item, project) in found)
        self.assertEqual(wrong, [], sorted(found))

    def test_2_each_resolution_chosen_in_turn_reaches_both_engines_with_no_gap(self):
        self.decide({})
        checked = 0
        for item_id, resolutions in sorted(WRITTEN.items()):
            for resolution_id, text in resolutions:
                with self.subTest(item=item_id, resolution=resolution_id):
                    self.decide({item_id: resolution_id})
                    model = collect.collect(self.db, self.repo)
                    item = next(i for i in model["items"] if i["id"] == item_id)
                    self.assertEqual(item["resolution"]["id"], resolution_id)
                    files = self.both(model)
                    name = render.skill_name(resolution_id)
                    copilot = files[engines.COPILOT][f".github/upgrades/skills/{name}.md"]
                    claude_text = files[engines.CLAUDE][claude.skill_path(name)]
                    for text_ in (copilot, claude_text):
                        self.assertIn(_first_words(text), " ".join(text_.split()))
                        if GUIDANCE[item_id].get("guidance"):
                            self.assertIn(_first_words(GUIDANCE[item_id]["guidance"]), " ".join(text_.split()))
                        self.assertIn("- The target framework: `net10.0`.", text_)
                    gaps = [m for m in render.without_guidance(model)
                            if m["item"] == item_id and m["missing"] in ("resolution", "default")]
                    self.assertEqual(gaps, [])
                    for detail in (render.incomplete(model) or {}).get("details", []):
                        self.assertFalse(detail.startswith(item["name"] + ":") and "decision" not in detail, detail)
                    checked += 1
        self.assertEqual(checked, sum(len(r) for r in WRITTEN.values()))

    def test_3_the_frameworks_are_the_real_ones(self):
        self.decide({})
        model = collect.collect(self.db, self.repo)
        files = render.render(model)
        bridge = files[".github/upgrades/skills/applying-netstandard20-bridge.md"]
        self.assertIn("- `Shared/Shared.csproj`: the project's current framework is `v4.7`, `net47` in an SDK-style "
                      "project file.", bridge)
        self.assertIn("- The target framework: `net10.0`.", bridge)

    def test_4_package_management_points_to_the_packages_config_instruction(self):
        self.decide({})
        model = collect.collect(self.db, self.repo)
        options = {o["question"]: o for o in render.upgrade_options(model)}
        package = options["Package management (Central Package Management)"]
        self.assertFalse(package.get("missing"))
        self.assertEqual(package["answer"], "Move each packages.config project to PackageReference, as its instruction says")
        for engine, files in self.both(model).items():
            sheet = next(t for p, t in files.items() if p.endswith("decision-sheet.md"))
            self.assertNotIn("Keep the current arrangement", sheet, engine)
            self.assertNotIn("missing guidance", sheet, engine)

    def test_4b_the_project_file_and_its_packages_are_one_task_before_every_other_for_both_engines(self):
        self.decide({})
        model = collect.collect(self.db, self.repo)
        work = render.work_items(model)
        names = [w["name"] for w in work]
        self.assertEqual(names[:2], ["applying-sdk-style-project-conversion", "applying-packagereference-migration"])
        self.assertEqual(work[1]["together_with"], "applying-sdk-style-project-conversion")
        # Every task that retargets Batch or the library it depends on comes after them.
        for later in ("applying-netstandard20-bridge", "applying-ocp4-cronjob-container"):
            self.assertIn(later, names[2:])
        files = self.both(model)
        # Claude Code: its plan is the order, and the two are one step, one commit.
        plan = files[engines.CLAUDE][claude.instructions_path(model)]
        self.assertIn("1. `applying-sdk-style-project-conversion` and `applying-packagereference-migration`, in one task "
                      "and one commit: Convert to an SDK-style project (Old-style (non-SDK) project file); Move to "
                      "PackageReference (NuGet packages listed in packages.config)", plan)
        self.assertIn("A step that names more than one work item is one task", plan)
        self.assertLess(plan.index("`applying-packagereference-migration`, in one task"), plan.index("`applying-netstandard20-bridge`"))
        # GitHub Copilot plans for itself: each instruction says where it stands, and the decision sheet lists it.
        copilot = files[engines.COPILOT]
        skill = lambda name: copilot[f".github/upgrades/skills/{name}.md"]          # noqa: E731
        self.assertIn("- Apply this **first**, before every other instruction of this repository.",
                      skill("applying-sdk-style-project-conversion"))
        self.assertIn("- Apply **together with** `applying-packagereference-migration` (NuGet packages listed in "
                      "packages.config), in the same task and commit.", skill("applying-sdk-style-project-conversion"))
        self.assertIn("- Apply **together with** `applying-sdk-style-project-conversion` (Old-style (non-SDK) project "
                      "file), in the same task and commit.", skill("applying-packagereference-migration"))
        for later in ("applying-netstandard20-bridge", "applying-ocp4-cronjob-container"):
            self.assertIn("- Apply `applying-sdk-style-project-conversion` (Old-style (non-SDK) project file) **first**; "
                          "this one depends on it.", skill(later))
        sheet = copilot[f"{paths.PLATFORM_INPUTS_DIR}/decision-sheet.md"]
        self.assertIn("- `applying-sdk-style-project-conversion` runs first, before every other change", sheet)
        self.assertNotIn("bump the version everywhere", skill("applying-packagereference-migration"))

    def test_6_the_wcf_web_project_becomes_sdk_style_in_its_move(self):
        """Orders is a classic ASP.NET WCF web project: no project-file item of its own (test 1), and the WCF
        instructions it gets carry the SDK-style step."""
        step = "make it an SDK-style ASP.NET Core project in this same task, not before"
        for item_id, resolution_id in (("wcf-service", "wcf-service-corewcf"), ("wcf-service", "wcf-service-rest-rewrite"),
                                       ("wcf-service-host", "wcf-host-aspnetcore-web-host"),
                                       ("asmx-service", "corewcf-basichttp")):
            with self.subTest(resolution=resolution_id):
                self.decide({item_id: resolution_id})
                files = self.both(collect.collect(self.db, self.repo))
                name = render.skill_name(resolution_id)
                for text_ in (files[engines.COPILOT][f".github/upgrades/skills/{name}.md"],
                              files[engines.CLAUDE][claude.skill_path(name)]):
                    flat = " ".join(text_.split())
                    self.assertTrue(step in flat or "The project file becomes SDK-style in this same task, not before" in flat)
                    self.assertIn("A classic ASP.NET project has no supported SDK-style form on .NET Framework", flat)
                    self.assertIn('`<Project Sdk="Microsoft.NET.Sdk.Web">`', flat)
        self.decide({})
        files = self.both(collect.collect(self.db, self.repo))
        sdk = files[engines.COPILOT][".github/upgrades/skills/applying-sdk-style-project-conversion.md"]
        self.assertNotIn("Microsoft.NET.Sdk.Web", sdk)
        self.assertNotIn("Orders/Orders.csproj (", sdk.split("## Places", 1)[1].split("##", 1)[0])

    def test_7_a_package_pinned_higher_than_restore_resolves_is_kept_at_its_version(self):
        self.decide({})
        model = collect.collect(self.db, self.repo)
        batch = {p["id"]: p for p in next(x for x in model["packages_config"] if x["project"] == "Batch/Batch.csproj")["packages"]}
        self.assertEqual((batch["System.Runtime.CompilerServices.Unsafe"]["action"], batch["System.Runtime.CompilerServices.Unsafe"]["why"]),
                         ("keep", "restore would resolve 4.5.3 through `System.Memory` 4.5.4"))
        self.assertEqual(batch["System.Buffers"]["action"], "leave out")
        self.assertEqual(batch["System.Numerics.Vectors"]["action"], "leave out")
        self.assertEqual(batch["System.Memory"]["action"], "keep")
        self.assertEqual(batch["Newtonsoft.Json"]["action"], "keep")
        files = self.both(model)
        # Orders' packages move with it to ASP.NET Core: not in this table.
        self.assertNotIn("`Orders/Orders.csproj`", files[engines.COPILOT][".github/upgrades/skills/applying-packagereference-migration.md"])
        for text_ in (files[engines.COPILOT][".github/upgrades/skills/applying-packagereference-migration.md"],
                      files[engines.CLAUDE][claude.skill_path("applying-packagereference-migration")]):
            self.assertIn("| `Batch/Batch.csproj` | `System.Runtime.CompilerServices.Unsafe` | 6.0.0 | Keep as a direct "
                          "`PackageReference` at 6.0.0 | restore would resolve 4.5.3 through `System.Memory` 4.5.4 |", text_)
            self.assertIn("| `Batch/Batch.csproj` | `System.Buffers` | 4.5.1 | Leave out: restore brings it in | restore "
                          "resolves the same version through `System.Memory` 4.5.4 |", text_)
            self.assertIn("keep it as a direct `PackageReference` at the pinned version", " ".join(text_.split()))

    def test_8_choosing_a_resolution_that_keeps_something_unchanged_gives_no_warning(self):
        keep = {"wcf-service": "wcf-service-remain-windows-hosted", "wcf-service-host": "wcf-host-remain-windows-hosted",
                "windows-only-assembly-reference": "keep-project-on-windows", "legacy-project-format": "keep-old-style-project",
                "packages-config": "keep-packages-config",
                "directory-services-usage": "directory-services-usage-remain-windows-hosted"}
        self.decide(keep)
        model = collect.collect(self.db, self.repo)
        names = {i["id"]: i["name"] for i in model["items"]}
        files = self.both(model)
        for item_id, resolution_id in keep.items():
            text_ = files[engines.COPILOT][f".github/upgrades/skills/{render.skill_name(resolution_id)}.md"]
            self.assertIn("Leave this exactly as it is: ", text_)
            self.assertIn("Record it in the task's notes as left unchanged, with that reason.", " ".join(text_.split()))
        # An item with no text of its own (directory-services-usage) is not a gap: only a resolution, default or
        # decision is.
        self.assertEqual([m for m in render.without_guidance(model)
                          if m["item"] in keep and m["missing"] in ("resolution", "default", "decision")], [])
        context = type("Context", (), {"parameters": {"repository_id": str(self.repo.id), "new_conversion": True},
                                       "database_url": settings.database_url, "job_execution_id": str(uuid.uuid4())})()
        result = conversion_preparation.run(context)
        self.assertEqual(result.exit_status, "COMPLETED", result.exit_message)
        from app.engine import convert
        attempt = json.loads((convert.conversions_dir(self.ENGAGEMENT, self.repo.slug) / conversion_preparation.LAST_PREPARE)
                             .read_text(encoding="utf-8"))
        details = (attempt.get("incomplete") or {}).get("details", [])
        self.assertEqual([d for d in details if d.split(":")[0] in {names[i] for i in keep}], [], details)

    def test_5_preparation_end_to_end_reports_no_gap_but_the_decision_a_person_makes_first(self):
        for choices in ({}, {"ssis-package": "csharp-worker-container", "fx47-class-library": "net10-class-library",
                             "wcf-service": "wcf-service-rest-rewrite", "wcf-service-host": "wcf-host-retire",
                             "asmx-service": "rest-api-rewrite", "directory-services-usage": "identity-provider-claims",
                             "encoding-default": "explicit-legacy-code-page",
                             "fx-aspnet-mvc": "aspnetcore-incremental-adapters"}):
            with self.subTest(choices=sorted(choices)):
                self.decide(choices)
                context = type("Context", (), {"parameters": {"repository_id": str(self.repo.id), "new_conversion": True},
                                               "database_url": settings.database_url,
                                               "job_execution_id": str(uuid.uuid4())})()
                result = conversion_preparation.run(context)
                self.assertEqual(result.exit_status, "COMPLETED", result.exit_message)
                from app.engine import convert
                attempt = json.loads((convert.conversions_dir(self.ENGAGEMENT, self.repo.slug) / conversion_preparation.LAST_PREPARE)
                                     .read_text(encoding="utf-8"))
                self.assertIn(attempt["status"], ("prepared", "refreshed"), attempt.get("message"))
                details = (attempt.get("incomplete") or {}).get("details", [])
                written = {i["name"] for i in collect.collect(self.db, self.repo)["items"] if i["id"] in WRITTEN}
                # A default on the reviewed allow-list (ldap-protocols) is named with its reason, by design.
                unexpected = [d for d in details if d.split(":")[0] in written
                              and not d.startswith("Reference to an assembly that only loads on Windows: no decision")
                              and "(on the guidance allow-list: " not in d]
                self.assertEqual(unexpected, [], details)
                # The Windows-only assemblies wait for a person's decision, by design.
                self.assertTrue(any(d.startswith("Reference to an assembly that only loads on Windows: no decision")
                                    for d in details), details)


if __name__ == "__main__":
    unittest.main()
