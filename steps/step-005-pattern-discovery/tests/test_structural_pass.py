import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clustering.structural_pass import run_structural_pass


class StructuralPassTests(unittest.TestCase):
    def test_two_similar_apps_form_a_cluster_with_min_pairwise_score(self):
        app_signals = {
            "app-1": {"IIS_HOSTED_ASPX": "HOSTING_INDICATOR", "WEBFORMS_PAGE_BASE": "SOURCE_CONSTRUCT"},
            "app-2": {"IIS_HOSTED_ASPX": "HOSTING_INDICATOR", "WEBFORMS_PAGE_BASE": "SOURCE_CONSTRUCT"},
            "app-3": {"WCF_SERVICE_CONTRACT": "ENTRY_POINT"},
        }
        clusters, residue, pairwise = run_structural_pass(app_signals, threshold_strong=0.6)

        self.assertEqual(len(clusters), 1)
        cluster = clusters[0]
        self.assertEqual(cluster.members, ("app-1", "app-2"))
        self.assertEqual(cluster.formation_method, "structural")
        self.assertEqual(cluster.similarity_score, 1.0)
        self.assertEqual(residue, ["app-3"])

    def test_common_signals_is_intersection_not_union(self):
        app_signals = {
            "app-1": {"SHARED": "HOSTING_INDICATOR", "ONLY_1": "FILE_INDICATOR"},
            "app-2": {"SHARED": "HOSTING_INDICATOR", "ONLY_2": "FILE_INDICATOR"},
        }
        clusters, _residue, _pairwise = run_structural_pass(app_signals, threshold_strong=0.3)
        self.assertEqual(len(clusters), 1)
        names = {s["name"] for s in clusters[0].common_signals}
        self.assertEqual(names, {"SHARED"})  # not {"SHARED", "ONLY_1", "ONLY_2"}

    def test_similarity_score_is_minimum_not_average_across_a_three_member_cluster(self):
        # app-1/app-2 identical (score 1.0); app-1/app-3 and app-2/app-3
        # share only the common baseline (a lower score) — the cluster's
        # similarity_score must reflect that weaker link, not the average.
        app_signals = {
            "app-1": {"BASE": "HOSTING_INDICATOR", "EXTRA": "FILE_INDICATOR"},
            "app-2": {"BASE": "HOSTING_INDICATOR", "EXTRA": "FILE_INDICATOR"},
            "app-3": {"BASE": "HOSTING_INDICATOR"},
        }
        clusters, _residue, pairwise = run_structural_pass(app_signals, threshold_strong=0.5)
        self.assertEqual(len(clusters), 1)
        cluster = clusters[0]
        self.assertEqual(cluster.members, ("app-1", "app-2", "app-3"))
        min_score = min(
            pairwise.get("app-1", "app-2"),
            pairwise.get("app-1", "app-3"),
            pairwise.get("app-2", "app-3"),
        )
        self.assertEqual(cluster.similarity_score, min_score)
        self.assertLess(min_score, 1.0)

    def test_all_singletons_when_nothing_meets_threshold(self):
        app_signals = {
            "app-1": {"A": "HOSTING_INDICATOR"},
            "app-2": {"B": "HOSTING_INDICATOR"},
            "app-3": {"C": "HOSTING_INDICATOR"},
        }
        clusters, residue, _pairwise = run_structural_pass(app_signals, threshold_strong=0.6)
        self.assertEqual(clusters, [])
        self.assertEqual(residue, ["app-1", "app-2", "app-3"])

    def test_deterministic_ordering_across_repeated_runs(self):
        app_signals = {
            "app-z": {"SHARED": "HOSTING_INDICATOR"},
            "app-a": {"SHARED": "HOSTING_INDICATOR"},
            "app-m": {"OTHER": "FILE_INDICATOR"},
            "app-b": {"OTHER": "FILE_INDICATOR"},
        }
        first = run_structural_pass(app_signals, threshold_strong=0.9)
        second = run_structural_pass(app_signals, threshold_strong=0.9)
        self.assertEqual([c.members for c in first[0]], [c.members for c in second[0]])
        self.assertEqual(first[1], second[1])


if __name__ == "__main__":
    unittest.main()
