"""The probe evidence boundary — 29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md C10.

The platform ships to each client as code, the WCF client matrices with it;
each client's data lives only in that client's database. The shipped matrices
hold platform knowledge only: entries confirmed on the platform's own sample
evidence, which ships with them. A probe run in a client's environment, and a
confirmation made on its evidence, are client data in the database with the
engagement; the report applies them on top of the shipped matrix. Missing or
altered engagement evidence shows as evidence missing, and the report is not
ready for the client.

Run from backend/:  python -m unittest tests.test_wcf_probe_evidence_boundary -v
"""

import copy
import datetime
import hashlib
import unittest
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.db import engine
from app.estate import engagement_matrix, soap_compatibility, wcf_matrix, wcf_probe
from app.routers import estate as estate_router
from tests.support import TEST_ENGAGEMENT_ID, ensure_test_engagement
from tests.test_soap_compatibility import REGISTER

RUNTIME = "net10.0/netTcpBinding/Transport/Windows"
PLATFORM = "net10.0/linux/netTcpBinding/*/Windows"
DOCUMENT = {"scenario": "netTcp-Transport-Windows", "service": "Payments, bank-client",
            "result": {"outcome": "passed", "address": "net.tcp://payments.bank-client.example:808/Pay"}}


def matrix_bytes() -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(wcf_matrix.MATRIX_DIR.glob("wcf-client-*-*.json"))}


class ShippedFilesTests(unittest.TestCase):
    def test_shipped_matrices_and_platform_evidence_hold_platform_knowledge_only(self):
        matrices, evidence = wcf_probe.platform_files()
        self.assertTrue(matrices and evidence)
        self.assertEqual([], wcf_probe.evidence_boundary_violations(matrices, evidence))


class CheckCatchesTests(unittest.TestCase):
    """The check fails on each way a client's data could reach what ships."""

    def setUp(self):
        self.matrices, self.evidence = wcf_probe.platform_files()

    def violations(self):
        return wcf_probe.evidence_boundary_violations(self.matrices, self.evidence)

    def entry(self, entry_id="net10.0/linux/netTcpBinding/*/Windows"):
        return next(e for e in self.matrices["wcf-client-platform-1.2.0.json"]["entries"] if e["id"] == entry_id)

    def test_a_client_probe_in_a_matrix_even_as_a_reference(self):
        self.entry().setdefault("probes", []).append({"probedOn": "2026-11-02", "scenario": "s", "outcome": "passed",
                                                      "evidenceRef": {"engagement": "bank-client", "id": "x"}})
        self.assertTrue(any("client engagement's probe in a shipped matrix" in v for v in self.violations()))

    def test_a_client_confirmation_in_a_matrix(self):
        self.entry()["confirmation"] = {"status": "confirmed", "by": "Client reviewer", "on": "2026-11-02",
                                        "source": {"engagement": "bank-client"}, "evidence": []}
        self.assertTrue(any("client's confirmation in a shipped matrix" in v for v in self.violations()))

    def test_a_confirmation_resting_on_evidence_that_does_not_ship(self):
        self.entry()["confirmation"] = {"status": "confirmed", "by": "A", "on": "2026-11-02", "evidence": ["elsewhere/x.json"]}
        self.assertTrue(any("confirmed on evidence outside" in v for v in self.violations()))

    def test_evidence_attributed_to_an_engagement_in_the_platform_folder(self):
        path = next(iter(self.evidence))
        self.evidence[path] = {**self.evidence[path], "parameters": {"engagement_id": "bank-client"}}
        self.assertTrue(any(path in v and "attributed to an engagement" in v for v in self.violations()))

    def test_a_stray_file_in_the_platform_folder(self):
        self.evidence["steps/step-003-fingerprinting/probes/evidence/20261102T090000Z-x-linux.json"] = {"result": {}}
        self.assertTrue(any("no matrix entry references it" in v for v in self.violations()))


class PlanOwnerTests(unittest.TestCase):
    def test_a_plan_must_say_whose_evidence_it_writes(self):
        for plan in ({}, {"platformSample": True, "engagement": "bank-client"}, {"platformSample": "yes"}):
            with self.assertRaises(SystemExit):
                wcf_probe.evidence_owner(plan)
        self.assertIsNone(wcf_probe.evidence_owner({"platformSample": True}))
        self.assertEqual("bank-client", wcf_probe.evidence_owner({"engagement": "bank-client"}))


class EngagementDataTests(unittest.TestCase):
    """In a rolled-back transaction: nothing is left in the database."""

    def setUp(self):
        self.connection = engine.connect()
        self.outer = self.connection.begin()
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")
        ensure_test_engagement(self.db)
        self.before = matrix_bytes()

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.connection.close()
        self.assertEqual(self.before, matrix_bytes(), "a matrix file changed")

    def evidence(self, evidence_id="E1", entries=(RUNTIME, PLATFORM)):
        return engagement_matrix.record_evidence(
            self.db, TEST_ENGAGEMENT_ID, evidence_id, DOCUMENT, scenario="netTcp-Transport-Windows", where="linux-container",
            outcome="passed", matrix_entries=list(entries), probed_on=datetime.date(2026, 11, 2),
            covers={"wcfClient": "8.1.2", "runtime": "10.0.12", "os": "linux"})

    def decide(self, **changes):
        decision = {"id": "CLIENT-1", "by": "Client reviewer", "on": "2026-11-02",
                    "instruction": f"confirm {RUNTIME} and {PLATFORM} on probe E1", "entries": [RUNTIME, PLATFORM],
                    "evidence": {RUNTIME: ["E1"], PLATFORM: ["E1"]}, **changes}
        return engagement_matrix.record_decision(self.db, TEST_ENGAGEMENT_ID, decision)

    def report(self):
        artifact = {"matrixVersion": "1.1.0", "platformMatrixVersion": "1.1.0", "hosts": soap_compatibility.build(copy.deepcopy(REGISTER))["hosts"]}
        engagement = SimpleNamespace(target_framework="net10.0", target_wcf_client_version=None)
        return estate_router._soap_report(artifact, [], engagement, engagement_matrix.overlay(self.db, TEST_ENGAGEMENT_ID))

    def tcp(self, report):
        return {h["host"]: h for h in report["hosts"]}["tcp.corp.example.com"]["callers"][0]["environments"][0]

    def test_a_client_confirmation_lives_in_the_database_and_applies_on_top_of_the_shipped_matrix(self):
        self.evidence()
        self.assertEqual([RUNTIME, PLATFORM], self.decide())
        self.assertEqual("unconfirmed", wcf_matrix.entries("platform")[PLATFORM]["confirmation"]["status"])   # shipped: untouched
        env = self.tcp(self.report())
        self.assertEqual((True, "Client reviewer", "engagement", False),
                         (env["platform"]["matrixConfirmed"], env["platform"]["confirmedBy"],
                          env["platform"]["confirmationSource"], env["platform"]["evidenceMissing"]))
        probe = next(p for p in env["platform"]["probes"] if p.get("evidenceRef"))
        self.assertEqual({"engagement": TEST_ENGAGEMENT_ID, "id": "E1"}, probe["evidenceRef"])
        self.assertNotIn("payments.bank-client", repr(probe))                     # the probe record carries no client detail

    def test_altered_evidence_shows_as_missing_and_the_report_is_not_ready(self):
        self.evidence()
        self.decide()
        row = self.db.get(engagement_matrix.models.EngagementProbeEvidence, (TEST_ENGAGEMENT_ID, "E1"))
        row.content = row.content.replace("passed", "failed")
        self.db.flush()
        report = self.report()
        env = self.tcp(report)
        self.assertTrue(env["platform"]["evidenceMissing"])
        self.assertIn(PLATFORM, report["matrix"]["evidenceMissingEntries"])
        self.assertFalse(report["matrix"]["readyForClient"])
        self.assertIn("NO - evidence missing", estate_router.soap_csv(report, "net10.0"))

    def test_emptied_evidence_shows_as_missing(self):
        self.evidence()
        self.decide()
        row = self.db.get(engagement_matrix.models.EngagementProbeEvidence, (TEST_ENGAGEMENT_ID, "E1"))
        row.content = None
        self.db.flush()
        self.assertIn(RUNTIME, self.report()["matrix"]["evidenceMissingEntries"])

    def test_a_client_confirmation_needs_named_entries_and_their_own_evidence(self):
        self.evidence()
        self.evidence("E2", entries=("net10.0/netTcpBinding/Transport/None",))
        for bad in ({"evidence": {RUNTIME: [], PLATFORM: ["E1"]}},                               # no evidence
                    {"evidence": {RUNTIME: ["E2"], PLATFORM: ["E1"]}},                           # evidence for another entry
                    {"evidence": {RUNTIME: ["E1"], PLATFORM: ["E1"], "net10.0/netTcpBinding/Transport/None": ["E2"]}},
                    {"entries": [RUNTIME, "net10.0/netTcpBinding/Transport/Everything"]},
                    {"evidence": {RUNTIME: ["NOPE"], PLATFORM: ["E1"]}}):
            with self.assertRaises(ValueError, msg=str(bad)):
                self.decide(**bad)
        self.assertEqual({}, engagement_matrix.overlay(self.db, TEST_ENGAGEMENT_ID)["confirmations"])

    def test_a_revert_keeps_the_row_and_the_report_drops_the_confirmation(self):
        self.evidence()
        self.decide()
        engagement_matrix.revert(self.db, TEST_ENGAGEMENT_ID, PLATFORM, "Client reviewer", "wrong service probed")
        self.assertNotIn(PLATFORM, engagement_matrix.overlay(self.db, TEST_ENGAGEMENT_ID)["confirmations"])
        rows = self.db.query(engagement_matrix.models.EngagementMatrixConfirmation).filter_by(engagement_id=TEST_ENGAGEMENT_ID).all()
        self.assertEqual(2, len(rows))                                            # never deleted
        self.assertFalse(self.tcp(self.report())["platform"]["matrixConfirmed"])

    def test_the_database_refuses_a_confirmation_of_an_entry_its_decision_does_not_name(self):
        from sqlalchemy.exc import IntegrityError
        self.evidence()
        self.db.add(engagement_matrix.models.EngagementMatrixConfirmation(
            engagement_id=TEST_ENGAGEMENT_ID, matrix_kind="platform", entry_id=PLATFORM, decision_id="X", decided_by="A",
            decided_on=datetime.date(2026, 11, 2), instruction="confirm the runtime entry", named_entries=[RUNTIME],
            evidence_ids=["E1"]))
        with self.assertRaises(IntegrityError):
            self.db.flush()

    def test_the_stored_hash_is_of_the_stored_document(self):
        sha = self.evidence()
        row = self.db.get(engagement_matrix.models.EngagementProbeEvidence, (TEST_ENGAGEMENT_ID, "E1"))
        self.assertEqual(sha, hashlib.sha256(row.content.encode("utf-8")).hexdigest())
        self.assertIn('"engagement": "' + TEST_ENGAGEMENT_ID, row.content)


if __name__ == "__main__":
    unittest.main()
