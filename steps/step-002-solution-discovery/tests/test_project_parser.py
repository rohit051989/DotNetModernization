import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from discovery import project_parser

LEGACY_CSPROJ = """<?xml version="1.0" encoding="utf-8"?>
<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup>
    <TargetFrameworkVersion>v4.7.2</TargetFrameworkVersion>
    <OutputType>Library</OutputType>
    <AssemblyName>Legacy.Core</AssemblyName>
    <RootNamespace>Legacy.Core</RootNamespace>
  </PropertyGroup>
  <ItemGroup>
    <ProjectReference Include="..\\Other\\Other.csproj" />
  </ItemGroup>
</Project>
"""

SDK_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net6.0</TargetFramework>
    <OutputType>Exe</OutputType>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Newtonsoft.Json" Version="13.0.1" />
  </ItemGroup>
</Project>
"""

SDK_MULTI_TARGET_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFrameworks>net472;net6.0</TargetFrameworks>
  </PropertyGroup>
</Project>
"""

PACKAGES_CONFIG = """<?xml version="1.0" encoding="utf-8"?>
<packages>
  <package id="log4net" version="2.0.15" targetFramework="net472" />
</packages>
"""


class ProjectParserExtensionTests(unittest.TestCase):
    def test_extension_map_covers_part_d(self):
        cases = {
            ".csproj": ("csharp_project", "csharp"),
            ".vbproj": ("vb_project", "vb"),
            ".fsproj": ("fsharp_project", "fsharp"),
            ".sqlproj": ("sql_database_project", "sql"),
            ".dtproj": ("ssis_project", "ssis"),
            ".shproj": ("shared_project", "shared"),
            ".vcxproj": ("cpp_project", "cpp"),
        }
        for extension, expected in cases.items():
            self.assertEqual(project_parser.EXTENSION_MAP[extension], expected)


class ProjectParserParseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, relative: str, text: str, encoding="utf-8") -> Path:
        path = self.repo_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if encoding == "utf-8":
            path.write_text(text, encoding="utf-8")
        else:
            path.write_bytes(text.encode(encoding))
        return path

    def test_legacy_project_parses(self):
        path = self._write("src/Legacy/Legacy.csproj", LEGACY_CSPROJ)
        result = project_parser.parse(path, self.repo_root)

        self.assertEqual(result["parse_status"], "success")
        self.assertEqual(result["project_format"], "legacy_msbuild")
        self.assertEqual(result["structural_type"], "csharp_project")
        self.assertEqual(result["target_framework_raw"], "v4.7.2")
        self.assertEqual(result["target_frameworks_raw"], ["v4.7.2"])
        self.assertFalse(result["is_multi_targeting"])
        self.assertEqual(result["output_type"], "Library")
        self.assertEqual(result["assembly_name"], "Legacy.Core")
        self.assertEqual(result["root_namespace"], "Legacy.Core")
        self.assertEqual(len(result["project_references"]), 1)
        self.assertEqual(result["project_references"][0]["raw_path"], "..\\Other\\Other.csproj")

    def test_a_project_reference_declared_twice_is_recorded_once_with_a_warning(self):
        path = self._write("src/App/App.csproj", """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>
  <ItemGroup>
    <ProjectReference Include="..\\Domain\\Domain.csproj" />
    <ProjectReference Include="..\\Core\\Core.csproj" />
  </ItemGroup>
  <ItemGroup>
    <ProjectReference Include="..\\Domain\\Domain.csproj" />
  </ItemGroup>
</Project>
""")
        result = project_parser.parse(path, self.repo_root)

        self.assertEqual(result["parse_status"], "success")
        self.assertEqual([r["raw_path"] for r in result["project_references"]], ["..\\Domain\\Domain.csproj", "..\\Core\\Core.csproj"])
        self.assertEqual(result["parse_warnings"], ["ProjectReference '..\\Domain\\Domain.csproj' is declared more than once; recorded once"])

    def test_references_differing_only_in_slashes_or_case_are_one_reference(self):
        path = self._write("src/App/App.csproj", """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>
  <ItemGroup>
    <ProjectReference Include="..\\Domain\\Domain.csproj" />
    <ProjectReference Include="../domain/Domain.csproj" />
  </ItemGroup>
</Project>
""")
        result = project_parser.parse(path, self.repo_root)

        self.assertEqual([r["raw_path"] for r in result["project_references"]], ["..\\Domain\\Domain.csproj"])
        self.assertEqual(result["parse_warnings"],
                         ["ProjectReference '../domain/Domain.csproj' is declared more than once (as '..\\Domain\\Domain.csproj'); recorded once"])

    def test_sdk_style_project_parses(self):
        path = self._write("src/Web/Web.csproj", SDK_CSPROJ)
        result = project_parser.parse(path, self.repo_root)

        self.assertEqual(result["parse_status"], "success")
        self.assertEqual(result["project_format"], "sdk_style")
        self.assertEqual(result["target_framework_raw"], "net6.0")
        self.assertEqual(result["output_type"], "Exe")
        self.assertEqual(len(result["packages"]), 1)
        self.assertEqual(result["packages"][0]["package_name"], "Newtonsoft.Json")
        self.assertEqual(result["packages"][0]["version_raw"], "13.0.1")
        self.assertEqual(result["package_management_style"], "packagereference")

    def test_framework_from_directory_packages_props_when_the_project_has_none(self):
        """eShopOnWeb sets TargetFramework once, in Directory.Packages.props."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Directory.Packages.props").write_text(
                "<Project><PropertyGroup><Tfm>net8.0</Tfm><TargetFramework>$(Tfm)</TargetFramework></PropertyGroup></Project>",
                encoding="utf-8",
            )
            project = root / "src" / "Web" / "Web.csproj"
            project.parent.mkdir(parents=True)
            project.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><Nullable>enable</Nullable></PropertyGroup></Project>', encoding="utf-8")
            result = project_parser.parse(project, root)
        self.assertEqual(result["target_frameworks_raw"], ["net8.0"])
        self.assertEqual(result["target_framework_source"], "Directory.Packages.props")

    def test_project_file_framework_wins_and_packages_props_overrides_build_props(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Directory.Build.props").write_text(
                "<Project><PropertyGroup><TargetFramework>net6.0</TargetFramework></PropertyGroup></Project>", encoding="utf-8")
            (root / "Directory.Packages.props").write_text(
                "<Project><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>", encoding="utf-8")
            inherits = root / "a" / "A.csproj"
            inherits.parent.mkdir()
            inherits.write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>', encoding="utf-8")
            own = root / "b" / "B.csproj"
            own.parent.mkdir()
            own.write_text(SDK_CSPROJ, encoding="utf-8")
            a = project_parser.parse(inherits, root)
            b = project_parser.parse(own, root)
        self.assertEqual((a["target_framework_raw"], a["target_framework_source"]), ("net8.0", "Directory.Packages.props"))
        self.assertEqual((b["target_framework_raw"], b["target_framework_source"]), ("net6.0", "project"))

    def test_sdk_and_output_type_are_known_not_null(self):
        """Later steps treat null as unknown, so what MSBuild defines is recorded."""
        cases = [
            ('<Project Sdk="Microsoft.NET.Sdk.BlazorWebAssembly"></Project>', "Microsoft.NET.Sdk.BlazorWebAssembly", "Exe", "sdk_default"),
            ('<Project Sdk="Microsoft.NET.Sdk.Web/8.0.0"></Project>', "Microsoft.NET.Sdk.Web", "Exe", "sdk_default"),
            ('<Project Sdk="Microsoft.NET.Sdk"></Project>', "Microsoft.NET.Sdk", "Library", "sdk_default"),
            ('<Project><Sdk Name="Microsoft.NET.Sdk.Worker" /></Project>', "Microsoft.NET.Sdk.Worker", "Exe", "sdk_default"),
            ('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>WinExe</OutputType></PropertyGroup></Project>', "Microsoft.NET.Sdk", "WinExe", "project"),
            (LEGACY_CSPROJ, "none", "Library", "project"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i, (xml, sdk, output_type, source) in enumerate(cases):
                project = root / f"P{i}" / f"P{i}.csproj"
                project.parent.mkdir()
                project.write_text(xml, encoding="utf-8")
                result = project_parser.parse(project, root)
                with self.subTest(sdk=sdk, output_type=output_type):
                    self.assertEqual((result["project_sdk"], result["output_type"], result["output_type_source"]), (sdk, output_type, source))

    def test_output_type_from_directory_build_props(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Directory.Build.props").write_text(
                "<Project><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup></Project>", encoding="utf-8")
            project = root / "A.csproj"
            project.write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>', encoding="utf-8")
            result = project_parser.parse(project, root)
        self.assertEqual((result["output_type"], result["output_type_source"]), ("Exe", "Directory.Build.props"))

    def test_conditional_props_value_is_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Directory.Build.props").write_text(
                "<Project><PropertyGroup Condition=\"'$(X)' == 'y'\"><TargetFramework>net6.0</TargetFramework></PropertyGroup></Project>",
                encoding="utf-8")
            project = root / "A.csproj"
            project.write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>', encoding="utf-8")
            result = project_parser.parse(project, root)
        self.assertEqual((result["target_frameworks_raw"], result["target_framework_source"]), (None, None))

    def test_multi_targeting_records_all_frameworks(self):
        path = self._write("src/Multi/Multi.csproj", SDK_MULTI_TARGET_CSPROJ)
        result = project_parser.parse(path, self.repo_root)

        self.assertEqual(result["target_frameworks_raw"], ["net472", "net6.0"])
        self.assertEqual(result["target_framework_raw"], "net472")  # first declared, verbatim
        self.assertTrue(result["is_multi_targeting"])

    def test_packages_config_detected_and_parsed(self):
        self._write("src/Old/packages.config", PACKAGES_CONFIG)
        path = self._write("src/Old/Old.csproj", LEGACY_CSPROJ)
        result = project_parser.parse(path, self.repo_root)

        self.assertTrue(result["has_packages_config"])
        config_packages = [p for p in result["packages"] if p["declaration_source"] == "packages_config"]
        self.assertEqual(len(config_packages), 1)
        self.assertEqual(config_packages[0]["package_name"], "log4net")
        self.assertEqual(result["package_management_style"], "packages_config")

    def test_unknown_extension_is_out_of_scope_not_failed(self):
        path = self._write("src/Weird/Weird.xproj", "<Project></Project>")
        result = project_parser.parse(path, self.repo_root)

        self.assertEqual(result["structural_type"], "unknown_project")
        self.assertEqual(result["language"], "unknown")
        self.assertEqual(result["parse_status"], "out_of_scope")
        self.assertEqual(result["parse_warnings"], ["unrecognised project extension, recorded but not analysed"])

    def test_known_non_dotnet_extensions_are_success_with_no_metadata(self):
        cases = {
            "docker-compose.dcproj": ("docker_compose_project", "Docker Compose"),
            "frontend.njsproj": ("nodejs_project", "Node.js"),
            "scripts.pyproj": ("python_project", "Python"),
            "app.esproj": ("javascript_project", "JavaScript"),
            "installer.wapproj": ("windows_packaging_project", "Windows Packaging"),
            "setup.wixproj": ("wix_installer_project", "WiX installer"),
            "release.deployproj": ("deployment_project", "Deployment"),
            "model.modelproj": ("modeling_project", "Modeling"),
        }
        for filename, (structural_type, label) in cases.items():
            path = self._write(filename, "<Project></Project>")
            result = project_parser.parse(path, self.repo_root)

            self.assertEqual(result["structural_type"], structural_type, filename)
            self.assertEqual(result["language"], "unknown", filename)
            self.assertEqual(result["parse_status"], "success", filename)
            self.assertEqual(result["target_framework_raw"], None, filename)
            self.assertEqual(
                result["parse_warnings"],
                [f"{label} project, recorded but not analysed (not a .NET project)"],
                filename,
            )

    def test_malformed_xml_recorded_not_skipped(self):
        path = self._write("src/Broken/Broken.csproj", "<Project><Unclosed>")
        result = project_parser.parse(path, self.repo_root)

        self.assertEqual(result["structural_type"], "csharp_project")  # extension-based, still recorded
        self.assertEqual(result["parse_status"], "failed")
        self.assertTrue(result["parse_warnings"])
        self.assertTrue(result["parse_warnings"][-1].startswith("parse failed:"))

    def test_bom_prefixed_project_parses(self):
        path = self.repo_root / "Bom.csproj"
        path.write_bytes(b"\xef\xbb\xbf" + LEGACY_CSPROJ.encode("utf-8"))
        result = project_parser.parse(path, self.repo_root)
        self.assertEqual(result["parse_status"], "success")
        self.assertEqual(result["target_framework_raw"], "v4.7.2")

    def test_sqlproj_and_dtproj_structural_types(self):
        sql_path = self._write("db/Database.sqlproj", '<Project Sdk="Microsoft.Build.Sql"></Project>')
        dtproj_path = self._write("etl/Package.dtproj", "<DtProj></DtProj>")

        sql_result = project_parser.parse(sql_path, self.repo_root)
        dtproj_result = project_parser.parse(dtproj_path, self.repo_root)

        self.assertEqual(sql_result["structural_type"], "sql_database_project")
        self.assertEqual(sql_result["language"], "sql")
        self.assertEqual(dtproj_result["structural_type"], "ssis_project")
        self.assertEqual(dtproj_result["language"], "ssis")


if __name__ == "__main__":
    unittest.main()
