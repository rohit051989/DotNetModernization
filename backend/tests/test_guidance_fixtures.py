"""The engine guidance written on 2026-11-24, proved on a made-up repository (tests/fixtures/guidance_repository.py)
scanned by the real discovery job:

- each item is detected on the project it is meant for, the two project-file items included;
- for each resolution with guidance, chosen in turn, both engines' inputs carry the item's and the resolution's text
  in its work item, with the real frameworks in place of the roles the text names, and preparation's warning has no
  entry for it; every generated file passes the self-containedness and secret checks (inputs.build refuses otherwise);
- the decision sheet's Package management answer points to the packages.config instruction instead of reporting
  missing guidance;
- the preparation itself, end to end, with the defaults and then with the other resolutions chosen, reports no gap
  but the undecided Windows-only assemblies (a decision a person makes first, by design).

Runs in this run's own schema. Run from backend/:  python -m unittest tests.test_guidance_fixtures -v
"""
import json
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

import yaml

from app import models
from app.config import settings
from app.db import SessionLocal
from app.engine import engines, inputs
from app.engine.inputs import claude, collect, render
from app.items import baseline
from app.steps import conversion_preparation
from tests.fixtures import guidance_repository as fixture

GUIDANCE = yaml.safe_load(baseline.ENGINE_GUIDANCE_FILE.read_text(encoding="utf-8"))["items"]
WRITTEN = {item: sorted((g.get("resolutions") or {}).items()) for item, g in GUIDANCE.items() if item in fixture.EXPECTED}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@client-a.example", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def _first_words(text: str) -> str:
    return " ".join(text.split()[:12])


class GuidanceOnAScannedRepository(unittest.TestCase):
    ENGAGEMENT = f"t-guidance-{uuid.uuid4().hex[:6]}"

    @classmethod
    def setUpClass(cls):
        from app.repositories import service as repositories_service
        from app.repositories.schemas import RegisterLocalPathRequest
        from app.workflow.runtime import service as runtime

        cls.tmp = Path(tempfile.mkdtemp(prefix="guidance-"))
        cls.root = cls.tmp / "orders-platform"
        fixture.write(cls.root)
        _git(cls.root, "init", "-q", "-b", "main")
        _git(cls.root, "add", "-A", "-f")
        _git(cls.root, "commit", "-qm", "a made-up .NET Framework repository")
        cls.db = SessionLocal()
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
        missing = sorted(f"{item} on {project}" for item, project in fixture.EXPECTED.items() if (item, project) not in found)
        self.assertEqual(missing, [], sorted(found))

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
        # The SDK-style conversion and the packages move are one task, before the class library's retarget.
        work = [w["item"]["id"] for w in render.work_items(model)]
        self.assertLess(work.index("legacy-project-format"), work.index("fx47-class-library"))
        moving = render.render(model)[".github/upgrades/skills/applying-packagereference-migration.md"]
        self.assertIn("Apply **together with** `applying-sdk-style-project-conversion`", moving)

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
