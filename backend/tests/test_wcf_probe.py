"""The WCF client matrix probe — 29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md
C11: evidence on matrix entries, never a verdict. What can be tested without a
container runtime: it refuses to simulate one, evidence carries no machine
path, and recording appends probes without touching verdicts or confirmations.

Run from backend/:  python -m unittest tests.test_wcf_probe -v
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.estate import wcf_matrix, wcf_probe


class ContainerRuntimeTests(unittest.TestCase):
    def test_no_docker_is_said_plainly_never_simulated(self):
        with mock.patch.object(wcf_probe.shutil, "which", lambda name: None):
            self.assertEqual("docker is not installed", wcf_probe.linux_container_runtime())

    def test_windows_containers_are_not_a_linux_runtime(self):
        done = mock.Mock(returncode=0, stdout="windows\n", stderr="")
        with mock.patch.object(wcf_probe.shutil, "which", lambda name: "docker"), mock.patch.object(wcf_probe, "_run", lambda *a, **k: done):
            self.assertEqual("docker runs windows containers, not linux", wcf_probe.linux_container_runtime())

    def test_main_stops_and_records_nothing_without_a_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            plan.write_text(json.dumps({"scenarios": {}}), encoding="utf-8")
            with mock.patch.object(wcf_probe, "linux_container_runtime", lambda: "docker is not installed"), \
                    mock.patch.object(wcf_probe, "append_probes") as append, \
                    mock.patch("sys.argv", ["wcf_probe", "--plan", str(plan)]):
                with self.assertRaises(SystemExit) as stop:
                    wcf_probe.main()
            self.assertEqual(2, stop.exception.code)
            append.assert_not_called()


class EvidenceTests(unittest.TestCase):
    def test_evidence_carries_no_machine_path_and_its_hash_is_of_what_was_written(self):
        # Under backend/runs (gitignored): write_evidence names files relative to the repository.
        with mock.patch.object(wcf_probe, "EVIDENCE_DIR", wcf_probe.REPO / "backend" / "runs" / "probes" / "test-evidence"):
            command = ["dotnet", str(wcf_probe.REPO / "backend" / "runs" / "probes" / "WcfClientProbe" / "WcfClientProbe.dll")]
            path, sha = wcf_probe.write_evidence("20261012T000000Z", "basicHttp-None-None", "windows-host", {"command": command})
            text = (wcf_probe.REPO / path).read_text(encoding="utf-8")
            (wcf_probe.REPO / path).unlink()
            wcf_probe.EVIDENCE_DIR.rmdir()
        self.assertNotIn(str(wcf_probe.REPO), text)
        self.assertNotIn(json.dumps(str(wcf_probe.REPO))[1:-1], text)
        self.assertIn("<repo>", text)
        self.assertEqual(wcf_probe.hashlib.sha256(text.encode("utf-8")).hexdigest(), sha)
        self.assertTrue(path.startswith("steps/") or path.startswith("backend/"))


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "wcf-client-platform-1.0.0.json"
        self.matrix = {"matrix": "wcf-client-platform", "entries": [
            {"id": "net10.0/linux/netTcpBinding/*/Windows", "verdict": "requires_change", "probes": [],
             "confirmation": {"status": "unconfirmed", "by": None, "on": None, "note": None}}]}
        self.path.write_text(json.dumps(self.matrix, indent=2) + "\n", encoding="utf-8")
        self.patch = mock.patch.object(wcf_matrix, "path_of", lambda kind, version=None: self.path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def entry(self):
        return json.loads(self.path.read_text(encoding="utf-8"))["entries"][0]

    def test_a_probe_is_appended_and_nothing_else_changes(self):
        record = {"probedOn": "2026-10-12", "scenario": "s", "outcome": "passed", "summary": "ok"}
        wcf_probe.append_probes("platform", {"net10.0/linux/netTcpBinding/*/Windows": [record]})
        entry = self.entry()
        self.assertEqual([record], entry["probes"])
        self.assertEqual(("requires_change", "unconfirmed"), (entry["verdict"], entry["confirmation"]["status"]))

    def test_not_probed_is_recorded_once_while_its_reason_holds(self):
        record = {"probedOn": "2026-10-12", "outcome": "not_probed", "reason": wcf_probe.NOT_PROBED[0]["reason"]}
        for _ in range(2):
            wcf_probe.append_probes("platform", {"net10.0/linux/netTcpBinding/*/Windows": [dict(record)]})
        self.assertEqual(1, len(self.entry()["probes"]))
        self.assertIn("needs Kerberos", self.entry()["probes"][0]["reason"])

    def test_an_entry_the_matrix_does_not_have_is_refused(self):
        with self.assertRaises(SystemExit):
            wcf_probe.append_probes("platform", {"net10.0/linux/nope/*/*": [{"outcome": "passed"}]})


class VersionAndCertificateTests(unittest.TestCase):
    def test_a_probe_records_the_wcf_client_package_and_runtime_it_ran_against(self):
        package = wcf_probe.wcf_client_package()
        self.assertRegex(package, r"^\d+\.\d+\.\d+")
        result = {"wcfClient": f"{package}+a47960f", "framework": ".NET 10.0.12"}
        self.assertEqual({"wcfClient": package, "runtime": "10.0.12", "os": "linux"}, wcf_probe.covers(result, package, "linux"))

    def test_a_client_that_is_not_the_referenced_package_is_refused(self):
        with self.assertRaises(SystemExit):
            wcf_probe.covers({"wcfClient": "6.2.0+abc", "framework": ".NET 10.0.12"}, "8.1.2", "linux")

    def test_the_server_is_pinned_by_its_certificate_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cer = Path(tmp) / "server.cer"
            cer.write_bytes(b"not really a certificate, but bytes all the same")
            self.assertEqual(wcf_probe.hashlib.sha1(cer.read_bytes()).hexdigest().upper(), wcf_probe.thumbprint(cer))

    def test_evidence_older_than_the_target_wcf_client_predates_it(self):
        entry = {"probes": [{"outcome": "passed", "covers": {"wcfClient": "8.1.2", "runtime": "10.0.12"}},
                            {"outcome": "not_probed", "reason": "needs Kerberos"}]}
        self.assertEqual({"wcfClient": "8.1.2", "runtimes": ["10.0.12"], "probes": 1}, wcf_matrix.evidence_covers(entry))
        self.assertFalse(wcf_matrix.evidence_predates(entry, "8.1.2"))
        self.assertTrue(wcf_matrix.evidence_predates(entry, "10.0.0"))
        self.assertTrue(wcf_matrix.evidence_predates(entry, "8.1.10"))                 # numbers, not text
        self.assertIsNone(wcf_matrix.evidence_covers({"probes": [{"outcome": "not_probed"}]}))


class ScenarioTests(unittest.TestCase):
    def test_every_scenario_and_not_probed_entry_is_in_the_real_matrices(self):
        support, platform = wcf_matrix.entries("support"), wcf_matrix.entries("platform")
        for item in wcf_probe.SCENARIOS + wcf_probe.NOT_PROBED:
            self.assertIn(item["support"], support)
            self.assertIn(item["platform"], platform)

    def test_kerberos_netTcp_is_an_open_item_for_the_clients_identity_team(self):
        for kind, entry_id in (("support", "net10.0/netTcpBinding/Transport/Windows"), ("platform", "net10.0/linux/netTcpBinding/*/Windows")):
            not_probed = [p for p in wcf_matrix.entries(kind)[entry_id]["probes"] if p["outcome"] == "not_probed"]
            self.assertEqual(1, len(not_probed))
            self.assertIn("identity team", not_probed[0]["openItem"])


if __name__ == "__main__":
    unittest.main()
