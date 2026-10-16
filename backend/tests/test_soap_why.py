"""The Why of a SOAP verdict (wcf_matrix.why): the matrix entry that decided it and its evidence, or, for an unknown
verdict, which of the three reasons it is. Read against the shipped matrices."""
import unittest

from app.estate import wcf_matrix

PLATFORM = wcf_matrix.entries("platform")


class SoapWhyTests(unittest.TestCase):
    def why(self, verdict, reasons, entry_id):
        return wcf_matrix.why("platform", verdict, reasons, entry_id, PLATFORM.get(entry_id or ""))

    def test_a_binding_not_resolved_from_configuration(self):
        text = self.why("unknown", ["binding unresolved"], None)
        self.assertEqual(text, "Unknown: the binding was not resolved from configuration, so no matrix entry can be chosen.")
        self.assertIn("security mode was not resolved",
                      self.why("unknown", ["basicHttpBinding: security mode unresolved"], None))

    def test_no_entry_covers_the_combination(self):
        text = self.why("unknown", ["customBinding, None security, None credentials: no entry in the WCF client platform matrix 1.2.0"], None)
        self.assertTrue(text.startswith("Unknown: no matrix entry covers this combination"), text)

    def test_only_an_unprobed_wildcard_covers_it(self):
        text = self.why("unknown", [], "net10.0/linux/basicHttpsBinding/*/*")
        self.assertTrue(text.startswith("Unknown: only the unprobed wildcard matrix entry net10.0/linux/basicHttpsBinding/*/*"), text)

    def test_a_specific_entry_names_its_probe_and_its_matched_control(self):
        text = self.why("compatible", [], "net10.0/linux/basicHttpsBinding/Transport/Certificate")
        self.assertIn("Decided by matrix entry net10.0/linux/basicHttpsBinding/Transport/Certificate (compatible)", text)
        self.assertIn("probe basicHttps-Transport-Certificate passed on Linux on 2026-10-16", text)
        self.assertIn("control linux-container-no-client-certificate failed, as expected", text)

    def test_a_failed_probe_says_the_error(self):
        text = self.why("incompatible", [], "net10.0/linux/wsHttpBinding/TransportWithMessageCredential/Certificate")
        self.assertIn("failed on Linux", text)
        self.assertIn("control windows-host passed", text)

    def test_a_verdict_the_scan_worsened_says_why_beyond_the_entry(self):
        text = self.why("requires_change", [
            "basicHttpBinding, None security, None credentials: compatible on Linux — chart Linux: ...",
            "unqualified hostname 'appsrv0341': use the fully qualified name"], "net10.0/linux/basicHttpBinding/None/None")
        self.assertIn("The verdict is requires change, not the entry's compatible, because: unqualified hostname 'appsrv0341'", text)

    def test_the_new_basic_https_entries_are_specific_and_confirmed_by_a_named_decision(self):
        for credential in ("None", "Certificate"):
            entry = PLATFORM[f"net10.0/linux/basicHttpsBinding/Transport/{credential}"]
            self.assertEqual(entry["verdict"], "compatible")
            confirmation = entry["confirmation"]
            self.assertEqual((confirmation["status"], confirmation["by"], confirmation["decision"]),
                             ("confirmed", "Rohit Khanna", "RK-2026-10-17-a"))
            self.assertIn("the container must trust the services' issuing certificate authority", confirmation["note"])
            self.assertTrue(all(p["outcome"] == "passed" for p in entry["probes"]))
        pair = PLATFORM["net10.0/linux/basicHttpsBinding/Transport/Certificate"]["probes"][-1]
        control = pair["controls"][0]
        self.assertEqual((control["where"], control["outcome"], control["asExpected"]),
                         ("linux-container-no-client-certificate", "failed", True))
        self.assertEqual(control["evidence"][:43], "steps/step-003-fingerprinting/probes/eviden")


if __name__ == "__main__":
    unittest.main()
