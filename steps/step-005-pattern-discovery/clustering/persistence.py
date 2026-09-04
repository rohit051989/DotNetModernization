"""Raw psycopg SQL — no ORM, since this package must not import
backend.app, where the SQLAlchemy models live (same rule as step 2 and
step 3; see discovery/persistence.py's docstring).

Two responsibilities, both engagement-scoped rather than repository-scoped
— this is what makes step 5 different from steps 1-4 (23-STEP-005 Part B):

1. Read every candidate application's step 3 signals across *every*
   in-scope repository in the engagement, in one query, straight from the
   `fingerprint_signals` / `project_fingerprints` tables step 3 already
   writes. This sidesteps the cross-execution artifact-resolution gap
   recorded in 23-STEP-005-PATTERN-DISCOVERY.md Part A3 entirely — step 5
   never needs to locate or parse any repository's
   `application-fingerprint.json` file, because the same data step 3 wrote
   into the artifact it also wrote into these tables. Only the DB path is
   used.
2. Wholesale-replace this engagement's `pattern_discovery_clusters` /
   `pattern_discovery_cluster_members` rows — delete by engagement_id, then
   insert — the same pattern step 2 uses for `repository_id` (Part C:
   "simpler than reconciling, and correct given the artifact is a
   point-in-time snapshot").
"""

from __future__ import annotations

import re

import psycopg
from psycopg.types.json import Json

_DRIVER_SUFFIX_RE = re.compile(r"^(postgres(?:ql)?)\+[^:]+://")

# Step 3 only writes usable signals for projects it actually analysed.
# `failed` / `skipped` / `not_supported` fingerprints carry no meaningful
# signal set and must not be treated as "an application with zero signals
# in common with everything" — they are excluded from clustering entirely,
# not folded in as trivial singletons.
_USABLE_FINGERPRINT_STATUS = ("complete", "partial")


def _normalize_database_url(database_url: str) -> str:
    return _DRIVER_SUFFIX_RE.sub(r"\1://", database_url)


def _pattern_classification_table_exists(cur) -> bool:
    """Step 4 (`pattern-classification`) now exists — see
    24-STEP-004-CLASSIFICATION.md. It writes one row per project to
    `project_classifications`, keyed by `project_id`, with a
    `classification_status` column whose values are `MATCHED`,
    `MULTIPLE_MATCHES`, `AMBIGUOUS`, `NOT_ELIGIBLE`,
    `INSUFFICIENT_FINGERPRINT`, `NO_PATTERN_MATCHED`, `SKIPPED` or
    `CLASSIFICATION_FAILED` (engine/classify.py `_classify_project`).
    Checked defensively via `information_schema` rather than importing
    anything step-4-owned (this package must not import `backend.app`, same
    rule as steps 2/3), and so a database that predates step 4's migration
    still degrades gracefully to the interim behaviour below."""
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'project_classifications')"
    )
    (exists,) = cur.fetchone()
    return bool(exists)


# Step 4 statuses that mean "the catalog does not have this application" —
# the population step 5 exists to cluster into candidate new patterns.
# `NOT_ELIGIBLE` (role-excluded) and `INSUFFICIENT_FINGERPRINT` /
# `SKIPPED` / `CLASSIFICATION_FAILED` (no usable evaluation) are
# deliberately excluded: those are not "unmatched, needs a new pattern",
# they're "step 4 couldn't or shouldn't judge this one" and clustering it
# would misrepresent it as coverage residue.
_UNMATCHED_CLASSIFICATION_STATUS = ("NO_PATTERN_MATCHED", "AMBIGUOUS")


def load_candidate_applications(database_url: str, engagement_id: str) -> dict[str, str]:
    """Returns `{project_id: repository_id}` (both as strings) for every
    application in scope for step 5, across the whole engagement.

    With step 4's `project_classifications` table present, a project is a
    candidate when it has never been classified at all (no row — step 4
    hasn't reached it yet) or when its `classification_status` is one of
    `_UNMATCHED_CLASSIFICATION_STATUS`. `MATCHED` / `MULTIPLE_MATCHES`
    projects are already in the catalog and drop out; `NOT_ELIGIBLE` /
    `INSUFFICIENT_FINGERPRINT` / `SKIPPED` / `CLASSIFICATION_FAILED`
    projects are excluded too (see `_UNMATCHED_CLASSIFICATION_STATUS`'s
    docstring). With no `project_classifications` table at all (a database
    that predates step 4's migration), every fingerprinted application is a
    candidate, same interim behaviour as before step 4 existed.
    """
    database_url = _normalize_database_url(database_url)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            has_classification = _pattern_classification_table_exists(cur)

            base_query = """
                SELECT pf.project_id, pf.repository_id
                FROM project_fingerprints pf
                JOIN repositories r ON r.id = pf.repository_id
                WHERE r.engagement_id = %s
                  AND r.deleted_at IS NULL
                  AND pf.fingerprint_status = ANY(%s)
            """
            if has_classification:
                cur.execute(
                    base_query
                    + """
                  AND (
                      NOT EXISTS (
                          SELECT 1 FROM project_classifications pc
                          WHERE pc.project_id = pf.project_id
                      )
                      OR EXISTS (
                          SELECT 1 FROM project_classifications pc
                          WHERE pc.project_id = pf.project_id
                            AND pc.classification_status = ANY(%s)
                      )
                  )
                """,
                    (
                        engagement_id,
                        list(_USABLE_FINGERPRINT_STATUS),
                        list(_UNMATCHED_CLASSIFICATION_STATUS),
                    ),
                )
            else:
                cur.execute(base_query, (engagement_id, list(_USABLE_FINGERPRINT_STATUS)))

            return {str(project_id): str(repository_id) for project_id, repository_id in cur.fetchall()}


def load_application_signals(database_url: str, project_ids: list[str]) -> dict[str, dict[str, str]]:
    """Returns `{project_id: {signal_name: signal_category}}` — one entry
    per *distinct* signal name for that project (Part C: names, not full
    signal rows; `fingerprint_signals` can carry several rows for the same
    name at different `source_path`s, which collapse to one entry here).
    Repository-level signals (`project_id IS NULL`) are out of scope for
    per-application similarity and are not read."""
    if not project_ids:
        return {}

    database_url = _normalize_database_url(database_url)
    result: dict[str, dict[str, str]] = {pid: {} for pid in project_ids}
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT project_id, signal_name, signal_category
                FROM fingerprint_signals
                WHERE project_id = ANY(%s)
                """,
                (project_ids,),
            )
            for project_id, signal_name, signal_category in cur.fetchall():
                result[str(project_id)][signal_name] = signal_category
    return result


def load_signal_details(database_url: str, project_ids: list[str]) -> dict[str, list[dict]]:
    """Returns `{project_id: [{name, category, type, value,
    occurrence_count}, ...]}` — richer than `load_application_signals`
    (which only needs `name`/`category` for the weighted-Jaccard formula).
    Used exclusively to build the pass-2 LLM summaries
    (`llm_client.LlmClient.summarize_application`) for the (typically much
    smaller) set of residue applications reaching pass 2 — never called for
    every candidate application, to keep this extra query cheap."""
    if not project_ids:
        return {}

    database_url = _normalize_database_url(database_url)
    result: dict[str, list[dict]] = {pid: [] for pid in project_ids}
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT project_id, signal_name, signal_category, signal_type, value, occurrence_count
                FROM fingerprint_signals
                WHERE project_id = ANY(%s)
                ORDER BY signal_category, signal_name, source_path
                """,
                (project_ids,),
            )
            for project_id, name, category, signal_type, value, occurrence_count in cur.fetchall():
                result[str(project_id)].append(
                    {
                        "name": name,
                        "category": category,
                        "type": signal_type,
                        "value": value,
                        "occurrence_count": occurrence_count,
                    }
                )
    return result


def replace_all(
    database_url: str,
    engagement_id: str,
    *,
    rows: list[dict],
    repository_of: dict[str, str],
    source_job_execution_id: str | None,
) -> None:
    """One transaction: delete every `pattern_discovery_clusters` /
    `pattern_discovery_cluster_members` row this step owns for the
    engagement, then insert the fresh clustering result. `rows` is the
    output of `clustering.assembly.assemble_rows` — each row already
    carries its assigned `id`, a `members` list and `member_similarities`.
    `repository_of` maps every candidate `project_id` to its
    `repository_id` (from `persistence.load_candidate_applications`) —
    passed once here rather than duplicated onto every row."""
    database_url = _normalize_database_url(database_url)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM pattern_discovery_cluster_members WHERE cluster_id IN "
                "(SELECT id FROM pattern_discovery_clusters WHERE engagement_id = %s)",
                (engagement_id,),
            )
            cur.execute("DELETE FROM pattern_discovery_clusters WHERE engagement_id = %s", (engagement_id,))

            for row in rows:
                cur.execute(
                    """
                    INSERT INTO pattern_discovery_clusters (
                        id, engagement_id, status, formation_method, member_count,
                        common_signals, similarity_score, similarity_method,
                        review_priority, source_job_execution_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row["id"],
                        engagement_id,
                        row["status"],
                        row["formation_method"],
                        len(row["members"]),
                        Json(row["common_signals"]),
                        row["similarity_score"],
                        row["similarity_method"],
                        row["review_priority"],
                        source_job_execution_id,
                    ),
                )
                member_similarities = row["member_similarities"]
                for project_id in row["members"]:
                    cur.execute(
                        """
                        INSERT INTO pattern_discovery_cluster_members (
                            cluster_id, project_id, repository_id, similarity_to_cluster
                        ) VALUES (%s, %s, %s, %s)
                        """,
                        (
                            row["id"],
                            project_id,
                            repository_of[project_id],
                            member_similarities.get(project_id),
                        ),
                    )
