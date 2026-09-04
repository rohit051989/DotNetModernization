"""Artifact `pattern-discovery-clusters@1.0.0` —
23-STEP-005-PATTERN-DISCOVERY.md Part F. snake_case, mirroring the DB rows
`persistence.py` writes — a deliberate, documented departure from step 3's
camelCase `application-fingerprint` artifact (payload casing is a
per-artifact choice, not a platform-wide rule per 11-STEP-CONTRACT.md, and
this artifact exists mainly to checksum what the step wrote to
`pattern_discovery_clusters` / `pattern_discovery_cluster_members`, so
matching the table shape wins over matching step 3's)."""

from __future__ import annotations

from .similarity import DEFAULT_CATEGORY_WEIGHTS, SIMILARITY_METHOD
from .structural_pass import DEFAULT_THRESHOLD_STRONG, DEFAULT_THRESHOLD_WEAK

ARTIFACT_TYPE = "pattern-discovery-clusters"
ARTIFACT_VERSION = "1.0.0"


def build_artifact(
    engagement_id: str,
    rows: list[dict],
    *,
    unmatched_input_count: int,
    threshold_strong: float = DEFAULT_THRESHOLD_STRONG,
    threshold_weak: float = DEFAULT_THRESHOLD_WEAK,
    category_weights: dict[str, float] = DEFAULT_CATEGORY_WEIGHTS,
) -> dict:
    clusters = []
    structural_count = 0
    llm_assisted_count = 0
    candidate_pattern_count = 0
    unclustered_count = 0

    for row in sorted(rows, key=lambda r: r["id"]):
        clusters.append(
            {
                "candidate_id": row["id"],
                "status": row["status"],
                "formation_method": row["formation_method"],
                "applications": list(row["members"]),
                "common_signals": row["common_signals"],
                "similarity_score": row["similarity_score"],
                "review_priority": row["review_priority"],
            }
        )
        if row["status"] == "candidate_pattern":
            candidate_pattern_count += 1
            if row["formation_method"] == "structural":
                structural_count += 1
            elif row["formation_method"] == "llm_assisted":
                llm_assisted_count += 1
        else:
            unclustered_count += 1

    return {
        "artifact_type": ARTIFACT_TYPE,
        "artifact_version": ARTIFACT_VERSION,
        "engagement_id": engagement_id,
        "similarity_method": SIMILARITY_METHOD,
        "config": {
            "threshold_strong": threshold_strong,
            "threshold_weak": threshold_weak,
            "category_weights": category_weights,
        },
        "clusters": clusters,
        "summary": {
            "unmatched_input_count": unmatched_input_count,
            "candidate_pattern_count": candidate_pattern_count,
            "unclustered_count": unclustered_count,
            "structural_cluster_count": structural_count,
            "llm_assisted_cluster_count": llm_assisted_count,
        },
    }
