"""Pass 1 — structural clustering. 23-STEP-005-PATTERN-DISCOVERY.md Part D.

Always runs, no LLM. Builds a similarity graph over every candidate
application using `similarity.weighted_jaccard`, connects an edge wherever
the score is at or above `threshold_strong`, and takes connected components
as clusters. Every component with 2+ members becomes a structural
candidate pattern; every singleton is residue handed to pass 2
(`llm_pass.py`).

Pure and deterministic — no I/O, no randomness, no LLM calls — so it is
trivially unit-testable and, per 11-STEP-CONTRACT.md obligation 1
(idempotent), always produces the same clusters for the same input.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass, field

from .similarity import DEFAULT_CATEGORY_WEIGHTS, weighted_jaccard

DEFAULT_THRESHOLD_STRONG = 0.6
DEFAULT_THRESHOLD_WEAK = 0.35


@dataclass(frozen=True)
class PairwiseSimilarities:
    """Every application pair's score, computed once and reused by both
    pass 1 (at `threshold_strong`) and pass 2 (at `threshold_weak`) so the
    O(n^2) weighted-Jaccard pass only ever runs a single time per
    execution."""

    scores: dict[frozenset, float] = field(default_factory=dict)

    def get(self, a: str, b: str) -> float:
        if a == b:
            return 1.0
        return self.scores.get(frozenset((a, b)), 0.0)


def compute_pairwise(
    app_signals: dict[str, dict[str, str]],
    *,
    weights: dict[str, float] = DEFAULT_CATEGORY_WEIGHTS,
) -> PairwiseSimilarities:
    ids = sorted(app_signals)
    scores: dict[frozenset, float] = {}
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            scores[frozenset((a, b))] = weighted_jaccard(app_signals[a], app_signals[b], weights=weights)
    return PairwiseSimilarities(scores)


class UnionFind:
    """Textbook union-find with path compression. Boring on purpose — this
    is the entire "clustering algorithm"; no external graph library needed
    for a few hundred nodes."""

    def __init__(self, items: list[str]) -> None:
        self._parent = {item: item for item in items}

    def find(self, x: str) -> str:
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


def connected_components(ids: list[str], pairwise: PairwiseSimilarities, threshold: float) -> list[set[str]]:
    uf = UnionFind(ids)
    for pair, score in pairwise.scores.items():
        if score >= threshold:
            a, b = tuple(pair)
            uf.union(a, b)
    groups: dict[str, set[str]] = defaultdict(set)
    for item in ids:
        groups[uf.find(item)].add(item)
    return list(groups.values())


@dataclass(frozen=True)
class ClusterCandidate:
    """One candidate pattern (2+ members). `formation_method` is set by the
    caller — `structural_pass` always produces `"structural"`;
    `llm_pass` reuses this same shape for `"llm_assisted"` results."""

    members: tuple[str, ...]  # project_id strings, sorted — the DB/artifact join key
    common_signals: tuple[dict, ...]  # [{"name", "category"}], intersection across every member
    similarity_score: float  # minimum pairwise similarity within the cluster (Part E — the weakest link)
    formation_method: str


def common_signals_for(members: list[str], app_signals: dict[str, dict[str, str]]) -> list[dict]:
    """The intersection of every member's distinct signal-name set — Part E:
    "the intersection across members, not the union or one representative's
    signals". Deterministically ordered by signal name."""
    common: set[str] | None = None
    category_of: dict[str, str] = {}
    for member in members:
        names = set(app_signals[member])
        common = names if common is None else (common & names)
        category_of.update(app_signals[member])
    common = common or set()
    return [{"name": name, "category": category_of[name]} for name in sorted(common)]


def minimum_pairwise_similarity(members: list[str], pairwise: PairwiseSimilarities) -> float:
    scores = [pairwise.get(a, b) for a, b in itertools.combinations(members, 2)]
    return min(scores) if scores else 0.0


def run_structural_pass(
    app_signals: dict[str, dict[str, str]],
    *,
    threshold_strong: float = DEFAULT_THRESHOLD_STRONG,
    weights: dict[str, float] = DEFAULT_CATEGORY_WEIGHTS,
) -> tuple[list[ClusterCandidate], list[str], PairwiseSimilarities]:
    """Returns `(clusters, residue_ids, pairwise)`.

    `residue_ids` are the applications with no edge at `threshold_strong` —
    candidates for pass 2 (`llm_pass.run_llm_pass`), which reuses `pairwise`
    to find weak-threshold groupings among them without recomputing
    similarity scores.
    """
    ids = sorted(app_signals)
    pairwise = compute_pairwise(app_signals, weights=weights)
    components = connected_components(ids, pairwise, threshold_strong)

    clusters: list[ClusterCandidate] = []
    residue: list[str] = []
    for group in components:
        if len(group) < 2:
            residue.extend(group)
            continue
        members = sorted(group)
        clusters.append(
            ClusterCandidate(
                members=tuple(members),
                common_signals=tuple(common_signals_for(members, app_signals)),
                similarity_score=minimum_pairwise_similarity(members, pairwise),
                formation_method="structural",
            )
        )

    # Deterministic ordering — obligation 1 (idempotent): the same input
    # must yield the same cluster list in the same order every run, since
    # candidate_id assignment (persistence.assign_candidate_ids) numbers
    # clusters in the order it receives them.
    clusters.sort(key=lambda c: c.members)
    residue.sort()
    return clusters, residue, pairwise
