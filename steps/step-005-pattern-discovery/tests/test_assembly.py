import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clustering.assembly import assemble_rows, review_priority_for
from clustering.structural_pass import ClusterCandidate, PairwiseSimilarities


class ReviewPriorityTests(unittest.TestCase):
    def test_large_cluster_is_high_priority(self):
        self.assertEqual(review_priority_for(5, 0.9), "high")
        self.assertEqual(review_priority_for(4, 0.9), "standard")

    def test_ambiguous_similarity_band_is_high_priority(self):
        self.assertEqual(review_priority_for(2, 0.5, threshold_weak=0.35, threshold_strong=0.6), "high")
        self.assertEqual(review_priority_for(2, 0.6, threshold_weak=0.35, threshold_strong=0.6), "standard")
        self.assertEqual(review_priority_for(2, 0.34, threshold_weak=0.35, threshold_strong=0.6), "standard")

    def test_unclustered_score_none_is_always_standard(self):
        self.assertEqual(review_priority_for(1, None), "standard")


class AssembleRowsTests(unittest.TestCase):
    def test_candidate_ids_assigned_in_deterministic_member_order(self):
        cluster_b = ClusterCandidate(
            members=("proj-b1", "proj-b2"),
            common_signals=({"name": "X", "category": "HOSTING_INDICATOR"},),
            similarity_score=0.9,
            formation_method="structural",
        )
        cluster_a = ClusterCandidate(
            members=("proj-a1", "proj-a2"),
            common_signals=({"name": "Y", "category": "HOSTING_INDICATOR"},),
            similarity_score=0.9,
            formation_method="structural",
        )
        pairwise = PairwiseSimilarities(
            {
                frozenset(("proj-a1", "proj-a2")): 0.9,
                frozenset(("proj-b1", "proj-b2")): 0.9,
            }
        )
        rows = assemble_rows("client-a-ocp4", [cluster_b, cluster_a], ["proj-z1"], pairwise)

        # proj-a* sorts before proj-b* sorts before proj-z1 -> ids in that order
        self.assertEqual([r["id"] for r in rows], ["CAND-client-a-ocp4-0001", "CAND-client-a-ocp4-0002", "CAND-client-a-ocp4-0003"])
        self.assertEqual(rows[0]["members"], ["proj-a1", "proj-a2"])
        self.assertEqual(rows[2]["status"], "unclustered")
        self.assertEqual(rows[2]["members"], ["proj-z1"])
        self.assertIsNone(rows[2]["similarity_score"])
        self.assertIsNone(rows[2]["formation_method"])
        self.assertEqual(rows[2]["member_similarities"], {"proj-z1": None})

    def test_unclustered_row_never_shaped_like_a_one_member_candidate(self):
        rows = assemble_rows("eng", [], ["solo"], PairwiseSimilarities({}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "unclustered")
        self.assertNotEqual(rows[0]["status"], "candidate_pattern")

    def test_idempotent_rerun_same_ids(self):
        cluster = ClusterCandidate(
            members=("proj-1", "proj-2"),
            common_signals=(),
            similarity_score=0.7,
            formation_method="structural",
        )
        pairwise = PairwiseSimilarities({frozenset(("proj-1", "proj-2")): 0.7})
        first = assemble_rows("eng", [cluster], ["proj-3"], pairwise)
        second = assemble_rows("eng", [cluster], ["proj-3"], pairwise)
        self.assertEqual([r["id"] for r in first], [r["id"] for r in second])
        self.assertEqual([r["members"] for r in first], [r["members"] for r in second])


if __name__ == "__main__":
    unittest.main()
