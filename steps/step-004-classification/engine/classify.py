"""Top-level per-project orchestration — 24-STEP-004-CLASSIFICATION.md Part E
'Primary versus secondary', 'Conflict rejection' and 'Status resolution'.
"""

import itertools

from . import confidence as conf
from . import role as role_engine
from . import rules


def _relationship(pattern_a: dict, pattern_b: dict) -> tuple[str, str]:
    """('conflicting' | 'compatible', 'declared' | 'defaulted') — checked
    symmetrically since either pattern's catalog entry may declare it.
    Part E: an undeclared relationship (absent from both patterns'
    compatible_with and conflicts_with) defaults to CONFLICTING, never
    compatible — defaulting to compatible would silently assert a project is
    two things at once; defaulting to conflicting forces a human look."""
    if pattern_b["id"] in pattern_a.get("conflicts_with", []) or pattern_a["id"] in pattern_b.get("conflicts_with", []):
        return "conflicting", "declared"
    if pattern_b["id"] in pattern_a.get("compatible_with", []) or pattern_a["id"] in pattern_b.get("compatible_with", []):
        return "compatible", "declared"
    return "conflicting", "defaulted"


def _is_conflicting(pattern_a: dict, pattern_b: dict) -> bool:
    return _relationship(pattern_a, pattern_b)[0] == "conflicting"


def candidate_application_patterns(patterns: list[dict]) -> list[dict]:
    """Every non-role pattern in the active catalog, unfiltered — candidate
    selection is a **full scan**, and that is load-bearing rather than
    incidental.

    Part B1 describes `anchor_signals` as being "for the inverted index",
    and a signal-keyed index is the obvious optimisation: evaluate only
    those patterns whose anchor signals the project actually emitted. It has
    never been built — nothing reads `anchor_signals` at evaluation time,
    only coverage reporting does — and a **metadata-only pattern is exactly
    what such an index would break**. `ssis-package` detects on
    `structuralType` alone, so its `anchor_signals` is `[]`; an index keyed
    on anchor signals would return it for no project at all and silently
    drop it from evaluation, turning every SSIS package back into
    `NO_PATTERN_MATCHED` with nothing in the output to explain why.

    So if an index is ever added for throughput, this function is the place
    to add it, and a pattern with empty `anchor_signals` must bypass it and
    always be evaluated. See 24-STEP-004-CLASSIFICATION.md Part C,
    "Candidate selection".
    """
    return [p for p in patterns if p["classification_role"] != "PROJECT_ROLE"]


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
            "role_patterns_matched": [],
            "signals_present": [],
            "evaluated_pattern_count": 0,
            "primary_pattern_id": None,
            "matches": [],
            "warnings": [
                {"code": "CLASSIFICATION_FAILED", "severity": "error", "message": f"{type(exc).__name__}: {exc}"}
            ],
        }


def _classify_project(project: dict, patterns: list[dict], config: dict) -> dict:
    warnings: list[dict] = []
    undeclared_relationships_reported: set[frozenset] = set()

    def _note_undeclared_relationship(pattern_id_a: str, pattern_id_b: str) -> None:
        # A governance observation (same shape as REPOSITORY_SCOPED_PATTERN_SKIPPED
        # below), naming both pattern ids so the catalog can be corrected as
        # the estate is learned. Deduplicated per pair, per project.
        pair = frozenset((pattern_id_a, pattern_id_b))
        if pair in undeclared_relationships_reported:
            return
        undeclared_relationships_reported.add(pair)
        warnings.append(
            {
                "code": "UNDECLARED_PATTERN_RELATIONSHIP",
                "severity": "warning",
                "message": (
                    f"Patterns '{pattern_id_a}' and '{pattern_id_b}' both matched with no declared "
                    "relationship (absent from both compatible_with and conflicts_with); defaulted to "
                    "CONFLICTING. Declare the relationship in the catalog so this reflects a deliberate "
                    "decision rather than a default."
                ),
            }
        )

    role_patterns = [p for p in patterns if p["classification_role"] == "PROJECT_ROLE"]
    application_patterns = candidate_application_patterns(patterns)
    signals_present = sorted(project["signals_by_name"].keys())

    # The role pass runs BEFORE the SKIPPED gate, deliberately. Role rules key
    # off project metadata as much as signals — role-deployment-project is
    # pure `structuralType` — and that metadata is present even when step 3
    # skipped the project. "Skipped, and it is a deployment artifact" is more
    # useful than "skipped, role unknown", and it costs nothing: no signals
    # are needed to reach it.
    role_result = role_engine.resolve_role(role_patterns, project["signals_by_name"], project["metadata"])
    project_role = role_result["value"] if role_result else None
    project_role_confidence = role_result["confidence"] if role_result else None

    def _role_fields() -> dict:
        return {
            "project_role": project_role,
            "project_role_confidence": project_role_confidence,
            "role_pattern_id": role_result["pattern_id"] if role_result else None,
            "role_patterns_evaluated": [p["id"] for p in role_patterns],
            "role_patterns_matched": role_result["matched_pattern_ids"] if role_result else [],
            "signals_present": signals_present,
        }

    if project["fingerprint_status"] == "SKIPPED":
        return {
            "classification_status": "SKIPPED",
            **_role_fields(),
            "evaluated_pattern_count": 0,
            "primary_pattern_id": None,
            "matches": [],
            "warnings": warnings,
        }

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
                "relationship_source": None,
            }
        )

        if matched:
            for warning_text in pattern["detection_rules"].get("matchWarnings", []) or []:
                warnings.append(
                    {
                        "code": "PATTERN_MATCH_WARNING",
                        "severity": "info",
                        "message": f"'{pattern['id']}' matched: {warning_text}",
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
            other["score"] for other in primary_candidates if other is not m and _is_conflicting(m["pattern"], other["pattern"])
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
            relationship, source = _relationship(higher["pattern"], lower["pattern"])
            if relationship != "conflicting":
                continue
            gap = higher["score"] - lower["score"]
            if gap > margin:
                rejected_ids.add(lower["pattern"]["id"])
                lower["rejection_reason"] = (
                    f"Rejected in favour of '{higher['pattern']['id']}' "
                    f"(score {higher['score']} vs {lower['score']}, gap {gap} exceeds the "
                    f"ambiguity margin of {margin})."
                )
                lower["relationship_source"] = source
                higher["relationship_source"] = higher["relationship_source"] or source
                if source == "defaulted":
                    _note_undeclared_relationship(higher["pattern"]["id"], lower["pattern"]["id"])

    surviving = [m for m in sorted_candidates if m["pattern"]["id"] not in rejected_ids]

    ambiguous_pairs = []
    for a, b in itertools.combinations(surviving, 2):
        relationship, source = _relationship(a["pattern"], b["pattern"])
        if relationship == "conflicting" and abs(a["score"] - b["score"]) <= margin:
            ambiguous_pairs.append((a, b, source))
    ambiguous = bool(ambiguous_pairs)

    primary_pattern_id = None
    if ambiguous:
        classification_status = "AMBIGUOUS"
        for a, b, source in ambiguous_pairs:
            a["relationship_source"] = a["relationship_source"] or source
            b["relationship_source"] = b["relationship_source"] or source
            if source == "defaulted":
                _note_undeclared_relationship(a["pattern"]["id"], b["pattern"]["id"])
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
        **_role_fields(),
        "evaluated_pattern_count": evaluated_count,
        "primary_pattern_id": primary_pattern_id,
        "matches": matches,
        "warnings": warnings,
    }
