"""Project ids are derived, not generated: the same project in the same
repository gets the same id on every scan, so a rescan updates its row
instead of orphaning everything keyed to it."""

import unittest
import uuid

from main import project_id_for


class ProjectIdTests(unittest.TestCase):
    REPO = "3f1c9a2e-1111-4222-8333-444455556666"

    def test_same_repository_and_path_give_the_same_id(self):
        self.assertEqual(project_id_for(self.REPO, "src/Api/Api.csproj"), project_id_for(self.REPO, "src/Api/Api.csproj"))

    def test_case_and_separator_do_not_change_the_id(self):
        """Windows paths are case-insensitive."""
        self.assertEqual(project_id_for(self.REPO, "src/Api/Api.csproj"), project_id_for(self.REPO, r"SRC\api\API.csproj"))

    def test_different_path_or_repository_gives_a_different_id(self):
        base = project_id_for(self.REPO, "src/Api/Api.csproj")
        self.assertNotEqual(base, project_id_for(self.REPO, "src/Web/Web.csproj"))
        self.assertNotEqual(base, project_id_for(str(uuid.uuid4()), "src/Api/Api.csproj"))

    def test_is_a_valid_uuid(self):
        self.assertEqual(uuid.UUID(project_id_for(self.REPO, "a.csproj")).version, 5)


if __name__ == "__main__":
    unittest.main()
