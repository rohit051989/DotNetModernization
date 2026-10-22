"""Opening a file in the person's editor: which paths the backend opens and which it refuses (app.editors,
04-FRONTEND-SPEC.md "File links"). Nothing here starts an editor.

Uses stdlib unittest, same rationale as test_repository_ingest.py.
"""

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
