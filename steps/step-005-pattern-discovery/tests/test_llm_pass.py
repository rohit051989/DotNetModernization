import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clustering.llm_client import LlmError
from clustering.llm_pass import run_llm_pass
from clustering.structural_pass import PairwiseSimilarities


class FakeLlmClient:
    """Same two-method shape as `llm_client.LlmClient`, no network."""

    def __init__(self, *, available=True, judgment=None, raise_on_judge=None, raise_on_summarize=None):
        self._available = available
        self._judgment = judgment if judgment is not None else {"groups": [], "rationale": ""}
        self._raise_on_judge = raise_on_judge
        self._raise_on_summarize = raise_on_summarize
        self.summarize_calls: list[str] = []
        self.judge_calls: list[dict] = []

    @property
    def available(self):
        return self._available

    def summarize_application(self, project_id, signals):
        self.summarize_calls.append(project_id)
        if self._raise_on_summarize:
            raise self._raise_on_summarize
        return f"summary of {project_id}"

    def judge_group(self, summaries):
        self.judge_calls.append(dict(summaries))
        if self._raise_on_judge:
            raise self._raise_on_judge
        return self._judgment


class LlmPassTests(unittest.TestCase):
    def test_unavailable_client_skips_pass_and_returns_all_residue_unclustered(self):
        client = FakeLlmClient(available=False)
        clusters, still_unclustered, diagnostics = run_llm_pass(
            ["app-1", "app-2"], {}, {}, PairwiseSimilarities({}), threshold_weak=0.35, client=client
        )
        self.assertEqual(clusters, [])
        self.assertEqual(still_unclustered, ["app-1", "app-2"])
        self.assertEqual(diagnostics[0]["code"], "LLM_PASS_SKIPPED")
        self.assertEqual(client.summarize_calls, [])

    def test_isolated_singleton_never_reaches_the_llm(self):
        # app-3 has zero weak-threshold edges to anything -> no LLM call at all.
        pairwise = PairwiseSimilarities({frozenset(("app-1", "app-2")): 0.4})
        client = FakeLlmClient(judgment={"groups": [["app-1", "app-2"]], "rationale": "same shape"})
        app_signals = {"app-1": {"X": "HOSTING_INDICATOR"}, "app-2": {"X": "HOSTING_INDICATOR"}, "app-3": {}}
        clusters, still_unclustered, _diag = run_llm_pass(
            ["app-1", "app-2", "app-3"], app_signals, {}, pairwise, threshold_weak=0.35, client=client
        )
        self.assertNotIn("app-3", client.summarize_calls)
        self.assertEqual(still_unclustered, ["app-3"])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].members, ("app-1", "app-2"))
        self.assertEqual(clusters[0].formation_method, "llm_assisted")

    def test_llm_affirmed_group_becomes_llm_assisted_cluster(self):
        pairwise = PairwiseSimilarities({frozenset(("app-1", "app-2")): 0.4})
        app_signals = {"app-1": {"X": "HOSTING_INDICATOR"}, "app-2": {"X": "HOSTING_INDICATOR"}}
        client = FakeLlmClient(judgment={"groups": [["app-1", "app-2"]], "rationale": "same legacy shape"})
        clusters, still_unclustered, diagnostics = run_llm_pass(
            ["app-1", "app-2"], app_signals, {}, pairwise, threshold_weak=0.35, client=client
        )
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].members, ("app-1", "app-2"))
        self.assertEqual(still_unclustered, [])
        self.assertEqual(diagnostics, [])
        self.assertEqual(sorted(client.summarize_calls), ["app-1", "app-2"])

    def test_llm_rejecting_a_group_leaves_it_unclustered(self):
        pairwise = PairwiseSimilarities({frozenset(("app-1", "app-2")): 0.4})
        app_signals = {"app-1": {"X": "HOSTING_INDICATOR"}, "app-2": {"X": "HOSTING_INDICATOR"}}
        client = FakeLlmClient(judgment={"groups": [], "rationale": "not actually related"})
        clusters, still_unclustered, _diag = run_llm_pass(
            ["app-1", "app-2"], app_signals, {}, pairwise, threshold_weak=0.35, client=client
        )
        self.assertEqual(clusters, [])
        self.assertEqual(still_unclustered, ["app-1", "app-2"])

    def test_judgment_failure_is_a_diagnostic_not_an_exception(self):
        pairwise = PairwiseSimilarities({frozenset(("app-1", "app-2")): 0.4})
        app_signals = {"app-1": {"X": "HOSTING_INDICATOR"}, "app-2": {"X": "HOSTING_INDICATOR"}}
        client = FakeLlmClient(raise_on_judge=LlmError("bad json"))
        clusters, still_unclustered, diagnostics = run_llm_pass(
            ["app-1", "app-2"], app_signals, {}, pairwise, threshold_weak=0.35, client=client
        )
        self.assertEqual(clusters, [])
        self.assertEqual(still_unclustered, ["app-1", "app-2"])
        self.assertEqual(diagnostics[0]["code"], "LLM_JUDGMENT_FAILED")

    def test_summary_failure_skips_judgment_for_that_component_only(self):
        pairwise = PairwiseSimilarities(
            {
                frozenset(("app-1", "app-2")): 0.4,
                frozenset(("app-3", "app-4")): 0.4,
            }
        )
        app_signals = {pid: {"X": "HOSTING_INDICATOR"} for pid in ("app-1", "app-2", "app-3", "app-4")}

        class SelectivelyFailingClient(FakeLlmClient):
            def summarize_application(self, project_id, signals):
                self.summarize_calls.append(project_id)
                if project_id == "app-1":
                    raise LlmError("summary failed")
                return f"summary of {project_id}"

        client = SelectivelyFailingClient(judgment={"groups": [["app-3", "app-4"]], "rationale": "ok"})
        clusters, still_unclustered, diagnostics = run_llm_pass(
            ["app-1", "app-2", "app-3", "app-4"], app_signals, {}, pairwise, threshold_weak=0.35, client=client
        )
        self.assertEqual([c.members for c in clusters], [("app-3", "app-4")])
        self.assertEqual(still_unclustered, ["app-1", "app-2"])
        self.assertTrue(any(d["code"] == "LLM_SUMMARY_FAILED" for d in diagnostics))


if __name__ == "__main__":
    unittest.main()
