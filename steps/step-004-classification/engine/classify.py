"""Top-level per-project orchestration — 24-STEP-004-CLASSIFICATION.md Part E
'Primary versus secondary', 'Conflict rejection' and 'Status resolution'.
"""

import itertools

from . import confidence as conf
from . import role as role_engine
from . import rules


def _conflicts(pattern_a: dict, pattern_b: dict) -> bool:
    return (
        pattern_b["id"] in pattern_a.get("conflicts_with", [])
        or pattern_a["id"] in pattern_b.get("conflicts_with", [])
    )


def classify_project(project: dict, patterns: list[dict], config: dict) -> dict:
    """
    `project` — {fingerprint_status, analysis_capabilities, metadata,
    signals_by_name}. `patterns` — catalog rows with `detection_rules`
    already positional-id-assigned. Returns a dict matching the shapes
    `main.py` persists to `project_classifications` / `classification_matches`.
    """
    try:
        return _classify_project(project, patterns, config)
    except Exception as exc:  # Part E status 8 — engine error, never a crash.
        return {
            "classification_status": "CLASSIFICATION_FAILED",
            "project_role": None,
            "project_role_confidence": None,
            "role_pattern_id": None,
            "role_patterns_evaluated": [],
            "evaluated_pattern_count": 0,
            "primary_pattern_id": None,
            "matches": [],
            "warnings": [
                {"code": "CLASSIFICATION_FAILED", "severity": "error", "message": f"{type(exc).__name__}: {exc}"}
            ],
        }


def _classify_project(project: dict, patterns: list[dict], config: dict) -> dict:
    warnings: list[dict] = []

    if project["fingerprint_status"] == "SKIPPED":
        return {
            "classification_status": "SKIPPED",
            "project_role": None,
            "project_role_confidence": None,
            "role_pattern_id": None,
            "role_patterns_evaluated": [],
            "evaluated_pattern_count": 0,
            "primary_pattern_id": None,
            "matches": [],
            "warnings": warnings,
        }

    role_patterns = [p for p in patterns if p["classification_role"] == "PROJECT_ROLE"]
    application_patterns = [p for p in patterns if p["classification_role"] != "PROJECT_ROLE"]

    role_result = role_engine.resolve_role(role_patterns, project["signals_by_name"], project["metadata"])
    project_role = role_result["value"] if role_result else None
    project_role_confidence = role_result["confidence"] if role_result else None

    evaluated_count = 0
    eligible_primary_count = 0
    role_excluded_primary_count = 0
    matches: list[dict] = []

    for pattern in application_patterns:
        if pattern["scope"] == "REPOSITORY":
            # Part A8: v1 evaluates PROJECT scope only.
            warnings.append(
                {
                    "code": "REPOSITORY_SCOPED_PATTERN_SKIPPED",
                    "severity": "info",
                    "message": f"Pattern '{pattern['id']}' is REPOSITORY-scoped; skipped (v1 evaluates PROJECT scope only).",
                }
            )
            continue
        if pattern["rules_status"] != "active":
            continue  # never evaluated, per Part B3

        eligibility = pattern.get("eligibility") or {}
        allowed_statuses = eligibility.get("fingerprintStatuses") or []
        if allowed_statuses and project["fingerprint_status"] not in allowed_statuses:
            continue  # this fingerprint status is out of scope for this pattern entirely

        excluded_roles = eligibility.get("excludedProjectRoles") or []
        role_excluded = project_role is not None and project_role in excluded_roles

        evaluated_count += 1
        if pattern["classification_role"] == "PRIMARY":
            eligible_primary_count += 1
            if role_excluded:
                role_excluded_primary_count += 1

        outcome = rules.evaluate_ruleset(pattern["detection_rules"], project["signals_by_name"], project["metadata"])
        score = rules.score_outcome(outcome)
        matched = (not outcome.disqualified) and score >= pattern["thresholds"]["minimumScore"]
        cap_factor, required_missing = conf.capability_factor(
            pattern.get("analysis_requirements"), project["analysis_capabilities"], config
        )

        matches.append(
            {
                "pattern": pattern,
                "outcome": outcome,
                "score": score,
                "matched": matched,
                "role_excluded": role_excluded,
                "capability_factor": cap_factor,
                "required_capability_missing": required_missing,
                "is_primary_selected": False,
                "rejection_reason": None,
            }
        )

    # PRIMARY candidates: matched, not role-excluded, capability-sufficient.
    primary_candidates = [
        m
        for m in matches
        if m["pattern"]["classification_role"] == "PRIMARY"
        and m["matched"]
        and not m["role_excluded"]
        and not m["required_capability_missing"]
    ]

    # Ambiguity factor needs every other conflicting candidate's score, so
    # confidence is computed only after every pattern has been scored.
    for m in matches:
        conflicting_scores = [
            other["score"] for other in primary_candidates if other is not m and _conflicts(m["pattern"], other["pattern"])
        ]
        amb_factor = conf.ambiguity_factor(m["score"], conflicting_scores, config)
        m["confidence"] = conf.compute_confidence(
            m["score"],
            project["fingerprint_status"],
            m["outcome"].matched_signal_rows,
            m["capability_factor"],
            amb_factor,
            config,
        )
        m["confidence_level"] = conf.confidence_level(m["confidence"], config)

    # Conflict rejection among primary candidates (Part E). Pairwise — the
    # catalog has no conflict chains longer than two, and this reads clearly
    # for that shape; revisit if a three-way conflict cluster is ever added.
    margin = config["ambiguityMargin"]
    rejected_ids: set[str] = set()
    sorted_candidates = sorted(primary_candidates, key=lambda m: -m["score"])
    for i, higher in enumerate(sorted_candidates):
        if higher["pattern"]["id"] in rejected_ids:
            continue
        for lower in sorted_candidates[i + 1 :]:
            if lower["pattern"]["id"] in rejected_ids:
                continue
            if not _conflicts(higher["pattern"], lower["pattern"]):
                continue
            gap = higher["score"] - lower["score"]
            if gap > margin:
                rejected_ids.add(lower["pattern"]["id"])
                lower["rejection_reason"] = (
                    f"Rejected in favour of '{higher['pattern']['id']}' "
                    f"(score {higher['score']} vs {lower['score']}, gap {gap} exceeds the "
                    f"ambiguity margin of {margin})."
                )

    surviving = [m for m in sorted_candidates if m["pattern"]["id"] not in rejected_ids]

    ambiguous = any(
        _conflicts(a["pattern"], b["pattern"]) and abs(a["score"] - b["score"]) <= margin
        for a, b in itertools.combinations(surviving, 2)
    )

    primary_pattern_id = None
    if ambiguous:
        classification_status = "AMBIGUOUS"
    elif len(surviving) >= 2:
        classification_status = "MULTIPLE_MATCHES"
        for m in surviving:
            m["is_primary_selected"] = True
    elif len(surviving) == 1:
        classification_status = "MATCHED"
        surviving[0]["is_primary_selected"] = True
        primary_pattern_id = surviving[0]["pattern"]["id"]
    else:
        # No surviving candidate. Distinguish role exclusion / insufficient
        # fingerprint / genuine no-match, per Part E status resolution 2-3, 7.
        if eligible_primary_count > 0 and role_excluded_primary_count == eligible_primary_count:
            classification_status = "NOT_ELIGIBLE"
        else:
            non_excluded_evaluated = [
                m
                for m in matches
                if m["pattern"]["classification_role"] == "PRIMARY" and not m["role_excluded"]
            ]
            if non_excluded_evaluated and all(m["required_capability_missing"] for m in non_excluded_evaluated):
                classification_status = "INSUFFICIENT_FINGERPRINT"
            else:
                classification_status = "NO_PATTERN_MATCHED"

    return {
        "classification_status": classification_status,
        "project_role": project_role,
        "project_role_confidence": project_role_confidence,
        "role_pattern_id": role_result["pattern_id"] if role_result else None,
        "role_patterns_evaluated": [p["id"] for p in role_patterns],
        "evaluated_pattern_count": evaluated_count,
        "primary_pattern_id": primary_pattern_id,
        "matches": matches,
        "warnings": warnings,
    }
