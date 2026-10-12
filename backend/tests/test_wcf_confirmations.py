"""Confirmations of WCF client matrix entries — 29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md
C10: a confirmation records a person's decision about named entries. The tool
can only record one for an entry the authorising decision names, and every
confirmed entry in every matrix traces to such a decision.

Run from backend/:  python -m unittest tests.test_wcf_confirmations -v
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.estate import wcf_matrix

NAMED = "net10.0/basicHttpBinding/None/None"
NOT_NAMED = "net10.0/basicHttpBinding/Transport/None"


def decision(**changes):
    return {"id": "TEST-1", "by": "A. Reviewer", "on": "2026-10-13", "instruction": f"confirm {NAMED}",
            "entries": [NAMED], **changes}


class RealMatricesTests(unittest.TestCase):
    def test_every_confirmed_entry_in_every_matrix_traces_to_a_decision_that_names_it(self):
        for path in sorted(wcf_matrix.MATRIX_DIR.glob("wcf-client-*-*.json")):
            matrix = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([], wcf_matrix.confirmation_violations(matrix), path.name)

    def test_every_recorded_decision_says_who_when_and_the_instruction(self):
        for path in sorted(wcf_matrix.MATRIX_DIR.glob("wcf-client-*-*.json")):
            for d in json.loads(path.read_text(encoding="utf-8")).get("decisions", []):
                for field in wcf_matrix.DECISION_FIELDS:
                    self.assertTrue(d.get(field), f"{path.name}: decision {d.get('id')} lacks {field}")


class RecordDecisionTests(unittest.TestCase):
    """On copies of the real matrices: the files are never touched."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = {}
        for kind in wcf_matrix.KINDS:
            source = wcf_matrix.path_of(kind)
            self.paths[kind] = Path(self.tmp.name) / source.name
            shutil.copy2(source, self.paths[kind])
            matrix = json.loads(self.paths[kind].read_text(encoding="utf-8"))
            for entry in matrix["entries"]:                       # start from nothing confirmed
                entry["confirmation"] = {"status": "unconfirmed", "by": None, "on": None, "note": None}
            matrix["decisions"] = []
            self.paths[kind].write_text(json.dumps(matrix), encoding="utf-8")
        self.patch = mock.patch.object(wcf_matrix, "path_of", lambda kind, version=None: self.paths[kind])
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def entries(self, kind="support"):
        return {e["id"]: e for e in json.loads(self.paths[kind].read_text(encoding="utf-8"))["entries"]}

    def test_only_the_entries_the_decision_names_are_confirmed(self):
        self.assertEqual([NAMED], wcf_matrix.record_decision(decision()))
        entries = self.entries()
        self.assertEqual(("confirmed", "A. Reviewer", "TEST-1"),
                         (entries[NAMED]["confirmation"]["status"], entries[NAMED]["confirmation"]["by"],
                          entries[NAMED]["confirmation"]["decision"]))
        self.assertEqual(1, sum(1 for e in entries.values() if e["confirmation"]["status"] == "confirmed"))
        self.assertEqual("unconfirmed", entries[NOT_NAMED]["confirmation"]["status"])
        self.assertEqual("unconfirmed", self.entries("platform")["net10.0/linux/basicHttpBinding/None/None"]["confirmation"]["status"])

    def test_a_decision_that_names_no_entry_confirms_nothing(self):
        with self.assertRaises(ValueError):
            wcf_matrix.record_decision(decision(entries=[]))
        with self.assertRaises(ValueError):
            wcf_matrix.record_decision(decision(instruction=""))
        self.assertFalse(any(e["confirmation"]["status"] == "confirmed" for e in self.entries().values()))

    def test_an_entry_no_matrix_has_is_refused_and_nothing_is_written(self):
        with self.assertRaises(ValueError):
            wcf_matrix.record_decision(decision(entries=[NAMED, "net10.0/basicHttpBinding/None/Everything"]))
        self.assertEqual("unconfirmed", self.entries()[NAMED]["confirmation"]["status"])

    def test_a_confirmation_the_decision_does_not_name_is_a_violation(self):
        wcf_matrix.record_decision(decision())
        matrix = json.loads(self.paths["support"].read_text(encoding="utf-8"))
        extended = next(e for e in matrix["entries"] if e["id"] == NOT_NAMED)
        extended["confirmation"] = {"status": "confirmed", "by": "A. Reviewer", "on": "2026-10-13", "decision": "TEST-1"}
        bare = next(e for e in matrix["entries"] if e["id"] == "net10.0/netTcpBinding/Transport/None")
        bare["confirmation"] = {"status": "confirmed", "by": "A. Reviewer", "on": "2026-10-13"}
        problems = wcf_matrix.confirmation_violations(matrix)
        self.assertEqual(2, len(problems))
        self.assertTrue(any("does not name it" in p and NOT_NAMED in p for p in problems))
        self.assertTrue(any("no recorded decision" in p for p in problems))

    def test_a_reverted_confirmation_keeps_what_was_reverted_and_why(self):
        wcf_matrix.record_decision(decision())
        wcf_matrix.revert_confirmation(NAMED, "2026-10-14", "the decision was withdrawn")
        confirmation = self.entries()[NAMED]["confirmation"]
        self.assertEqual(("unconfirmed", "the decision was withdrawn", "TEST-1"),
                         (confirmation["status"], confirmation["reverted"]["reason"], confirmation["reverted"]["was"]["decision"]))


class LiveVerdictTests(unittest.TestCase):
    """The repository page's SOAP view: the scan's verdict with the matrix read live."""

    def test_a_confirmed_entry_shows_who_confirmed_it_and_the_decision(self):
        live = wcf_matrix.live_verdict("support", "supported", NAMED, "8.1.2")
        self.assertEqual(("supported", True, "Rohit Khanna", "RK-2026-10-12-b", False),
                         (live["verdict"], live["matrixConfirmed"], live["confirmedBy"], live["decision"], live["evidencePredatesTarget"]))
        self.assertTrue(wcf_matrix.live_verdict("support", "supported", NAMED, "10.0.0")["evidencePredatesTarget"])

    def test_a_contradicted_entry_reads_under_review_never_its_verdict(self):
        entry = {"id": "x", "verdict": "compatible", "probes": [{"scenario": "s", "outcome": "failed", "summary": "boom"}],
                 "confirmation": {"status": "unconfirmed"}}
        with mock.patch.object(wcf_matrix, "entries", lambda kind, version=None: {"x": entry}):
            live = wcf_matrix.live_verdict("platform", "compatible", "x", None)
        self.assertEqual(("under_review", "compatible"), (live["verdict"], live["unrevisedVerdict"]))

    def test_no_entry_is_said(self):
        live = wcf_matrix.live_verdict("platform", "unknown", None, None)
        self.assertEqual((None, "unknown"), (live["matrixConfirmed"], live["verdict"]))


if __name__ == "__main__":
    unittest.main()
