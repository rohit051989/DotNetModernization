"""Bridges the two clustering passes' raw output into DB/artifact-ready
rows. 23-STEP-005-PATTERN-DISCOVERY.md Part E (data model) and Part D
(review_priority, replacing the original `requires_human_validation` flag).
"""

from __future__ import annotations

from .similarity import SIMILARITY_METHOD
from .structural_pass import DEFAULT_THRESHOLD_STRONG, DEFAULT_THRESHOLD_WEAK, ClusterCandidate, PairwiseSimilarities

REVIEW_PRIORITY_HIGH_MEMBER_COUNT = 5


def review_priority_for(
    member_count: int,
    similarity_score: float | None,
    *,
    threshold_weak: float = DEFAULT_THRESHOLD_WEAK,
    threshold_strong: float = DEFAULT_THRESHOLD_STRONG,
) -> str:
    """`high` when the cluster is either large enough to be a meaningful
    accelerator candidate (`member_count >= 5`) or its similarity score
    landed in the ambiguous band between the weak and strong thresholds —
    a borderline call worth a reviewer's attention first. `unclustered`
    rows (`similarity_score is None`) are always `standard`."""
    if member_count >= REVIEW_PRIORITY_HIGH_MEMBER_COUNT:
        return "high"
    if similarity_score is not None and threshold_weak <= similarity_score < threshold_strong:
        return "high"
    return "standard"


def _member_similarities(members: list[str], pairwise: PairwiseSimilarities) -> dict[str, float | None]:
    if len(members) < 2:
        return {members[0]: None} if members else {}
    return {m: min(pairwise.get(m, o) for o in members if o != m) for m in members}


def assemble_rows(
    engagement_id: str,
    clusters: list[ClusterCandidate],
    unclustered_ids: list[str],
    pairwise: PairwiseSimilarities,
    *,
    threshold_weak: float = DEFAULT_THRESHOLD_WEAK,
    threshold_strong: float = DEFAULT_THRESHOLD_STRONG,
) -> list[dict]:
    """Assigns `CAND-{engagement_id}-{seq:04d}` ids across *every* output
    row — candidate patterns and unclustered residue share one sequence
    space (see the worked example in Part F) — in one deterministic order,
    sorted by member project ids, so re-running against unchanged input
    reproduces identical ids and membership (11-STEP-CONTRACT.md
    obligation 1: idempotent).
    """
    groups: list[tuple[str, ...]] = []
    kind_by_group: dict[tuple[str, ...], ClusterCandidate | None] = {}
    for cluster in clusters:
        groups.append(cluster.members)
        kind_by_group[cluster.members] = cluster
    for project_id in unclustered_ids:
        key = (project_id,)
        groups.append(key)
        kind_by_group[key] = None

    groups.sort()

    rows: list[dict] = []
    for seq, members in enumerate(groups, start=1):
        cluster = kind_by_group[members]
        candidate_id = f"CAND-{engagement_id}-{seq:04d}"
        if cluster is None:
            rows.append(
                {
                    "id": candidate_id,
                    "status": "unclustered",
                    "formation_method": None,
                    "members": list(members),
                    "common_signals": [],
                    "similarity_score": None,
                    "similarity_method": SIMILARITY_METHOD,
                    "review_priority": "standard",
                    "member_similarities": _member_similarities(list(members), pairwise),
                }
            )
        else:
            rows.append(
                {
                    "id": candidate_id,
                    "status": "candidate_pattern",
                    "formation_method": cluster.formation_method,
                    "members": list(cluster.members),
                    "common_signals": [dict(s) for s in cluster.common_signals],
                    "similarity_score": cluster.similarity_score,
                    "similarity_method": SIMILARITY_METHOD,
                    "review_priority": review_priority_for(
                        len(cluster.members),
                        cluster.similarity_score,
                        threshold_weak=threshold_weak,
                        threshold_strong=threshold_strong,
                    ),
                    "member_similarities": _member_similarities(list(cluster.members), pairwise),
                }
            )
    return rows
