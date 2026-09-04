"""Similarity model — 23-STEP-005-PATTERN-DISCOVERY.md Part C.

Weighted Jaccard over distinct signal *names* (not full signal rows —
`occurrence_count` and `evidence` are expected to differ between two
applications of the same underlying shape, so folding them in would only
add noise). Deterministic, no embeddings, no LLM in this module.
"""

from __future__ import annotations

# Method identifier recorded alongside every score this module produces, so
# a future embeddings-based method can be introduced additively rather than
# silently changing what an old `similarity_score` meant (11-STEP-CONTRACT.md's
# artifact-versioning rule, applied to a payload-internal value here).
SIMILARITY_METHOD = "weighted_jaccard_v1"

# Keyed off step 3's `signalCategory` enum (application-fingerprint-1.0.0
# .schema.json / backend/app/models.py SIGNAL_CATEGORY). Higher weight means
# more diagnostic of "what kind of application this is" — TESTING_INDICATOR
# is weighted lowest deliberately: xUnit-plus-Moq shows up on almost
# everything and says nothing about the application's shape.
DEFAULT_CATEGORY_WEIGHTS: dict[str, float] = {
    "HOSTING_INDICATOR": 2.0,
    "ENTRY_POINT": 2.0,
    "FRAMEWORK_REFERENCE": 2.0,
    "ENDPOINT_INDICATOR": 2.0,
    "PROJECT_METADATA": 1.0,
    "SOURCE_CONSTRUCT": 1.0,
    "DATA_ACCESS_INDICATOR": 1.0,
    "MESSAGING_INDICATOR": 1.0,
    "SCHEDULING_INDICATOR": 1.0,
    "EXECUTION_INDICATOR": 1.0,
    "UI_INDICATOR": 1.0,
    "PACKAGE_DEPENDENCY": 0.75,
    "CONFIGURATION_INDICATOR": 0.75,
    "FILE_INDICATOR": 0.75,
    "DEPLOYMENT_INDICATOR": 0.75,
    "TESTING_INDICATOR": 0.25,
}

# A category outside the table above (e.g. a future signal category this
# module hasn't been taught about yet) falls back to this weight rather than
# raising — see the docstring on `weighted_jaccard` for why 1.0 (neutral,
# same as most of the table) is the right default rather than 0.0 (silently
# erasing it) or refusing to score the pair.
_FALLBACK_WEIGHT = 1.0


def signal_category_weight(category: str, weights: dict[str, float] = DEFAULT_CATEGORY_WEIGHTS) -> float:
    return weights.get(category, _FALLBACK_WEIGHT)


def weighted_jaccard(
    signals_a: dict[str, str],
    signals_b: dict[str, str],
    *,
    weights: dict[str, float] = DEFAULT_CATEGORY_WEIGHTS,
) -> float:
    """`signals_a` / `signals_b` map this application's distinct signal
    names to their category (one entry per distinct `signal_name` — callers
    are responsible for having already deduplicated per application, e.g.
    via `persistence.load_application_signals`).

    sim(A, B) = Σ weight(category(s)) for s in (SigA ∩ SigB)
              / Σ weight(category(s)) for s in (SigA ∪ SigB)

    A signal name is expected to map to the same category from both
    applications (it comes from the same step 3 signal registry either
    way); when it doesn't — or when only one side carries the name — the
    category recorded by whichever side has it is used, preferring `A`.

    Two applications with no signals at all are defined as similarity 0.0,
    not 1.0 — "nothing in common because nothing was observed" must never
    be mistaken for "identical", or a pair of totally unscanned/empty
    applications would silently masquerade as a perfect match.
    """
    names_a = set(signals_a)
    names_b = set(signals_b)
    union = names_a | names_b
    if not union:
        return 0.0

    category_of = {**signals_b, **signals_a}  # A wins on conflict
    intersection = names_a & names_b

    union_weight = sum(signal_category_weight(category_of[name], weights) for name in union)
    if union_weight == 0.0:
        return 0.0

    intersection_weight = sum(signal_category_weight(category_of[name], weights) for name in intersection)
    return intersection_weight / union_weight


def common_signal_names(signals_a: dict[str, str], signals_b: dict[str, str]) -> set[str]:
    """The pairwise intersection — used by callers building up a cluster's
    `common_signals` as the running intersection across every member
    (Part E: "the intersection across members, not the union")."""
    return set(signals_a) & set(signals_b)
