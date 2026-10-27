"""Central results (app.results): what is stored, for how long, how existing scans are copied, how a list is paged, and
what someone on another machine is given for what only the owner's machine has. With hand-made artifacts; the
end-to-end proof with real scans is tests/test_shared_results.py.

Runs in this test run's own schema (tests/__init__.py). Uses stdlib unittest, same rationale as test_repository_ingest.py.
"""
import datetime
import hashlib
import io
import json
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from sqlalchemy import text

from app import models
from app.auth import machine, service
from app.config import settings
from app.db import SessionLocal
from app.results import __main__ as copy_command
from app.results import conversions, store, views
from app.results.paging import PageParams, page
from app.routers import conversion as conversion_router
from app.routers import workflow_artifacts
from app.workflow.runtime import artifacts as artifacts_service
from tests.support import TEST_ENGAGEMENT_ID, CommittedTestEngagement

HOST_A, HOST_B = "DEVBOX-A", "DEVBOX-B"


def on(host: str):
    return mock.patch.object(machine, "hostname", return_value=host)


def pages(**kw) -> PageParams:
    return PageParams(q=kw.get("q", ""), offset=kw.get("offset", 0), limit=kw.get("limit", 20))


class CentralResults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tag = uuid.uuid4().hex[:6]
        with SessionLocal() as db:
            cls.ann = service.create_user(db, login=f"ann-{cls.tag}", name="Ann", windows_account=rf"CORP\ann{cls.tag}",
                                          role="developer", host_names=[HOST_A], password="ann-long-password",
                                          must_change_password=False)
            db.commit()
            cls.ann_id = cls.ann.id

    @classmethod
    def tearDownClass(cls):
        with SessionLocal() as db:
            db.delete(db.get(models.User, cls.ann_id))
            db.commit()

    def setUp(self):
        self.db = SessionLocal()
        self.engagement = CommittedTestEngagement(self.db)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repositories: list[models.Repository] = []
        self.repo = self.repository()
        self.definition = self.db.query(models.WfJobDefinition).filter_by(job_name="phase0-repository-discovery").first()

    def tearDown(self):
        self.db.rollback()
        for repo in self.repositories:
            executions = [e for (e,) in self.db.execute(text(
                "select j.id from wf_job_executions j join wf_job_instances i on i.id = j.job_instance_id "
                "where i.parameters->>'repository_id' = :r"), {"r": str(repo.id)})]
            for table in ("wf_artifacts", "wf_step_executions"):
                self.db.execute(text(f"delete from {table} where job_execution_id = any(:e)"), {"e": executions})
            self.db.execute(text("delete from wf_job_executions where id = any(:e)"), {"e": executions})
            self.db.execute(text("delete from wf_job_instances where parameters->>'repository_id' = :r"), {"r": str(repo.id)})
            self.db.execute(text("delete from repositories where id = :r"), {"r": repo.id})
        self.db.execute(text("delete from result_contents c where not exists "
                             "(select 1 from result_artifacts a where a.checksum = c.checksum)"))
        self.db.commit()
        self.engagement.remove()
        self.db.close()

    # ---- helpers

    def repository(self) -> models.Repository:
        repo = models.Repository(engagement_id=TEST_ENGAGEMENT_ID, name=f"Shop {self.tag} {len(self.repositories)}",
                                 slug=f"shop-{self.tag}-{len(self.repositories)}", source_type="local_path",
                                 local_path=str(Path(self.tmp.name) / f"shop{len(self.repositories)}"),
                                 local_path_normalised=str(Path(self.tmp.name) / f"shop{len(self.repositories)}").lower(),
                                 root_folder_name=f"shop{len(self.repositories)}", ingest_status="scanned",
                                 owner_user_id=self.ann_id, registered_host=HOST_A)
        self.db.add(repo)
        self.db.commit()
        self.repositories.append(repo)
        return repo

    def execution(self, repo: models.Repository | None = None, host: str = HOST_A):
        repo = repo or self.repo
        instance = models.WfJobInstance(job_name="phase0-repository-discovery", job_key=uuid.uuid4().hex,
                                        parameters={"engagement_id": TEST_ENGAGEMENT_ID, "repository_id": str(repo.id)})
        self.db.add(instance)
        self.db.flush()
        execution = models.WfJobExecution(job_instance_id=instance.id, job_definition_id=self.definition.id,
                                          execution_number=1, batch_status="COMPLETED", engine_version="test",
                                          queued_by_host=host)
        self.db.add(execution)
        self.db.flush()
        step = models.WfStepExecution(job_execution_id=execution.id, step_name="test-step", step_version="1.0.0",
                                      batch_status="COMPLETED")
        self.db.add(step)
        self.db.flush()
        return execution, step

    def artifact(self, execution, step, kind: str, content, minutes: int = 0, publish: bool = True) -> models.WfArtifact:
        raw = json.dumps(content).encode()
        path = Path(self.tmp.name) / f"{uuid.uuid4().hex}.json"
        path.write_bytes(raw)
        row = models.WfArtifact(step_execution_id=step.id, job_execution_id=execution.id, artifact_type=kind,
                                artifact_version="1.0.0", uri=path.as_uri(),
                                checksum="sha256:" + hashlib.sha256(raw).hexdigest(), size_bytes=len(raw),
                                created_at=datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)
                                + datetime.timedelta(minutes=minutes))
        self.db.add(row)
        self.db.flush()
        if publish:
            store.publish(self.db, row)
        return row

    def stored_kinds(self, repo=None) -> list[tuple[str, uuid.UUID]]:
        return [(a.artifact_type, a.artifact_id) for a in self.db.query(models.ResultArtifact)
                .filter_by(repository_id=(repo or self.repo).id).order_by(models.ResultArtifact.created_at)]

    # ---- storage and retention

    def test_a_result_is_stored_once_per_checksum_and_a_raw_output_stays_local(self):
        execution, step = self.execution()
        content = {"summary": {"found": 1}, "projects": [{"projectPath": "a.csproj", "items": []}]}
        first = self.artifact(execution, step, "item-occurrences", content)
        again, again_step = self.execution()
        carried = self.artifact(again, again_step, "item-occurrences", content, minutes=1)
        sarif = self.artifact(execution, step, "fingerprint-sarif", {"runs": []})
        self.assertEqual(first.checksum, carried.checksum)
        self.assertEqual(self.db.query(models.ResultContent).filter_by(checksum=first.checksum).count(), 1)
        self.assertEqual({k for k, _ in self.stored_kinds()}, {"item-occurrences"})
        self.assertFalse(store.is_stored(self.db, sarif.id))
        stored = self.db.get(models.ResultContent, first.checksum)
        self.assertEqual(stored.head, {"summary": {"found": 1}})          # the lists are left out of the head
        self.assertEqual(stored.content, content)

    def test_the_newest_of_each_kind_are_kept_and_older_ones_pruned_with_the_run_folders_untouched(self):
        with mock.patch.object(settings, "results_keep", 2):
            rows = []
            for minute in range(4):
                execution, step = self.execution()
                rows.append(self.artifact(execution, step, "item-occurrences", {"summary": {"n": minute}}, minutes=minute))
                self.artifact(execution, step, "dependency-assessment", {"summary": {"n": minute}}, minutes=minute)
        kept = self.stored_kinds()
        self.assertEqual(sorted(k for k, _ in kept), ["dependency-assessment"] * 2 + ["item-occurrences"] * 2)
        self.assertEqual({i for k, i in kept if k == "item-occurrences"}, {rows[2].id, rows[3].id})
        self.assertIsNone(self.db.get(models.ResultContent, rows[0].checksum))      # no longer referenced
        self.assertTrue(all(Path(store.local_path_from_uri(r.uri)).exists() for r in rows))

    def test_copy_existing_copies_what_is_on_this_machine_once(self):
        execution, step = self.execution()
        here = self.artifact(execution, step, "entry-point-inventory", {"summary": {}}, publish=False)
        gone = self.artifact(execution, step, "outbound-invocation-inventory", {"summary": {}}, publish=False)
        store.local_path_from_uri(gone.uri).unlink()
        self.db.commit()
        with redirect_stdout(io.StringIO()):
            first = copy_command.copy_existing(self.db, self.repo)
            second = copy_command.copy_existing(self.db, self.repo)
        self.assertEqual((first["copied"], first["not_here"]), (1, 1))
        self.assertEqual((second["copied"], second["already"]), (0, 1))
        self.assertTrue(store.is_stored(self.db, here.id))

    # ---- what another machine is given

    def test_another_machine_reads_a_result_from_the_database_and_is_told_where_a_raw_output_is(self):
        execution, step = self.execution()
        work = self.artifact(execution, step, "item-occurrences", {"summary": {"found": 3}})
        sarif = self.artifact(execution, step, "fingerprint-sarif", {"runs": []})
        for row in (work, sarif):
            store.local_path_from_uri(row.uri).unlink()              # not on this machine
        self.db.commit()
        with on(HOST_B):
            served = workflow_artifacts.get_artifact_content(work.id, self.db)
            self.assertEqual(json.loads(served.body), {"summary": {"found": 3}})
            with self.assertRaises(HTTPException) as refused:
                workflow_artifacts.get_artifact_content(sarif.id, self.db)
            detail = artifacts_service.to_artifact_detail(self.db, sarif)
        self.assertEqual(refused.exception.status_code, 404)
        self.assertEqual(refused.exception.detail[0]["code"], "LOCAL_ONLY")
        self.assertIn("on Ann's machine (DEVBOX-A)", refused.exception.detail[0]["message"])
        self.assertEqual(detail.held_on, "on Ann's machine (DEVBOX-A)")
        with on(HOST_A), self.assertRaises(HTTPException) as missing:
            workflow_artifacts.get_artifact_content(sarif.id, self.db)    # on its own machine: simply missing
        self.assertEqual(missing.exception.detail[0]["code"], "ARTIFACT_FILE_MISSING")

    def test_conversions_are_shown_elsewhere_as_their_owners_machine_last_published_them(self):
        snapshot = {"entries": [{
            "number": 1, "branch": "conversion/1", "state": "verified", "baseline": "abc123", "baseline_from": None,
            "scanned_at": None, "head": "def456", "commits_beyond_inputs": 2, "uncommitted": [], "worktree": r"D:\runs\w",
            "prepared_at": None, "runbook_path": r"D:\runs\RUNBOOK.md", "runbook": "# Runbook", "opening_message": "Go.",
            "package_step": {}, "left_for_agent": {}, "verify_refusal": None, "plan_id": None,
            "verification": {"verdict": "PROVEN", "reasons": ["ok"], "verifiedAt": "2026-10-01", "tip": "def456",
                             "markdown": "# VERIFICATION", "current": True}}],
            "next": {"starts_from": "def456", "starts_from_subject": "work"}, "last_prepare": {"status": "prepared"}}
        with mock.patch.object(conversions, "local_snapshot", return_value=snapshot):
            with on(HOST_A):
                here = conversion_router.list_conversions(self.repo.id, self.db)
            with on(HOST_B):
                there = conversion_router.list_conversions(self.repo.id, self.db)
                current = conversion_router.get_current_conversion(self.repo.id, self.db)
        self.assertIsNone(here.held)
        self.assertEqual(there.held.held_on, "on Ann's machine (DEVBOX-A)")
        self.assertEqual([e.model_dump() for e in there.conversions], [e.model_dump() for e in here.conversions])
        self.assertEqual(there.conversions[0].verification.markdown, "# VERIFICATION")
        self.assertEqual(current.runbook, "# Runbook")

    # ---- paging

    def test_a_page_counts_filters_and_escapes_the_filter(self):
        source = """select jsonb_build_object('n', n) as item, n as k, lower(s) as search
                    from (values (1, 'a_b'), (2, 'a%b'), (3, 'ab'), (4, 'xyz')) v(n, s)"""
        everything = page(self.db, source, {}, pages(limit=2), order="k")
        self.assertEqual((everything.total, everything.matching, [i["n"] for i in everything.items]), (4, 4, [1, 2]))
        self.assertEqual([i["n"] for i in page(self.db, source, {}, pages(offset=2), order="k").items], [3, 4])
        self.assertEqual([i["n"] for i in page(self.db, source, {}, pages(q="_"), order="k").items], [1])
        self.assertEqual([i["n"] for i in page(self.db, source, {}, pages(q="%"), order="k").items], [2])
        narrowed = page(self.db, source, {}, pages(q="a"), order="k", where="k < 3")
        self.assertEqual((narrowed.total, narrowed.matching), (2, 2))

    def test_the_work_list_is_paged_and_filtered_by_the_database_as_the_view_showed_it(self):
        projects = [{"projectPath": f"src/P{p:02d}/P{p:02d}.csproj", "projectId": str(uuid.uuid4()), "items": [
            {"itemId": "wcf-service", "scope": "occurrence", "detectionState": "found", "reason": None,
             "occurrences": [{"filePath": f"src/P{p:02d}/F{f}.cs", "value": None, "certainty": "possible" if f == 0 else "confirmed",
                              "evidence": [{"line_start": 10 + f}]} for f in range(3)]},
            {"itemId": "msmq-usage", "scope": "occurrence", "detectionState": "checked_absent", "reason": None, "occurrences": []},
        ]} for p in range(25)]
        execution, step = self.execution()
        work = self.artifact(execution, step, "item-occurrences", {"summary": {"found": 25}, "projects": projects})
        first = views.list_work_items(work.id, False, pages(), self.db)
        self.assertEqual((first.total, first.matching, len(first.items)), (25, 25, 20))
        self.assertEqual(first.items[0]["project"], "src/P00/P00.csproj")
        self.assertEqual((first.items[0]["fileCount"], first.items[0]["possibleCount"]), (3, 1))
        self.assertEqual(first.items[0]["files"]["items"][0]["certainty"], "confirmed")    # confirmed first
        self.assertEqual(views.list_work_items(work.id, True, pages(), self.db).total, 50)
        narrowed = views.list_work_items(work.id, False, pages(q="p07"), self.db)
        self.assertEqual([r["project"] for r in narrowed.items], ["src/P07/P07.csproj"])
        totals = views.get_work_item_totals(work.id, self.db)
        self.assertEqual((totals.occurrence_rows, totals.possible_rows), (75, 25))
        files = views.list_work_item_files(work.id, projects[3]["projectId"], "wcf-service", False, pages(limit=2), self.db)
        self.assertEqual((files.total, [f["filePath"] for f in files.items]), (3, ["src/P03/F1.cs", "src/P03/F2.cs"]))

    def test_dependency_packages_are_grouped_by_id_and_version_with_what_blocks_first(self):
        def pkg(package_id, version, outcome, vulnerable=False):
            return {"packageId": package_id, "currentVersion": version, "outcome": outcome,
                    "vulnerable": {"maxSeverity": "high", "advisories": []} if vulnerable else None,
                    "declaredAt": {"filePath": "x.csproj", "line": 3}}
        content = {"summary": {"packageCount": 5}, "projects": [
            {"projectPath": "a/A.csproj", "packages": [pkg("Lib.Current", "1.0.0", "current"), pkg("Lib.Safe", "2.0.0", "upgrade_safe"),
                                                       pkg("Lib.Drift", "1.0.0", "current")]},
            {"projectPath": "b/B.csproj", "packages": [pkg("Lib.Drift", "2.0.0", "current"), pkg("lib.safe", "2.0.0", "upgrade_breaking", True)]},
        ]}
        execution, step = self.execution()
        assessment = self.artifact(execution, step, "dependency-assessment", content)
        shown = views.list_dependency_packages(assessment.id, False, pages(), self.db)
        self.assertEqual([g["packageId"] for g in shown.items], ["Lib.Safe", "Lib.Drift"])   # vulnerable first; current hidden unless drift
        safe = shown.items[0]["versions"][0]
        self.assertEqual((safe["useCount"], safe["outcomes"], safe["worst"]["project"]), (2, ["upgrade_breaking", "upgrade_safe"], "b/B.csproj"))
        self.assertEqual(views.list_dependency_packages(assessment.id, True, pages(), self.db).total, 3)
        uses = views.list_dependency_uses(assessment.id, "LIB.SAFE", "2.0.0", pages(), self.db)
        self.assertEqual([u["project"] for u in uses.items], ["a/A.csproj", "b/B.csproj"])

    def test_a_hard_deleted_repository_takes_its_results_but_not_a_content_another_shares(self):
        from app.deletion import service as deletion

        other = self.repository()
        content = {"summary": {"same": True}}
        execution, step = self.execution()
        mine = self.artifact(execution, step, "item-occurrences", content)
        other_execution, other_step = self.execution(other)
        self.artifact(other_execution, other_step, "item-occurrences", content)
        self.artifact(execution, step, "dependency-assessment", {"summary": {"only": "mine"}})
        self.db.commit()
        repo_id, shared = self.repo.id, mine.checksum
        with mock.patch.object(deletion, "_remove_files", return_value={"worktrees": [], "branches": [], "folders": []}):
            deletion.delete(self.db, deletion.repository_plan(self.db, self.repo), self.repo.name, via="test")
        self.repositories.remove(self.repo)
        self.assertEqual(self.db.query(models.ResultArtifact).filter_by(repository_id=repo_id).count(), 0)
        self.assertIsNotNone(self.db.get(models.ResultContent, shared))                  # the other repository's
        self.assertEqual(self.db.query(models.ResultContent).filter(
            models.ResultContent.head == {"summary": {"only": "mine"}}).count(), 0)
