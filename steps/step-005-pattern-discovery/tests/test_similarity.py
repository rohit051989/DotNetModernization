import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clustering.similarity import DEFAULT_CATEGORY_WEIGHTS, weighted_jaccard


class WeightedJaccardTests(unittest.TestCase):
    def test_identical_signal_sets_score_one(self):
        signals = {"IIS_HOSTED_ASPX": "HOSTING_INDICATOR", "XUNIT_TEST_ATTRIBUTE": "TESTING_INDICATOR"}
        self.assertEqual(weighted_jaccard(signals, dict(signals)), 1.0)

    def test_disjoint_signal_sets_score_zero(self):
        a = {"IIS_HOSTED_ASPX": "HOSTING_INDICATOR"}
        b = {"WCF_SERVICE_CONTRACT": "ENTRY_POINT"}
        self.assertEqual(weighted_jaccard(a, b), 0.0)

    def test_both_empty_scores_zero_not_one(self):
        # "Nothing in common because nothing was observed" must never look
        # like "identical" — two unscanned applications are not a match.
        self.assertEqual(weighted_jaccard({}, {}), 0.0)

    def test_high_weight_overlap_beats_low_weight_overlap_of_same_size(self):
        # Two applications sharing one HOSTING_INDICATOR (weight 2.0) score
        # higher than two sharing one TESTING_INDICATOR (weight 0.25), for
        # an otherwise identical shape of disjoint extra signals.
        hosting_pair = (
            {"IIS_HOSTED_ASPX": "HOSTING_INDICATOR", "ONLY_A": "FILE_INDICATOR"},
            {"IIS_HOSTED_ASPX": "HOSTING_INDICATOR", "ONLY_B": "FILE_INDICATOR"},
        )
        testing_pair = (
            {"XUNIT_TEST_ATTRIBUTE": "TESTING_INDICATOR", "ONLY_A": "FILE_INDICATOR"},
            {"XUNIT_TEST_ATTRIBUTE": "TESTING_INDICATOR", "ONLY_B": "FILE_INDICATOR"},
        )
        hosting_score = weighted_jaccard(*hosting_pair)
        testing_score = weighted_jaccard(*testing_pair)
        self.assertGreater(hosting_score, testing_score)

    def test_matches_hand_computed_value(self):
        a = {"HOSTING_A": "HOSTING_INDICATOR", "TEST_A": "TESTING_INDICATOR", "SHARED": "PROJECT_METADATA"}
        b = {"SHARED": "PROJECT_METADATA", "FILE_B": "FILE_INDICATOR"}
        # intersection = {SHARED} -> weight 1.0
        # union = {HOSTING_A(2.0), TEST_A(0.25), SHARED(1.0), FILE_B(0.75)} -> 4.0
        expected = 1.0 / 4.0
        self.assertAlmostEqual(weighted_jaccard(a, b), expected, places=9)

    def test_unknown_category_falls_back_to_neutral_weight(self):
        a = {"NEW_SIGNAL": "SOME_FUTURE_CATEGORY"}
        b = {"NEW_SIGNAL": "SOME_FUTURE_CATEGORY"}
        self.assertNotIn("SOME_FUTURE_CATEGORY", DEFAULT_CATEGORY_WEIGHTS)
        self.assertEqual(weighted_jaccard(a, b), 1.0)  # identical sets still score 1.0 regardless of weight


if __name__ == "__main__":
    unittest.main()
