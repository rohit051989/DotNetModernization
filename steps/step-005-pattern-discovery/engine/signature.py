"""Structural signature and cluster identity — 26-STEP-005-PATTERN-DISCOVERY.md
Part B. Pure functions, no I/O, so the corpus exercises them directly.
"""

import hashlib
import json

# Part B "Facets". Framework *version* is deliberately absent: family
# discriminates, version parameterises (the principle established in
# 24-STEP-004-CLASSIFICATION.md Part C). Two projects differing only in
# patch version are the same shape and must land in the same cluster.
FACET_FIELDS = ("project_role", "framework_family", "output_type", "structural_type")


def core_signature(signal_rows: list[dict], min_signal_confidence: float) -> list[str]:
    """The sorted set of distinct signal names present on a project.

    Presence, not occurrence count: a project with three
    HTTP_GET_ATTRIBUTE occurrences and one with twenty are the same shape.
    Signals below `min_signal_confidence` are dropped so low-confidence
    noise does not drive clustering.
    """
    return sorted(
        {
            row["signal_name"]
            for row in signal_rows
            if (row["extraction_confidence"] is None or float(row["extraction_confidence"]) >= min_signal_confidence)
        }
    )


def facets(project_row: dict) -> dict:
    return {field: project_row.get(field) for field in FACET_FIELDS}


def canonical_signature(facet_values: dict, signals: list[str]) -> dict:
    """The shape, in the exact form that gets hashed. Sorted keys, sorted
    arrays — Part B "Cluster identity"."""
    return {
        "facets": {k: facet_values.get(k) for k in sorted(FACET_FIELDS)},
        "signals": sorted(signals),
    }


def cluster_id(signature: dict) -> str:
    """sha256(canonical_signature)[:12].

    Derived from the **shape**, not from membership. That is the entire
    accumulation mechanism (Part D): the same shape in a later run hashes
    to the same id, resolves to the same row, and inherits step 6's
    decision instead of re-asking it. Anything membership-dependent must
    stay out of this hash — including member count, repository
    distribution and cohesion, all of which legitimately change run to
    run for a cluster that is still the same shape.
    """
    payload = json.dumps(signature, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def jaccard(a: set[str], b: set[str]) -> float:
    """|A ∩ B| / |A ∪ B|. Deterministic, no vectors, no ML, and directly
    explainable to a human: "these two projects share 8 of 11 signals."

    Two projects with no signals at all are identical shapes, not
    undefined ones — an empty union returns 1.0 rather than dividing by
    zero. They will already have grouped exactly in pass 1.
    """
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def facets_agree(a: dict, b: dict, facet_mode: str) -> bool:
    if facet_mode == "signals_only":
        return True
    return all(a.get(f) == b.get(f) for f in FACET_FIELDS)
