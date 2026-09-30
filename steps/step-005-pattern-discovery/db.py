"""Raw psycopg SQL — no ORM, since this package must not import
backend.app (same reasoning as step 4's db.py).

Step 5 declares no `consumes` and reads the database directly: its inputs
are per-repository artifacts produced by a *different* job, and
${artifacts.x} resolves only within one job
(26-STEP-005-PATTERN-DISCOVERY.md A3).
"""

import json
import re

import psycopg
from psycopg.rows import dict_row

_DRIVER_SUFFIX_RE = re.compile(r"^(postgres(?:ql)?)\+[^:]+://")


def normalize_database_url(database_url: str) -> str:
    return _DRIVER_SUFFIX_RE.sub(r"\1://", database_url)


def connect(database_url: str):
    return psycopg.connect(normalize_database_url(database_url), row_factory=dict_row)


def repositories_in_engagement(conn, engagement_id: str) -> list[dict]:
    """In-scope, non-deleted repositories — the denominator for coverage."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name
            FROM repositories
            WHERE engagement_id = %s AND deleted_at IS NULL
            ORDER BY name
            """,
            (engagement_id,),
        )
        return cur.fetchall()


def repositories_with_classifications(conn, engagement_id: str) -> set[str]:
    """Repositories step 4 has produced results for. The numerator for
    coverage — and the set step 5 actually clusters over."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT c.repository_id
            FROM project_classifications c
            JOIN repositories r ON r.id = c.repository_id
            WHERE r.engagement_id = %s AND r.deleted_at IS NULL
            """,
            (engagement_id,),
        )
        return {str(row["repository_id"]) for row in cur.fetchall()}


def eligible_projects(conn, engagement_id: str, statuses: tuple[str, ...]) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.project_id, c.repository_id, c.classification_status,
                   c.project_role, c.framework_family, c.step_execution_id AS classification_step_execution_id,
                   p.relative_path AS project_path, p.output_type, p.structural_type,
                   r.name AS repository_name
            FROM project_classifications c
            JOIN projects p ON p.id = c.project_id
            JOIN repositories r ON r.id = c.repository_id
            WHERE r.engagement_id = %s
              AND r.deleted_at IS NULL
              AND c.classification_status = ANY(%s)
            ORDER BY r.name, p.relative_path
            """,
            (engagement_id, list(statuses)),
        )
        return cur.fetchall()


def eligibility_breakdown(conn, engagement_id: str) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.classification_status, count(*) AS n
            FROM project_classifications c
            JOIN repositories r ON r.id = c.repository_id
            WHERE r.engagement_id = %s AND r.deleted_at IS NULL
            GROUP BY c.classification_status
            """,
            (engagement_id,),
        )
        return {row["classification_status"]: row["n"] for row in cur.fetchall()}


def signals_for_projects(conn, project_ids: list[str]) -> dict[str, list[dict]]:
    if not project_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT project_id, signal_name, extraction_confidence
            FROM fingerprint_signals
            WHERE project_id = ANY(%s)
            """,
            (project_ids,),
        )
        grouped: dict[str, list[dict]] = {}
        for row in cur.fetchall():
            grouped.setdefault(str(row["project_id"]), []).append(row)
        return grouped


def active_pattern_signal_sets(conn) -> dict[str, set[str]]:
    """Every signal name an active pattern references, for proximity
    scoring. Anchors plus all rule groups — the same traversal step 4's
    coverage report uses."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, anchor_signals, detection_rules
            FROM patterns
            WHERE deleted_at IS NULL AND rules_status = 'active'
              AND classification_role = 'PRIMARY'
            ORDER BY id
            """
        )
        result: dict[str, set[str]] = {}
        for row in cur.fetchall():
            names = set(row["anchor_signals"] or [])
            rules = row["detection_rules"] or {}
            for group in ("all", "any", "supporting", "none"):
                for condition in rules.get(group) or []:
                    names.add(condition["signal"]["name"])
            for group in rules.get("atLeast") or []:
                for condition in group.get("of") or []:
                    names.add(condition["signal"]["name"])
            result[row["id"]] = names
        return result


def load_existing_clusters(conn, engagement_id: str) -> dict[str, dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT cluster_id, status, resolved_pattern_id, resolution_note,
                   decided_at_coverage, decided_at_member_count,
                   needs_rereview, rereview_reason, first_seen_at
            FROM pattern_candidate_clusters
            WHERE engagement_id = %s
            """,
            (engagement_id,),
        )
        return {row["cluster_id"]: row for row in cur.fetchall()}


def upsert_clusters(conn, engagement_id: str, clusters: list[dict], step_execution_id: str | None) -> None:
    """Upsert, never delete-then-insert (Part D "Cluster accumulation
    across runs").

    Refreshed: membership, counts, distribution, cohesion,
    similar_patterns, last_seen_at, step_execution_id.
    Preserved: first_seen_at, status, resolved_pattern_id,
    resolution_note, decided_at_*.

    `pattern_candidate_members` IS replaced per cluster, since membership
    genuinely is a snapshot; the cluster row is not.
    """
    seen_ids = [c["cluster_id"] for c in clusters]
    with conn.cursor() as cur:
        for cluster in clusters:
            cur.execute(
                """
                INSERT INTO pattern_candidate_clusters (
                    cluster_id, engagement_id, cluster_method, canonical_signature,
                    signal_count, member_count, repository_count, repository_distribution,
                    cohesion, is_singleton, similar_patterns, needs_rereview, rereview_reason,
                    is_stale, last_seen_at, step_execution_id
                ) VALUES (
                    %(cluster_id)s, %(engagement_id)s, %(cluster_method)s, %(canonical_signature)s,
                    %(signal_count)s, %(member_count)s, %(repository_count)s, %(repository_distribution)s,
                    %(cohesion)s, %(is_singleton)s, %(similar_patterns)s, %(needs_rereview)s, %(rereview_reason)s,
                    false, now(), %(step_execution_id)s
                )
                ON CONFLICT (cluster_id) DO UPDATE SET
                    cluster_method = EXCLUDED.cluster_method,
                    canonical_signature = EXCLUDED.canonical_signature,
                    signal_count = EXCLUDED.signal_count,
                    member_count = EXCLUDED.member_count,
                    repository_count = EXCLUDED.repository_count,
                    repository_distribution = EXCLUDED.repository_distribution,
                    cohesion = EXCLUDED.cohesion,
                    is_singleton = EXCLUDED.is_singleton,
                    similar_patterns = EXCLUDED.similar_patterns,
                    needs_rereview = EXCLUDED.needs_rereview,
                    rereview_reason = EXCLUDED.rereview_reason,
                    is_stale = false,
                    last_seen_at = now(),
                    step_execution_id = EXCLUDED.step_execution_id
                """,
                {
                    "cluster_id": cluster["cluster_id"],
                    "engagement_id": engagement_id,
                    "cluster_method": cluster["cluster_method"],
                    "canonical_signature": json.dumps(cluster["canonical_signature"], sort_keys=True),
                    "signal_count": cluster["signal_count"],
                    "member_count": cluster["member_count"],
                    "repository_count": cluster["repository_count"],
                    "repository_distribution": json.dumps(cluster["repository_distribution"], sort_keys=True),
                    "cohesion": cluster["cohesion"],
                    "is_singleton": cluster["is_singleton"],
                    "similar_patterns": json.dumps(cluster.get("similar_patterns") or []),
                    "needs_rereview": cluster.get("needs_rereview", False),
                    "rereview_reason": cluster.get("rereview_reason"),
                    "step_execution_id": step_execution_id,
                },
            )

            cur.execute("DELETE FROM pattern_candidate_members WHERE cluster_id = %s", (cluster["cluster_id"],))
            for member in cluster["members"]:
                cur.execute(
                    """
                    INSERT INTO pattern_candidate_members (
                        cluster_id, project_id, repository_id, classification_status,
                        similarity_to_signature, signal_count, classification_step_execution_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        cluster["cluster_id"],
                        member["project_id"],
                        member["repository_id"],
                        member["classification_status"],
                        member["similarity_to_signature"],
                        member["signal_count"],
                        member["classification_step_execution_id"],
                    ),
                )

        # A cluster whose members all disappeared is retained, not deleted
        # (Part D). Members disappear for ordinary reasons — a repository
        # was deregistered, or the projects finally classified because
        # someone added the pattern step 6 asked for, and in that second
        # case the disappearance is the success. Deleting the row would
        # discard the step 6 decision that caused it.
        cur.execute(
            """
            UPDATE pattern_candidate_clusters
            SET member_count = 0, repository_count = 0, repository_distribution = '{}'::jsonb,
                is_stale = true, last_seen_at = now(), step_execution_id = %s
            WHERE engagement_id = %s
              AND NOT (cluster_id = ANY(%s))
              AND is_stale = false
            """,
            (step_execution_id, engagement_id, seen_ids or [""]),
        )
        cur.execute(
            "DELETE FROM pattern_candidate_members WHERE cluster_id IN ("
            "  SELECT cluster_id FROM pattern_candidate_clusters"
            "  WHERE engagement_id = %s AND is_stale = true)",
            (engagement_id,),
        )
    conn.commit()


def stale_cluster_count(conn, engagement_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM pattern_candidate_clusters WHERE engagement_id = %s AND is_stale = true",
            (engagement_id,),
        )
        return cur.fetchone()["n"]


def apply_narration(conn, entries: list[dict]) -> None:
    """Narration lands on the cluster row so step 6 can render a name
    beside the shape it belongs to without parsing a file off disk.

    Advisory still means advisory: these columns are suggestions, never
    `patterns` rows, and step 6 edits them freely. A `human` naming_source
    is never overwritten by a later machine run — once a person has named
    a shape, re-running narration must not quietly replace their words.
    """
    with conn.cursor() as cur:
        for entry in entries:
            cur.execute(
                """
                UPDATE pattern_candidate_clusters
                SET suggested_name = %(name)s,
                    suggested_description = %(description)s,
                    suggested_pattern_id = %(slug)s,
                    narration_confidence = %(confidence)s,
                    naming_source = %(source)s,
                    narration_model_version = %(model)s,
                    narrated_at = CASE WHEN %(source)s = 'none' THEN narrated_at ELSE now() END
                WHERE cluster_id = %(cluster_id)s
                  AND naming_source <> 'human'
                """,
                {
                    "cluster_id": entry["cluster_id"],
                    "name": entry["suggested_name"],
                    "description": entry["suggested_description"],
                    "slug": entry["suggested_pattern_id"],
                    "confidence": entry["confidence"],
                    "source": entry["naming_source"],
                    "model": entry["model_version"],
                },
            )
    conn.commit()


def record_run(conn, engagement_id: str, step_execution_id: str | None, summary: dict,
               status: str, reason: str | None, narrated: int, output_dir: str | None,
               cluster_count: int) -> None:
    """`cluster_count` is passed in rather than read from `summary`, where
    it deliberately counts only non-singleton clusters. Every cluster is
    narrated, singleton or not, so taking it from the summary produced the
    nonsense row "0 clusters, 3 narrated"."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pattern_discovery_runs (
                engagement_id, step_execution_id, cluster_count, narrated_cluster_count,
                coverage_ratio, partial_estate, narration_status, narration_reason, output_dir
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                engagement_id,
                step_execution_id,
                cluster_count,
                narrated,
                summary["coverage"]["coverage_ratio"],
                summary["coverage"]["partial_estate"],
                status,
                reason,
                output_dir,
            ),
        )
    conn.commit()


def latest_run(conn, engagement_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, step_execution_id, cluster_count, narrated_cluster_count, coverage_ratio,
                   partial_estate, narration_status, narration_reason, output_dir, run_at
            FROM pattern_discovery_runs
            WHERE engagement_id = %s
            ORDER BY run_at DESC
            LIMIT 1
            """,
            (engagement_id,),
        )
        return cur.fetchone()


def clusters_for_narration(conn, engagement_id: str) -> list[dict]:
    """Re-reads what the last run clustered, in the shape narrate() wants.

    The retry action rebuilds this from the database rather than
    re-clustering: the deterministic artifact is unaffected by narration,
    so there is nothing to recompute, and recomputing it would risk
    producing a DIFFERENT clustering (the estate may have been rescanned
    since) and silently renaming shapes the human is mid-review on.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT cluster_id, canonical_signature, member_count, repository_count
            FROM pattern_candidate_clusters
            WHERE engagement_id = %s AND is_stale = false
            ORDER BY cluster_id
            """,
            (engagement_id,),
        )
        clusters = cur.fetchall()
        cur.execute(
            """
            SELECT m.cluster_id, p.relative_path AS project_path
            FROM pattern_candidate_members m
            JOIN pattern_candidate_clusters c ON c.cluster_id = m.cluster_id
            JOIN projects p ON p.id = m.project_id
            WHERE c.engagement_id = %s
            ORDER BY m.cluster_id, p.relative_path
            """,
            (engagement_id,),
        )
        members: dict[str, list[dict]] = {}
        for row in cur.fetchall():
            members.setdefault(row["cluster_id"], []).append({"project_path": row["project_path"]})

    return [
        {
            "cluster_id": c["cluster_id"],
            "canonical_signature": c["canonical_signature"],
            "member_count": c["member_count"],
            "repository_count": c["repository_count"],
            "members": members.get(c["cluster_id"], []),
        }
        for c in clusters
    ]
