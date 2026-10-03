"""Lifecycle step 6, item-detection — 28-ITEM-AND-CONVERSION-MODEL.md Parts
C to G, 17-LIFECYCLE-STEPS.md step 6.

Three layers:
- the pure evaluation and role functions, on hand-built signal rows;
- detect_repository() against the database, inside one rolled-back
  transaction, for detection_state and repository-level visibility;
- end to end: the REAL published step 3 binary fingerprints a fixture
  repository on disk, its signals are loaded, and step 6 runs on them. This
  closes the wcf-nettcp-client case deferred from the catalog work.

Uses stdlib unittest, like the other backend tests. Needs the database
migrated and seeded (`python -m app.seed`), and the step 3 binary published
(steps/step-003-fingerprinting/publish) for the end-to-end class.

Run from backend/:  python -m unittest tests.test_item_detection -v
"""

import json
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.db import engine
from tests.support import TEST_ENGAGEMENT_ID, ensure_test_engagement
from app.items import evaluation, roles
from app.steps.item_detection import detect_repository

STEP3_EXE = Path(settings.platform_root) / "steps" / "step-003-fingerprinting" / "publish" / "Fingerprinting.Cli.exe"


def row(value=None, source_path="a.cs", occurrences=1, repository_level=False, category="SOURCE_CONSTRUCT", evidence=None):
    return {
        "signal_category": category,
        "signal_type": "API_INVOCATION",
        "value": value,
        "source_type": "SOURCE_CODE",
        "source_path": source_path,
        "occurrence_count": occurrences,
        "extraction_confidence": 0.9,
        "evidence": evidence if evidence is not None else [{"lineStart": 3, "lineEnd": 3}],
        "repository_level": repository_level,
    }


def cond(rule_id, name, **signal):
    return {"id": rule_id, "signal": {"name": name, **signal}}


class EvaluationTests(unittest.TestCase):
    def test_groups_combine_all_any_none_and_metadata(self):
        match = {
            "all": [cond("a", "A")],
            "any": [cond("b", "B"), cond("c", "C")],
            "none": [cond("n", "N")],
            "metadata": [{"id": "m", "field": "frameworkFamily", "in": ["net"]}],
        }
        signals = {"A": [row()], "C": [row()]}
        self.assertTrue(evaluation.evaluate_match(match, signals, {"frameworkFamily": "net"})[0])
        self.assertFalse(evaluation.evaluate_match(match, {**signals, "N": [row()]}, {"frameworkFamily": "net"})[0])
        self.assertFalse(evaluation.evaluate_match(match, {"A": [row()]}, {"frameworkFamily": "net"})[0])
        self.assertFalse(evaluation.evaluate_match(match, signals, {"frameworkFamily": "net-framework"})[0])

    def test_value_predicates_and_quantities(self):
        c = cond("x", "X", value={"equals": "netTcpBinding"})
        self.assertFalse(evaluation.evaluate_signal_condition(c, {"X": [row("basicHttpBinding")]})[0])
        self.assertTrue(evaluation.evaluate_signal_condition(c, {"X": [row("netTcpBinding")]})[0])
        many = cond("y", "Y", minimumOccurrences=3)
        self.assertFalse(evaluation.evaluate_signal_condition(many, {"Y": [row(occurrences=2)]})[0])
        self.assertTrue(evaluation.evaluate_signal_condition(many, {"Y": [row(occurrences=2), row(source_path="b.cs")]})[0])

    def test_projection_keeps_only_rows_the_condition_accepts(self):
        """A Serilog sink whose path is not a Windows path is not an
        occurrence of an item that requires one."""
        detection = {
            "match": {"all": [cond("sink", "SINK", value={"regex": r"^[A-Za-z]:\\"})]},
            "occurrence_source": {"signal": "SINK", "group_by": "source_path"},
        }
        signals = {"SINK": [
            row(r"G:\Logs", "appsettings.json", evidence=[{"lineStart": 6, "lineEnd": 6}]),
            row("/var/log/app", "appsettings.Linux.json"),
            row(r"C:\logs", "appsettings.Dev.json"),
        ]}
        located = evaluation.project_occurrences(detection, signals)
        self.assertEqual([o["file_path"] for o in located], ["appsettings.Dev.json", "appsettings.json"])
        self.assertEqual(located[1]["evidence"][0]["line_start"], 6)

    def test_repository_level_rows_never_locate(self):
        detection = {"match": {"all": [cond("f", "F")]}, "occurrence_source": {"signal": "F"}}
        located = evaluation.project_occurrences(detection, {"F": [row(source_path="k8s/deploy.yaml", repository_level=True)]})
        self.assertEqual(located, [])

    def test_source_path_and_value_splits_one_file(self):
        detection = {"match": {"all": [cond("k", "K")]}, "occurrence_source": {"signal": "K", "group_by": "source_path_and_value"}}
        located = evaluation.project_occurrences(detection, {"K": [row("ApiKey", "web.config"), row("Password", "web.config")]})
        self.assertEqual([(o["file_path"], o["value"]) for o in located], [("web.config", "ApiKey"), ("web.config", "Password")])


class RoleTests(unittest.TestCase):
    def role(self, structural="csharp_project", output=None, fingerprinted=True, packages=(), signals=(), entry=()):
        return roles.derive_role(
            {"structural_type": structural, "output_type": output, "fingerprinted": fingerprinted},
            list(packages), set(signals), set(entry),
        )[0]

    def test_part_d_roles(self):
        self.assertEqual(self.role("docker_compose_project"), "DEPLOYMENT")
        self.assertEqual(roles.derive_role(
            {"structural_type": "unknown_project", "extension": ".sfproj", "output_type": None, "fingerprinted": False},
            [], set(), set())[0], "DEPLOYMENT")
        self.assertEqual(self.role("sql_database_project"), "DATABASE")
        self.assertEqual(self.role(entry=["WEB_APPLICATION_CREATE_BUILDER_ENTRY_POINT"]), "APPLICATION")
        self.assertEqual(self.role(output="WinExe"), "APPLICATION")
        self.assertEqual(self.role(signals=["SVC_FILE"]), "APPLICATION")
        self.assertEqual(self.role(output="Library"), "LIBRARY")
        self.assertEqual(self.role(fingerprinted=False), "UNKNOWN")
        self.assertEqual(self.role("nodejs_project"), "UNKNOWN")

    def test_test_project_is_not_an_application(self):
        """Microsoft.NET.Test.Sdk makes a test project's OutputType Exe."""
        self.assertEqual(self.role(output="Exe", packages=["Microsoft.NET.Test.Sdk", "xunit"]), "TEST")
        self.assertEqual(self.role(signals=["FACT_ATTRIBUTE"], entry=["MAIN_METHOD_ENTRY_POINT"]), "TEST")


class DetectionTestCase(unittest.TestCase):
    """Fixture repository rows inside one rolled-back transaction."""

    def setUp(self):
        self.connection = engine.connect()
        self.outer = self.connection.begin()
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")
        tag = uuid.uuid4().hex[:8]
        ensure_test_engagement(self.db)
        self.repo = models.Repository(
            engagement_id=TEST_ENGAGEMENT_ID, name=f"t-{tag}", root_folder_name=f"t-{tag}", slug=f"t-{tag}",
            local_path=f"C:/t-{tag}", local_path_normalised=f"c:/t-{tag}", source_type="local_path", ingest_status="scanned",
        )
        self.db.add(self.repo)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.connection.close()

    def add_project(self, relative_path, output_type="Library", framework_family="net", fingerprinted=True, project_sdk="Microsoft.NET.Sdk"):
        # Step 2 records a value for output type and SDK on every .NET project
        # (MSBuild's default when undeclared), so a fixture does too: a null
        # here means "unknown" and makes metadata conditions not_checked.
        project = models.Project(
            repository_id=self.repo.id, name=Path(relative_path).stem, relative_path=relative_path, extension=".csproj",
            structural_type="csharp_project", project_format="sdk_style", language="csharp",
            package_management_style="packagereference", parse_status="success",
            output_type=output_type, framework_family=framework_family, project_sdk=project_sdk,
        )
        self.db.add(project)
        self.db.flush()
        if fingerprinted:
            self.db.add(models.ProjectFingerprint(
                project_id=project.id, repository_id=self.repo.id, fingerprint_status="partial",
                scanner_version="test", analysis_capabilities={},
            ))
        return project

    def scan(self, registry_version):
        self.db.add(models.FingerprintScan(
            repository_id=self.repo.id, scan_status="partial", scanner_version="test",
            signal_registry_version=registry_version, semantic_analysis_enabled=False,
        ))

    def signal(self, name, project=None, source_path="Program.cs", value=None, category="ENTRY_POINT", type_="ENTRY_POINT", evidence=None):
        self.db.add(models.FingerprintSignal(
            project_id=project.id if project else None, repository_id=self.repo.id, signal_name=name,
            signal_category=category, signal_type=type_, value=value, source_type="SOURCE_CODE",
            source_path=source_path, evidence_kind="FILE", occurrence_count=1,
            evidence=evidence or [{"lineStart": 1, "lineEnd": 1}], extractor="test", extraction_confidence=1,
        ))

    def states(self):
        self.db.flush()
        detect_repository(self.db, self.repo)
        return {
            (o.project_id, o.item_id): o.detection_state
            for o in self.db.query(models.ItemOccurrence).filter_by(repository_id=self.repo.id)
        }


class DetectionTests(DetectionTestCase):
    def test_repository_level_manifest_counts_for_every_project(self):
        self.scan("1.5.0")
        api = self.add_project("src/Api/Api.csproj")
        worker = self.add_project("src/Worker/Worker.csproj")
        for project in (api, worker):
            self.signal("WEB_APPLICATION_CREATE_BUILDER_ENTRY_POINT", project, f"{project.relative_path}/../Program.cs")
        self.signal("OCP4_MANIFEST_FILE", None, "k8s/deployment.yaml", category="DEPLOYMENT_INDICATOR", type_="FILE_PRESENCE")

        states = self.states()
        for project in (api, worker):
            self.assertEqual(states[(project.id, "missing-ocp4-manifests")], "checked_absent")
            self.assertEqual(states[(project.id, "missing-dockerfile")], "found")

    def test_older_registry_is_not_checked_never_checked_absent(self):
        """Scanned under 1.3.0: DOCKERFILE_FILE (1.4.0) did not exist yet, so
        'no Dockerfile' cannot be concluded."""
        self.scan("1.3.0")
        api = self.add_project("src/Api/Api.csproj")
        self.signal("WEB_APPLICATION_CREATE_BUILDER_ENTRY_POINT", api)
        states = self.states()
        self.assertEqual(states[(api.id, "missing-dockerfile")], "not_checked")
        self.assertNotIn("checked_absent", {s for (p, i), s in states.items() if i == "missing-dockerfile"})

    def test_unfingerprinted_project_is_not_checked(self):
        """Step 3 never reached it: a rescan can fix that, so not_checked."""
        self.scan("1.5.0")
        project = self.add_project("src/Legacy/Legacy.csproj", output_type="Exe", fingerprinted=False)
        states = self.states()
        signal_based = {s for (p, i), s in states.items() if p == project.id and i != "ssis-package"}
        self.assertEqual(signal_based, {"not_checked"})

    def test_project_step3_skipped_as_out_of_scope_writes_no_signal_rows(self):
        """A .dcproj is never fingerprinted; not_checked would flag it for a
        rescan forever. Only metadata-only items (ssis-package) apply."""
        self.scan("1.5.0")
        compose = self.add_project("docker-compose.dcproj", fingerprinted=False)
        compose.structural_type, compose.extension = "docker_compose_project", ".dcproj"
        self.db.add(models.ProjectFingerprint(
            project_id=compose.id, repository_id=self.repo.id, fingerprint_status="skipped",
            scanner_version="test", analysis_capabilities={},
        ))
        states = self.states()
        self.assertEqual({i for (p, i) in states if p == compose.id}, {"ssis-package"})
        self.assertNotIn("not_checked", {s for (p, i), s in states.items() if p == compose.id})

    def test_role_exclusion_writes_no_row(self):
        self.scan("1.5.0")
        tests = self.add_project("tests/Unit/Unit.csproj", output_type="Exe")
        self.db.add(models.ProjectPackage(project_id=tests.id, package_name="xunit", declaration_source="packagereference"))
        self.signal("WEB_APPLICATION_CREATE_BUILDER_ENTRY_POINT", tests)
        states = self.states()
        # missing-dockerfile excludes TEST.
        self.assertNotIn((tests.id, "missing-dockerfile"), states)

    def test_occurrence_rows_and_rescan_replaces(self):
        self.scan("1.5.0")
        api = self.add_project("src/Api/Api.csproj")
        for path in ("src/Api/A.cs", "src/Api/B.cs"):
            self.signal("DATETIME_NOW_USAGE", api, path, value="System.DateTime.Now", category="SOURCE_CONSTRUCT", type_="API_INVOCATION")
        self.states()
        self.states()  # a second run replaces, never duplicates
        rows = self.db.query(models.ItemOccurrence).filter_by(repository_id=self.repo.id, item_id="datetime-now-usage").all()
        self.assertEqual(sorted(r.file_path for r in rows), ["src/Api/A.cs", "src/Api/B.cs"])
        self.assertTrue(all(r.detection_state == "found" and r.evidence for r in rows))


@unittest.skipUnless(STEP3_EXE.exists(), "step 3 binary not published")
class EndToEndNetTcpTests(DetectionTestCase):
    """The deferred test: a project hosting a NetTcp SERVICE while calling an
    HTTP client must not produce a wcf-nettcp-client occurrence — real step
    3 extraction, real step 6 detection."""

    SERVICE_NETTCP_CLIENT_HTTP = """<configuration>
  <system.serviceModel>
    <services><service name="Orders"><endpoint contract="IOrders" binding="netTcpBinding" /></service></services>
    <client><endpoint name="Ledger" contract="ILedger" binding="basicHttpBinding" address="https://ledger/svc" /></client>
  </system.serviceModel>
</configuration>
"""
    CLIENT_NETTCP = """<configuration>
  <system.serviceModel>
    <client><endpoint name="Ledger" contract="ILedger" binding="netTcpBinding" address="net.tcp://ledger/svc" /></client>
  </system.serviceModel>
</configuration>
"""

    def fingerprint_and_detect(self, web_config: str) -> dict:
        with tempfile.TemporaryDirectory(prefix="step6-e2e-") as tmp:
            root = Path(tmp) / "repo"
            (root / "Svc").mkdir(parents=True)
            (root / "Svc" / "Svc.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk" />', encoding="utf-8")
            (root / "Svc" / "web.config").write_text(web_config, encoding="utf-8")
            inventory = Path(tmp) / "inventory.json"
            inventory.write_text(json.dumps({
                # Step 2's solution-project-inventory, snake_case as it writes it.
                "repository_id": str(self.repo.id), "repository_slug": self.repo.slug,
                "projects": [{"relative_path": "Svc/Svc.csproj", "parse_status": "success", "structural_type": "csharp_project"}],
            }), encoding="utf-8")
            out = Path(tmp) / "out"
            subprocess.run([str(STEP3_EXE), "--repo", str(root), "--inventory", str(inventory), "--out", str(out)],
                           check=True, capture_output=True, timeout=300)
            artifact = json.loads((out / "application-fingerprint.json").read_text(encoding="utf-8"))

        project = self.add_project("Svc/Svc.csproj")
        self.scan(artifact["signalRegistryVersion"])
        (fp,) = [p for p in artifact["projects"] if p["projectPath"] == "Svc/Svc.csproj"]
        for s in fp["signals"]:
            self.db.add(models.FingerprintSignal(
                project_id=project.id, repository_id=self.repo.id, signal_name=s["name"], signal_category=s["category"],
                signal_type=s["type"], value=s["value"], source_type=s["sourceType"], source_path=s["sourcePath"],
                evidence_kind=s["evidenceKind"], occurrence_count=s["occurrenceCount"], evidence=s["evidence"],
                extractor=s["extractor"], extraction_confidence=s["extractionConfidence"],
            ))
        return self.states(), project

    def test_nettcp_service_with_http_client_does_not_match(self):
        states, project = self.fingerprint_and_detect(self.SERVICE_NETTCP_CLIENT_HTTP)
        self.assertEqual(states[(project.id, "wcf-nettcp-client")], "checked_absent")

    def test_nettcp_client_matches(self):
        states, project = self.fingerprint_and_detect(self.CLIENT_NETTCP)
        self.assertEqual(states[(project.id, "wcf-nettcp-client")], "found")


if __name__ == "__main__":
    unittest.main()
