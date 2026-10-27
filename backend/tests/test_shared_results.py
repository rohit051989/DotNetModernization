"""Shared results with two simulated machines against one database (app.results; docs/VDI-SETUP.md, "More than one
person"). Each machine is a hostname, the Windows account its backend runs under (app.auth.machine, patched) and a
RUNS_DIR of its own; the app is called as a server would call it (tests.asgi_client), through the real sign-in guard.

- Ann scans the synthetic 170-project repository on machine A.
- Ben, on machine B with an empty RUNS_DIR and no clone, opens every tab and view of it: every list, every page,
  every nested list, is exactly what Ann sees on A, and as complete as the artifacts on A's disk.
- What only A has (a raw SARIF export, the clone's files) is named "on Ann's machine (DEVBOX-A)" on B.
- Ben scans a repository of his own on B; Ada, an admin on machine C with an empty RUNS_DIR, runs the estate
  consolidation (a developer may not), and it covers both repositories.
- Measured on the 170-project repository: the database space one scan's results take, compressed, and how long each
  tab takes to load (printed; docs/VDI-SETUP.md quotes them).

Runs the published step programs (scripts/bootstrap.ps1 stage 6) offline, like test_platform_scale. A few minutes.
"""
import contextlib
import json
import statistics
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from sqlalchemy import text

from app import models
from app.auth import machine, service
from app.config import settings
from app.db import SessionLocal
from app.deletion import service as deletion
from app.main import app
from app.repositories import service as repositories_service
from app.repositories.schemas import RegisterLocalPathRequest
from app.workflow.adapters.base import local_path_from_uri
from app.workflow.runtime import service as runtime
from tests.asgi_client import Client
from tests.fixtures import synthetic_repository

ENGAGEMENT = "t-engagement-shared"
MACHINE_A, MACHINE_B, MACHINE_C = "DEVBOX-A", "DEVBOX-B", "DEVBOX-C"
PASSWORD = "shared-results-password"


@contextlib.contextmanager
def on(host: str, account: str, runs: Path):
    """This process, as the backend on `host`, under `account`, with `runs` as its RUNS_DIR."""
    with mock.patch.object(machine, "hostname", return_value=host), \
            mock.patch.object(machine, "windows_account", return_value=account), \
            mock.patch.object(settings, "runs_dir", str(runs)):
        yield


def small_repository(root: Path) -> None:
    """One web application with one controller that calls another service: what machine B scans."""
    project = root / "src" / "Orders.Api"
    (project / "Controllers").mkdir(parents=True)
    (project / "Orders.Api.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk.Web">\n  <PropertyGroup>\n    <TargetFramework>net8.0</TargetFramework>\n'
        '  </PropertyGroup>\n</Project>\n', encoding="utf-8")
    (project / "Program.cs").write_text(
        "var builder = WebApplication.CreateBuilder(args);\nbuilder.Services.AddControllers();\n"
        "var app = builder.Build();\napp.MapControllers();\napp.Run();\n", encoding="utf-8")
    (project / "Controllers" / "OrdersController.cs").write_text(
        "using Microsoft.AspNetCore.Mvc;\n\nnamespace Orders.Api.Controllers;\n\n[ApiController]\n[Route(\"api/orders\")]\n"
        "public class OrdersController : ControllerBase\n{\n    private static readonly HttpClient Http = new();\n\n"
        "    [HttpGet(\"{id}\")]\n    public async Task<IActionResult> Get(int id)\n    {\n"
        "        var stock = await Http.GetStringAsync(\"http://inventory.client-a.example/api/stock/\" + id);\n"
        "        return Ok(stock);\n    }\n}\n", encoding="utf-8")


class SharedResults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.runs = {host: base / f"runs-{host}" for host in (MACHINE_A, MACHINE_B, MACHINE_C)}
        for folder in cls.runs.values():
            folder.mkdir()
        cls.clone = base / "A" / "SynthCo170"
        synthetic_repository.generate(cls.clone)
        cls.small = base / "B" / "Orders"
        small_repository(cls.small)

        cls.tag = uuid.uuid4().hex[:6]
        cls.db = SessionLocal()
        db = cls.db
        cls.accounts = {"ann": rf"CORP\ann{cls.tag}", "ben": rf"CORP\ben{cls.tag}", "ada": rf"CORP\ada{cls.tag}"}
        cls.users = {
            "ann": service.create_user(db, login=f"ann-{cls.tag}", name="Ann", windows_account=cls.accounts["ann"],
                                       role="developer", host_names=[MACHINE_A], password=PASSWORD, must_change_password=False),
            "ben": service.create_user(db, login=f"ben-{cls.tag}", name="Ben", windows_account=cls.accounts["ben"],
                                       role="developer", host_names=[MACHINE_B], password=PASSWORD, must_change_password=False),
            "ada": service.create_user(db, login=f"ada-{cls.tag}", name="Ada", windows_account=cls.accounts["ada"],
                                       role="admin", host_names=[MACHINE_C], password=PASSWORD, must_change_password=False),
        }
        db.add(models.Engagement(id=ENGAGEMENT, client_name="Test engagement (shared results)",
                                 target_platform="Linux / OpenShift Container Platform 4", default_posture="lift-and-shift"))
        db.commit()
        cls.hosts = {"ann": MACHINE_A, "ben": MACHINE_B, "ada": MACHINE_C}
        cls.clients = {who: cls.sign_in(who) for who in cls.users}

        # Ann registers and scans the 170-project repository, on A.
        cls.repo_a = cls.register(cls.clone, "ann")
        with mock.patch.object(settings, "compare_public_nuget_feed", False):
            started = time.monotonic()
            cls.scan_a = cls.discover(cls.repo_a, "ann")
            cls.scan_seconds = time.monotonic() - started

    @classmethod
    def tearDownClass(cls):
        cls.db.rollback()
        engagement = cls.db.get(models.Engagement, ENGAGEMENT)
        if engagement is not None:
            deletion.delete(cls.db, deletion.engagement_plan(cls.db, engagement), engagement.client_name, via="test")
        for user in cls.users.values():
            cls.db.delete(cls.db.get(models.User, user.id))
        cls.db.commit()
        cls.db.close()
        cls.tmp.cleanup()

    # ---- helpers

    @classmethod
    def as_(cls, who: str, host: str | None = None):
        host = host or cls.hosts[who]
        return on(host, cls.accounts[who], cls.runs[host])

    @classmethod
    def sign_in(cls, who: str) -> Client:
        client = Client(app)
        with cls.as_(who):
            answer = client.post("/api/auth/sign-in", {"login": cls.users[who].login, "password": PASSWORD})
        assert answer.status == 200, answer.body
        return client

    @classmethod
    def register(cls, folder: Path, who: str) -> models.Repository:
        """Registered on its owner's machine, as the register endpoint records it."""
        engagement = cls.db.get(models.Engagement, ENGAGEMENT)
        repo = repositories_service.register_local_path(cls.db, engagement, RegisterLocalPathRequest(
            source_type="local_path", local_path=str(folder)))
        repo.owner_user_id, repo.registered_host = cls.users[who].id, cls.hosts[who]
        cls.db.commit()
        return repo

    @classmethod
    def discover(cls, repo: models.Repository, who: str) -> dict:
        """Discovery on its owner's machine, queued there and writing to that machine's RUNS_DIR (a rescan without
        preparing a conversion)."""
        with cls.as_(who):
            execution = runtime.launch_job(cls.db, "phase0-repository-discovery", {
                "engagement_id": ENGAGEMENT, "repository_id": str(repo.id), "ingest_token": repo.ingest_token,
                "prepare_conversion": False}, triggered_by="manual")
            cls.db.commit()
        assert execution.batch_status == "COMPLETED", execution.exit_message
        assert execution.queued_by_host == cls.hosts[who]
        return {"id": str(execution.id)}

    def get(self, who: str, url: str, host: str | None = None, status: int = 200):
        with self.as_(who, host):
            answer = self.clients[who].get(url)
        self.assertEqual(answer.status, status, f"{url}: {answer.body[:500]!r}")
        return answer.json() if status == 200 else answer

    def all_pages(self, who: str, url: str) -> dict:
        items, offset = [], 0
        while True:
            page = self.get(who, f"{url}{'&' if '?' in url else '?'}offset={offset}&limit=500")
            items += page["items"]
            offset += len(page["items"])
            if not page["items"] or offset >= page["matching"]:
                return {"total": page["total"], "items": items}

    def crawl(self, who: str, repo_id) -> dict:
        """Every tab and view of the repository page, every list to its last page, and every nested list."""
        r, seen = f"/api/repositories/{repo_id}", {}

        def take(key: str, value):
            seen[key] = value
            return value

        stored = self.get(who, f"{r}/results")
        stored.pop("held_on")   # where the repository was scanned, when that is not here: the one thing that differs
        results = take("results", stored)["results"]
        fp = results["application-fingerprint"]["artifact_id"]
        da = results["dependency-assessment"]["artifact_id"]
        wo = results["item-occurrences"]["artifact_id"]
        overview = take("fingerprint", self.get(who, f"/api/results/{fp}/fingerprint"))
        for c in overview["categories"]:
            take(f"signals:{c['category']}", self.all_pages(who, f"/api/results/{fp}/fingerprint/signals?category={c['category']}"))
        take("feeds", self.get(who, f"/api/results/{da}/dependencies/feeds"))
        packages = take("packages", self.all_pages(who, f"/api/results/{da}/dependencies/packages?show_current=true"))
        for p in packages["items"][:40]:
            for v in p["versions"]:
                take(f"uses:{p['packageId']}:{v['version']}", self.all_pages(
                    who, f"/api/results/{da}/dependencies/uses?package_id={p['packageId']}&version={v['version']}"))
        take("work-totals", self.get(who, f"/api/results/{wo}/work-items/totals"))
        work = take("work", self.all_pages(who, f"/api/results/{wo}/work-items?show_all=true"))
        for row in [w for w in work["items"] if w["fileCount"] > 0][:40]:
            take(f"files:{row['projectId']}:{row['itemId']}", self.all_pages(
                who, f"/api/results/{wo}/work-items/files?project_id={row['projectId']}&item_id={row['itemId']}"
                     f"&by_file={str(row['groupBy'] == 'source_path_and_value').lower()}"))

        take("entry-summary", self.get(who, f"{r}/entry-points/summary"))
        for requests in ("true", "false"):
            projects = take(f"entry-projects:{requests}", self.all_pages(who, f"{r}/entry-points/projects?with_requests={requests}"))
            for p in projects["items"]:
                for k in p["kinds"]:
                    take(f"entries:{p['project_id']}:{k['entry_class']}:{k['kind']}", self.all_pages(
                        who, f"{r}/entry-points/list?project_id={p['project_id']}&entry_class={k['entry_class']}&kind={k['kind']}"))
        take("outbound-summary", self.get(who, f"{r}/outbound-invocations/summary"))
        for invocations in ("true", "false"):
            projects = take(f"outbound-projects:{invocations}", self.all_pages(who, f"{r}/outbound-invocations/projects?with_invocations={invocations}"))
            for p in projects["items"]:
                for m in p["mechanisms"]:
                    take(f"invocations:{p['project_id']}:{m['mechanism']}", self.all_pages(
                        who, f"{r}/outbound-invocations/list?project_id={p['project_id']}&mechanism={m['mechanism']}"))
        take("backend-summary", self.get(who, f"{r}/entry-point-backend/summary"))
        for app_row in take("backend-apps", self.all_pages(who, f"{r}/entry-point-backend/applications"))["items"]:
            take(f"operations:{app_row['project_id']}", self.all_pages(who, f"{r}/entry-point-backend/operations?project_id={app_row['project_id']}"))
        take("soap-summary", self.get(who, f"{r}/soap-compatibility/summary"))
        take("soap-calls", self.all_pages(who, f"{r}/soap-compatibility/calls"))

        take("structure", self.get(who, f"{r}/structure?warnings=false"))
        take("warnings", self.all_pages(who, f"{r}/structure/warnings"))
        for s in take("solutions", self.all_pages(who, f"{r}/solutions/page"))["items"]:
            take(f"members:{s['id']}", self.all_pages(who, f"{r}/solutions/{s['id']}/members"))
        take("standalone", self.all_pages(who, f"{r}/projects/page?standalone=true"))
        take("artifacts", self.all_pages(who, f"{r}/artifacts/page"))
        take("hierarchy", self.get(who, f"{r}/hierarchy?transitive=false&show=all"))

        take("impact-summary", self.get(who, f"{r}/impact/summary"))
        for name, url in (("hotspots", "impact/files?hotspots=true"), ("impact-files", "impact/files?hotspots=false"),
                          ("impact-work-items", "impact/work-items"), ("rule-conflicts", "impact/rule-conflicts"),
                          ("work-item-conflicts", "impact/work-item-conflicts")):
            take(name, self.all_pages(who, f"{r}/{url}"))
        take("tests-summary", self.get(who, f"{r}/tests/summary"))
        for name in ("test-projects", "test-classes", "projects", "source-files"):
            take(f"tests:{name}", self.all_pages(who, f"{r}/tests/{name}"))

        conversions = self.get(who, f"{r}/conversions")
        conversions.pop("held", None)
        take("conversions", conversions)
        take("executions", self.get(who, f"{r}/executions"))
        return seen

    # ---- the proof

    def test_1_another_machine_sees_every_tab_complete_without_the_owners_files_or_clone(self):
        repo = self.repo_a
        ann = self.crawl("ann", repo.id)

        # As complete as the artifacts on A's disk.
        stored = {a.artifact_type: a for a in self.db.query(models.WfArtifact).filter_by(job_execution_id=uuid.UUID(self.scan_a["id"]))}
        content = {kind: json.loads(local_path_from_uri(a.uri).read_text(encoding="utf-8-sig")) for kind, a in stored.items()
                   if kind in ("item-occurrences", "dependency-assessment", "application-fingerprint", "entry-point-inventory")}
        rows = sum(len(p.get("items") or []) for p in content["item-occurrences"]["projects"])
        self.assertEqual(ann["work"]["total"], rows)
        self.assertGreaterEqual(rows, 170)
        package_ids = {k["packageId"].lower() for p in content["dependency-assessment"]["projects"] for k in p.get("packages") or []}
        self.assertEqual(ann["packages"]["total"], len(package_ids))
        signals = sum(len(p.get("signals") or []) for p in content["application-fingerprint"]["projects"]) + \
            len(content["application-fingerprint"].get("repositorySignals") or [])
        self.assertEqual(sum(c["signals"] for c in ann["fingerprint"]["categories"]), signals)
        entries = sum(len(v["items"]) for k, v in ann.items() if k.startswith("entries:"))
        self.assertEqual(entries, ann["entry-summary"]["entry_point_count"])
        # The same as the whole-repository endpoints the tools still have, page by page.
        whole = self.get("ann", f"/api/repositories/{repo.id}/impact")
        self.assertEqual(ann["impact-summary"]["totals"], whole["totals"])
        self.assertEqual(ann["impact-files"]["items"], whole["files"])
        self.assertEqual(ann["hotspots"]["items"], whole["hotspots"])
        self.assertEqual(ann["impact-work-items"]["items"], whole["work_items"])
        # Impact states the work list's figures: its "plus N possible" are the work list's, each marked.
        possible = content["item-occurrences"]["summary"]["possible_only_found"]
        self.assertEqual(whole["totals"]["possible_work_items"], possible)
        self.assertEqual(sum(1 for w in whole["work_items"] if w["possible_only"]), possible)
        whole = self.get("ann", f"/api/repositories/{repo.id}/tests")
        self.assertEqual(ann["tests:source-files"]["items"], whole["source_files"])
        self.assertEqual(ann["tests:projects"]["items"], whole["projects"])
        self.assertEqual(ann["tests:test-classes"]["items"], whole["test_classes"])

        # Machine B: an empty RUNS_DIR, and no clone; A's folders are not reachable from it.
        self.assertEqual(list(self.runs[MACHINE_B].iterdir()), [])
        with self.not_on_this_machine(self.clone, self.runs[MACHINE_A]):
            ben = self.crawl("ben", repo.id)
            self.assertEqual(sorted(ben), sorted(ann))
            for key in ann:
                self.assertEqual(ben[key], ann[key], key)
            self.where_only_a_has_it(repo, stored, content)

    @contextlib.contextmanager
    def not_on_this_machine(self, *folders: Path):
        """The folders, moved out of reach while B looks: in this process, A's folders would otherwise be readable."""
        moved = [(folder, folder.with_name(folder.name + "-not-here")) for folder in folders]
        for folder, away in moved:
            folder.rename(away)
        try:
            yield
        finally:
            for folder, away in moved:
                away.rename(folder)

    def where_only_a_has_it(self, repo, stored, content):

        # Where only A has it, B is told whose machine it is on.
        detail = self.get("ben", f"/api/repositories/{repo.id}")
        self.assertEqual(detail["files_held_on"], "on Ann's machine (DEVBOX-A)")
        sarif = stored["fingerprint-sarif"]
        missing = self.get("ben", f"/api/workflow/artifacts/{sarif.id}/content", status=404)
        self.assertEqual(missing.code, "LOCAL_ONLY")
        self.assertIn("on Ann's machine (DEVBOX-A)", missing.message)
        self.assertEqual(self.get("ben", f"/api/workflow/artifacts/{sarif.id}")["held_on"], "on Ann's machine (DEVBOX-A)")
        # A result a view reads is served from the database to B.
        work = stored["item-occurrences"]
        self.assertTrue(self.get("ben", f"/api/workflow/artifacts/{work.id}")["in_database"])
        self.assertEqual(self.get("ben", f"/api/workflow/artifacts/{work.id}/content")["summary"], content["item-occurrences"]["summary"])
        conversions = self.get("ben", f"/api/repositories/{repo.id}/conversions")
        self.assertEqual(conversions["held"]["held_on"], "on Ann's machine (DEVBOX-A)")

    def test_2_estate_consolidation_by_the_admin_covers_repositories_scanned_on_different_machines(self):
        repo_b = self.register(self.small, "ben")
        with mock.patch.object(settings, "compare_public_nuget_feed", False):
            self.discover(repo_b, "ben")

        launch = {"parameters": {"engagement_id": ENGAGEMENT, "run_token": str(uuid.uuid4())}}
        with self.as_("ben"):
            refused = self.clients["ben"].post("/api/workflow/jobs/phase0-estate-consolidation/launch", launch)
        self.assertEqual(refused.status, 403, refused.body)

        # Ada, an admin, on a machine of her own with an empty RUNS_DIR: the consolidation reads only the database.
        self.assertEqual(list(self.runs[MACHINE_C].iterdir()), [])
        with self.as_("ada"):
            answer = self.clients["ada"].post("/api/workflow/jobs/phase0-estate-consolidation/launch", launch)
        self.assertEqual(answer.status, 202, answer.body)
        self.assertEqual(answer.json()["batch_status"], "COMPLETED", answer.json())

        # Both machines' repositories are in it, each by what it contributes: A's packages, B's application and the
        # host B's application calls. Read by either developer, from the database.
        for who in ("ann", "ben"):
            estate = self.get(who, f"/api/engagements/{ENGAGEMENT}/estate")
            coverage = estate["artifacts"]["endpoint-register"]["coverage"]
            packages = self.all_pages(who, f"/api/engagements/{ENGAGEMENT}/estate/packages")
            apps = self.all_pages(who, f"/api/engagements/{ENGAGEMENT}/estate/integration/applications?exposed=all")
            hosts = self.all_pages(who, f"/api/engagements/{ENGAGEMENT}/estate/register/hosts")
            seen = {"coverage": (coverage["repositoriesIncluded"], coverage["repositoriesInEngagement"]),
                    "package repositories": sorted({r for p in packages["items"] for r in p["repositories"]}),
                    "applications": sorted({a["repositorySlug"] for a in apps["items"]}),
                    "hosts": sorted(h["host"]["host"] for h in hosts["items"] if "host" in h)}
            self.assertEqual(seen["coverage"], (2, 2), seen)
            self.assertIn(self.repo_a.slug, seen["package repositories"], seen)
            self.assertIn(repo_b.slug, seen["applications"], seen)
            self.assertIn("inventory.client-a.example", seen["hosts"], seen)

    def test_3_measured_on_the_170_project_repository(self):
        """Not a pass or fail: the figures the guide quotes. Space: the database's own size of one scan's stored results
        (compressed); time: each tab's first load as another machine makes it, in this process."""
        space = self.db.execute(text("""
            select count(*), coalesce(sum(pg_column_size(c.content) + pg_column_size(c.head)), 0), coalesce(sum(c.size_bytes), 0)
            from result_contents c where c.checksum in (select checksum from result_artifacts where job_execution_id = :e)
        """), {"e": uuid.UUID(self.scan_a["id"])}).one()
        r = f"/api/repositories/{self.repo_a.id}"
        results = self.get("ben", f"{r}/results")["results"]
        fp, da, wo = (results[k]["artifact_id"] for k in ("application-fingerprint", "dependency-assessment", "item-occurrences"))
        tabs = {
            "Overview": [r, f"{r}/results", f"{r}/soap-compatibility/summary", f"{r}/conversions", f"{r}/executions"],
            "Surface": [f"{r}/entry-points/summary", f"{r}/entry-points/projects?with_requests=true", f"{r}/outbound-invocations/summary",
                        f"{r}/outbound-invocations/projects?with_invocations=true", f"{r}/entry-point-backend/summary",
                        f"{r}/entry-point-backend/applications", f"{r}/soap-compatibility/summary", f"{r}/soap-compatibility/calls"],
            "Projects": [f"{r}/structure?warnings=false", f"{r}/solutions/page", f"{r}/projects/page?standalone=true",
                         f"/api/results/{fp}/fingerprint"],
            "Dependencies": [f"/api/results/{da}/dependencies/feeds", f"/api/results/{da}/dependencies/packages"],
            "Dependency graph": [f"{r}/hierarchy?transitive=false&show=all"],
            "Impact": [f"{r}/impact/summary", f"{r}/impact/files?hotspots=true", f"{r}/impact/rule-conflicts",
                       f"{r}/impact/work-item-conflicts", f"{r}/impact/work-items", f"{r}/impact/files?hotspots=false"],
            "Tests": [f"{r}/tests/summary", f"{r}/tests/test-projects", f"{r}/tests/projects", f"{r}/tests/source-files"],
            "Work list": [f"/api/results/{wo}/work-items/totals", f"/api/results/{wo}/work-items"],
            "Conversion": [f"{r}/conversions"],
            "Executions": [f"{r}/executions"],
            "Details": [r],
        }
        timings = {}
        for tab, urls in tabs.items():
            runs = []
            for _ in range(3):
                started = time.perf_counter()
                for url in urls:
                    self.get("ben", url)
                runs.append(time.perf_counter() - started)
            timings[tab] = statistics.median(runs)
        print(f"\n170-project repository: discovery took {self.scan_seconds:.0f} s; one scan's stored results: "
              f"{space[0]} artifacts, {space[2] / 1024 / 1024:.1f} MB as JSON, {space[1] / 1024 / 1024:.2f} MB in the database "
              f"(compressed)")
        for tab, seconds in timings.items():
            print(f"  {tab:<17} {seconds * 1000:6.0f} ms  ({len(tabs[tab])} requests, as another machine, in-process)")
        self.assertLess(space[1], space[2])
        self.assertTrue(all(seconds < 5 for seconds in timings.values()), timings)
