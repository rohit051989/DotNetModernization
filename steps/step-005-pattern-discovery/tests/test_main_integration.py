"""End-to-end test for `run()` against a real Postgres (this codebase does
not mock the DB — same rule as step 2's own integration test). Sets up
fabricated `repositories` / `projects` / `project_fingerprints` /
`fingerprint_signals` rows via raw psycopg — the exact tables step 3
writes — then runs step 5 against them and checks both the
`pattern_discovery_clusters` / `pattern_discovery_cluster_members` rows and
the artifact file.

Requires the platform's dev Postgres to be reachable and migrated to head.
Set DATABASE_URL (plain `postgresql://` form) to override; defaults to the
local dev database from docker/docker-compose.yml. No ANTHROPIC_API_KEY is
required or used here: with none configured, `LlmClient.available` is
False and pass 2 is skipped, so this test's residue applications land in
`unclustered` — the actual, honest behaviour of an environment with no LLM
credentials configured, not a mocked shortcut.
"""

import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from psycopg.types.json import Json

import main as step_main

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://catalog:catalog_dev_pw@localhost:5433/modernization_catalog"
)
ENGAGEMENT_ID = "client-a-ocp4"  # seeded by backend/app/seed


class MainIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.tmp.name) / "out"
        self.conn = psycopg.connect(DATABASE_URL)
        self.repository_ids: list[str] = []
        self.project_ids: list[str] = []

    def tearDown(self):
        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM pattern_discovery_cluster_members WHERE cluster_id IN "
                "(SELECT id FROM pattern_discovery_clusters WHERE engagement_id = %s)",
                (ENGAGEMENT_ID,),
            )
            cur.execute("DELETE FROM pattern_discovery_clusters WHERE engagement_id = %s", (ENGAGEMENT_ID,))
            for repository_id in self.repository_ids:
                cur.execute("DELETE FROM repositories WHERE id = %s", (repository_id,))
        self.conn.commit()
        self.conn.close()
        self.tmp.cleanup()

    def _make_repository(self, name: str) -> str:
        repository_id = str(uuid.uuid4())
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO repositories (
                    id, engagement_id, name, root_folder_name, slug, local_path,
                    local_path_normalised, clone_url, clone_url_normalised, source_type, ingest_status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repository_id,
                    ENGAGEMENT_ID,
                    name,
                    name,
                    f"{name}-{repository_id[:8]}",
                    f"/tmp/{name}",
                    f"/tmp/{name}".lower(),
                    f"https://github.com/example/{name}.git",
                    f"https://github.com/example/{name}",
                    "local_path",
                    "registered",
                ),
            )
        self.conn.commit()
        self.repository_ids.append(repository_id)
        return repository_id

    def _make_fingerprinted_project(self, repository_id: str, name: str, signals: list[tuple[str, str]]) -> str:
        project_id = str(uuid.uuid4())
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO projects (
                    id, repository_id, name, relative_path, extension, structural_type,
                    project_format, language, package_management_style, parse_status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    project_id,
                    repository_id,
                    name,
                    f"src/{name}/{name}.csproj",
                    ".csproj",
                    "application_project",
                    "sdk_style",
                    "csharp",
                    "packagereference",
                    "success",
                ),
            )
            cur.execute(
                """
                INSERT INTO project_fingerprints (
                    project_id, repository_id, fingerprint_status, scanner_version, analysis_capabilities
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (project_id, repository_id, "complete", "test-scanner-1.0.0", Json({})),
            )
            for signal_name, signal_category in signals:
                cur.execute(
                    """
                    INSERT INTO fingerprint_signals (
                        project_id, repository_id, signal_name, signal_category, signal_type,
                        source_type, extractor, extraction_confidence
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (project_id, repository_id, signal_name, signal_category, "FILE_PRESENCE", "FILE_STRUCTURE", "test", 1.0),
                )
        self.conn.commit()
        self.project_ids.append(project_id)
        return project_id

    def _make_context(self) -> dict:
        return {
            "envelope_version": "1.0",
            "step_name": "pattern-discovery-clustering",
            "step_version": "1.0.0",
            "job_name": "phase0-estate-consolidation",
            "job_execution_id": str(uuid.uuid4()),
            "step_execution_id": str(uuid.uuid4()),
            "parameters": {"engagement_id": ENGAGEMENT_ID},
            "config": {},
            "working_dir": str(Path(self.tmp.name) / "work"),
            "output_dir": str(self.output_dir),
            "database_url": DATABASE_URL,
        }

    def test_two_identical_apps_cluster_one_distinct_app_is_unclustered(self):
        repo_a = self._make_repository("step5-repo-a")
        repo_b = self._make_repository("step5-repo-b")
        shared_signals = [("IIS_HOSTED_ASPX", "HOSTING_INDICATOR"), ("WEBFORMS_PAGE_BASE", "SOURCE_CONSTRUCT")]
        self._make_fingerprinted_project(repo_a, "app-alpha", shared_signals)
        self._make_fingerprinted_project(repo_b, "app-beta", shared_signals)
        self._make_fingerprinted_project(repo_a, "app-gamma", [("WCF_SERVICE_CONTRACT", "ENTRY_POINT")])

        result = step_main.run(self._make_context())

        self.assertEqual(result["exit_status"], "COMPLETED")
        self.assertEqual(len(result["outputs"]), 1)
        self.assertEqual(result["metrics"]["read_count"], 3)

        artifact_path = Path(result["outputs"][0]["uri"].removeprefix("file://"))
        artifact = json.loads(artifact_path.read_text())
        self.assertEqual(artifact["artifact_type"], "pattern-discovery-clusters")
        self.assertEqual(artifact["summary"]["candidate_pattern_count"], 1)
        self.assertEqual(artifact["summary"]["unclustered_count"], 1)

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT status, member_count, common_signals, similarity_score FROM pattern_discovery_clusters "
                "WHERE engagement_id = %s ORDER BY id",
                (ENGAGEMENT_ID,),
            )
            rows = cur.fetchall()
        self.assertEqual(len(rows), 2)
        statuses = sorted(r[0] for r in rows)
        self.assertEqual(statuses, ["candidate_pattern", "unclustered"])
        candidate_row = next(r for r in rows if r[0] == "candidate_pattern")
        self.assertEqual(candidate_row[1], 2)  # member_count
        self.assertEqual({s["name"] for s in candidate_row[2]}, {"IIS_HOSTED_ASPX", "WEBFORMS_PAGE_BASE"})
        self.assertEqual(float(candidate_row[3]), 1.0)

    def test_rerun_with_unchanged_input_is_idempotent(self):
        repo_a = self._make_repository("step5-repo-idempotent-a")
        repo_b = self._make_repository("step5-repo-idempotent-b")
        shared_signals = [("IIS_HOSTED_ASPX", "HOSTING_INDICATOR")]
        self._make_fingerprinted_project(repo_a, "app-one", shared_signals)
        self._make_fingerprinted_project(repo_b, "app-two", shared_signals)

        context = self._make_context()
        first = step_main.run(context)
        with self.conn.cursor() as cur:
            cur.execute("SELECT id FROM pattern_discovery_clusters WHERE engagement_id = %s ORDER BY id", (ENGAGEMENT_ID,))
            first_ids = [r[0] for r in cur.fetchall()]

        second = step_main.run(self._make_context())
        with self.conn.cursor() as cur:
            cur.execute("SELECT id FROM pattern_discovery_clusters WHERE engagement_id = %s ORDER BY id", (ENGAGEMENT_ID,))
            second_ids = [r[0] for r in cur.fetchall()]

        self.assertEqual(first["exit_status"], "COMPLETED")
        self.assertEqual(second["exit_status"], "COMPLETED")
        self.assertEqual(first_ids, second_ids)

    def test_no_candidate_applications_completes_cleanly(self):
        result = step_main.run(self._make_context())
        self.assertEqual(result["exit_status"], "COMPLETED")
        self.assertEqual(result["metrics"]["read_count"], 0)


if __name__ == "__main__":
    unittest.main()
