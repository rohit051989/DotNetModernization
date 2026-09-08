"""Project role determination — 24-STEP-004-CLASSIFICATION.md Part D. A
first pass over `classification_role: PROJECT_ROLE` patterns, using the same
rule engine as everything else. Highest score wins; ties break on priority."""

from . import rules


def resolve_role(role_patterns: list[dict], signals_by_name: dict, project_metadata: dict) -> dict | None:
    best = None  # (score, priority, pattern, outcome)
    matched_pattern_ids: list[str] = []
    for pattern in role_patterns:
        outcome = rules.evaluate_ruleset(pattern["detection_rules"], signals_by_name, project_metadata)
        score = rules.score_outcome(outcome)
        if score < pattern["thresholds"]["minimumScore"]:
            continue
        # Every role pattern that cleared its threshold, not just the winner.
        # Coverage needs this: role-unknown always matches and never wins
        # (priority 0), so counting winners only put the deliberate
        # always-matching fallback in never_matched_pattern_ids.
        matched_pattern_ids.append(pattern["id"])
        key = (score, pattern["priority"])
        if best is None or key > (best[0], best[1]):
            best = (score, pattern["priority"], pattern, outcome)

    if best is None:
        # role-unknown's empty ruleset always scores >= its own threshold, so
        # this only happens if that pattern is missing or misconfigured.
        return None

    score, _priority, pattern, outcome = best
    return {
        "value": pattern["classification_value"],
        "confidence": score / 100.0,
        "pattern_id": pattern["id"],
        "score": score,
        "outcome": outcome,
        "matched_pattern_ids": sorted(matched_pattern_ids),
    }
