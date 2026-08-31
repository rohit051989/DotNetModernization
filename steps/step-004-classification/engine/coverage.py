"""Catalog governance metrics — step-4-pattern-classification-against-catalog.md
section 18, plus Part B2's 'group pending signals by expected extractor' and
Part F's 'most frequent unmatched signal combinations'."""

from collections import Counter, defaultdict


def _referenced_signal_names(pattern: dict) -> set[str]:
    names = set(pattern.get("anchor_signals") or [])
    ruleset = pattern["detection_rules"]
    for group in ("all", "any", "supporting", "none"):
        for condition in ruleset.get(group, []):
            names.add(condition["signal"]["name"])
    for group in ruleset.get("atLeast", []):
        for condition in group.get("of", []):
            names.add(condition["signal"]["name"])
    return names


def build_coverage_report(
    patterns: list[dict],
    project_results: list[dict],
    registered_signal_names: frozenset[str],
    catalog_version: str,
    catalog_revision: int,
    signal_registry_version: str | None,
) -> dict:
    active_patterns = [p for p in patterns if p["rules_status"] == "active"]

    referenced: set[str] = set()
    for pattern in patterns:
        referenced |= _referenced_signal_names(pattern)

    evaluated_ids: set[str] = set()
    matched_ids: set[str] = set()
    unmatched_combinations: Counter[tuple[str, ...]] = Counter()
    for result in project_results:
        for m in result["matches"]:
            pattern = m["pattern"]
            evaluated_ids.add(pattern["id"])
            if m["matched"]:
                matched_ids.add(pattern["id"])
            elif pattern["anchor_signals"]:
                unmatched_combinations[tuple(sorted(pattern["anchor_signals"]))] += 1
        # Role patterns (Part D) are evaluated in their own first pass, never
        # added to `matches` — track them here so they don't read as "never
        # matched" just because they live in a separate code path.
        evaluated_ids.update(result.get("role_patterns_evaluated") or [])
        if result.get("role_pattern_id"):
            matched_ids.add(result["role_pattern_id"])

    never_matched = sorted(p["id"] for p in active_patterns if p["id"] not in matched_ids)

    awaiting_by_extractor: dict[str, list[str]] = defaultdict(list)
    for pattern in patterns:
        if pattern["rules_status"] != "awaiting_signals":
            continue
        for pending in pattern.get("required_signals_pending") or []:
            awaiting_by_extractor[pending["expected_extractor"]].append(pattern["id"])
    for extractor in awaiting_by_extractor:
        awaiting_by_extractor[extractor] = sorted(set(awaiting_by_extractor[extractor]))

    return {
        "catalog_version": catalog_version,
        "catalog_revision": catalog_revision,
        "signal_registry_version": signal_registry_version,
        "registered_signal_count": len(registered_signal_names),
        "referenced_signal_count": len(referenced & registered_signal_names),
        "unreferenced_signal_count": len(registered_signal_names - referenced),
        "active_pattern_count": len(active_patterns),
        "evaluated_pattern_count": len(evaluated_ids),
        "matched_pattern_count": len(matched_ids),
        "never_matched_pattern_ids": never_matched,
        "patterns_awaiting_signals_by_extractor": dict(awaiting_by_extractor),
        "most_frequent_unmatched_signal_combinations": [
            {"anchor_signals": list(combo), "count": count}
            for combo, count in unmatched_combinations.most_common(5)
        ],
    }
