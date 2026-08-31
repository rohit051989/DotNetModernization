"""Confidence formula and levels — Part E 'Confidence'. All coefficients
come from the classification-config file, never hardcoded here."""


def confidence_level(confidence: float, config: dict) -> str:
    levels = config["confidenceLevels"]
    if confidence >= levels["HIGH"]:
        return "HIGH"
    if confidence >= levels["MEDIUM"]:
        return "MEDIUM"
    if confidence >= levels["LOW"]:
        return "LOW"
    return "VERY_LOW"


def completeness_factor(fingerprint_status: str, config: dict) -> float:
    return config["completenessFactor"].get(fingerprint_status, 0.0)


def extraction_factor(matched_signal_rows: list[dict]) -> float:
    """Mean extraction_confidence of signals that matched conditions. 1.0
    when nothing matched (e.g. a pure-metadata/negative-evidence pattern),
    since there is no extraction uncertainty to discount."""
    confidences = [r["extraction_confidence"] for r in matched_signal_rows]
    if not confidences:
        return 1.0
    return sum(confidences) / len(confidences)


def capability_factor(
    analysis_requirements: dict | None, project_capabilities: dict, config: dict
) -> tuple[float, bool]:
    """Returns (factor, required_capability_missing). 0 if any `required`
    capability is absent — the pattern cannot be evaluated at all. 0.9 if a
    `preferred` capability is absent. Otherwise 1.0."""
    requirements = analysis_requirements or {}
    required = requirements.get("required", {})
    preferred = requirements.get("preferred", {})

    for capability, needed in required.items():
        if needed and not project_capabilities.get(capability, False):
            return 0.0, True

    missing_preferred = [c for c, needed in preferred.items() if needed and not project_capabilities.get(c, False)]
    if missing_preferred:
        return config["capabilityFactor"]["preferredMissing"], False
    return 1.0, False


def ambiguity_factor(this_score: int, conflicting_scores: list[int], config: dict) -> float:
    """0.8 when a conflicting pattern scored within ambiguityMargin, else 1.0."""
    margin = config["ambiguityMargin"]
    for other_score in conflicting_scores:
        if abs(this_score - other_score) <= margin:
            return config["ambiguityFactor"]["conflictWithinMargin"]
    return 1.0


def compute_confidence(
    match_score: int,
    fingerprint_status: str,
    matched_signal_rows: list[dict],
    capability_factor_value: float,
    ambiguity_factor_value: float,
    config: dict,
) -> float:
    return (
        (match_score / 100)
        * completeness_factor(fingerprint_status, config)
        * extraction_factor(matched_signal_rows)
        * capability_factor_value
        * ambiguity_factor_value
    )
