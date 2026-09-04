"""Pass 2 — LLM-assisted grouping of pass-1 residue.
23-STEP-005-PATTERN-DISCOVERY.md Part D.

Runs only on the applications `structural_pass.run_structural_pass` left as
residue (no edge at `threshold_strong`). Two steps:

1. Weak-threshold grouping: reuse the pairwise similarities already
   computed in pass 1 and connect edges at `threshold_weak` (looser than
   pass 1's `threshold_strong`) among residue only. A residue application
   with zero weak-threshold edges is fully isolated even under the relaxed
   bar and goes straight to `unclustered` without spending an LLM call —
   see the note below.
2. For every weak-threshold component of size 2+, generate an LLM
   structural summary for each member and ask the LLM to judge which
   members represent the same underlying pattern
   (`llm_client.LlmClient.judge_group`). An affirmed sub-group becomes a
   `formation_method: "llm_assisted"` cluster; anything not affirmed falls
   through to `unclustered`.

Isolated residue singletons (no weak-graph edge at all) never reach the LLM
in this implementation — a semantic comparison between two applications
with *zero* structural signal overlap, even at a loose 0.35 threshold, is
unlikely to be productive, and skipping it keeps LLM spend bounded to the
residue pass 1's own signal already flagged as possibly related.
23-STEP-005 Part D notes a coarse pre-filter over isolated singletons
(e.g. by primary `HOSTING_INDICATOR`) as a possible future refinement;
that's deliberately out of scope here.
"""

from __future__ import annotations

from collections import defaultdict

from .llm_client import LlmClient, LlmError
from .structural_pass import ClusterCandidate, PairwiseSimilarities, UnionFind, common_signals_for


def _weak_components(residue_ids: list[str], pairwise: PairwiseSimilarities, threshold_weak: float) -> list[list[str]]:
    uf = UnionFind(residue_ids)
    for i, a in enumerate(residue_ids):
        for b in residue_ids[i + 1 :]:
            if pairwise.get(a, b) >= threshold_weak:
                uf.union(a, b)
    groups: dict[str, list[str]] = defaultdict(list)
    for item in residue_ids:
        groups[uf.find(item)].append(item)
    return [sorted(group) for group in groups.values() if len(group) >= 2]


def _pairs(members: list[str]):
    for i, a in enumerate(members):
        for b in members[i + 1 :]:
            yield a, b


def run_llm_pass(
    residue_ids: list[str],
    app_signals: dict[str, dict[str, str]],
    signal_details: dict[str, list[dict]],
    pairwise: PairwiseSimilarities,
    *,
    threshold_weak: float,
    client: LlmClient,
) -> tuple[list[ClusterCandidate], list[str], list[dict]]:
    """Returns `(clusters, still_unclustered_ids, diagnostics)`. Never
    raises — an LLM failure on one weak-threshold component is recorded as
    a diagnostic and that component's applications fall through to
    `unclustered`; the rest of the pass continues (Part D is a best-effort
    catch-net on top of the always-on structural pass, not something step 5
    depends on to produce a result)."""
    diagnostics: list[dict] = []
    residue_ids = sorted(residue_ids)

    if not client.available:
        diagnostics.append(
            {
                "level": "info",
                "code": "LLM_PASS_SKIPPED",
                "message": "No LLM credentials configured; pass 2 skipped, all residue is unclustered.",
            }
        )
        return [], residue_ids, diagnostics

    weak_components = _weak_components(residue_ids, pairwise, threshold_weak)
    grouped_ids: set[str] = set()
    clusters: list[ClusterCandidate] = []

    for component in weak_components:
        summaries: dict[str, str] = {}
        failed = False
        for project_id in component:
            try:
                summaries[project_id] = client.summarize_application(project_id, signal_details.get(project_id, []))
            except LlmError as exc:
                diagnostics.append(
                    {"level": "warning", "code": "LLM_SUMMARY_FAILED", "message": str(exc), "ref": project_id}
                )
                failed = True
        if failed or len(summaries) < 2:
            continue

        try:
            judgment = client.judge_group(summaries)
        except LlmError as exc:
            diagnostics.append(
                {
                    "level": "warning",
                    "code": "LLM_JUDGMENT_FAILED",
                    "message": str(exc),
                    "ref": ",".join(component),
                }
            )
            continue

        for group in judgment["groups"]:
            members = sorted(group)
            clusters.append(
                ClusterCandidate(
                    members=tuple(members),
                    common_signals=tuple(common_signals_for(members, app_signals)),
                    similarity_score=min((pairwise.get(a, b) for a, b in _pairs(members)), default=0.0),
                    formation_method="llm_assisted",
                )
            )
            grouped_ids.update(members)

    still_unclustered = sorted(set(residue_ids) - grouped_ids)
    clusters.sort(key=lambda c: c.members)
    return clusters, still_unclustered, diagnostics
