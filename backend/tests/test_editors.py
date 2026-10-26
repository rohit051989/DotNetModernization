"""Opening a file in the person's editor: which paths the backend opens and which it refuses (app.editors,
04-FRONTEND-SPEC.md "File links"). Nothing here starts an editor.

Uses stdlib unittest, same rationale as test_repository_ingest.py.
"""

import json
import tempfile
from datetime import datetime, timezone
import unittest
from pathlib import Path
from unittest import mock

from app import editors, models
from app.db import SessionLocal
from app.repositories import service as repositories_service
from app.repositories.schemas import RegisterLocalPathRequest
from tests.support import CommittedTestEngagement


class CheckedFileTests(unittest.TestCase):
    """Only a file inside an allowed folder is opened; everything else is refused before any editor is touched."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.allowed = base / "allowed"
        self.outside = base / "outside"
        for folder in (self.allowed / "src", self.outside):
            folder.mkdir(parents=True)
        (self.allowed / "src" / "Service.cs").write_text("class Service {}\n", encoding="utf-8")
        (self.outside / "secret.txt").write_text("not for opening\n", encoding="utf-8")
        patcher = mock.patch.object(editors, "allowed_roots", return_value=[self.allowed])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_a_file_inside_an_allowed_folder_is_opened(self):
        self.assertEqual(editors.checked_file(None, str(self.allowed / "src" / "Service.cs")),
                         (self.allowed / "src" / "Service.cs").resolve())

    def test_the_comparison_ignores_case_and_slash_direction(self):
        path = str(self.allowed / "SRC" / "service.CS").replace("\\", "/")
        self.assertTrue(editors.checked_file(None, path).is_file())

    def test_a_file_outside_every_allowed_folder_is_refused(self):
        with self.assertRaisesRegex(editors.PathNotAllowed, "outside every registered repository"):
            editors.checked_file(None, str(self.outside / "secret.txt"))

    def test_climbing_out_with_dot_dot_is_refused(self):
        with self.assertRaises(editors.PathNotAllowed):
            editors.checked_file(None, str(self.allowed / "src" / ".." / ".." / "outside" / "secret.txt"))

    def test_a_folder_is_refused(self):
        with self.assertRaisesRegex(editors.PathNotAllowed, "not a file"):
            editors.checked_file(None, str(self.allowed / "src"))

    def test_a_missing_file_is_refused(self):
        with self.assertRaisesRegex(editors.PathNotAllowed, "does not exist"):
            editors.checked_file(None, str(self.allowed / "src" / "Missing.cs"))

    def test_a_folder_whose_name_starts_like_an_allowed_one_is_refused(self):
        sibling = Path(self.tmp.name) / "allowed-not"
        sibling.mkdir()
        (sibling / "x.cs").write_text("x\n", encoding="utf-8")
        with self.assertRaises(editors.PathNotAllowed):
            editors.checked_file(None, str(sibling / "x.cs"))

    def test_visual_studio_is_never_asked_about_a_refused_path(self):
        vs = editors.VisualStudio(r"C:\devenv.exe", "17.14.0", "Visual Studio")
        with mock.patch.object(editors, "visual_studio", return_value=vs), \
                mock.patch.object(editors, "_helper") as helper, mock.patch.object(editors.subprocess, "Popen") as popen:
            with self.assertRaises(editors.PathNotAllowed):
                editors.open_in_visual_studio(None, str(self.outside / "secret.txt"), 3)
        helper.assert_not_called()
        popen.assert_not_called()


class OpenInVisualStudioTests(unittest.TestCase):
    """What the answer says, for each thing Visual Studio's automation object reports. No editor is started."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "Service.cs"
        self.file.write_text("class Service {}\n", encoding="utf-8")
        for patcher in (mock.patch.object(editors, "allowed_roots", return_value=[Path(self.tmp.name)]),
                        mock.patch.object(editors, "visual_studio",
                                          return_value=editors.VisualStudio(r"C:\devenv.exe", "17.14.0", "Visual Studio"))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_running_instance_opens_it_at_the_line(self):
        with mock.patch.object(editors, "_helper", return_value={"state": "at_line"}), \
                mock.patch.object(editors.subprocess, "Popen") as popen:
            answer = editors.open_in_visual_studio(None, str(self.file), 42)
        self.assertEqual((answer["opened"], answer["at_line"]), (True, True))
        self.assertIn("line 42", answer["message"])
        popen.assert_not_called()

    def test_with_none_running_one_is_started_and_moved_to_the_line(self):
        with mock.patch.object(editors, "_helper", side_effect=[{"state": "not_running"}, {"state": "at_line"}]), \
                mock.patch.object(editors.subprocess, "Popen") as popen:
            answer = editors.open_in_visual_studio(None, str(self.file), 7)
        self.assertTrue(answer["at_line"])
        self.assertEqual(popen.call_args.args[0][1:], ["/Edit", str(self.file.resolve())])

    def test_when_the_line_cannot_be_set_the_answer_says_so_plainly(self):
        with mock.patch.object(editors, "_helper", side_effect=[{"state": "not_running"}, {"state": "not_running"}]), \
                mock.patch.object(editors.subprocess, "Popen"):
            answer = editors.open_in_visual_studio(None, str(self.file), 7)
        self.assertEqual((answer["opened"], answer["at_line"]), (True, False))
        self.assertIn("could not be moved to line 7", answer["message"])

    def test_without_visual_studio_installed_nothing_is_opened(self):
        with mock.patch.object(editors, "visual_studio", return_value=None):
            with self.assertRaises(editors.EditorNotAvailable):
                editors.open_in_visual_studio(None, str(self.file), 1)

    def test_the_automation_object_name_follows_the_major_version(self):
        self.assertEqual(editors.VisualStudio("d", "17.14.37", "n").prog_id, "VisualStudio.DTE.17.0")
        self.assertEqual(editors.VisualStudio("d", "18.0.1", "n").prog_id, "VisualStudio.DTE.18.0")


class DetectionTests(unittest.TestCase):
    """Which installations vswhere lists are offered, for every combination people have: Visual Studio 2022, 2026 or
    both, with or without SQL Server Management Studio 22 (built on the Visual Studio 2026 shell, installed through
    the Visual Studio Installer), Build Tools, and the two settings. vswhere's answers are given; nothing is started."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.file = base / "repo" / "Service.cs"
        self.file.parent.mkdir()
        self.file.write_text("class Service {}\n", encoding="utf-8")

        def program(*parts):
            path = base.joinpath(*parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
            return str(path)

        self.vs2022 = {"instanceId": "vs2022", "productId": "Microsoft.VisualStudio.Product.Enterprise",
                       "displayName": "Visual Studio Enterprise 2022", "installationVersion": "17.14.37516.0",
                       "productPath": program("2022", "Enterprise", "Common7", "IDE", "devenv.exe"), "isComplete": True}
        self.vs2026 = {"instanceId": "vs2026", "productId": "Microsoft.VisualStudio.Product.Enterprise",
                       "displayName": "Visual Studio Enterprise 2026", "installationVersion": "18.0.11205.157",
                       "productPath": program("18", "Enterprise", "Common7", "IDE", "devenv.exe"), "isComplete": True}
        # SSMS 22 is installed through the Visual Studio Installer, on the 2026 shell, and has the core editor.
        self.ssms22 = {"instanceId": "ssms22", "productId": "Microsoft.SqlServer.ManagementStudio",
                       "displayName": "SQL Server Management Studio 22", "installationVersion": "22.0.11205.157",
                       "productPath": program("SSMS 22", "Common7", "IDE", "Ssms.exe"), "isComplete": True}
        self.build_tools = {"instanceId": "bt2022", "productId": "Microsoft.VisualStudio.Product.BuildTools",
                            "displayName": "Visual Studio Build Tools 2022", "installationVersion": "17.14.37516.0",
                            "productPath": "", "isComplete": True}
        self.core_editor = {"vs2022", "vs2026", "ssms22"}
        self.entries = []
        for patcher in (mock.patch.object(editors, "_vswhere", side_effect=self.vswhere),
                        mock.patch.object(editors, "VSWHERE", mock.Mock(is_file=mock.Mock(return_value=True))),
                        mock.patch.object(editors.shutil, "which", return_value=None),
                        mock.patch.object(editors.settings, "visual_studio", ""),
                        mock.patch.object(editors.settings, "visual_studio_path", ""),
                        mock.patch.object(editors, "allowed_roots", return_value=[base / "repo"])):
            patcher.start()
            self.addCleanup(patcher.stop)
        editors._installations.cache_clear()
        self.addCleanup(editors._installations.cache_clear)

    def vswhere(self, *arguments):
        if "-requires" in arguments:
            return [e for e in self.entries if e["instanceId"] in self.core_editor]
        return list(self.entries)

    def offered(self, *entries):
        self.entries = list(entries)
        editors._installations.cache_clear()
        return [(e["label"], e["installation"]) for e in editors.available()]

    def test_2022_only(self):
        self.assertEqual(self.offered(self.vs2022), [("Visual Studio Enterprise 2022", "vs2022")])

    def test_2026_only(self):
        self.assertEqual(self.offered(self.vs2026), [("Visual Studio Enterprise 2026", "vs2026")])

    def test_both_are_offered_by_full_name_newest_first(self):
        self.assertEqual(self.offered(self.vs2022, self.vs2026),
                         [("Visual Studio Enterprise 2026", "vs2026"), ("Visual Studio Enterprise 2022", "vs2022")])
        self.assertEqual(editors.visual_studio().id, "vs2026")
        self.assertEqual(editors.visual_studio("vs2022").devenv, self.vs2022["productPath"])

    def test_a_later_version_is_accepted_with_no_upper_bound(self):
        later = {**self.vs2026, "instanceId": "vs2028", "displayName": "Visual Studio Enterprise 2028",
                 "installationVersion": "19.0.1"}
        self.core_editor.add("vs2028")
        self.assertEqual(self.offered(self.vs2026, later)[0], ("Visual Studio Enterprise 2028", "vs2028"))
        self.assertEqual(editors.visual_studio().prog_id, "VisualStudio.DTE.19.0")

    def test_2026_with_ssms_22_offers_visual_studio_only(self):
        self.assertEqual(self.offered(self.ssms22, self.vs2026), [("Visual Studio Enterprise 2026", "vs2026")])
        refused = [f for f in editors.found_installations() if not f.accepted]
        self.assertEqual([(f.id, f.reason) for f in refused],
                         [("ssms22", "SQL Server Management Studio, not Visual Studio (it is built on the Visual Studio shell)")])

    def test_2026_with_ssms_22_opens_visual_studio_2026_at_the_line(self):
        """The case seen on an installation: SSMS 22 is the newest product vswhere lists, and used to be launched.
        Now Visual Studio 2026 is: its own devenv.exe, through its own versioned automation object."""
        self.offered(self.ssms22, self.vs2026)
        calls = []

        def helper_run(command, timeout):
            calls.append(command)
            state = "not_running" if len(calls) == 1 else "at_line"
            return mock.Mock(stdout=json.dumps({"state": state, "reason": ""}), stderr="", stopped_why=None)

        with mock.patch.object(editors.processes, "run", side_effect=helper_run), \
                mock.patch.object(editors.subprocess, "Popen") as popen:
            answer = editors.open_in_visual_studio(None, str(self.file), 42)
        self.assertEqual((answer["opened"], answer["at_line"]), (True, True))
        self.assertEqual(answer["message"], "Opened Service.cs at line 42 in Visual Studio Enterprise 2026.")
        self.assertEqual(popen.call_args.args[0], [self.vs2026["productPath"], "/Edit", str(self.file.resolve())])
        for command in calls:
            self.assertEqual(command[command.index("-ProgId") + 1], "VisualStudio.DTE.18.0")
            self.assertEqual(command[command.index("-Devenv") + 1], self.vs2026["productPath"])
            self.assertEqual(command[command.index("-Line") + 1], "42")
        self.assertNotIn("Ssms", " ".join(" ".join(c) for c in calls))

    def test_ssms_alone_is_not_offered(self):
        self.assertEqual(self.offered(self.ssms22), [])
        with self.assertRaises(editors.EditorNotAvailable):
            editors.open_in_visual_studio(None, str(self.file), 1)

    def test_build_tools_alone_are_not_offered(self):
        self.assertEqual(self.offered(self.build_tools), [])
        self.assertEqual([f.reason for f in editors.found_installations()], ["Build Tools: no editor"])

    def test_an_edition_without_the_core_editor_or_devenv_is_not_offered(self):
        self.core_editor.discard("vs2022")
        self.assertEqual(self.offered(self.vs2022), [])
        self.assertIn("core editor", editors.found_installations()[0].reason)
        self.core_editor.add("vs2022")
        other = {**self.vs2022, "productPath": str(Path(self.vs2022["productPath"]).with_name("other.exe"))}
        self.assertEqual(self.offered(other), [])

    def test_visual_studio_2019_is_not_offered(self):
        old = {**self.vs2022, "instanceId": "vs2019", "installationVersion": "16.11.5", "displayName": "Visual Studio 2019"}
        self.core_editor.add("vs2019")
        self.assertEqual(self.offered(old), [])

    def test_visual_studio_off_removes_the_option(self):
        with mock.patch.object(editors.settings, "visual_studio", "off"):
            self.assertEqual(self.offered(self.vs2022, self.vs2026), [])
            self.assertIn("none (VISUAL_STUDIO=off)", editors.report())

    def test_visual_studio_path_overrides_detection(self):
        with mock.patch.object(editors.settings, "visual_studio_path", self.vs2022["productPath"]):
            self.assertEqual(self.offered(self.vs2022, self.vs2026, self.ssms22),
                             [("Visual Studio Enterprise 2022", editors.OVERRIDE_ID)])
            self.assertEqual(editors.visual_studio().prog_id, "VisualStudio.DTE.17.0")

    def test_visual_studio_path_that_is_not_devenv_or_missing_offers_nothing(self):
        for path in (self.ssms22["productPath"], str(Path(self.tmp.name) / "missing" / "devenv.exe")):
            with mock.patch.object(editors.settings, "visual_studio_path", path):
                self.assertEqual(self.offered(self.vs2026), [])
                self.assertIn("VISUAL_STUDIO_PATH", editors.report())

    def test_the_report_lists_each_installation_accepted_or_why_not(self):
        self.entries = [self.vs2022, self.vs2026, self.ssms22, self.build_tools]
        text = editors.report()
        self.assertIn("Installations vswhere lists (4):", text)
        self.assertIn("ACCEPTED  Visual Studio Enterprise 2026  18.0.11205.157", text)
        self.assertIn("ACCEPTED  Visual Studio Enterprise 2022  17.14.37516.0", text)
        self.assertIn("REFUSED   SQL Server Management Studio 22", text)
        self.assertIn("why: Build Tools: no editor", text)
        self.assertIn("Offered in the UI, newest first (2):", text)
        self.assertIn("(automation VisualStudio.DTE.18.0)", text)


class AllowedRootsTests(unittest.TestCase):
    """The allowed folders come from the database: a registered repository counts until it is soft-deleted."""

    def setUp(self):
        self.db = SessionLocal()
        self.tmp = tempfile.TemporaryDirectory()
        self.test_engagement = CommittedTestEngagement(self.db)
        folder = Path(self.tmp.name) / "repo"
        folder.mkdir()
        (folder / "Program.cs").write_text("class Program {}\n", encoding="utf-8")
        self.folder = folder
        self.repo = repositories_service.register_local_path(
            self.db, self.test_engagement.engagement,
            RegisterLocalPathRequest(source_type="local_path", local_path=str(folder)))
        self.db.commit()

    def tearDown(self):
        row = self.db.get(models.Repository, self.repo.id)
        if row is not None:
            self.db.delete(row)
        self.db.commit()
        self.test_engagement.remove()
        self.db.close()
        self.tmp.cleanup()

    def test_a_registered_repository_and_runs_dir_are_allowed(self):
        roots = [str(r) for r in editors.allowed_roots(self.db)]
        self.assertIn(str(self.folder), roots)
        self.assertIn(str(editors.settings.runs_path), roots)
        self.assertTrue(editors.checked_file(self.db, str(self.folder / "Program.cs")).is_file())

    def test_a_soft_deleted_repository_is_no_longer_allowed(self):
        self.repo.deleted_at = datetime.now(timezone.utc)
        self.db.commit()
        with self.assertRaises(editors.PathNotAllowed):
            editors.checked_file(self.db, str(self.folder / "Program.cs"))


if __name__ == "__main__":
    unittest.main()
