"""Raw psycopg SQL — no ORM, since this package must not import backend.app
(same reasoning as steps/step-002-solution-discovery/discovery/persistence.py).
Read-heavy (patterns, projects, fingerprints, signals), so this uses
dict_row rather than step 2's plain tuples.
"""

import re

import psycopg
from psycopg.rows import dict_row

_DRIVER_SUFFIX_RE = re.compile(r"^(postgres(?:ql)?)\+[^:]+://")


def normalize_database_url(database_url: str) -> str:
    return _DRIVER_SUFFIX_RE.sub(r"\1://", database_url)


def connect(database_url: str):
    return psycopg.connect(normalize_database_url(database_url), row_factory=dict_row)


def load_active_catalog(conn) -> list[dict]:
    """Every non-deleted pattern, shaped for the engine. `detection_rules`
    is trusted as stored — every rule id was assigned at write time
    (24-STEP-004-CLASSIFICATION.md Part B3/C, enforced by the backend)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, version, classification_role, classification_family,
                   classification_value, scope, priority, compatible_with, conflicts_with,
                   anchor_signals, eligibility, analysis_requirements, thresholds,
                   rules_status, required_signals_pending, detection_rules
            FROM patterns
            WHERE deleted_at IS NULL
            ORDER BY id
            """
        )
        return cur.fetchall()


def current_catalog_revision(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(id), 0) AS revision FROM catalog_revisions")
        return cur.fetchone()["revision"]


def load_repository(conn, repository_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM repositories WHERE id = %s", (repository_id,))
        return cur.fetchone()


def load_projects_for_repository(conn, repository_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.id, p.name, p.relative_path, p.extension, p.structural_type,
                   p.project_format, p.language, p.output_type, p.framework_family,
                   p.framework_version,
                   f.fingerprint_status, f.scanner_version, f.analysis_capabilities,
                   f.project_sdk
            FROM projects p
            LEFT JOIN project_fingerprints f ON f.project_id = p.id
            WHERE p.repository_id = %s
            ORDER BY p.relative_path
            """,
            (repository_id,),
        )
        rows = cur.fetchall()

    # `project_fingerprints.fingerprint_status` is stored lowercase (its own
    # CHECK constraint), but Part E/§19 and this engine's config both use the
    # spec's uppercase vocabulary (COMPLETE/PARTIAL/SKIPPED/...) — normalize
    # once at the DB boundary rather than case-fold at every comparison site.
    for row in rows:
        if row["fingerprint_status"] is not None:
            row["fingerprint_status"] = row["fingerprint_status"].upper()
        else:
            row["fingerprint_status"] = "SKIPPED"  # no fingerprint row at all -> never analyzed
    return rows


def load_signals_for_project(conn, project_id: str) -> dict[str, list[dict]]:
    """Aggregated fingerprint_signals rows for one project, grouped by
    signal_name — the shape engine.rules.evaluate_signal_condition expects."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT signal_name, signal_category, signal_type, value, source_type,
                   source_path, occurrence_count, extraction_confidence
            FROM fingerprint_signals
            WHERE project_id = %s
            """,
            (project_id,),
        )
        by_name: dict[str, list[dict]] = {}
        for row in cur.fetchall():
            by_name.setdefault(row["signal_name"], []).append(
                {
                    "signal_category": row["signal_category"],
                    "signal_type": row["signal_type"],
                    "value": row["value"],
                    "source_type": row["source_type"],
                    "source_path": row["source_path"],
                    "occurrence_count": row["occurrence_count"],
                    "extraction_confidence": float(row["extraction_confidence"]),
                }
            )
        return by_name


def project_metadata(project_row: dict) -> dict:
    """Part C metadata-condition field names (camelCase, per the spec's own
    naming) mapped from the snake_case project/fingerprint columns."""
    return {
        "outputType": project_row["output_type"],
        "projectFormat": project_row["project_format"],
        "frameworkFamily": project_row["framework_family"],
        "frameworkVersion": project_row["framework_version"],
        "projectSdk": project_row["project_sdk"],
        "structuralType": project_row["structural_type"],
        "extension": project_row["extension"],
        "fingerprintStatus": project_row["fingerprint_status"],
    }


def signal_registry_version(conn, repository_id: str) -> str | None:
    """`fingerprint_scans` holds one row per repository (upserted on each
    scan, not appended), so with more than one repository registered an
    unfiltered query can return an arbitrary repository's row — always scope
    to the repository actually being classified."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT signal_registry_version FROM fingerprint_scans WHERE repository_id = %s", (repository_id,)
        )
        row = cur.fetchone()
        return row["signal_registry_version"] if row else None


def replace_classification_results(
    conn,
    repository_id: str,
    project_results: list[dict],
    coverage_report: dict,
) -> None:
    """Wholesale replace-by-repository_id, matching step 2/3's convention —
    the artifact and these tables are a point-in-time snapshot, replaced on
    rescan rather than reconciled."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM classification_matches WHERE repository_id = %s", (repository_id,)
        )
        cur.execute(
            "DELETE FROM project_classifications WHERE repository_id = %s", (repository_id,)
        )
        cur.execute(
            "DELETE FROM catalog_coverage_reports WHERE repository_id = %s", (repository_id,)
        )

        for result in project_results:
            cur.execute(
                """
                INSERT INTO project_classifications (
                    project_id, repository_id, classification_status, project_role,
                    project_role_confidence, framework_family, framework_version,
                    catalog_revision, signal_registry_version,
                    config_version, evaluated_pattern_count, primary_pattern_id, warnings,
                    step_execution_id, classified_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                """,
                (
                    result["project_id"],
                    repository_id,
                    result["classification_status"],
                    result["project_role"],
                    result["project_role_confidence"],
                    result["framework_family"],
                    result["framework_version"],
                    result["catalog_revision"],
                    result["signal_registry_version"],
                    result["config_version"],
                    result["evaluated_pattern_count"],
                    result["primary_pattern_id"],
                    psycopg.types.json.Json(result["warnings"]),
                    result["step_execution_id"],
                ),
            )
            for m in result["matches"]:
                cur.execute(
                    """
                    INSERT INTO classification_matches (
                        project_id, repository_id, pattern_id, pattern_version, matched,
                        classification_role, match_score, confidence, confidence_level,
                        is_primary_selected, rejection_reason, relationship_source, engagement_scope_status,
                        matched_rules, failed_rules, missing_preferred, negative_triggered,
                        explanation
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        result["project_id"],
                        repository_id,
                        m["pattern_id"],
                        m["pattern_version"],
                        m["matched"],
                        m["classification_role"],
                        m["match_score"],
                        m["confidence"],
                        m["confidence_level"],
                        m["is_primary_selected"],
                        m["rejection_reason"],
                        m["relationship_source"],
                        m["engagement_scope_status"],
                        psycopg.types.json.Json(m["matched_rules"]),
                        psycopg.types.json.Json(m["failed_rules"]),
                        psycopg.types.json.Json(m["missing_preferred"]),
                        psycopg.types.json.Json(m["negative_triggered"]),
                        m["explanation"],
                    ),
                )

        cur.execute(
            """
            INSERT INTO catalog_coverage_reports (
                repository_id, catalog_version, catalog_revision, signal_registry_version,
                registered_signal_count, referenced_signal_count, unreferenced_signal_count,
                active_pattern_count, evaluated_pattern_count, matched_pattern_count,
                never_matched_pattern_ids, patterns_awaiting_signals_by_extractor,
                most_frequent_unmatched_signal_combinations, step_execution_id, generated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            """,
            (
                repository_id,
                coverage_report["catalog_version"],
                coverage_report["catalog_revision"],
                coverage_report["signal_registry_version"],
                coverage_report["registered_signal_count"],
                coverage_report["referenced_signal_count"],
                coverage_report["unreferenced_signal_count"],
                coverage_report["active_pattern_count"],
                coverage_report["evaluated_pattern_count"],
                coverage_report["matched_pattern_count"],
                psycopg.types.json.Json(coverage_report["never_matched_pattern_ids"]),
                psycopg.types.json.Json(coverage_report["patterns_awaiting_signals_by_extractor"]),
                psycopg.types.json.Json(coverage_report["most_frequent_unmatched_signal_combinations"]),
                coverage_report["step_execution_id"],
            ),
        )
    conn.commit()
