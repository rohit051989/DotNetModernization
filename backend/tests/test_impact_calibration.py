"""impact-analysis calibrated against a hand analysis — app/impact/calibration.py.

The oracle (tests/fixtures/impact_oracle/wcf-net10-rest.yaml) is
sampleapps/WCF/MODERNIZATION-NET10-REST.md, file by file. Its floors are the
recall and precision measured when the rules were last calibrated, and its
ceiling the review rate: a later rule edit (catalog/items/ is what is read)
that drops recall or precision below its floor, or reviews its way past the
ceiling, fails here — and so does any disagreement the oracle does not
classify and tag with the work expected to resolve it.

Needs the published step (steps/step-003-fingerprinting/publish/impact-analysis)
and the sample repository (sampleapps/WCF). No database.

Run from backend/:  python -m unittest tests.test_impact_calibration -v
"""

import copy
import unittest

import yaml

from app.impact import calibration


class CalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.oracle = yaml.safe_load(calibration.DEFAULT_ORACLE.read_text(encoding="utf-8"))
        cls.result = calibration.run()

    def test_recall_and_precision_hold_their_floors(self):
        floors = self.oracle["floors"]
        report = calibration.report(self.result)
        self.assertGreaterEqual(self.result.recall, floors["recall"], report)
        self.assertGreaterEqual(self.result.recall_in_scope, floors["recall_in_scope"], report)
        self.assertGreaterEqual(self.result.precision, floors["precision"], report)

    def test_review_stays_under_its_ceiling(self):
        self.assertLessEqual(self.result.review_rate, self.oracle["ceilings"]["review_rate"], calibration.summary(self.result))

    def test_every_disagreement_is_classified_and_tagged(self):
        self.assertEqual([], [r.path for r in self.result.unclassified], calibration.report(self.result))
        self.assertEqual([], [r.path for r in self.result.untagged], calibration.report(self.result))

    def test_review_is_an_abstention_not_a_gain(self):
        # Turn every claim into review: precision cannot rise by it, recall falls,
        # and the review rate breaks the ceiling.
        def over_review(catalog):
            catalog = copy.deepcopy(catalog)
            for item in catalog["items"]:
                for resolution in item["resolutions"]:
                    resolution["rules"] = [{**r, "action": "review"} if r.get("action") in ("update", "rewrite", "delete") else r
                                           for r in resolution["rules"]]
            return catalog

        reviewed = calibration.run(transform_catalog=over_review)
        self.assertLess(reviewed.recall, self.result.recall)
        self.assertGreater(reviewed.review_rate, self.oracle["ceilings"]["review_rate"])

    def test_a_weakened_rule_is_caught(self):
        # Drop the REST rewrite's contract rules: the contract interfaces, the
        # contracts project and the fault type are no longer found.
        def weaken(catalog):
            catalog = copy.deepcopy(catalog)
            for item in catalog["items"]:
                for resolution in item["resolutions"]:
                    if resolution["id"] == "wcf-service-rest-rewrite":
                        resolution["rules"] = [r for r in resolution["rules"]
                                               if r["id"] not in ("contracts", "contracts-project", "fault-exception", "data-contracts")]
            return catalog

        weakened = calibration.run(transform_catalog=weaken)
        self.assertLess(weakened.recall, self.oracle["floors"]["recall"])


if __name__ == "__main__":
    unittest.main()
