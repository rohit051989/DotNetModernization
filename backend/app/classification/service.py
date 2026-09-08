"""Read-only query logic over step 4's (pattern-classification) results —
see 24-STEP-004-CLASSIFICATION.md Part I. Nothing here mutates; the
standalone script under steps/step-004-classification/ owns every row in
these tables.
"""

import uuid
from collections import Counter

from sqlalchemy.orm import Session

from app import catalog_rules, models
from app.catalog_rules import registered_signal_names


def _match_to_dict(match: models.ClassificationMatch, pattern: models.Pattern | None) -> dict:
    return {
        "pattern_id": match.pattern_id,
        "pattern_name": pattern.name if pattern else match.pattern_id,
        "pattern_version": match.pattern_version,
        "classification_role": match.classification_role,
        "classification_family": pattern.classification_family if pattern else None,
        "classification_value": pattern.classification_value if pattern else None,
        "matched": match.matched,
        "match_score": match.match_score,
        "confidence": float(match.confidence),
        "confidence_level": match.confidence_level,
        "is_primary_selected": match.is_primary_selected,
        "rejection_reason": match.rejection_reason,
        "relationship_source": match.relationship_source,
        "matched_rules": match.matched_rules or [],
        "failed_rules": match.failed_rules or [],
        "missing_preferred": match.missing_preferred or [],
        "negative_triggered": match.negative_triggered or [],
        "explanation": match.explanation,
    }


def classification_summary(db: Session, repository_id: uuid.UUID) -> dict:
    rows = (
        db.query(models.ProjectClassification)
        .filter(models.ProjectClassification.repository_id == repository_id)
        .all()
    )
    counts = Counter(r.classification_status for r in rows)
    return {
        "repository_id": str(repository_id),
        "evaluated": len(rows),
        "matched": counts.get("MATCHED", 0),
        "multiple_matches": counts.get("MULTIPLE_MATCHES", 0),
        "ambiguous": counts.get("AMBIGUOUS", 0),
        "no_pattern_matched": counts.get("NO_PATTERN_MATCHED", 0),
        "insufficient_fingerprint": counts.get("INSUFFICIENT_FINGERPRINT", 0),
        "not_eligible": counts.get("NOT_ELIGIBLE", 0),
        "skipped": counts.get("SKIPPED", 0),
        "classification_failed": counts.get("CLASSIFICATION_FAILED", 0),
    }


def list_classifications(
    db: Session,
    repository_id: uuid.UUID,
    status: str | None = None,
    pattern_id: str | None = None,
    role: str | None = None,
) -> list[dict]:
    query = db.query(models.ProjectClassification).filter(
        models.ProjectClassification.repository_id == repository_id
    )
    if status:
        query = query.filter(models.ProjectClassification.classification_status == status)
    if role:
        query = query.filter(models.ProjectClassification.project_role == role)
    if pattern_id:
        query = query.filter(models.ProjectClassification.primary_pattern_id == pattern_id)
    rows = query.order_by(models.ProjectClassification.project_id).all()
    if not rows:
        return []

    projects = {
        p.id: p
        for p in db.query(models.Project).filter(models.Project.id.in_([r.project_id for r in rows]))
    }
    pattern_ids = {r.primary_pattern_id for r in rows if r.primary_pattern_id}
    patterns = (
        {p.id: p for p in db.query(models.Pattern).filter(models.Pattern.id.in_(pattern_ids))}
        if pattern_ids
        else {}
    )
    confidence_by_project = {
        m.project_id: m.confidence_level
        for m in db.query(models.ClassificationMatch).filter(
            models.ClassificationMatch.project_id.in_([r.project_id for r in rows]),
            models.ClassificationMatch.is_primary_selected.is_(True),
        )
    }

    return [
        {
            "project_id": str(r.project_id),
            "project_path": projects[r.project_id].relative_path if r.project_id in projects else "",
            "project_role": r.project_role,
            "primary_pattern_id": r.primary_pattern_id,
            "primary_pattern_name": patterns[r.primary_pattern_id].name if r.primary_pattern_id in patterns else None,
            "confidence_level": confidence_by_project.get(r.project_id),
            "classification_status": r.classification_status,
            "classified_at": r.classified_at,
        }
        for r in rows
    ]


def project_classification_detail(db: Session, project_id: uuid.UUID) -> dict | None:
    pc = db.get(models.ProjectClassification, project_id)
    if pc is None:
        return None

    project = db.get(models.Project, project_id)
    matches = (
        db.query(models.ClassificationMatch)
        .filter(models.ClassificationMatch.project_id == project_id)
        .order_by(models.ClassificationMatch.pattern_id)
        .all()
    )
    pattern_ids = {m.pattern_id for m in matches}
    patterns = (
        {p.id: p for p in db.query(models.Pattern).filter(models.Pattern.id.in_(pattern_ids))}
        if pattern_ids
        else {}
    )

    matched = [_match_to_dict(m, patterns.get(m.pattern_id)) for m in matches if m.matched]
    near_misses = [_match_to_dict(m, patterns.get(m.pattern_id)) for m in matches if not m.matched]

    return {
        "project_id": str(pc.project_id),
        "project_path": project.relative_path if project else "",
        "repository_id": str(pc.repository_id),
        "classification_status": pc.classification_status,
        "project_role": pc.project_role,
        "project_role_confidence": float(pc.project_role_confidence) if pc.project_role_confidence is not None else None,
        "framework_family": pc.framework_family,
        "framework_version": pc.framework_version,
        "catalog_revision": pc.catalog_revision,
        "signal_registry_version": pc.signal_registry_version,
        "config_version": pc.config_version,
        "evaluated_pattern_count": pc.evaluated_pattern_count,
        "primary_pattern_id": pc.primary_pattern_id,
        "matches": matched,
        "near_misses": near_misses,
        "warnings": pc.warnings or [],
        "classified_at": pc.classified_at,
    }


def classification_summary_across(db: Session, engagement_id: str) -> dict:
    """Same buckets as `classification_summary`, aggregated across every
    repository in the engagement — the dashboard Patterns card's source."""
    repo_ids = _engagement_repository_ids(db, engagement_id)
    if not repo_ids:
        return {
            "evaluated": 0, "matched": 0, "multiple_matches": 0, "ambiguous": 0,
            "no_pattern_matched": 0, "insufficient_fingerprint": 0, "not_eligible": 0,
            "skipped": 0, "classification_failed": 0,
        }
    rows = (
        db.query(models.ProjectClassification)
        .filter(models.ProjectClassification.repository_id.in_(repo_ids))
        .all()
    )
    counts = Counter(r.classification_status for r in rows)
    return {
        "evaluated": len(rows),
        "matched": counts.get("MATCHED", 0),
        "multiple_matches": counts.get("MULTIPLE_MATCHES", 0),
        "ambiguous": counts.get("AMBIGUOUS", 0),
        "no_pattern_matched": counts.get("NO_PATTERN_MATCHED", 0),
        "insufficient_fingerprint": counts.get("INSUFFICIENT_FINGERPRINT", 0),
        "not_eligible": counts.get("NOT_ELIGIBLE", 0),
        "skipped": counts.get("SKIPPED", 0),
        "classification_failed": counts.get("CLASSIFICATION_FAILED", 0),
    }


def _engagement_repository_ids(db: Session, engagement_id: str) -> list[uuid.UUID]:
    return [
        r.id
        for r in db.query(models.Repository.id).filter(
            models.Repository.engagement_id == engagement_id, models.Repository.deleted_at.is_(None)
        )
    ]


def pattern_distribution(db: Session, engagement_id: str) -> dict:
    repo_ids = _engagement_repository_ids(db, engagement_id)
    empty = {
        "engagement_id": engagement_id,
        "projects_evaluated": 0,
        "primary_pattern_distribution": [],
        "secondary_capability_distribution": [],
        "confidence_distribution": {},
        "pattern_match_rate": 0.0,
        "pattern_ambiguity_rate": 0.0,
    }
    if not repo_ids:
        return empty

    classifications = (
        db.query(models.ProjectClassification)
        .filter(models.ProjectClassification.repository_id.in_(repo_ids))
        .all()
    )
    if not classifications:
        return empty

    matches = (
        db.query(models.ClassificationMatch)
        .filter(models.ClassificationMatch.repository_id.in_(repo_ids))
        .all()
    )

    primary_counts = Counter(c.primary_pattern_id for c in classifications if c.primary_pattern_id)
    secondary_counts = Counter(
        m.pattern_id for m in matches if m.matched and m.classification_role == "SECONDARY"
    )
    confidence_counts = Counter(m.confidence_level for m in matches if m.is_primary_selected)

    pattern_ids = set(primary_counts) | set(secondary_counts)
    patterns = (
        {p.id: p for p in db.query(models.Pattern).filter(models.Pattern.id.in_(pattern_ids))}
        if pattern_ids
        else {}
    )

    def _to_counts(counter: Counter) -> list[dict]:
        return [
            {"pattern_id": pid, "pattern_name": patterns[pid].name if pid in patterns else pid, "count": count}
            for pid, count in counter.most_common()
        ]

    evaluated = len(classifications)
    matched_something = sum(1 for c in classifications if c.classification_status in ("MATCHED", "MULTIPLE_MATCHES"))
    ambiguous = sum(1 for c in classifications if c.classification_status == "AMBIGUOUS")

    return {
        "engagement_id": engagement_id,
        "projects_evaluated": evaluated,
        "primary_pattern_distribution": _to_counts(primary_counts),
        "secondary_capability_distribution": _to_counts(secondary_counts),
        "confidence_distribution": dict(confidence_counts),
        "pattern_match_rate": round(matched_something / evaluated, 4) if evaluated else 0.0,
        "pattern_ambiguity_rate": round(ambiguous / evaluated, 4) if evaluated else 0.0,
    }


def catalog_coverage(db: Session, engagement_id: str) -> dict | None:
    """Aggregates the latest coverage report per repository in this
    engagement. The catalog itself is shared master IP; this is only ever
    an *observed* view through what this engagement's repositories have
    actually been scanned against."""
    repo_ids = _engagement_repository_ids(db, engagement_id)
    if not repo_ids:
        return None

    reports = []
    for repo_id in repo_ids:
        latest = (
            db.query(models.CatalogCoverageReport)
            .filter(models.CatalogCoverageReport.repository_id == repo_id)
            .order_by(models.CatalogCoverageReport.generated_at.desc())
            .first()
        )
        if latest is not None:
            reports.append(latest)
    if not reports:
        return None

    most_recent = max(reports, key=lambda r: r.generated_at)

    never_matched = set(reports[0].never_matched_pattern_ids or [])
    for report in reports[1:]:
        never_matched &= set(report.never_matched_pattern_ids or [])

    awaiting_by_extractor: dict[str, set[str]] = {}
    for report in reports:
        for extractor, pattern_ids in (report.patterns_awaiting_signals_by_extractor or {}).items():
            awaiting_by_extractor.setdefault(extractor, set()).update(pattern_ids)

    combo_counts: Counter[tuple] = Counter()
    for report in reports:
        for entry in report.most_frequent_unmatched_signal_combinations or []:
            combo_counts[tuple(entry["anchor_signals"])] += entry["count"]

    # Derived from each report's never_matched_pattern_ids against the
    # *current* active pattern set, rather than classification_matches
    # directly — that table never carries PROJECT_ROLE evaluations (role
    # patterns are tracked separately, per engine/classify.py), so it would
    # silently undercount both evaluated and matched patterns.
    active_pattern_ids = {
        row.id
        for row in db.query(models.Pattern.id).filter(
            models.Pattern.rules_status == "active", models.Pattern.deleted_at.is_(None)
        )
    }
    matched_pattern_ids: set[str] = set()
    evaluated_pattern_ids: set[str] = set()
    for report in reports:
        never_matched_this_repo = set(report.never_matched_pattern_ids or []) & active_pattern_ids
        matched_this_repo = active_pattern_ids - never_matched_this_repo
        matched_pattern_ids |= matched_this_repo
        evaluated_pattern_ids |= matched_this_repo | never_matched_this_repo

    return {
        "engagement_id": engagement_id,
        "repositories_included": len(reports),
        "catalog_version": most_recent.catalog_version,
        "signal_registry_version": most_recent.signal_registry_version,
        "registered_signal_count": len(registered_signal_names()),
        "referenced_signal_count": most_recent.referenced_signal_count,
        "unreferenced_signal_count": most_recent.unreferenced_signal_count,
        "active_pattern_count": most_recent.active_pattern_count,
        "evaluated_pattern_count": len(evaluated_pattern_ids),
        "matched_pattern_count": len(matched_pattern_ids),
        "never_matched_pattern_ids": sorted(never_matched),
        "patterns_awaiting_signals_by_extractor": {k: sorted(v) for k, v in awaiting_by_extractor.items()},
        "most_frequent_unmatched_signal_combinations": [
            {"anchor_signals": list(combo), "count": count} for combo, count in combo_counts.most_common(5)
        ],
        "rule_references_never_emitted_signal": catalog_rules.never_emitted_signal_findings(db, engagement_id),
    }
