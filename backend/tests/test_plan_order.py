"""The plan's order on the review hand-off's second repository (2026-11-25, gap 1): web services sharing a class library
(tests/fixtures/services_repository.py), scanned by the real discovery job. The library's bridge comes before the MVC
application's move to ASP.NET Core and the WCF service's REST rewrite that both reference it, in both engines' plans and
Prerequisites; the first repository's order is proved in tests/test_guidance_fixtures.py (test 4b).

Runs in this run's own schema. Run from backend/:  python -m unittest tests.test_plan_order -v
"""
import re
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from app import models
from app.config import settings
from app.db import SessionLocal
from app.engine import engines, inputs
from app.engine.inputs import claude, collect, render
from tests.fixtures import services_repository as fixture

BRIDGE = "applying-netstandard20-bridge"
MOVES = ("applying-aspnetcore-incremental-adapters", "applying-wcf-service-rest-rewrite")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@client-a.example", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


class PlanOrderOnSharedLibraryServices(unittest.TestCase):
    ENGAGEMENT = f"t-plan-{uuid.uuid4().hex[:6]}"

    @classmethod
    def setUpClass(cls):
        from app.repositories import service as repositories_service
        from app.repositories.schemas import RegisterLocalPathRequest
        from app.workflow.runtime import service as runtime

        cls.tmp = Path(tempfile.mkdtemp(prefix="plan-order-"))
        cls.root = cls.tmp / "quote-services"
        fixture.write(cls.root)
        _git(cls.root, "init", "-q", "-b", "main")
        _git(cls.root, "add", "-A", "-f")
        _git(cls.root, "commit", "-qm", "a made-up set of web services")
        cls.db = SessionLocal()
        cls.db.add(models.Engagement(id=cls.ENGAGEMENT, client_name="Test engagement (plan order)",
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
        cls.db.add(models.EngagementDecision(engagement_id=cls.ENGAGEMENT, item_id="wcf-service",
                                             resolution_id="wcf-service-rest-rewrite", status="approved",
                                             approver_name="Test", rationale="chosen for the test"))
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        from app.deletion import service as deletion

        cls.db.rollback()
        engagement = cls.db.get(models.Engagement, cls.ENGAGEMENT)
        if engagement is not None:
            with mock.patch.object(deletion, "_remove_files", return_value={"worktrees": [], "branches": [], "folders": []}):
                deletion.delete(cls.db, deletion.engagement_plan(cls.db, engagement), engagement.client_name, via="test")
        cls.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_1_the_items_are_detected(self):
        self.assertEqual(self.execution.batch_status, "COMPLETED", self.execution.exit_message)
        found = {(o.item_id, p) for o, p in self.db.query(models.ItemOccurrence, models.Project.relative_path)
                 .join(models.Project, models.Project.id == models.ItemOccurrence.project_id)
                 .filter(models.ItemOccurrence.repository_id == self.repo.id, models.ItemOccurrence.detection_state == "found")}
        missing = sorted(f"{i} on {p}" for i, ps in fixture.EXPECTED.items() for p in ps if (i, p) not in found)
        self.assertEqual(missing, [], sorted(found))

    def test_2_the_library_comes_before_the_applications_that_reference_it_in_both_engines(self):
        model = collect.collect(self.db, self.repo)
        self.assertEqual(sorted(model["references"]["Portal/Portal.csproj"]), ["Common/Common.csproj"])
        names = [w["name"] for w in render.work_items(model)]
        self.assertEqual(names[0], "applying-sdk-style-project-conversion")
        for move in MOVES:
            self.assertLess(names.index(BRIDGE), names.index(move), names)
        files = {engine: inputs.build(model, Path(self.repo.local_path), [], engine) for engine in engines.ENGINES}
        plan = files[engines.CLAUDE][claude.instructions_path(model)]
        plan = plan.split("## How to run this conversion", 1)[1].split("\n## ", 1)[0]
        listed = re.findall(r"^\d+\. `(applying-[^`]+)`", plan, re.MULTILINE)
        for move in MOVES:
            self.assertLess(listed.index(BRIDGE), listed.index(move), listed)
        for engine, text in files.items():
            sheet = next(t for p, t in text.items() if p.endswith("decision-sheet.md"))
            ordering = re.findall(r"`(applying-[^`]+)`", sheet.split("## Ordering", 1)[1].split("\n## ", 1)[0])
            for move in MOVES:
                self.assertLess(ordering.index(BRIDGE), ordering.index(move), (engine, ordering))
                skill = (text[f".github/upgrades/skills/{move}.md"] if engine == engines.COPILOT
                         else text[claude.skill_path(move)])
                self.assertIn(f"Apply after `{BRIDGE}` (.NET Standard 2.0 bridge (.NET Framework 4.7 class library)): it "
                              "changes a project this one references.", " ".join(skill.split()), (engine, move))
                self.assertIn("Phase 4 of 6, retarget and host applications", skill)


if __name__ == "__main__":
    unittest.main()
