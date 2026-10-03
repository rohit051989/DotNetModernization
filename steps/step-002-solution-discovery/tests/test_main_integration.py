"""End-to-end test for `run()` — parses a small fabricated repository,
persists to a real Postgres (this codebase does not mock the DB), and
checks the artifact file. Does not import backend.app: sets up its own
`repositories` row via raw psycopg, same as main.py itself does.

Requires the platform's dev Postgres to be reachable. Set DATABASE_URL
(plain `postgresql://` form) to override; defaults to the local dev
database from docker/docker-compose.yml.
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

import main as step_main

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://catalog:catalog_dev_pw@localhost:5433/modernization_catalog"
)

LEGACY_CSPROJ = """<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup>
    <TargetFrameworkVersion>v4.7.2</TargetFrameworkVersion>
    <OutputType>Library</OutputType>
  </PropertyGroup>
</Project>
"""

SDK_CSPROJ_TEMPLATE = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net6.0</TargetFramework>
  </PropertyGroup>
  <ItemGroup>
    <ProjectReference Include="{reference}" />
  </ItemGroup>
</Project>
"""

STANDALONE_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net6.0</TargetFramework>
  </PropertyGroup>
</Project>
"""


def _sln(entries: list[tuple[str, str, str]]) -> str:
    lines = ["Microsoft Visual Studio Solution File, Format Version 12.00", "VisualStudioVersion = 17.0.31903.59"]
    for name, raw_path, guid in entries:
        lines.append(f'Project("{{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}}") = "{name}", "{raw_path}", "{{{guid}}}"')
        lines.append("EndProject")
    return "\n".join(lines) + "\n"


class MainIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tmp.name) / "repo"
        self.repo_root.mkdir()
        self.output_dir = Path(self.tmp.name) / "out"

        self.repository_id = str(uuid.uuid4())
        # Its own engagement, so the test does not depend on client data
        # that a demo reset (scripts/reset-demo.ps1) is free to remove.
        self.engagement_id = f"step2-integration-test-{self.repository_id[:8]}"
        self.conn = psycopg.connect(DATABASE_URL)
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO engagements (id, client_name) VALUES (%s, %s)",
                (self.engagement_id, "step 2 integration test"),
            )
            cur.execute(
                """
                INSERT INTO repositories (
                    id, engagement_id, name, root_folder_name, slug, local_path,
                    local_path_normalised, clone_url, clone_url_normalised, source_type, ingest_status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    self.repository_id,
                    self.engagement_id,
                    "step2-integration-test",
                    "repo",
                    f"step2-integration-test-{self.repository_id[:8]}",
                    str(self.repo_root),
                    str(self.repo_root).lower(),
                    "https://github.com/example/step2-integration-test.git",
                    "https://github.com/example/step2-integration-test",
                    "local_path",
                    "registered",
                ),
            )
        self.conn.commit()

    def tearDown(self):
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM repositories WHERE id = %s", (self.repository_id,))
            cur.execute("DELETE FROM engagements WHERE id = %s", (self.engagement_id,))
        self.conn.commit()
        self.conn.close()
        self.tmp.cleanup()

    def _write(self, relative: str, text: str) -> None:
        path = self.repo_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _make_context(self) -> dict:
        inventory = {"local_path": str(self.repo_root), "slug": "step2-integration-test"}
        inventory_path = Path(self.tmp.name) / "repository-inventory.json"
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
        return {
            "envelope_version": "1.0",
            "step_name": "solution-discovery",
            "step_version": "1.0.0",
            "job_name": "phase0-repository-discovery",
            "job_execution_id": str(uuid.uuid4()),
            "step_execution_id": str(uuid.uuid4()),
            "parameters": {"engagement_id": self.engagement_id, "repository_id": self.repository_id},
            "inputs": {
                "repository-inventory": {
                    "artifact_type": "repository-inventory",
                    "artifact_version": "1.1.0",
                    "uri": inventory_path.as_uri(),
                    "checksum": "sha256:0",
                }
            },
            "working_dir": str(Path(self.tmp.name) / "work"),
            "output_dir": str(self.output_dir),
            "database_url": DATABASE_URL,
        }

    def test_multi_project_solution_standalone_and_shared_project(self):
        # Solution A references Core and Web. Solution B also references Core
        # (making it shared), and a "Missing" entry with no file on disk.
        self._write("src/Core/Core.csproj", LEGACY_CSPROJ)
        self._write("src/Web/Web.csproj", SDK_CSPROJ_TEMPLATE.format(reference="..\\Core\\Core.csproj"))
        self._write("src/Standalone/Standalone.csproj", STANDALONE_CSPROJ)
        self._write(
            "SolutionA.sln",
            _sln(
                [
                    ("Core", "src\\Core\\Core.csproj", "11111111-1111-1111-1111-111111111111"),
                    ("Web", "src\\Web\\Web.csproj", "22222222-2222-2222-2222-222222222222"),
                ]
            ),
        )
        self._write(
            "SolutionB.sln",
            _sln(
                [
                    ("Core", "src\\Core\\Core.csproj", "33333333-3333-3333-3333-333333333333"),
                    ("Gone", "src\\Gone\\Gone.csproj", "44444444-4444-4444-4444-444444444444"),
                ]
            ),
        )

        result = step_main.run(self._make_context())

        self.assertEqual(result["exit_status"], "COMPLETED")
        self.assertEqual(len(result["outputs"]), 1)

        with self.conn.cursor() as cur:
            cur.execute("SELECT scan_status, solution_count, project_file_count, standalone_project_count, "
                        "shared_project_count, unresolved_reference_count FROM repository_structure WHERE repository_id = %s",
                        (self.repository_id,))
            row = cur.fetchone()
        self.assertEqual(row[0], "complete")
        self.assertEqual(row[1], 2)  # two solutions
        self.assertEqual(row[2], 3)  # Core, Web, Standalone
        self.assertEqual(row[3], 1)  # Standalone
        self.assertEqual(row[4], 1)  # Core, shared across A and B
        self.assertEqual(row[5], 1)  # "Gone" entry in Solution B

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT is_standalone, solution_membership_count FROM projects "
                "WHERE repository_id = %s AND relative_path = 'src/Standalone/Standalone.csproj'",
                (self.repository_id,),
            )
            standalone_row = cur.fetchone()
        self.assertEqual(standalone_row, (True, 0))

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT resolution_status FROM project_references WHERE source_project_id = "
                "(SELECT id FROM projects WHERE repository_id = %s AND relative_path = 'src/Web/Web.csproj')",
                (self.repository_id,),
            )
            reference_status = cur.fetchone()[0]
        self.assertEqual(reference_status, "resolved")

        artifact_path = self.output_dir / "solution-project-inventory.json"
        self.assertTrue(artifact_path.exists())
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        self.assertNotIn("generated_at", artifact)
        self.assertEqual(artifact["summary"]["shared_project_count"], 1)

    def test_project_reference_outside_repository_is_external(self):
        self._write("src/App/App.csproj", SDK_CSPROJ_TEMPLATE.format(reference="..\\..\\..\\Elsewhere\\Elsewhere.csproj"))

        result = step_main.run(self._make_context())
        self.assertEqual(result["exit_status"], "COMPLETED")

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT resolution_status FROM project_references WHERE source_project_id = "
                "(SELECT id FROM projects WHERE repository_id = %s)",
                (self.repository_id,),
            )
            status = cur.fetchone()[0]
        self.assertEqual(status, "external_repository")

    def test_unknown_project_extension_counted_not_skipped_and_does_not_degrade_scan_status(self):
        self._write("src/Weird/Weird.xproj", "<Project></Project>")

        result = step_main.run(self._make_context())
        self.assertEqual(result["exit_status"], "COMPLETED")

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT scan_status, unknown_project_count, out_of_scope_project_count, failed_parse_count "
                "FROM repository_structure WHERE repository_id = %s",
                (self.repository_id,),
            )
            row = cur.fetchone()
        self.assertEqual(row, ("complete", 1, 0, 0))

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT parse_status FROM projects WHERE repository_id = %s AND relative_path = 'src/Weird/Weird.xproj'",
                (self.repository_id,),
            )
            parse_status = cur.fetchone()[0]
        self.assertEqual(parse_status, "out_of_scope")

    def test_known_non_dotnet_project_type_does_not_degrade_scan_status(self):
        self._write("docker-compose.dcproj", "<Project></Project>")
        self._write("frontend/app.esproj", "<Project></Project>")

        result = step_main.run(self._make_context())
        self.assertEqual(result["exit_status"], "COMPLETED")

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT scan_status, out_of_scope_project_count, unknown_project_count, failed_parse_count "
                "FROM repository_structure WHERE repository_id = %s",
                (self.repository_id,),
            )
            row = cur.fetchone()
        self.assertEqual(row, ("complete", 2, 0, 0))

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT relative_path, structural_type, parse_status FROM projects WHERE repository_id = %s ORDER BY relative_path",
                (self.repository_id,),
            )
            rows = cur.fetchall()
        self.assertEqual(
            rows,
            [
                ("docker-compose.dcproj", "docker_compose_project", "success"),
                ("frontend/app.esproj", "javascript_project", "success"),
            ],
        )

    def test_malformed_dotnet_project_drives_partial_scan_status(self):
        self._write("src/Core/Core.csproj", LEGACY_CSPROJ)
        self._write("src/Broken/Broken.csproj", "<Project><Unclosed>")

        result = step_main.run(self._make_context())
        self.assertEqual(result["exit_status"], "COMPLETED")

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT scan_status, failed_parse_count FROM repository_structure WHERE repository_id = %s",
                (self.repository_id,),
            )
            row = cur.fetchone()
        self.assertEqual(row, ("partial", 1))

    def test_no_dotnet_projects_completes_cleanly(self):
        (self.repo_root / "README.md").write_text("nothing to see here\n", encoding="utf-8")

        result = step_main.run(self._make_context())
        self.assertEqual(result["exit_status"], "COMPLETED")

        with self.conn.cursor() as cur:
            cur.execute("SELECT scan_status, solution_count, project_file_count FROM repository_structure WHERE repository_id = %s", (self.repository_id,))
            row = cur.fetchone()
        self.assertEqual(row, ("complete", 0, 0))

    def test_rescan_replaces_rows_without_duplicates(self):
        self._write("src/Core/Core.csproj", LEGACY_CSPROJ)

        step_main.run(self._make_context())
        step_main.run(self._make_context())

        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM projects WHERE repository_id = %s", (self.repository_id,))
            count = cur.fetchone()[0]
        self.assertEqual(count, 1)

    def test_two_runs_over_unchanged_repository_produce_identical_checksums(self):
        self._write("src/Core/Core.csproj", LEGACY_CSPROJ)

        result1 = step_main.run(self._make_context())
        result2 = step_main.run(self._make_context())

        self.assertEqual(result1["outputs"][0]["checksum"], result2["outputs"][0]["checksum"])


if __name__ == "__main__":
    unittest.main()
