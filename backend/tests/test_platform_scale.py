"""The platform end to end at scale, and the artifact version contract over every registered step (release 7).

The synthetic 170-project repository (tests/fixtures/synthetic_repository.py; 37-DEPENDENCY-HIERARCHY.md Part H) is
generated for this test into a scratch folder — never registered anywhere permanent — and scanned by the real jobs,
in this test run's own schema (tests/__init__.py): phase0-repository-discovery, then phase0-estate-consolidation.
It runs the published step programs (scripts/bootstrap.ps1 stage 6), offline: the repository's client feed is a local
folder, and the public comparison is off.

It checks:
- every step of both jobs completes, and dependency-hierarchy finishes well within its time limits;
- the dependency graph matches the project files (each shared library once, each declared edge once);
- for every registered step that produces artifacts, each artifact's version — the one the step reported, the one the
  file itself declares, and the one its registration produces — is the same. A new step that produces artifacts and is
  not exercised here fails the test until it is.

Uses stdlib unittest, same rationale as test_repository_ingest.py. About two minutes.
"""

import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from app import models
from app.config import settings
from app.db import SessionLocal
from app.deletion import service as deletion
from app.repositories import service as repositories_service
from app.repositories.schemas import RegisterLocalPathRequest
from app.seed import platform
from app.workflow.adapters.base import declared_version, local_path_from_uri
from app.workflow.runtime import service as runtime
from tests.fixtures import synthetic_repository

ENGAGEMENT = "t-engagement-scale"
# Generous: dependency-hierarchy takes seconds on this repository; the engine allows it an hour, 300 s per project.
HIERARCHY_SECONDS = 120


class PlatformAtScaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name) / "SynthCo170"
        synthetic_repository.generate(cls.root)
        cls.db = SessionLocal()
        cls.engagement = models.Engagement(id=ENGAGEMENT, client_name="Test engagement (scale)", target_platform="Linux / OpenShift Container Platform 4",
                                           default_posture="lift-and-shift")
        cls.db.add(cls.engagement)
        cls.db.commit()
        cls.repo = repositories_service.register_local_path(
            cls.db, cls.engagement, RegisterLocalPathRequest(source_type="local_path", local_path=str(cls.root)))
        cls.db.commit()

        with mock.patch.object(settings, "compare_public_nuget_feed", False):
            started = time.monotonic()
            cls.discovery = runtime.launch_job(cls.db, "phase0-repository-discovery", {
                "engagement_id": ENGAGEMENT, "repository_id": str(cls.repo.id), "ingest_token": cls.repo.ingest_token,
                "prepare_conversion": False,
            }, triggered_by="manual")
            cls.db.commit()
            cls.discovery_seconds = time.monotonic() - started
            cls.estate = runtime.launch_job(cls.db, "phase0-estate-consolidation", {"engagement_id": ENGAGEMENT, "run_token": str(uuid.uuid4())},
                                            triggered_by="manual")
            cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.rollback()
        engagement = cls.db.get(models.Engagement, ENGAGEMENT)
        if engagement is not None:
            deletion.delete(cls.db, deletion.engagement_plan(cls.db, engagement), engagement.client_name, via="test")
        cls.db.close()
        cls.tmp.cleanup()

    def steps(self, execution):
        return self.db.query(models.WfStepExecution).filter_by(job_execution_id=execution.id).order_by(models.WfStepExecution.started_at).all()

    def test_every_step_of_both_jobs_completes(self):
        for execution in (self.discovery, self.estate):
            failed = [(s.step_name, s.exit_status, s.exit_message) for s in self.steps(execution) if s.batch_status != "COMPLETED"]
            self.assertEqual(failed, [], execution.exit_message)
            self.assertEqual(execution.batch_status, "COMPLETED")

    def test_the_dependency_hierarchy_finishes_well_within_its_time_limits(self):
        step = next(s for s in self.steps(self.discovery) if s.step_name == "dependency-hierarchy")
        seconds = (step.ended_at - step.started_at).total_seconds()
        self.assertLess(seconds, HIERARCHY_SECONDS, step.exit_message)
        self.assertIn("171 project(s)", step.exit_message)                  # 170, and the reference to a missing one

    def test_the_dependency_graph_matches_the_project_files(self):
        self.assertEqual(synthetic_repository.check(self.root, str(self.repo.id)), [])

    def test_every_producing_step_writes_the_version_it_reports_and_registers(self):
        registered = {}
        for path in platform.registration_files():
            registration = json.loads(path.read_text(encoding="utf-8"))
            for produced in registration["produces"]:
                registered[(registration["step_name"], produced["artifact_type"])] = produced["artifact_version"]

        seen, problems = set(), []
        for execution in (self.discovery, self.estate):
            names = {s.id: s.step_name for s in self.steps(execution)}
            for artifact in self.db.query(models.WfArtifact).filter_by(job_execution_id=execution.id):
                step = names[artifact.step_execution_id]
                key = (step, artifact.artifact_type)
                seen.add(key)
                written = declared_version(artifact.uri)
                if written is None:
                    problems.append(f"{key}: {local_path_from_uri(artifact.uri).name} declares no version")
                if written != artifact.artifact_version:
                    problems.append(f"{key}: reported {artifact.artifact_version}, the file declares {written}")
                if registered.get(key) != artifact.artifact_version:
                    problems.append(f"{key}: reported {artifact.artifact_version}, registered {registered.get(key)}")

        self.assertEqual(problems, [])
        # Every registered (step, artifact) was produced by these two jobs: none escapes the check.
        self.assertEqual(sorted(set(registered) - seen), [])
