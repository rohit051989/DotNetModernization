"""Read-only response shapes over step 4's (pattern-classification) results.
See 24-STEP-004-CLASSIFICATION.md Part I and step-4-pattern-classification-
against-catalog.md section 25.
"""

import datetime

from pydantic import BaseModel, Field

ClassificationStatus = str  # see models.CLASSIFICATION_STATUS; free string here, not re-declared as a Literal


class ClassificationSummaryOut(BaseModel):
    """§25.1 — repository-scoped classification status counts."""

    repository_id: str
    evaluated: int = Field(description="Projects with a classification result, of any status.")
    matched: int = Field(description="Projects with classification_status MATCHED.")
    multiple_matches: int = Field(description="Projects with classification_status MULTIPLE_MATCHES.")
    ambiguous: int = Field(description="Projects with classification_status AMBIGUOUS.")
    no_pattern_matched: int = Field(description="Projects with classification_status NO_PATTERN_MATCHED — step 5 candidates.")
    insufficient_fingerprint: int = Field(description="Projects with classification_status INSUFFICIENT_FINGERPRINT — not a step 5 candidate.")
    not_eligible: int = Field(description="Projects with classification_status NOT_ELIGIBLE (role excluded every candidate).")
    skipped: int = Field(description="Projects with classification_status SKIPPED (fingerprint was SKIPPED).")
    classification_failed: int = Field(description="Projects with classification_status CLASSIFICATION_FAILED (engine error).")


class ClassificationListItemOut(BaseModel):
    """One row for the repository detail Classification section's project table."""

    project_id: str
    project_path: str
    project_role: str | None
    primary_pattern_id: str | None
    primary_pattern_name: str | None
    confidence_level: str | None = Field(description="Confidence level of the primary match, null if none selected.")
    classification_status: str
    classified_at: datetime.datetime


class ClassificationListOut(BaseModel):
    repository_id: str
    projects: list[ClassificationListItemOut]


class ClassificationMatchOut(BaseModel):
    """One evaluated pattern for a project — matched or a near-miss. §20's
    traceability requirement: every matched rule links back to its step 3
    signal and evidence via `matched_rules`."""

    pattern_id: str
    pattern_name: str
    pattern_version: int
    classification_role: str
    classification_family: str | None
    classification_value: str | None
    matched: bool
    match_score: int
    confidence: float
    confidence_level: str
    is_primary_selected: bool
    rejection_reason: str | None = Field(description="Set only when a conflicting pattern outscored this one outside the ambiguity margin.")
    relationship_source: str | None = Field(
        description="'declared' or 'defaulted' — set only when this match participated in a conflict/ambiguity "
        "determination against another PRIMARY candidate. 'defaulted' means neither pattern's catalog entry "
        "declares compatible_with/conflicts_with for the other; the relationship defaulted to CONFLICTING."
    )
    matched_rules: list[dict] = Field(description="Rule id, signal, required vs actual occurrences, evidence.")
    failed_rules: list[dict] = Field(description="What this pattern still needs — the tuning input for near-misses.")
    missing_preferred: list[dict]
    negative_triggered: list[dict] = Field(description="Disqualifying or penalizing conditions that fired.")
    explanation: str | None


class ProjectClassificationDetailOut(BaseModel):
    """§25.4 project classification detail, full tree."""

    project_id: str
    project_path: str
    repository_id: str
    classification_status: str
    project_role: str | None
    project_role_confidence: float | None
    framework_family: str | None = Field(
        description="Echoed from step 2. Framework family (net-framework/net-core/net-standard/net) is what "
        "discriminates a pattern — Framework versus Core is a genuine pattern boundary."
    )
    framework_version: str | None = Field(
        description="Echoed from step 2. A parameter, not a discriminator: step 10's risk scoring and an "
        "accelerator's breaking-change set read it; no pattern splits on it."
    )
    catalog_revision: int
    signal_registry_version: str | None
    config_version: str
    evaluated_pattern_count: int
    primary_pattern_id: str | None
    matches: list[ClassificationMatchOut] = Field(description="Every matched pattern — the selected primary and any secondary capabilities.")
    near_misses: list[ClassificationMatchOut] = Field(
        description="Every evaluated-but-not-matched pattern, with its failed rules — what makes tuning possible."
    )
    warnings: list[dict]
    classified_at: datetime.datetime


class PatternCountOut(BaseModel):
    pattern_id: str
    pattern_name: str
    count: int


class PatternDistributionOut(BaseModel):
    """§25.2 — engagement-scoped, aggregated across every repository in the
    engagement. Labelled honestly per Part I: 'Projects classified as X',
    never 'X applications'."""

    engagement_id: str
    projects_evaluated: int
    primary_pattern_distribution: list[PatternCountOut] = Field(description="Projects by selected primary pattern.")
    secondary_capability_distribution: list[PatternCountOut] = Field(
        description="Projects by matched SECONDARY capability pattern. Empty until the catalog has any SECONDARY patterns."
    )
    confidence_distribution: dict[str, int] = Field(description="Count of primary-selected matches per confidence level.")
    pattern_match_rate: float = Field(description="Fraction of evaluated projects with a primary match (MATCHED or MULTIPLE_MATCHES).")
    pattern_ambiguity_rate: float = Field(description="Fraction of evaluated projects that resolved AMBIGUOUS.")


class NeverEmittedSignalFindingOut(BaseModel):
    """RULE_REFERENCES_NEVER_EMITTED_SIGNAL — an active pattern whose rules
    reference a registered signal that has never appeared in any fingerprint
    anywhere in this engagement. Distinguishes a genuinely-absent legacy
    shape from a broken rule referencing the wrong signal name — both would
    otherwise look identical in never_matched_pattern_ids."""

    pattern_id: str
    name: str
    never_emitted_signals: list[str]


class CatalogCoverageOut(BaseModel):
    """§25.3 / Part I 'Catalog coverage — master view'. The catalog is
    shared master IP, but coverage is only observable through what an
    engagement's repositories have actually been scanned against — this
    aggregates the latest coverage report per repository in the engagement."""

    engagement_id: str
    repositories_included: int = Field(description="Repositories in this engagement with at least one coverage report.")
    catalog_version: str
    signal_registry_version: str | None
    registered_signal_count: int
    referenced_signal_count: int
    unreferenced_signal_count: int
    active_pattern_count: int
    evaluated_pattern_count: int
    matched_pattern_count: int
    never_matched_pattern_ids: list[str] = Field(description="Active patterns matched by zero projects across this engagement's repositories.")
    patterns_awaiting_signals_by_extractor: dict[str, list[str]] = Field(
        description="awaiting_signals patterns grouped by the step 3 extractor expected to unblock them — the extractor backlog."
    )
    most_frequent_unmatched_signal_combinations: list[dict]
    rule_references_never_emitted_signal: list[NeverEmittedSignalFindingOut] = Field(
        description="Active patterns whose rules reference a signal never seen in any fingerprint across this engagement — a likely broken rule, not just an absent legacy shape."
    )
