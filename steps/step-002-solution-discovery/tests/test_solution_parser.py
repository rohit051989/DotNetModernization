import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from discovery import solution_parser

SAMPLE_SLN = """
Microsoft Visual Studio Solution File, Format Version 12.00
# Visual Studio Version 17
VisualStudioVersion = 17.0.31903.59
MinimumVisualStudioVersion = 10.0.40219.1
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Core", "src\\Core\\Core.csproj", "{11111111-1111-1111-1111-111111111111}"
EndProject
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Web", "src\\Web\\Web.csproj", "{22222222-2222-2222-2222-222222222222}"
EndProject
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Missing", "src\\Gone\\Gone.csproj", "{33333333-3333-3333-3333-333333333333}"
EndProject
Project("{2150E333-8FDC-42A3-9474-1A3956D46DE8}") = "Solution Items", "Solution Items", "{44444444-4444-4444-4444-444444444444}"
EndProject
Global
\tGlobalSection(NestedProjects) = preSolution
\t\t{11111111-1111-1111-1111-111111111111} = {44444444-4444-4444-4444-444444444444}
\tEndGlobalSection
EndGlobal
"""


class SolutionParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_sln(self, text: str) -> Path:
        path = self.repo_root / "MySolution.sln"
        path.write_text(text, encoding="utf-8")
        return path

    def test_parses_header_and_entries(self):
        path = self._write_sln(SAMPLE_SLN)
        result = solution_parser.parse(path, self.repo_root)

        self.assertEqual(result["parse_status"], "success")
        self.assertEqual(result["format_version"], "12.00")
        self.assertEqual(result["visual_studio_version"], "17.0.31903.59")
        self.assertEqual(result["minimum_vs_version"], "10.0.40219.1")
        self.assertEqual(len(result["entries"]), 4)

        folder_entries = [e for e in result["entries"] if e["is_folder"]]
        self.assertEqual(len(folder_entries), 1)
        self.assertEqual(folder_entries[0]["name"], "Solution Items")

    def test_nested_projects_maps_to_solution_folder(self):
        path = self._write_sln(SAMPLE_SLN)
        result = solution_parser.parse(path, self.repo_root)
        folder_names_by_guid = {e["project_guid"]: e["name"] for e in result["entries"] if e["is_folder"]}

        core_entry = next(e for e in result["entries"] if e["name"] == "Core")
        folder_path = solution_parser.solution_folder_path(
            core_entry["project_guid"], result["nested"], folder_names_by_guid
        )
        self.assertEqual(folder_path, "Solution Items")

        web_entry = next(e for e in result["entries"] if e["name"] == "Web")
        self.assertIsNone(
            solution_parser.solution_folder_path(web_entry["project_guid"], result["nested"], folder_names_by_guid)
        )

    def test_unrecognisable_file_fails(self):
        path = self.repo_root / "not-a-solution.sln"
        path.write_text("this is not a solution file\njust some text\n", encoding="utf-8")
        result = solution_parser.parse(path, self.repo_root)
        self.assertEqual(result["parse_status"], "failed")
        self.assertIsNotNone(result["parse_error"])

    def test_utf16_bom_parses(self):
        path = self.repo_root / "Utf16.sln"
        path.write_bytes(b"\xff\xfe" + SAMPLE_SLN.encode("utf-16-le"))
        result = solution_parser.parse(path, self.repo_root)
        self.assertEqual(result["parse_status"], "success")
        self.assertEqual(result["format_version"], "12.00")


if __name__ == "__main__":
    unittest.main()
