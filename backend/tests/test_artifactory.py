"""The Artifactory tab's artifactory list (app.routers.artifactory): URL normalisation, the duplicate check, soft delete, and
that no credential is ever stored or returned. Runs in this test run's own schema (tests/__init__.py). Stdlib unittest.
"""
import os
import unittest
from unittest import mock

from fastapi import HTTPException

from app import models
from app.db import SessionLocal
from app.routers import artifactory
from app.routers.artifactory import ArtifactoryIn, normalise_url
from app.workflow.runtime import executor
from tests.support import TEST_ENGAGEMENT_ID, CommittedTestEngagement

URL = "http://localhost:8081/repository/nuget-private/index.json"


class Normalise(unittest.TestCase):
    def test_case_slash_userinfo_query_and_fragment_do_not_make_a_different_artifactory(self):
        expected = normalise_url(URL)
        for variant in ("HTTP://LOCALHOST:8081/repository/nuget-private/index.json",
                        "http://user:example-pw@localhost:8081/repository/nuget-private/index.json?x=1#top",
                        " http://localhost:8081/repository/nuget-private/index.json "):
            self.assertEqual(normalise_url(variant), expected)
        self.assertEqual(normalise_url("https://host/artifactory/"), "https://host/artifactory")

    def test_only_absolute_http_urls(self):
        for bad in ("", "nuget-private", "ftp://host/artifactory", r"C:\artifactories", "file:///c:/artifactories"):
            with self.assertRaises(ValueError, msg=bad):
                normalise_url(bad)

    def test_default_name_comes_from_the_url(self):
        self.assertEqual(artifactory.default_name(normalise_url(URL)), "nuget-private")


class MachineLogin(unittest.TestCase):
    """ARTIFACTORY_TOKEN beside ARTIFACTORY_USERNAME and ARTIFACTORY_PASSWORD (docs/39-ARTIFACTORY.md): the method is named, a
    value never is, and the step programs receive what is set. The rules a call follows are ArtifactoryLogin's, tested in C#."""

    def test_the_method_is_named_the_token_wins_and_an_empty_token_counts_as_not_set(self):
        from app.config import artifactory_method
        self.assertEqual(artifactory_method("example-token", "me", "example-pw"), "token")
        self.assertEqual(artifactory_method("example-token", None, None), "token")
        self.assertEqual(artifactory_method("", "me", "example-pw"), "username and password")
        self.assertEqual(artifactory_method("  ", None, None), "none")
        self.assertEqual(artifactory_method(None, "me", None), "none")

    def test_the_settings_reach_the_step_programs_and_an_empty_token_does_not(self):
        from pydantic import SecretStr

        from app import config
        for token, expected in (("example-token-7Qx", "example-token-7Qx"), ("", None)):
            with mock.patch.dict("os.environ", {}, clear=False):
                for key in ("ARTIFACTORY_TOKEN", "ARTIFACTORY_USERNAME", "ARTIFACTORY_PASSWORD", "PGUSER", "PGPASSWORD"):
                    os.environ.pop(key, None)
                s = config.settings.model_copy(update={"artifactory_token": SecretStr(token), "artifactory_username": "me",
                                                       "artifactory_password": SecretStr("example-pw")})
                config.apply_credentials(s)
                env = os.environ
                self.assertEqual(env.get("ARTIFACTORY_TOKEN"), expected)
                self.assertEqual((env.get("ARTIFACTORY_USERNAME"), env.get("ARTIFACTORY_PASSWORD")), ("me", "example-pw"))

    def test_the_status_names_a_token_and_never_its_value(self):
        from pydantic import SecretStr
        with mock.patch.object(artifactory.settings, "artifactory_token", SecretStr("example-token-7Qx")),                 mock.patch.object(artifactory.settings, "artifactory_username", None),                 mock.patch.object(artifactory.settings, "artifactory_password", None),                 mock.patch.object(artifactory, "_engagement", lambda db, eid: None):
            status = artifactory.credentials_status(TEST_ENGAGEMENT_ID, None)
        self.assertEqual(status.model_dump(), {"machine_login": True, "method": "token"})
        self.assertNotIn("example-token-7Qx", status.model_dump_json())
        with mock.patch.object(artifactory.settings, "artifactory_token", None),                 mock.patch.object(artifactory.settings, "artifactory_username", None),                 mock.patch.object(artifactory.settings, "artifactory_password", None),                 mock.patch.object(artifactory, "_engagement", lambda db, eid: None):
            self.assertEqual(artifactory.credentials_status(TEST_ENGAGEMENT_ID, None).model_dump(),
                             {"machine_login": False, "method": "none"})


class ArtifactoryCase(unittest.TestCase):
    """The engagement and the helpers; no tests of its own."""

    def setUp(self):
        self.db = SessionLocal()
        self.engagement = CommittedTestEngagement(self.db)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.db.rollback()
        self.db.query(models.EngagementFeed).filter_by(engagement_id=TEST_ENGAGEMENT_ID).delete()
        self.db.commit()
        self.engagement.remove()
        self.db.close()

    def add(self, url=URL, name=None):
        return artifactory.add_artifactory(TEST_ENGAGEMENT_ID, ArtifactoryIn(url=url, name=name), self.db)

    def refused(self, code, **kw):
        with self.assertRaises(HTTPException) as caught:
            self.add(**kw)
        self.assertEqual(caught.exception.detail[0]["code"], code)
        return caught.exception


class Artifactories(ArtifactoryCase):
    def test_a_artifactory_is_added_and_listed(self):
        added = self.add()
        self.assertEqual((added.name, added.url), ("nuget-private", URL))
        self.assertEqual([f.id for f in artifactory.list_artifactories(TEST_ENGAGEMENT_ID, self.db)], [added.id])

    def test_the_same_url_is_refused_however_it_is_written(self):
        self.add()
        error = self.refused("DUPLICATE_ARTIFACTORY_URL", url="HTTP://localhost:8081/repository/nuget-private/index.json/", name="other")
        self.assertEqual((error.status_code, error.detail[0]["field"]), (409, "url"))

    def test_the_same_name_is_refused(self):
        self.add()
        self.refused("DUPLICATE_ARTIFACTORY_NAME", url="http://localhost:8081/repository/other/index.json", name="NUGET-PRIVATE")

    def test_a_login_in_the_url_is_refused_and_never_stored(self):
        self.refused("EMBEDDED_CREDENTIALS", url="http://me:example-pw@localhost:8081/repository/x/index.json")
        self.assertEqual(self.db.query(models.EngagementFeed).filter_by(engagement_id=TEST_ENGAGEMENT_ID).count(), 0)

    def test_an_invalid_url_is_a_field_error(self):
        error = self.refused("INVALID_ARTIFACTORY_URL", url="not a url")
        self.assertEqual((error.status_code, error.detail[0]["field"]), (422, "url"))

    def test_a_removed_artifactory_is_soft_deleted_and_its_url_can_be_added_again(self):
        first = self.add()
        artifactory.remove_artifactory(TEST_ENGAGEMENT_ID, first.id, self.db)
        self.assertEqual(artifactory.list_artifactories(TEST_ENGAGEMENT_ID, self.db), [])
        row = self.db.get(models.EngagementFeed, first.id)
        self.assertIsNotNone(row.deleted_at)                      # kept, not hard-deleted (CLAUDE.md rule 7)
        second = self.add()
        self.assertNotEqual(second.id, first.id)

    def test_credentials_status_says_only_whether_and_the_artifactories_context_never_carries_a_password(self):
        with mock.patch.object(artifactory.settings, "artifactory_username", "me"), \
                mock.patch.object(artifactory.settings, "artifactory_password", artifactory.settings.db_password.__class__("pw-secret")):
            status = artifactory.credentials_status(TEST_ENGAGEMENT_ID, self.db)
            self.assertEqual(status.model_dump(), {"machine_login": True, "method": "username and password"})
            self.add()
            context = executor._artifactories_context(self.db, "dependency-hierarchy", {"engagement_id": TEST_ENGAGEMENT_ID})
        self.assertEqual(context, {"artifactories": [{"name": "nuget-private", "url": URL}]})
        self.assertNotIn("pw-secret", repr(context))
        self.assertEqual(executor._artifactories_context(self.db, "solution-discovery", {"engagement_id": TEST_ENGAGEMENT_ID}), {})


UI = "https://host.client-a.example/ui/packages"


class FeedUrls(ArtifactoryCase):
    """Which URLs are taken (docs/39-ARTIFACTORY.md "Rules"): a web UI page is refused, a URL of no known feed shape is
    taken with a warning, and one saved before the check is named, and left working."""

    def test_a_web_ui_address_is_refused_and_says_what_to_use(self):
        for url in (UI, "https://host.client-a.example/ui/repos/tree/General/nuget-local", "https://host.client-a.example/UI"):
            error = self.refused("NOT_A_NUGET_FEED", url=url)
            self.assertEqual((error.status_code, error.detail[0]["field"]), (422, "url"))
            self.assertIn("api/nuget/v3/<repository-key>/index.json", error.detail[0]["message"])
        self.assertEqual(self.db.query(models.EngagementFeed).filter_by(engagement_id=TEST_ENGAGEMENT_ID).count(), 0)

    def test_feed_shapes_are_taken_without_a_warning_and_anything_else_with_one(self):
        for url, name in ((URL, "a"), ("https://host.client-a.example/artifactory/api/nuget/v3/nuget-local/", "b"),
                          ("https://host.client-a.example/artifactory/api/nuget/nuget-v2", "c")):
            self.assertIsNone(self.add(url=url, name=name).warning, url)
        odd = self.add(url="https://host.client-a.example/packages", name="d")
        self.assertIn("does not look like a NuGet feed", odd.warning)

    def test_a_web_ui_address_saved_before_the_check_is_listed_with_a_warning_and_left_working(self):
        self.db.add(models.EngagementFeed(engagement_id=TEST_ENGAGEMENT_ID, name="old", url=UI, url_normalised=UI))
        self.db.commit()
        listed = artifactory.list_artifactories(TEST_ENGAGEMENT_ID, self.db)
        self.assertEqual([(f.url, "web page" in (f.warning or "")) for f in listed], [(UI, True)])
        context = executor._artifactories_context(self.db, "dependency-assessment", {"engagement_id": TEST_ENGAGEMENT_ID})
        self.assertEqual(context, {"artifactories": [{"name": "old", "url": UI}]})


class EditArtifactory(ArtifactoryCase):
    """An admin changes a saved artifactory's URL (or name), with the adding checks and a version check."""

    def edit(self, row, url, name=None, version="1"):
        return artifactory.edit_artifactory(TEST_ENGAGEMENT_ID, row.id, ArtifactoryIn(url=url, name=name), self.db,
                                            if_match=version)

    def edit_refused(self, code, row, url, **kw):
        with self.assertRaises(HTTPException) as caught:
            self.edit(row, url, **kw)
        self.assertEqual(caught.exception.detail[0]["code"], code)
        return caught.exception

    def test_the_url_changes_the_name_stays_the_version_goes_up_and_it_is_recorded(self):
        row = self.add(name="nuget-private")
        new = "https://host.client-a.example/artifactory/api/nuget/v3/nuget-local/index.json"
        edited = self.edit(row, new)
        self.assertEqual((edited.id, edited.url, edited.name, edited.version), (row.id, new, "nuget-private", 2))
        self.assertIsNotNone(edited.updated_at)
        last = self.db.query(models.ActivityRecord).filter_by(subject_type="engagement_feed", subject_id=str(row.id)).one()
        self.assertEqual(last.action, "artifactory.edit")
        self.assertIn(new, last.summary)

    def test_the_adding_checks_apply(self):
        row = self.add()
        self.edit_refused("NOT_A_NUGET_FEED", row, UI)
        self.edit_refused("EMBEDDED_CREDENTIALS", row, "https://me:example-pw@host.client-a.example/api/nuget/v3/x/index.json")
        self.edit_refused("INVALID_ARTIFACTORY_URL", row, "not a url")
        other = self.add(url="http://localhost:8081/repository/other/index.json", name="other")
        self.edit_refused("DUPLICATE_ARTIFACTORY_URL", row, other.url)
        self.edit_refused("DUPLICATE_ARTIFACTORY_NAME", row, URL, name="OTHER")
        self.assertEqual(self.db.get(models.EngagementFeed, row.id).url, URL)

    def test_an_edit_names_its_version_and_a_stale_copy_is_refused(self):
        row = self.add()
        self.assertEqual(self.edit_refused("VERSION_REQUIRED", row, URL, version=None).status_code, 428)
        self.edit(row, "https://host.client-a.example/api/nuget/v3/a/index.json")
        stale = self.edit_refused("STALE_COPY", row, "https://host.client-a.example/api/nuget/v3/b/index.json", version="1")
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.db.get(models.EngagementFeed, row.id).url, "https://host.client-a.example/api/nuget/v3/a/index.json")

    def test_editing_is_for_admins_and_test_connection_for_everyone_signed_in(self):
        from app.auth import policy

        self.assertNotIn(("PUT", "/api/engagements/{engagement_id}/artifactories/{artifactory_id}"), policy.RULES)
        self.assertEqual(policy.RULES[("POST", "/api/engagements/{engagement_id}/artifactory/test-connection")], policy.ANY)


class TestConnection(unittest.TestCase):
    """Test connection runs the step's own check on this backend and returns what it answered, never a value."""

    def setUp(self):
        self.db = SessionLocal()
        self.engagement = CommittedTestEngagement(self.db)

    def tearDown(self):
        self.db.rollback()
        self.engagement.remove()
        self.db.close()

    def ask(self, stdout: str, url: str = URL):
        done = mock.Mock(stdout=stdout)
        with mock.patch.object(artifactory, "CHECK") as check, mock.patch.object(artifactory.subprocess, "run", return_value=done) as run:
            check.exists.return_value = True
            out = artifactory.test_connection(TEST_ENGAGEMENT_ID, artifactory.ConnectionIn(url=url), self.db)
        return out, run.call_args.args[0]

    def test_each_answer_is_read_with_the_login_used(self):
        cases = [
            ("login: token\nOK http://localhost:8081/repository/nuget-private/index.json: answered (login: token)",
             (True, "answered", "token")),
            ("FAILED http://localhost:8081/repository/nuget-private/index.json: rejected ARTIFACTORY_TOKEN (401) (login: token rejected)",
             (False, "rejected ARTIFACTORY_TOKEN (401)", "token rejected")),
            ("FAILED http://localhost:8081/repository/nuget-private/index.json: answered 404 (login: username and password)",
             (False, "answered 404", "username and password")),
            ("FAILED http://localhost:8081/repository/nuget-private/index.json: could not be reached: No such host is known. (localhost:8081) (login: none)",
             (False, "could not be reached: No such host is known. (localhost:8081)", "none")),
        ]
        for stdout, expected in cases:
            out, command = self.ask(stdout)
            self.assertEqual((out.ok, out.answer, out.login), expected)
            self.assertEqual(out.url, URL)
            self.assertEqual(command[1:], ["--check-artifactory", URL])

    def test_no_value_ever_comes_back_and_a_web_page_is_named(self):
        with mock.patch.dict(os.environ, {"ARTIFACTORY_TOKEN": "example-token-7Qx"}):
            out, _ = self.ask("FAILED https://host.client-a.example/ui/packages: answered 401 example-token-7Qx (login: token)", url=UI)
        self.assertNotIn("example-token-7Qx", out.model_dump_json())
        self.assertIn("web page", out.warning)

    def test_a_login_in_the_url_is_refused_before_anything_runs(self):
        with mock.patch.object(artifactory.subprocess, "run") as run, self.assertRaises(HTTPException) as caught:
            artifactory.test_connection(TEST_ENGAGEMENT_ID, artifactory.ConnectionIn(url="https://me:example-pw@host/x"), self.db)
        self.assertEqual(caught.exception.detail[0]["code"], "EMBEDDED_CREDENTIALS")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
