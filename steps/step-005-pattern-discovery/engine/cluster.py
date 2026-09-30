"""Two-pass clustering — 26-STEP-005-PATTERN-DISCOVERY.md Part C.

Both passes are deterministic and order-independent, which is what lets
Part F assert a stable checksum across runs.
"""

from . import signature as sig

# Part A4. AMBIGUOUS is in because recurring ambiguity usually means a
# missing discriminating pattern rather than a genuine tie.
# INSUFFICIENT_FINGERPRINT is out because clustering broken scans invents
# phantom patterns — it is why step 4 separates that status from
# NO_PATTERN_MATCHED at all.
ELIGIBLE_STATUSES = ("NO_PATTERN_MATCHED", "AMBIGUOUS")


def _connected_components(node_ids: list[str], edges: dict[str, set[str]]) -> list[list[str]]:
    """Order-independent by construction: nodes are visited in sorted
    order and each component is sorted before return, so the same graph
    always yields the same components in the same order regardless of how
    the edges were discovered."""
    seen: set[str] = set()
    components: list[list[str]] = []
    for node in sorted(node_ids):
        if node in seen:
            continue
        stack, component = [node], []
        seen.add(node)
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbour in sorted(edges.get(current, ())):
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        components.append(sorted(component))
    return components


def _cohesion(members: list[dict]) -> float:
    """Minimum pairwise Jaccard among members.

    Connected components chain: A similar to B, B to C, A not to C, all
    in one cluster. Rather than adopt a more restrictive linkage, Part C
    records it — a chained cluster carries visibly low cohesion, so the
    weakness is in front of the human at step 6 instead of hidden by the
    algorithm.
    """
    if len(members) < 2:
        return 1.0
    worst = 1.0
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            worst = min(worst, sig.jaccard(members[i]["signal_set"], members[j]["signal_set"]))
    return worst


def build_clusters(projects: list[dict], config: dict) -> list[dict]:
    """`projects` are the eligible ones, each with signal_set, facets,
    project_id, repository_id, repository_slug, project_path,
    classification_status, classification_step_execution_id.

    Returns clusters sorted by cluster_id, members sorted by project path.
    """
    threshold = config["similarity_threshold"]
    facet_mode = config["facet_mode"]
    min_cluster_size = config["min_cluster_size"]

    by_id = {p["project_id"]: p for p in projects}
    ids = sorted(by_id)

    # Pass 2 subsumes pass 1: an identical pair scores Jaccard 1.0, which
    # clears any threshold <= 1.0, so exact groups fall out as components
    # too. The passes are still distinguished in the output, because
    # `cluster_method` tells the human whether they are looking at one
    # shape or several merged ones, and that changes how much the
    # signature can be trusted as a pattern definition.
    edges: dict[str, set[str]] = {i: set() for i in ids}
    for a_idx in range(len(ids)):
        for b_idx in range(a_idx + 1, len(ids)):
            a, b = by_id[ids[a_idx]], by_id[ids[b_idx]]
            if not sig.facets_agree(a["facets"], b["facets"], facet_mode):
                continue
            if sig.jaccard(a["signal_set"], b["signal_set"]) >= threshold:
                edges[a["project_id"]].add(b["project_id"])
                edges[b["project_id"]].add(a["project_id"])

    clusters = []
    for component in _connected_components(ids, edges):
        members = [by_id[pid] for pid in component]
        signal_sets = [m["signal_set"] for m in members]
        is_exact = all(s == signal_sets[0] for s in signal_sets) and all(
            sig.facets_agree(members[0]["facets"], m["facets"], "strict") for m in members
        )

        # Part B: for a similarity cluster the canonical signature is the
        # INTERSECTION of member signal sets — the shape they actually
        # share. Using the union would define the cluster by signals some
        # members do not have, and the id would then move whenever a
        # member with an extra signal joined or left.
        shared = set.intersection(*signal_sets) if signal_sets else set()
        # Under `strict` every member agrees, so any member's facets are the
        # cluster's. Under `signals_only` facets did not constrain grouping,
        # so members may disagree and the cluster is not defined by them —
        # recording one member's values would make the id depend on which
        # member happened to sort first.
        if facet_mode == "strict":
            facet_values = members[0]["facets"]
        else:
            facet_values = {
                f: (members[0]["facets"].get(f) if len({m["facets"].get(f) for m in members}) == 1 else None)
                for f in sig.FACET_FIELDS
            }
        canonical = sig.canonical_signature(facet_values, sorted(shared))
        cid = sig.cluster_id(canonical)

        member_payload = []
        for m in members:
            member_payload.append(
                {
                    "project_id": m["project_id"],
                    "repository_id": m["repository_id"],
                    "repository_slug": m["repository_slug"],
                    "project_path": m["project_path"],
                    "classification_status": m["classification_status"],
                    "classification_step_execution_id": m["classification_step_execution_id"],
                    "similarity_to_signature": round(sig.jaccard(m["signal_set"], shared), 3),
                    "signal_count": len(m["signal_set"]),
                }
            )
        member_payload.sort(key=lambda x: (x["repository_slug"], x["project_path"]))

        distribution: dict[str, int] = {}
        for m in member_payload:
            distribution[m["repository_slug"]] = distribution.get(m["repository_slug"], 0) + 1

        clusters.append(
            {
                "cluster_id": cid,
                "cluster_method": "exact" if is_exact else "similarity",
                "canonical_signature": canonical,
                "signal_count": len(shared),
                "member_count": len(member_payload),
                "repository_count": len(distribution),
                "repository_distribution": dict(sorted(distribution.items())),
                "cohesion": round(_cohesion(members), 3),
                # Part C "Singletons": a one-off is not a pattern, but it is
                # still something a human should see — and a singleton today
                # may gain members when the next repository is scanned, at
                # which point it keeps this same cluster_id.
                "is_singleton": len(member_payload) < min_cluster_size,
                "members": member_payload,
            }
        )

    clusters.sort(key=lambda c: c["cluster_id"])
    return clusters


def pattern_proximity(clusters: list[dict], pattern_signal_sets: dict[str, set[str]], config: dict) -> None:
    """Part C "Existing-pattern proximity" — annotates each cluster in
    place with its top matches against active catalog patterns.

    This feeds step 6's "merge into existing pattern" action directly: the
    human sees *"this cluster is 0.62 similar to console-batch-job"*
    rather than deciding blind. It also surfaces the most common real
    cause of a cluster existing at all — an existing pattern being
    slightly too narrow.
    """
    threshold = config["proximity_threshold"]
    top_n = config["proximity_top_n"]
    for cluster in clusters:
        shape = set(cluster["canonical_signature"]["signals"])
        scored = []
        # An empty shape has no evidence to compare, so it is not "similar"
        # to anything — jaccard's empty-union convention returns 1.0, which
        # is the right answer for clustering (two signal-less projects ARE
        # the same shape) and a meaningless one here. Without this guard a
        # signal-less cluster reports a perfect match against every
        # metadata-only pattern, e.g. ssis-package, whose anchor_signals are
        # deliberately empty.
        if shape:
            for pattern_id, pattern_signals in pattern_signal_sets.items():
                if not pattern_signals:
                    continue
                score = sig.jaccard(shape, pattern_signals)
                if score >= threshold:
                    scored.append({"pattern_id": pattern_id, "similarity": round(score, 3)})
        # Sort by score desc then id asc, so ties are broken deterministically
        # rather than by dict iteration order.
        scored.sort(key=lambda x: (-x["similarity"], x["pattern_id"]))
        cluster["similar_patterns"] = scored[:top_n]
