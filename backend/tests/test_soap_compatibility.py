"""The SOAP backend compatibility report — 31-DEPENDENCY-AND-CONTEXT-MAP.md
Part J: per backend host, both verdicts per environment, what must change and
who changes it — the platform side from the platform matrix entry, keyed by
credential; a draft until a person confirms every matrix entry it rests on, no
probe contradicts one (a contradicted entry is under review, counted apart), and
no entry's evidence is older than the targeted WCF client.

Run from backend/:  python -m unittest tests.test_soap_compatibility -v
"""

import copy
import csv
import io
import unittest
from types import SimpleNamespace
from unittest import mock

from app.estate import analysis, soap_compatibility, wcf_matrix
from app.routers import estate as estate_router

BASIC, PIPE, TCP_WINDOWS, WS_WINDOWS = ("net10.0/linux/basicHttpBinding/None/None", "net10.0/linux/netNamedPipeBinding/*/*",
                                        "net10.0/linux/netTcpBinding/*/Windows", "net10.0/linux/wsHttpBinding/*/Windows")


def env(environment, host, binding, mode, credential, runtime, entry, platform, platform_reasons, platform_entry, source="declared"):
    return {"environment": environment, "sourceFile": "src/Host/App.config", "keyPath": "k", "scheme": "http", "host": host,
            "port": 80, "path": "/Svc.asmx", "resolution": "resolved",
            "soap": {"binding": binding, "securityMode": mode, "clientCredentialType": credential, "securitySource": source},
            "runtimeVerdict": runtime, "runtimeReasons": [f"{binding}: {runtime}"], "runtimeMatrixEntry": entry,
            "linuxVerdict": platform, "linuxReasons": platform_reasons, "platformMatrixEntry": platform_entry}


def call(call_id, slug, contract, binding, environments, servers=()):
    return {"id": call_id, "repository_id": slug, "repository_slug": slug, "project_path": f"src/{slug}/{slug}.csproj",
            "mechanism": "soap_client", "usage": "used", "linux_verdict": "compatible",
            "detail": {"block": {"contract": contract, "binding": binding, "securityMode": "None", "clientCredentialType": "None",
                                 "securitySource": "binding_default", "clientType": "FundsClient"}},
            "environment_bindings": environments, "operations": [{"operation": "Ping"}],
            "servers": [{"repository_slug": s} for s in servers]}


REGISTER = {"callsByKey": {
    # Another team's ASMX backend, plain basicHttp: supported; one environment on a short host name.
    "ftmt.corp.example.com": [call("a", "wcf", "FundsTransferWSSoap", "basicHttpBinding", [
        env("PROD", "ftmt.corp.example.com", "basicHttpBinding", "None", "None", "supported", "net10.0/basicHttpBinding/None/None",
            "compatible", ["basicHttpBinding: compatible on Linux"], BASIC, source="binding_default"),
        env("DEV", "appsrv0341", "basicHttpBinding", "None", "None", "supported", "net10.0/basicHttpBinding/None/None",
            "requires_change", ["basicHttpBinding: compatible on Linux", "unqualified hostname 'appsrv0341'"], BASIC,
            source="binding_default"),
    ])],
    # A wsHttp service left on its default Message security: unsupported by the WCF client;
    # its default Windows credential is Kerberos on Linux.
    "ledger.corp.example.com": [call("b", "billing", "ILedger", "wsHttpBinding", [
        env("PROD", "ledger.corp.example.com", "wsHttpBinding", "Message", "Windows", "unsupported", "net10.0/wsHttpBinding/Message/*",
            "requires_change", ["wsHttpBinding Message/Windows: requires change on Linux"], WS_WINDOWS, source="binding_default"),
    ])],
    # A named-pipe service this migration owns: only its owner can offer another binding.
    "localhost@wcf": [call("c", "wcf", "IOrderService", "netNamedPipeBinding", [
        env("default", "localhost", "netNamedPipeBinding", "None", "None", "supported", "net10.0/netNamedPipeBinding/None/None",
            "incompatible", ["netNamedPipeBinding: incompatible on Linux"], PIPE),
    ], servers=["wcf"])],
    # NetTcp on its default Windows credential: works on Linux with Kerberos, ours or the owner's to fix.
    "tcp.corp.example.com": [call("e", "wcf", "IAccountService", "netTcpBinding", [
        env("PROD", "tcp.corp.example.com", "netTcpBinding", "Transport", "Windows", "supported", "net10.0/netTcpBinding/Transport/Windows",
            "requires_change", ["netTcpBinding Transport/Windows: requires change on Linux"], TCP_WINDOWS, source="binding_default"),
    ])],
    # Not SOAP: not in the report.
    "api.corp.example.com": [{**call("d", "wcf", None, None, []), "mechanism": "http_client"}],
}}


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.report = soap_compatibility.build(copy.deepcopy(REGISTER))
        self.hosts = {h["host"]: h for h in self.report["hosts"]}

    def test_one_row_per_soap_backend_worst_runtime_first(self):
        self.assertEqual(["ledger.corp.example.com", "localhost@wcf", "ftmt.corp.example.com", "tcp.corp.example.com"],
                         [h["host"] for h in self.report["hosts"]])

    def test_an_unsupported_security_mode_is_the_backend_owners_change_and_ours_to_follow(self):
        ledger = self.hosts["ledger.corp.example.com"]
        self.assertEqual(("another_team", "unsupported", "requires_change"),
                         (ledger["backendOwner"], ledger["worstRuntime"], ledger["worstPlatform"]))
        changes = ledger["callers"][0]["environments"][0]["changes"]
        self.assertEqual(["backend_owner", "we", "we_or_backend_owner"], [c["who"] for c in changes])
        self.assertIn("not Message", changes[0]["change"])
        self.assertIn("Kerberos configuration on our side", changes[2]["change"])

    def test_a_service_the_estate_serves_is_this_migrations_change(self):
        wcf = self.hosts["localhost@wcf"]
        self.assertEqual(("this_migration", ["wcf"]), (wcf["backendOwner"], wcf["servedBy"]))
        change = wcf["callers"][0]["environments"][0]["changes"][0]
        self.assertEqual("backend_owner", change["who"])
        self.assertEqual(wcf_matrix.entries("platform")[PIPE]["fix"]["change"], change["change"])
        self.assertIn("this migration (wcf)", change["note"])

    def test_netTcp_with_a_windows_credential_is_kerberos_ours_or_the_owners_not_yet_known_which(self):
        """NetTcp works from Linux; its default Windows credential negotiates
        Kerberos, which we may configure on our side — not a required backend
        change until a probe in a Kerberos environment says so."""
        tcp = self.hosts["tcp.corp.example.com"]
        environment = tcp["callers"][0]["environments"][0]
        self.assertEqual(("supported", "requires_change"), (tcp["worstRuntime"], tcp["worstPlatform"]))
        self.assertEqual(["we_or_backend_owner"], [c["who"] for c in environment["changes"]])
        self.assertEqual("Kerberos configuration on our side, or a credential change by the backend's owner",
                         environment["changes"][0]["change"])
        self.assertEqual(TCP_WINDOWS, environment["platform"]["matrixEntry"])

    def test_a_supported_call_needs_nothing_except_where_its_own_configuration_is_wrong(self):
        funds = {e["environment"]: e for e in self.hosts["ftmt.corp.example.com"]["callers"][0]["environments"]}
        self.assertEqual([], funds["PROD"]["changes"])
        self.assertEqual(("None", "None", "binding_default"), (funds["PROD"]["securityMode"], funds["PROD"]["credentialType"], funds["PROD"]["securitySource"]))
        dev = funds["DEV"]["changes"]
        self.assertEqual(1, len(dev))                                   # "ports cleanly" is not a change
        self.assertEqual("we", dev[0]["who"])
        self.assertIn("appsrv0341", dev[0]["change"])

    def test_a_call_scanned_before_the_runtime_verdict_is_not_assessed_never_supported(self):
        old = copy.deepcopy(REGISTER)
        for e in old["callsByKey"]["ftmt.corp.example.com"][0]["environment_bindings"]:
            for key in ("runtimeVerdict", "runtimeReasons", "runtimeMatrixEntry"):
                e.pop(key)
        funds = {h["host"]: h for h in soap_compatibility.build(old)["hosts"]}["ftmt.corp.example.com"]
        environment = funds["callers"][0]["environments"][0]
        self.assertEqual("not_assessed", environment["runtime"]["verdict"])
        self.assertIn("rescan", environment["changes"][0]["change"])


def confirmed(matrix):
    matrix = copy.deepcopy(matrix)
    for entry in matrix["entries"]:
        entry["confirmation"] = {"status": "confirmed", "by": "A. Reviewer", "on": "2026-10-13", "note": None}
    return matrix


def probe(scenario, outcome, evidence, attribution=None):
    return {"probedOn": "2026-10-12", "scenario": scenario, "where": "linux-container", "outcome": outcome,
            "summary": "IUtilityService.Ping returned 'pong'" if outcome == "passed" else "System.UriFormatException: Invalid URI",
            "evidence": evidence, "sha256": "0" * 64, **({"attribution": attribution} if attribution else {})}


class ConfirmationTests(unittest.TestCase):
    def report(self, matrix, platform=None, target_wcf_client_version=None, run_version=None):
        # A run on the newest matrices of each kind unless a test says otherwise (support 1.1.0, platform 1.2.0).
        newest = {kind: (wcf_matrix.load(kind) or {}).get("matrixVersion") for kind in wcf_matrix.KINDS}
        artifact = {"matrixVersion": run_version or newest["support"], "platformMatrixVersion": run_version or newest["platform"],
                    "hosts": soap_compatibility.build(copy.deepcopy(REGISTER))["hosts"]}
        platform = platform or wcf_matrix.load("platform")
        engagement = SimpleNamespace(target_framework="net10.0", target_wcf_client_version=target_wcf_client_version)
        with mock.patch.object(soap_compatibility, "load_matrix", lambda version=None: matrix), \
                mock.patch.object(wcf_matrix, "load", lambda kind, version=None: platform if kind == "platform" else matrix):
            return estate_router._soap_report(artifact, [], engagement)

    def test_the_real_matrices_are_not_all_confirmed_so_the_report_is_a_draft(self):
        report = self.report(soap_compatibility.load_matrix())
        self.assertFalse(report["matrix"]["readyForClient"])
        self.assertIn("net10.0/wsHttpBinding/Message/*", report["matrix"]["unconfirmedEntries"])
        self.assertIn(TCP_WINDOWS, report["matrix"]["unconfirmedEntries"])            # the platform entries count too
        # 1.1.0: confirmed by a reviewer on probe evidence.
        self.assertNotIn("net10.0/basicHttpBinding/None/None", report["matrix"]["unconfirmedEntries"])
        self.assertIn("net10.0/basicHttpBinding/None/None", report["matrix"]["entriesUsed"])
        self.assertTrue(any(s["id"] == "chart-v2.1.0" for s in report["matrix"]["sources"]))

    def test_once_a_person_confirms_every_entry_used_the_report_is_ready_and_the_export_not_a_draft(self):
        report = self.report(confirmed(soap_compatibility.load_matrix()), confirmed(wcf_matrix.load("platform")))
        self.assertTrue(report["matrix"]["readyForClient"])
        environment = report["hosts"][0]["callers"][0]["environments"][0]
        self.assertEqual((True, "A. Reviewer"), (environment["runtime"]["matrixConfirmed"], environment["runtime"]["confirmedBy"]))
        self.assertEqual(True, environment["platform"]["matrixConfirmed"])

    def test_confirming_the_runtime_matrix_alone_is_not_enough(self):
        report = self.report(confirmed(soap_compatibility.load_matrix()))
        self.assertFalse(report["matrix"]["readyForClient"])
        self.assertTrue(all("/linux/" in e for e in report["matrix"]["unconfirmedEntries"]))

    def test_a_run_on_an_older_matrix_is_not_ready_until_it_is_rescanned(self):
        report = self.report(confirmed(soap_compatibility.load_matrix()), confirmed(wcf_matrix.load("platform")), run_version="1.0.0")
        self.assertEqual({"run": "1.0.0", "newest": "1.1.0"}, report["matrix"]["newerMatrices"]["support"])
        self.assertFalse(report["matrix"]["readyForClient"])

    def test_a_contradicted_entry_is_under_review_never_its_unrevised_verdict_and_counted_apart(self):
        """The named-pipe host's platform entry says incompatible, its owner must
        change; a passing probe contradicts it. Until a reviewer revises it, the
        verdict reads under review, the owner's change is withdrawn, and no total
        counts it as incompatible or as a backend change."""
        platform = confirmed(wcf_matrix.load("platform"))
        next(e for e in platform["entries"] if e["id"] == PIPE)["probes"] = [probe("netNamedPipe-None-None", "passed", "e/1.json")]
        report = self.report(confirmed(soap_compatibility.load_matrix()), platform)
        self.assertEqual([PIPE], report["matrix"]["contradictedEntries"])
        self.assertFalse(report["matrix"]["readyForClient"])

        host = {h["host"]: h for h in report["hosts"]}["localhost@wcf"]
        environment = host["callers"][0]["environments"][0]
        self.assertEqual(("under_review", "incompatible"), (environment["platform"]["verdict"], environment["platform"]["unrevisedVerdict"]))
        self.assertEqual("supported", environment["runtime"]["verdict"])                  # the runtime entry is not contradicted
        self.assertEqual([], environment["changes"])                                       # the owner's change is withdrawn
        self.assertIn("the entry says incompatible", environment["underReview"][0])
        self.assertEqual(("under_review", 1, []), (host["worstPlatform"], host["underReview"], host["changeOwners"]))
        self.assertEqual(dict(hosts=4, runtimeUnsupported=1, platformIncompatible=0, backendOwnerMustChange=1, underReview=1),
                         report["summary"])                                                # ledger is still the owner's

        rows = list(csv.DictReader(io.StringIO(estate_router.soap_csv(report, "net10.0"))))
        pipe = next(r for r in rows if r["backend_host"] == "localhost@wcf")
        self.assertEqual(("contradicted by probe - under review", "contradicted by probe - under review"),
                         (pipe["platform_verdict"], pipe["what_must_change"]))

    def test_evidence_older_than_the_targeted_wcf_client_is_flagged_and_keeps_the_report_a_draft(self):
        runtime, platform = confirmed(soap_compatibility.load_matrix()), confirmed(wcf_matrix.load("platform"))
        passed = {**probe("basicHttp-None-None", "passed", "e/5.json"), "covers": {"wcfClient": "8.1.2", "runtime": "10.0.12", "os": "linux"}}
        for matrix, entry_id in ((runtime, "net10.0/basicHttpBinding/None/None"), (platform, BASIC)):
            next(e for e in matrix["entries"] if e["id"] == entry_id)["probes"] = [passed]

        current = self.report(runtime, platform)                                           # the matrices' 8.1.2
        self.assertEqual(("8.1.2", "matrix", []), (current["matrix"]["targetWcfClientVersion"],
                                                   current["matrix"]["targetWcfClientVersionSource"], current["matrix"]["evidencePredatesTarget"]))
        self.assertTrue(current["matrix"]["readyForClient"])

        newer = self.report(runtime, platform, target_wcf_client_version="10.0.0")
        self.assertEqual(["net10.0/basicHttpBinding/None/None", BASIC], newer["matrix"]["evidencePredatesTarget"])
        self.assertFalse(newer["matrix"]["readyForClient"])
        funds = {h["host"]: h for h in newer["hosts"]}["ftmt.corp.example.com"]["callers"][0]["environments"][0]
        self.assertEqual(({"wcfClient": "8.1.2", "runtimes": ["10.0.12"], "probes": 1}, True),
                         (funds["platform"]["evidenceCovers"], funds["platform"]["evidencePredatesTarget"]))
        row = next(r for r in csv.DictReader(io.StringIO(estate_router.soap_csv(newer, "net10.0"))) if r["backend_host"] == "ftmt.corp.example.com")
        self.assertEqual(("runtime: WCF client 8.1.2 on .NET 10.0.12 | platform: WCF client 8.1.2 on .NET 10.0.12", "YES - re-probe"),
                         (row["evidence_covers"], row["evidence_predates_target"]))

    def test_a_linux_failure_that_passes_on_windows_contradicts_the_platform_entry_not_the_runtime_one(self):
        failure = probe("wsHttp-TransportWithMessageCredential-Certificate", "failed", "e/2.json", attribution="platform")
        self.assertEqual([], wcf_matrix.probe_contradictions("support", {"verdict": "supported_with_caveat", "probes": [failure]}))
        self.assertTrue(wcf_matrix.probe_contradictions("platform", {"verdict": "compatible", "probes": [failure]}))
        # Only the latest probe of a scenario counts: a pass after a fix clears it.
        later = probe("wsHttp-TransportWithMessageCredential-Certificate", "passed", "e/3.json")
        self.assertEqual([], wcf_matrix.probe_contradictions("platform", {"verdict": "compatible", "probes": [failure, later]}))
        # Not probed is not a contradiction.
        self.assertEqual([], wcf_matrix.probe_contradictions("platform", {"verdict": "requires_change", "probes": [
            {"probedOn": "2026-10-12", "outcome": "not_probed", "reason": "needs Kerberos"}]}))

    def test_the_csv_lists_each_probe_once_though_it_is_recorded_on_both_entries(self):
        runtime, platform = copy.deepcopy(soap_compatibility.load_matrix()), copy.deepcopy(wcf_matrix.load("platform"))
        passed = probe("basicHttp-None-None", "passed", "e/4.json")
        for matrix, entry_id in ((runtime, "net10.0/basicHttpBinding/None/None"), (platform, BASIC)):
            next(e for e in matrix["entries"] if e["id"] == entry_id)["probes"] = [passed]
        rows = list(csv.DictReader(io.StringIO(estate_router.soap_csv(self.report(runtime, platform), "net10.0"))))
        funds = next(r for r in rows if r["backend_host"] == "ftmt.corp.example.com")
        self.assertEqual("basicHttp-None-None on 2026-10-12: passed - IUtilityService.Ping returned 'pong'", funds["probe_results"])
        self.assertEqual("", funds["probe_contradictions"])

    def test_the_csv_carries_both_verdicts_who_changes_what_and_its_provenance(self):
        rows = list(csv.DictReader(io.StringIO(estate_router.soap_csv(self.report(soap_compatibility.load_matrix()), "net10.0"))))
        self.assertEqual(len(rows), 5)                                  # 2 environments + 1 + 1 + 1
        ledger = next(r for r in rows if r["backend_host"] == "ledger.corp.example.com")
        self.assertEqual(("unsupported", "requires_change", "Message", "Windows", "binding_default"),
                         (ledger["runtime_verdict"], ledger["platform_verdict"], ledger["security_mode"], ledger["credential_type"],
                          ledger["security_source"]))
        self.assertEqual("NO - awaiting confirmation", ledger["matrix_entry_confirmed"])
        self.assertIn("backend owner", ledger["who_changes_it"])
        self.assertEqual("another team", ledger["backend_owner"])
        self.assertIn("SupportedFeatures-v2.1.0.md", ledger["matrix_source"])
        self.assertEqual((WS_WINDOWS, "NO - awaiting confirmation"),
                         (ledger["platform_matrix_entry"], ledger["platform_matrix_entry_confirmed"]))
        self.assertIn("this migration or the backend owner", ledger["who_changes_it"])
        self.assertEqual("net10.0", ledger["target_framework"])


class RegisterKeepsItsGroupingTests(unittest.TestCase):
    def test_build_register_hands_back_the_calls_it_filed_under_each_row(self):
        calls = [{**call("x", "wcf", "IFunds", "basicHttpBinding", [
            env("PROD", "ftmt.corp.example.com", "basicHttpBinding", "None", "None", "supported", "e", "compatible", [], BASIC)]),
            "host": "localhost", "port": 8090, "path": "/F.asmx", "scheme": "http", "resolution": "resolved", "placeholder": None}]
        for c in calls:
            c.pop("servers")
        register = analysis.build_register(calls, [], production_environment="PROD")
        self.assertEqual(["ftmt.corp.example.com"], list(register["callsByKey"]))
        self.assertEqual("x", register["callsByKey"]["ftmt.corp.example.com"][0]["id"])


if __name__ == "__main__":
    unittest.main()
