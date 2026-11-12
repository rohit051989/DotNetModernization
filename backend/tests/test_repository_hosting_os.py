"""A repository's current and target hosting OS: who may set them, and what the schemas accept.

No database: the admin-only rule is a plain function of who is acting and what is being set, and the schemas are
Pydantic models. (That the values are stored and defaulted is checked with the other registration tests, in
test_register_by_url.)"""
import unittest

from pydantic import ValidationError

from app.auth import actor as actors
from app.repositories.schemas import (
    DEFAULT_CURRENT_HOSTING_OS,
    DEFAULT_TARGET_HOSTING_OS,
    RegisterGitCloneRequest,
    RegisterLocalPathRequest,
    RepositoryUpdate,
)
from app.routers.repositories import _require_admin_to_set_hosting as require


def acting(role: str):
    person = actors.Actor(None, f"{role}-login", role.title(), role, "PC-1")
    token = actors.set_current(person)
    return token


class HostingRuleTests(unittest.TestCase):
    def as_role(self, role):
        self.addCleanup(actors.reset, acting(role))

    def refused(self, *args) -> bool:
        try:
            require(*args)
        except Exception as caught:  # noqa: BLE001 - an HTTP error carrying a status code
            self.assertEqual(getattr(caught, "status_code", None), 403)
            return True
        return False

    def test_a_developer_registering_with_the_defaults_is_not_refused(self):
        self.as_role("developer")
        self.assertFalse(self.refused("windows", "linux", "windows", "linux"))

    def test_a_developer_choosing_another_value_is_refused_on_either_field(self):
        self.as_role("developer")
        self.assertTrue(self.refused("windows", "windows", "windows", "linux"))
        self.assertTrue(self.refused("linux", "linux", "windows", "linux"))

    def test_a_developer_saving_other_edits_leaves_them_alone(self):
        # An update that sends nothing, or what is stored already, changes nothing.
        self.as_role("developer")
        self.assertFalse(self.refused(None, None, "windows", "windows"))
        self.assertFalse(self.refused("windows", "windows", "windows", "windows"))

    def test_a_developer_cannot_change_a_stored_value_either(self):
        self.as_role("developer")
        self.assertTrue(self.refused(None, "linux", "windows", "windows"))

    def test_an_admin_sets_any_value(self):
        self.as_role("admin")
        self.assertFalse(self.refused("windows", "windows", "windows", "linux"))
        self.assertFalse(self.refused("linux", "linux", "windows", "linux"))

    def test_nobody_acting_is_not_an_admin(self):
        self.addCleanup(actors.reset, actors.set_current(None))
        self.assertTrue(self.refused("windows", "windows", "windows", "linux"))
        self.assertFalse(self.refused("windows", "linux", "windows", "linux"))


class HostingSchemaTests(unittest.TestCase):
    def test_registering_defaults_to_windows_then_linux(self):
        git = RegisterGitCloneRequest(source_type="git_clone", clone_url="https://git.client-a.example/t/r.git")
        local = RegisterLocalPathRequest(source_type="local_path", local_path="D:\\repos\\r")
        for payload in (git, local):
            self.assertEqual((payload.current_hosting_os, payload.target_hosting_os), ("windows", "linux"))
        self.assertEqual((DEFAULT_CURRENT_HOSTING_OS, DEFAULT_TARGET_HOSTING_OS), ("windows", "linux"))

    def test_an_update_that_names_neither_leaves_both_alone(self):
        update = RepositoryUpdate(name="Orders")
        self.assertEqual((update.current_hosting_os, update.target_hosting_os), (None, None))

    def test_only_windows_or_linux_is_accepted(self):
        with self.assertRaises(ValidationError):
            RegisterGitCloneRequest(source_type="git_clone", clone_url="https://git.client-a.example/t/r.git",
                                    target_hosting_os="mac")
        with self.assertRaises(ValidationError):
            RepositoryUpdate(name="Orders", current_hosting_os="solaris")


if __name__ == "__main__":
    unittest.main()
