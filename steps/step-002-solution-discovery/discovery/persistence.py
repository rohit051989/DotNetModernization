"""Wholesale replace-by-repository_id persistence for step 2's discovery
results. Raw psycopg SQL — no ORM, since this package must not import
backend.app, where the SQLAlchemy models live.

See 19-STEP-002-SOLUTION-DISCOVERY.md Part C: "All rows are owned by step 2
and replaced wholesale on rescan — delete by repository_id, then insert.
Simpler than reconciling, and correct given the artifact is a point-in-time
snapshot."
"""

import json
import re

import psycopg

# StepContext.database_url is an SQLAlchemy-style URL
# ("postgresql+psycopg://..."), since it comes from the same settings the
# backend's SQLAlchemy engine uses. psycopg's own connect() does not
# understand the "+driver" suffix, so it is stripped here.
_DRIVER_SUFFIX_RE = re.compile(r"^(postgres(?:ql)?)\+[^:]+://")


def _normalize_database_url(database_url: str) -> str:
    return _DRIVER_SUFFIX_RE.sub(r"\1://", database_url)


def _delete_existing(cur, repository_id: str) -> None:
    cur.execute(
        "DELETE FROM project_packages WHERE project_id IN (SELECT id FROM projects WHERE repository_id = %s)",
        (repository_id,),
    )
    cur.execute(
        "DELETE FROM project_references WHERE source_project_id IN "
        "(SELECT id FROM projects WHERE repository_id = %s)",
        (repository_id,),
    )
    cur.execute(
        "DELETE FROM solution_projects WHERE solution_id IN (SELECT id FROM solutions WHERE repository_id = %s)",
        (repository_id,),
    )
    cur.execute("DELETE FROM projects WHERE repository_id = %s", (repository_id,))
    cur.execute("DELETE FROM solutions WHERE repository_id = %s", (repository_id,))
    cur.execute("DELETE FROM repository_artifacts WHERE repository_id = %s", (repository_id,))
    cur.execute("DELETE FROM repository_structure WHERE repository_id = %s", (repository_id,))


def replace_all(
    database_url: str,
    repository_id: str,
    *,
    structure: dict,
    solutions: list[dict],
    projects: list[dict],
    solution_projects: list[dict],
    project_references: list[dict],
    project_packages: list[dict],
    repository_artifacts: list[dict],
) -> None:
    """One transaction: delete everything step 2 owns for this repository,
    then insert the fresh scan results. Every row dict already carries its
    own generated `id` (and, for children, their parent's id) — this
    function only writes what it is given."""
    database_url = _normalize_database_url(database_url)

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            _delete_existing(cur, repository_id)

            cur.execute(
                """
                INSERT INTO repository_structure (
                    repository_id, scan_status, solution_count, project_file_count,
                    projects_referenced_count, standalone_project_count, shared_project_count,
                    unresolved_reference_count, out_of_scope_project_count, unknown_project_count,
                    failed_parse_count, legacy_project_count,
                    sdk_project_count, framework_families, artifact_counts, parse_warnings,
                    step_execution_id, scanned_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repository_id,
                    structure["scan_status"],
                    structure["solution_count"],
                    structure["project_file_count"],
                    structure["projects_referenced_count"],
                    structure["standalone_project_count"],
                    structure["shared_project_count"],
                    structure["unresolved_reference_count"],
                    structure["out_of_scope_project_count"],
                    structure["unknown_project_count"],
                    structure["failed_parse_count"],
                    structure["legacy_project_count"],
                    structure["sdk_project_count"],
                    json.dumps(structure["framework_families"]),
                    json.dumps(structure["artifact_counts"]),
                    json.dumps(structure["parse_warnings"]),
                    structure.get("step_execution_id"),
                    structure["scanned_at"],
                ),
            )

            for s in solutions:
                cur.execute(
                    """
                    INSERT INTO solutions (
                        id, repository_id, name, relative_path, format_version,
                        visual_studio_version, minimum_vs_version, project_count,
                        resolved_project_count, missing_project_count, solution_folder_count,
                        shared_project_count, parse_status, parse_error
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        s["id"],
                        repository_id,
                        s["name"],
                        s["relative_path"],
                        s["format_version"],
                        s["visual_studio_version"],
                        s["minimum_vs_version"],
                        s["project_count"],
                        s["resolved_project_count"],
                        s["missing_project_count"],
                        s["solution_folder_count"],
                        s["shared_project_count"],
                        s["parse_status"],
                        s["parse_error"],
                    ),
                )

            for p in projects:
                cur.execute(
                    """
                    INSERT INTO projects (
                        id, repository_id, name, relative_path, extension, structural_type,
                        project_format, language, assembly_name, root_namespace, output_type,
                        target_framework_raw, target_frameworks_raw, framework_family,
                        framework_version, is_multi_targeting, solution_membership_count,
                        is_standalone, project_reference_count, package_reference_count,
                        package_management_style, has_packages_config, parse_status, parse_warnings
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        p["id"],
                        repository_id,
                        p["name"],
                        p["relative_path"],
                        p["extension"],
                        p["structural_type"],
                        p["project_format"],
                        p["language"],
                        p["assembly_name"],
                        p["root_namespace"],
                        p["output_type"],
                        p["target_framework_raw"],
                        json.dumps(p["target_frameworks_raw"]) if p["target_frameworks_raw"] is not None else None,
                        p["framework_family"],
                        p["framework_version"],
                        p["is_multi_targeting"],
                        p["solution_membership_count"],
                        p["is_standalone"],
                        p["project_reference_count"],
                        p["package_reference_count"],
                        p["package_management_style"],
                        p["has_packages_config"],
                        p["parse_status"],
                        json.dumps(p["parse_warnings"]),
                    ),
                )

            for sp in solution_projects:
                cur.execute(
                    """
                    INSERT INTO solution_projects (
                        id, solution_id, project_id, raw_path, project_guid,
                        project_type_guid, solution_folder, resolution_status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        sp["id"],
                        sp["solution_id"],
                        sp["project_id"],
                        sp["raw_path"],
                        sp["project_guid"],
                        sp["project_type_guid"],
                        sp["solution_folder"],
                        sp["resolution_status"],
                    ),
                )

            for pr in project_references:
                cur.execute(
                    """
                    INSERT INTO project_references (
                        id, source_project_id, referenced_project_id, raw_path,
                        resolution_status, is_cross_solution
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        pr["id"],
                        pr["source_project_id"],
                        pr["referenced_project_id"],
                        pr["raw_path"],
                        pr["resolution_status"],
                        pr["is_cross_solution"],
                    ),
                )

            for pkg in project_packages:
                cur.execute(
                    """
                    INSERT INTO project_packages (
                        id, project_id, package_name, version_raw, declaration_source,
                        target_framework_raw, is_malformed
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        pkg["id"],
                        pkg["project_id"],
                        pkg["package_name"],
                        pkg["version_raw"],
                        pkg["declaration_source"],
                        pkg["target_framework_raw"],
                        pkg["is_malformed"],
                    ),
                )

            for ra in repository_artifacts:
                cur.execute(
                    """
                    INSERT INTO repository_artifacts (id, repository_id, category, relative_path, file_name)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (ra["id"], repository_id, ra["category"], ra["relative_path"], ra["file_name"]),
                )
