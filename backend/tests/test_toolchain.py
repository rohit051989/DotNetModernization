"""Whether a machine can build and test a repository's baseline on its own frameworks (36-COPILOT-ENHANCED-CONVERSION.md
Part P; app.toolchain).

The machine is stood in for by folders: a .NET install is a folder with a dotnet.exe (only its PE header, which says
its architecture), sdk\\<version> and shared\\<framework>\\<version> folders; the reference assemblies are
v<version>\\mscorlib.dll folders. Nothing is run.

- a .NET 8 test project on a machine whose platform dotnet has only .NET 10, with .NET 8 in the machine-wide x64 and
  x86 installs: not ready, "Baseline tests cannot run here: needs the .NET 8 runtime (x64)", saying where it is;
- the same with .NET 8 in the platform's dotnet: ready;
- a legacy .NET Framework 4.7.2 project without its reference assemblies: the baseline cannot build;
- a legacy web application project needs the web application targets where dotnet build finds them; a test project
  reaching a web project needs the ASP.NET Core runtime;
- from the database: the projects in scope, the route on the repository's own machine (checked now and recorded)
  and on another (what its machine recorded), and the package step refusing with the summary.

Uses stdlib unittest, same rationale as test_repository_ingest.py.
"""
import contextlib
import os
import struct
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from app import models
from app.auth import machine as host_machine, service as auth_service
from app.db import SessionLocal
from app.main import app
from app.toolchain import machine, needs, service
from tests.asgi_client import Client

ENGAGEMENT = "t-engagement-toolchain"
PASSWORD = "a-long-enough-password"


def executable(path: Path, arch: int) -> None:
    """A file with only a PE header: enough for machine.architecture."""
    head = bytearray(0x100)
    head[0:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, 0x80)
    head[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", head, 0x84, arch)
    path.write_bytes(bytes(head))


def dotnet_install(root: Path, arch: int, runtimes: dict[str, list[str]], sdks: list[str] = ()) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    executable(root / machine.EXECUTABLE, arch)
    for version in sdks:
        (root / "sdk" / version).mkdir(parents=True)
    for name, versions in runtimes.items():
        for version in versions:
            (root / "shared" / name / version).mkdir(parents=True)
    return machine.install(root)


def project(path: str, frameworks: list[str], *, legacy=False, unit=False, aspnet=False, web_application=False) -> dict:
    return {"path": path, "frameworks": frameworks, "legacy": legacy, "unitTest": unit, "aspnet": aspnet,
            "desktop": False, "webApplication": web_application}


class MachineFacts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_an_install_is_read_from_its_folders_and_its_executables_header(self):
        found = dotnet_install(self.root / "x86", 0x014C, {"Microsoft.NETCore.App": ["8.0.29", "10.0.7", "9.0.1"]}, ["10.0.203"])
        self.assertEqual(found["architecture"], "x86")
        self.assertEqual(found["runtimes"]["Microsoft.NETCore.App"], ["8.0.29", "9.0.1", "10.0.7"])
        self.assertEqual(found["sdks"], ["10.0.203"])
        self.assertIsNone(machine.install(self.root / "nowhere"))

    def test_reference_assemblies_count_only_with_their_assemblies(self):
        base = self.root / "Reference Assemblies" / "Microsoft" / "Framework" / ".NETFramework"
        for version, real in (("v4.7.2", True), ("v4.8", True), ("v4.X", False)):
            (base / version).mkdir(parents=True)
            if real:
                (base / version / "mscorlib.dll").write_bytes(b"")
        with mock.patch.dict(os.environ, {"ProgramFiles(x86)": str(self.root)}):
            self.assertEqual(machine.reference_assemblies(), ["4.7.2", "4.8"])


class Check(unittest.TestCase):
    """needs.check against stood-in machines."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        # As on a machine whose backend/.env points DOTNET_ROOT at a per-user .NET 10.
        self.platform = dotnet_install(self.root / "user-dotnet-10", 0x8664, {"Microsoft.NETCore.App": ["10.0.7"],
                                       "Microsoft.AspNetCore.App": ["10.0.7"]}, ["10.0.203"])
        self.machine_wide = dotnet_install(self.root / "Program Files" / "dotnet", 0x8664,
                                           {"Microsoft.NETCore.App": ["8.0.29"], "Microsoft.AspNetCore.App": ["8.0.29"]})
        self.x86 = dotnet_install(self.root / "Program Files (x86)" / "dotnet", 0x014C, {"Microsoft.NETCore.App": ["8.0.29"]})

    def facts(self, platform=None, others=None, **more) -> dict:
        return {"dotnet": platform or self.platform, "dotnetRootSet": True, "others": others if others is not None else
                [self.machine_wide, self.x86], "referenceAssemblies": [], "netfxRelease": 533509, "netfx35": False,
                "visualStudioWebTargets": [], **more}

    def test_a_modern_framework_whose_runtime_is_missing_from_the_platforms_dotnet(self):
        projects = [project("src/Shop/Shop.csproj", ["net8.0"]),
                    project("tests/Shop.Tests/Shop.Tests.csproj", ["net8.0"], unit=True)]
        result = needs.check(projects, self.facts())
        self.assertFalse(result["ready"])
        self.assertEqual(result["summary"], "Baseline tests cannot run here: needs the .NET 8 runtime (x64)")
        missing = result["missing"][0]
        self.assertEqual((missing["for"], missing["projects"]), ("test", ["tests/Shop.Tests/Shop.Tests.csproj"]))
        self.assertIn("user-dotnet-10 (x64) only, which has .NET 10.0.7", missing["detail"])
        self.assertIn(f"{self.machine_wide['root']} (x64) has 8.0.29", missing["detail"])
        self.assertIn(f"{self.x86['root']} (x86) has 8.0.29", missing["detail"])
        self.assertIn("DOTNET_ROOT (backend\\.env) points the platform at the install without it", missing["detail"])
        # The SDK builds net8.0: present, and the build is not the problem.
        self.assertEqual([p["label"] for p in result["present"]], ["a .NET 8 SDK or later"])

        # Only the x86 runtime has it, as on a machine with nothing else: install the x64 one.
        result = needs.check(projects, self.facts(others=[self.x86]))
        self.assertIn("which is not x64: install the x64 runtime", result["missing"][0]["detail"])

    def test_a_modern_framework_whose_runtime_is_present(self):
        platform = dotnet_install(self.root / "dotnet", 0x8664, {"Microsoft.NETCore.App": ["8.0.29", "10.0.7"],
                                  "Microsoft.AspNetCore.App": ["8.0.29"]}, ["10.0.203"])
        projects = [project("src/Shop/Shop.csproj", ["net8.0"]),
                    project("tests/Shop.Tests/Shop.Tests.csproj", ["net8.0"], unit=True, aspnet=True)]
        result = needs.check(projects, self.facts(platform=platform))
        self.assertTrue(result["ready"])
        self.assertEqual(result["summary"], "Ready: this machine has what the baseline needs to build and run its tests")
        self.assertEqual([p["label"] for p in result["present"]],
                         ["a .NET 8 SDK or later", "the .NET 8 runtime (x64)", "the ASP.NET Core 8 runtime (x64)"])
        # A newer minor version of the same major runs it too; another major does not.
        self.assertEqual(needs._runtime_matches(["8.1.0", "9.0.0"], "8.0"), ["8.1.0"])

    def test_a_test_project_reaching_a_web_project_needs_the_aspnet_core_runtime(self):
        projects = [project("tests/Web.Tests/Web.Tests.csproj", ["net8.0"], unit=True, aspnet=True)]
        result = needs.check(projects, self.facts())
        self.assertEqual(result["summary"], "Baseline tests cannot run here: needs the .NET 8 runtime (x64) and the "
                                            "ASP.NET Core 8 runtime (x64)")

    def test_a_legacy_project_without_its_reference_assemblies(self):
        projects = [project("src/Legacy/Legacy.csproj", ["v4.7.2"], legacy=True),
                    project("tests/Legacy.Tests/Legacy.Tests.csproj", ["v4.7.2"], legacy=True, unit=True)]
        result = needs.check(projects, self.facts(referenceAssemblies=["4.8"]))
        self.assertFalse(result["ready"])
        self.assertEqual(result["summary"], "The baseline cannot build here: needs the .NET Framework 4.7.2 reference "
                                            "assemblies (its Developer Pack)")
        self.assertEqual(result["missing"][0]["projects"], ["src/Legacy/Legacy.csproj", "tests/Legacy.Tests/Legacy.Tests.csproj"])
        self.assertEqual(result["missing"][0]["detail"], "installed: 4.8")
        # The .NET Framework 4.8.1 runtime runs its 4.7.2 tests.
        self.assertEqual([p["label"] for p in result["present"]], ["the .NET Framework 4.7.2 runtime"])
        self.assertTrue(needs.check(projects, self.facts(referenceAssemblies=["4.7.2", "4.8"]))["ready"])

    def test_a_legacy_web_application_needs_the_web_targets_where_dotnet_build_finds_them(self):
        projects = [project("src/Site/Site.csproj", ["v4.8"], legacy=True, web_application=True)]
        result = needs.check(projects, self.facts(referenceAssemblies=["4.8"], visualStudioWebTargets=[r"C:\VS\WebApplications\Microsoft.WebApplication.targets"]))
        self.assertEqual(result["summary"], "The baseline cannot build here: needs the web application build targets "
                                            "(Microsoft.WebApplication.targets) where dotnet build finds them")
        self.assertIn("Visual Studio has them at C:\\VS\\WebApplications", result["missing"][0]["detail"])

    def test_an_sdk_style_project_on_net_framework_needs_only_an_sdk(self):
        result = needs.check([project("src/Lib/Lib.csproj", ["net472", "netstandard2.0"])], self.facts())
        self.assertTrue(result["ready"])
        self.assertEqual([p["label"] for p in result["present"]], ["a .NET SDK"])


@contextlib.contextmanager
def on(host: str, account: str):
    with mock.patch.object(host_machine, "hostname", return_value=host), \
            mock.patch.object(host_machine, "windows_account", return_value=account):
        yield


class FromTheDatabase(unittest.TestCase):
    """A repository's projects, the route on its own machine and on another, and the package step."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name).resolve() / "Shop"
        (cls.root / "src" / "Site").mkdir(parents=True)
        (cls.root / "src" / "Site" / "Site.csproj").write_text(
            '<Project><Import Project="$(VSToolsPath)\\WebApplications\\Microsoft.WebApplication.targets" /></Project>\n',
            encoding="utf-8")
        cls.tag = uuid.uuid4().hex[:6]
        cls.ann = (rf"CORP\ann{cls.tag}", f"HOST-A-{cls.tag}", f"ann-{cls.tag}")
        cls.db = SessionLocal()
        cls.user = auth_service.create_user(cls.db, login=cls.ann[2], name="Ann", windows_account=cls.ann[0],
                                            role="developer", host_names=[cls.ann[1]], password=PASSWORD,
                                            must_change_password=False).id
        cls.db.add(models.Engagement(id=ENGAGEMENT, client_name="Test engagement (toolchain)",
                                     target_platform="Linux / OpenShift Container Platform 4", default_posture="lift-and-shift"))
        cls.db.flush()
        cls.repo = models.Repository(engagement_id=ENGAGEMENT, name="Shop", slug=f"shop-{cls.tag}", source_type="local_path",
                                     local_path=str(cls.root), local_path_normalised=str(cls.root).lower(),
                                     root_folder_name="Shop", ingest_status="scanned", owner_user_id=cls.user,
                                     registered_host=cls.ann[1])
        cls.db.add(cls.repo)
        cls.db.flush()
        rows = {}
        for path, raw, fmt, sdk in (("src/Shop/Shop.csproj", "net8.0", "sdk_style", "Microsoft.NET.Sdk"),
                                    ("tests/Shop.Tests/Shop.Tests.csproj", "net8.0", "sdk_style", "Microsoft.NET.Sdk"),
                                    ("src/Site/Site.csproj", "v4.7.2", "legacy_msbuild", None),
                                    ("src/Old/Old.csproj", "v3.5", "legacy_msbuild", None)):
            rows[path] = models.Project(repository_id=cls.repo.id, name=Path(path).stem, relative_path=path,
                                        extension=".csproj", structural_type="project", project_format=fmt, language="csharp",
                                        project_sdk=sdk, target_framework_raw=raw, target_frameworks_raw=[raw],
                                        package_management_style="none", parse_status="success")
            cls.db.add(rows[path])
        cls.db.flush()
        cls.db.add(models.TestClass(repository_id=cls.repo.id, project_id=rows["tests/Shop.Tests/Shop.Tests.csproj"].id,
                                    project_path="tests/Shop.Tests/Shop.Tests.csproj", file_path="tests/Shop.Tests/A.cs",
                                    class_name="A", line_start=1, test_type="unit", classification_reason="test",
                                    test_count=1))
        # Old is out of the conversion's scope: not checked.
        cls.db.add(models.ConversionScope(repository_id=cls.repo.id, excluded_projects=["src/Old/Old.csproj"],
                                          known_projects=sorted(rows), saved_by_name="Ann"))
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        from sqlalchemy import text

        cls.db.rollback()
        cls.db.execute(text("DELETE FROM repositories WHERE id = :r"), {"r": cls.repo.id})
        cls.db.execute(text("DELETE FROM engagements WHERE id = :e"), {"e": ENGAGEMENT})
        cls.db.execute(text("UPDATE activity_records SET user_id = NULL WHERE user_id = :u"), {"u": cls.user})
        cls.db.execute(text("DELETE FROM users WHERE id = :u"), {"u": cls.user})
        cls.db.commit()
        cls.db.close()
        cls.tmp.cleanup()

    def facts(self, runtimes: list[str]) -> dict:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        platform = dotnet_install(Path(tmp.name) / "dotnet", 0x8664, {"Microsoft.NETCore.App": runtimes}, ["10.0.203"])
        return {"dotnet": platform, "dotnetRootSet": False, "others": [], "referenceAssemblies": ["4.7.2"],
                "netfxRelease": 533509, "netfx35": False, "visualStudioWebTargets": []}

    def get(self) -> dict:
        client = Client(app)
        with on(self.ann[1], self.ann[0]):
            self.assertEqual(client.post("/api/auth/sign-in", {"login": self.ann[2], "password": PASSWORD}).status, 200)
            answer = client.request("GET", f"/api/repositories/{self.repo.id}/toolchain")
        self.assertEqual(answer.status, 200, answer.body)
        return answer.json()

    def test_1_the_projects_in_scope_as_the_check_takes_them(self):
        self.db.expire_all()
        found = {p["path"]: p for p in service.projects_for(self.db, self.db.get(models.Repository, self.repo.id))}
        self.assertEqual(sorted(found), ["src/Shop/Shop.csproj", "src/Site/Site.csproj", "tests/Shop.Tests/Shop.Tests.csproj"])
        self.assertTrue(found["tests/Shop.Tests/Shop.Tests.csproj"]["unitTest"])
        self.assertFalse(found["src/Shop/Shop.csproj"]["unitTest"])
        self.assertTrue(found["src/Site/Site.csproj"]["webApplication"])     # read from its project file

    def test_2_on_its_own_machine_it_is_checked_now_and_recorded(self):
        with mock.patch.object(machine, "facts", return_value=self.facts(["10.0.7"])):
            shown = self.get()
        self.assertEqual((shown["checked"], shown["ready"], shown["held_on"]), (True, False, None))
        self.assertTrue(shown["summary"].startswith("The baseline cannot build here: needs the web application build "
                                                    "targets"), shown["summary"])
        self.assertIn("its tests also need the .NET 8 runtime (x64)", shown["summary"])
        self.assertEqual([m["label"] for m in shown["missing"]],
                         ["the web application build targets (Microsoft.WebApplication.targets) where dotnet build finds "
                          "them", "the .NET 8 runtime (x64)"])
        self.db.expire_all()
        row = self.db.get(models.ToolchainCheck, self.repo.id)
        self.assertEqual((row.host, row.ready, row.result["summary"]), (self.ann[1], False, shown["summary"]))

    def test_3_on_another_machine_it_shows_what_its_machine_recorded(self):
        from app.results import held

        # The backend of another machine (a session belongs to its own machine, so stood in for by held.elsewhere).
        with mock.patch.object(machine, "facts", side_effect=AssertionError("another machine's check is not made here")), \
                mock.patch.object(held, "elsewhere", return_value=True):
            shown = self.get()
        self.assertEqual((shown["checked"], shown["ready"], shown["host"]), (True, False, self.ann[1]))
        self.assertIsNotNone(shown["held_on"])

    def test_4_the_package_step_says_why_instead_of_starting(self):
        from app.engine import convert

        with mock.patch.object(machine, "facts", return_value=self.facts(["10.0.7"])), \
                mock.patch.object(convert.planner, "create", side_effect=AssertionError("not planned")):
            with self.assertRaisesRegex(LookupError, "^The baseline cannot build here: needs the web application"):
                convert.plan_packages(self.db, ENGAGEMENT, self.repo.slug, "base", "conversion/1", self.root)
