"""Several developers on one database (docs/VDI-SETUP.md, "More than one person"), with simulated machines: each is a
hostname and the Windows account its backend runs under (app.auth.machine, patched), and the app is called as a server
would call it (tests.asgi_client), through the real guard and policy.

Paths (app.repositories.clones):
- the owner and a viewer each open the same file from their own clone;
- a viewer without a clone is offered to record one, with the git clone command;
- a folder that is a clone of a different repository, or not the top of a clone, is refused.

Versions (app.platform_version):
- a developer's bootstrap behind the database, and one ahead of it, each stop with the right message; one at the
  database's version has nothing to do; an admin's migrates, unless the database is newer;
- a backend on a different version refuses to start;
- the admin updates while a developer's backend runs: the developer sees the banner's message and can change nothing.

Users (app.auth.management):
- disabling ends a live session, and signing in is then refused with a plain message; enabling restores it;
- deleting a user who owns a repository is refused, naming it, until it is reassigned; the activity record keeps their
  name afterwards;
- nobody disables or deletes themselves, nor the last admin; removing a machine; the command-line equivalents.

Runs in this test run's own schema (tests/__init__.py). Uses stdlib unittest, same rationale as test_repository_ingest.py.
"""
import asyncio
import contextlib
import datetime
import io
import json
import subprocess
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from sqlalchemy import text

from app import editors, models, platform_version
from app import users as users_cli
from app.auth import actor as actors
from app.auth import machine, management, service
from app.db import SessionLocal
from app.main import app, lifespan
from app.repositories import clones
from tests.asgi_client import Client
from tests.support import TEST_ENGAGEMENT_ID, CommittedTestEngagement

PASSWORD = "a-long-enough-password"
URL = "https://git.client-a.example/team/Shop.git"


@contextlib.contextmanager
def on(host: str, account: str):
    with mock.patch.object(machine, "hostname", return_value=host), \
            mock.patch.object(machine, "windows_account", return_value=account):
        yield


def git(folder: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True)


def clone_of(folder: Path, remote: str) -> Path:
    """A git repository whose origin is `remote`, with one source file: what a clone looks like to the check."""
    folder.mkdir(parents=True)
    git(folder, "init", "-q")
    git(folder, "remote", "add", "origin", remote)
    (folder / "src" / "Web").mkdir(parents=True)
    (folder / "src" / "Web" / "Orders.cs").write_text("class Orders {}\n", encoding="utf-8")
    return folder


class People(unittest.TestCase):
    """An admin, and two developers on their own machines."""

    def setUp(self):
        self.tag = uuid.uuid4().hex[:6]
        self.admin = (rf"CORP\boss{self.tag}", f"ADMIN-{self.tag}", f"boss-{self.tag}")
        self.ann = (rf"CORP\ann{self.tag}", f"HOST-A-{self.tag}", f"ann-{self.tag}")
        self.ben = (rf"CORP\ben{self.tag}", f"HOST-B-{self.tag}", f"ben-{self.tag}")
        with SessionLocal() as db:
            ids = {}
            for (account, host, login), role, name in ((self.admin, "admin", "Boss"), (self.ann, "developer", "Ann"),
                                                       (self.ben, "developer", "Ben")):
                ids[login] = service.create_user(db, login=login, name=name, windows_account=account, role=role,
                                                 host_names=[host], password=PASSWORD, must_change_password=False).id
            db.commit()
        self.ids = ids
        self.repositories: list[uuid.UUID] = []

    def tearDown(self):
        with SessionLocal() as db:
            db.execute(text("delete from repositories where id = any(:r)"), {"r": self.repositories})
            for user_id in self.ids.values():
                db.execute(text("update activity_records set user_id = null where user_id = :u"), {"u": user_id})
                db.execute(text("delete from users where id = :u"), {"u": user_id})
            db.commit()

    def client(self, who) -> Client:
        account, host, login = who
        client = Client(app)
        with on(host, account):
            answer = client.post("/api/auth/sign-in", {"login": login, "password": PASSWORD})
        self.assertEqual(answer.status, 200, answer.body)
        return client

    def call(self, client: Client, who, method: str, url: str, body=None):
        with on(who[1], who[0]):
            return client.request(method, url, body)

    def repository(self, db, owner_login: str, host: str, folder: str, clone_url: str | None = URL) -> models.Repository:
        name = f"Shop-{self.tag}-{len(self.repositories)}"
        repo = models.Repository(engagement_id=TEST_ENGAGEMENT_ID, name=name, slug=name.lower(), source_type="local_path",
                                 local_path=folder, local_path_normalised=folder.lower(), root_folder_name=Path(folder).name,
                                 ingest_status="scanned", clone_url=clone_url, owner_user_id=self.ids[owner_login],
                                 registered_host=host)
        db.add(repo)
        db.flush()
        clones.record_registered(db, repo)
        db.commit()
        self.repositories.append(repo.id)
        return repo


class Clones(People):
    def setUp(self):
        super().setUp()
        self.db = SessionLocal()
        self.engagement = CommittedTestEngagement(self.db)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Resolved: TEMP may be named by its short (8.3) form, and a recorded clone is stored by its full name.
        root = Path(self.tmp.name).resolve()
        self.ann_clone = clone_of(root / "ann" / "Shop", URL)
        # Ben cloned it over ssh: the same repository.
        self.ben_clone = clone_of(root / "ben" / "Shop", "git@git.client-a.example:team/Shop.git")
        self.other = clone_of(root / "ben" / "Other", "https://git.client-a.example/team/Other.git")
        self.repo = self.repository(self.db, self.ann[2], self.ann[1], str(self.ann_clone))

    def tearDown(self):
        self.db.close()
        super().tearDown()
        self.engagement.remove()

    def detail(self, who):
        return self.call(self.client(who), who, "GET", f"/api/repositories/{self.repo.id}").json()

    def test_the_owner_and_a_viewer_each_open_the_same_file_from_their_own_clone(self):
        relative = "src/Web/Orders.cs"     # as every scan stores a file's location: relative to the repository
        self.assertEqual(self.detail(self.ann)["my_clone_path"], str(self.ann_clone))

        ben = self.client(self.ben)
        recorded = self.call(ben, self.ben, "POST", f"/api/repositories/{self.repo.id}/clone",
                             {"local_path": str(self.ben_clone)})
        self.assertEqual(recorded.status, 200, recorded.body)
        self.assertEqual(recorded.json()["my_clone_path"], str(self.ben_clone))
        # The owner's is unchanged.
        self.assertEqual(self.detail(self.ann)["my_clone_path"], str(self.ann_clone))

        # Each joins their own clone with the file's relative path, and their own backend opens it there.
        for who, clone in ((self.ann, self.ann_clone), (self.ben, self.ben_clone)):
            with on(who[1], who[0]), SessionLocal() as db:
                opened = editors.checked_file(db, str(clone / relative))
            self.assertEqual(opened, (clone / relative).resolve())
        # Not someone else's clone, from another machine.
        with on(self.ann[1], self.ann[0]), SessionLocal() as db, self.assertRaises(editors.PathNotAllowed):
            editors.checked_file(db, str(self.ben_clone / relative))

    def test_a_viewer_without_a_clone_is_offered_to_record_one(self):
        seen = self.detail(self.ben)
        self.assertIsNone(seen["my_clone_path"])
        self.assertIn(f"git clone -c core.longpaths=true {URL}", seen["clone_command"])
        self.assertEqual(seen["files_held_on"], f"on Ann's machine ({self.ann[1]})")

    def test_a_folder_that_is_a_clone_of_another_repository_is_refused(self):
        ben = self.client(self.ben)
        for folder, code in ((self.other, "DIFFERENT_REPOSITORY"), (self.ben_clone / "src", "NOT_TOP"),
                             (Path(self.tmp.name) / "nowhere", "NOT_FOUND"), ("relative\\path", "INVALID_PATH")):
            refused = self.call(ben, self.ben, "POST", f"/api/repositories/{self.repo.id}/clone", {"local_path": str(folder)})
            self.assertEqual((refused.status, refused.code), (422, code), refused.body)
        self.assertIn("team/other", self.call(ben, self.ben, "POST", f"/api/repositories/{self.repo.id}/clone",
                                              {"local_path": str(self.other)}).body.decode().lower())
        self.assertIsNone(self.detail(self.ben)["my_clone_path"])

    def test_forgetting_a_clone_offers_it_again(self):
        ben = self.client(self.ben)
        self.call(ben, self.ben, "POST", f"/api/repositories/{self.repo.id}/clone", {"local_path": str(self.ben_clone)})
        forgot = self.call(ben, self.ben, "DELETE", f"/api/repositories/{self.repo.id}/clone")
        self.assertEqual((forgot.status, forgot.json()["my_clone_path"]), (200, None))
        self.assertTrue(self.ben_clone.is_dir())       # nothing on disk changed


class VersionedDatabase(People):
    """The database's recorded versions, put back after each test; an installation unless a test class says not."""
    OLD = platform_version.Version("a" * 40, datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc))
    NEW = platform_version.Version("b" * 40, datetime.datetime(2026, 10, 20, tzinfo=datetime.timezone.utc))
    OWN_REPOSITORY = False

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, platform_version, "_changed", None)
        # These commits are not in our repository's history: an installation orders them by commit date.
        patcher = mock.patch.object(platform_version, "_own_repository", return_value=self.OWN_REPOSITORY)
        patcher.start()
        self.addCleanup(patcher.stop)
        with SessionLocal() as db:
            self.before = db.execute(text("select coalesce(max(id), 0) from platform_version")).scalar()

    def tearDown(self):
        with SessionLocal() as db:
            db.execute(text("delete from platform_version where id > :i"), {"i": self.before})
            db.commit()
        super().tearDown()

    def database_at(self, version: platform_version.Version) -> None:
        with SessionLocal() as db:
            db.execute(text("insert into platform_version (commit, committed_at, fingerprint, recorded_by) "
                            "values (:c, :at, cast(:f as jsonb), 'Boss')"),
                       {"c": version.commit, "at": version.committed_at,
                        "f": json.dumps(version.fingerprint) if version.fingerprint else None})
            db.commit()

    def gate(self, who, mine: platform_version.Version) -> tuple[int, str]:
        said: list[str] = []
        with on(who[1], who[0]), mock.patch.object(platform_version, "local", return_value=mine), SessionLocal() as db:
            code = platform_version.gate(db, out=said.append)
        return code, " ".join(said)


class Versions(VersionedDatabase):
    def test_a_developers_bootstrap_behind_or_ahead_of_the_database_stops_with_the_right_message(self):
        self.database_at(self.NEW)
        code, said = self.gate(self.ann, self.OLD)
        self.assertEqual(code, platform_version.GATE_STOP)
        self.assertIn("The admin has updated the platform", said)
        self.assertIn("Pull the update first", said)

        code, said = self.gate(self.ann, platform_version.Version("c" * 40, datetime.datetime(2026, 10, 25, tzinfo=datetime.timezone.utc)))
        self.assertEqual(code, platform_version.GATE_STOP)
        self.assertIn("ask the admin to update first", said)

        code, said = self.gate(self.ann, self.NEW)
        self.assertEqual(code, platform_version.GATE_NOTHING)
        self.assertIn("nothing to migrate or seed", said)

    def test_an_installation_compares_commits_even_when_nothing_the_database_depends_on_changed(self):
        same = platform_version.fingerprint()
        self.database_at(platform_version.Version(self.NEW.commit, self.NEW.committed_at, same))
        older = platform_version.Version(self.OLD.commit, self.OLD.committed_at, same)
        code, said = self.gate(self.ann, older)
        self.assertEqual(code, platform_version.GATE_STOP)
        self.assertIn("Pull the update first", said)
        with mock.patch.object(platform_version, "local", return_value=older), \
                self.assertRaises(platform_version.VersionMismatch):
            platform_version.check_at_start()

    def test_a_version_is_described_in_utc_whatever_zone_its_commit_was_made_in(self):
        india = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        made = platform_version.Version("d" * 40, datetime.datetime(2026, 10, 27, 22, 28, tzinfo=india))
        self.assertEqual(made.describe(), "dddddddddddd, committed 2026-10-27 16:58 UTC")

    def test_only_the_admins_bootstrap_migrates_and_records_and_never_takes_the_database_back(self):
        self.database_at(self.OLD)
        self.assertEqual(self.gate(self.admin, self.NEW)[0], platform_version.GATE_MIGRATE)
        self.database_at(self.NEW)
        code, said = self.gate(self.admin, self.OLD)
        self.assertEqual(code, platform_version.GATE_STOP)
        self.assertIn("Pull the update first", said)
        # A developer cannot record a version, even by hand.
        with on(self.ann[1], self.ann[0]), SessionLocal() as db:
            self.assertEqual(platform_version.record(db, out=lambda _: None), 1)

    def test_a_backend_on_a_different_version_refuses_to_start(self):
        self.database_at(self.NEW)

        async def start():
            async with lifespan(app):
                pass

        with mock.patch.object(platform_version, "local", return_value=self.OLD), \
                self.assertRaises(platform_version.VersionMismatch) as refused:
            asyncio.run(start())
        self.assertIn("The admin has updated the platform", str(refused.exception))

    def test_the_admin_updates_while_a_developers_backend_runs(self):
        self.database_at(self.OLD)
        watch = platform_version.Watch(self.OLD)
        watch.check()
        self.assertIsNone(platform_version.updated())
        ann = self.client(self.ann)
        self.assertEqual(self.call(ann, self.ann, "GET", "/api/health").json()["platform_update"], None)

        self.database_at(self.NEW)          # the admin's bootstrap records the new version
        watch.check()
        banner = self.call(ann, self.ann, "GET", "/api/health").json()["platform_update"]
        self.assertIn("The admin has updated the platform", banner)
        self.assertIn("nothing can be changed", banner)
        # Reading goes on; no change is made.
        self.assertEqual(self.call(ann, self.ann, "GET", "/api/engagements").status, 200)
        refused = self.call(ann, self.ann, "POST", f"/api/engagements/{TEST_ENGAGEMENT_ID}/repositories/inspect-path",
                            {"local_path": "C:\\nowhere"})
        self.assertEqual((refused.status, refused.code), (409, "PLATFORM_UPDATED"))
        # Signing out still works.
        self.assertIn(self.call(ann, self.ann, "POST", "/api/auth/sign-out").status, (200, 204))


class OwnRepository(VersionedDatabase):
    """Our own development repository (no PLATFORM_SOURCE.json): what the database depends on is compared, not commits."""
    OWN_REPOSITORY = True

    def setUp(self):
        super().setUp()
        self.depends = platform_version.fingerprint()
        # Commits git does not know, so only the fingerprint and the migrations can tell.
        self.mine = platform_version.Version("e" * 40, self.NEW.committed_at, self.depends)

    def at(self, commit: str, **changed) -> platform_version.Version:
        return platform_version.Version(commit, self.OLD.committed_at, {**self.depends, **changed})

    def test_the_fingerprint_is_what_the_database_depends_on(self):
        self.assertEqual(set(self.depends), {"migration", "steps", "seed"})
        self.assertEqual(self.depends["migration"], platform_version._migration_head())
        self.assertIn("item-detection", self.depends["steps"])
        self.assertEqual(platform_version.fingerprint(), self.depends)          # the same files, the same fingerprint

    def test_a_commit_that_changes_nothing_the_database_depends_on_needs_no_update(self):
        self.database_at(self.at("a" * 40))
        code, said = self.gate(self.ann, self.mine)
        self.assertEqual(code, platform_version.GATE_NOTHING, said)
        with mock.patch.object(platform_version, "local", return_value=self.mine):
            self.assertEqual(platform_version.check_at_start(), self.mine)        # the backend starts

        watch = platform_version.Watch(self.mine)
        watch.check()
        self.database_at(self.at("f" * 40))     # the admin records another commit, changing nothing that matters
        watch.check()
        self.assertIsNone(platform_version.updated())
        ann = self.client(self.ann)
        self.assertIsNone(self.call(ann, self.ann, "GET", "/api/health").json()["platform_update"])

    def test_a_change_to_what_the_database_depends_on_still_stops_and_says_what(self):
        steps = {**self.depends["steps"], "item-detection": "9.9.9"}
        self.database_at(self.at("a" * 40, migration="f0f0f0f0f0f0", steps=steps))     # a migration this copy lacks
        code, said = self.gate(self.ann, self.mine)
        self.assertEqual(code, platform_version.GATE_STOP)
        self.assertIn("Pull the update first", said)
        self.assertIn("item-detection", said)
        self.assertIn("They differ in the migrations (", said)
        self.assertIn(") and the step registrations (", said)
        with mock.patch.object(platform_version, "local", return_value=self.mine), \
                self.assertRaises(platform_version.VersionMismatch):
            platform_version.check_at_start()
        watch = platform_version.Watch(self.mine)
        watch.check()
        self.assertIn("Pull the update first", platform_version.updated()["message"])

    def test_a_database_behind_this_copys_migrations_asks_the_admin_to_update(self):
        self.database_at(self.at("a" * 40, migration="c3e8a1d6f4b2"))       # an earlier revision of this copy's
        code, said = self.gate(self.ann, self.mine)
        self.assertEqual(code, platform_version.GATE_STOP)
        self.assertIn("ask the admin to update first", said)

    def test_a_version_recorded_before_fingerprints_is_compared_by_commit(self):
        self.database_at(platform_version.Version("a" * 40, self.OLD.committed_at))
        self.assertEqual(self.gate(self.ann, self.mine)[0], platform_version.GATE_STOP)
        # The admin's next bootstrap records one, and the same check passes.
        with on(self.admin[1], self.admin[0]), mock.patch.object(platform_version, "local", return_value=self.mine), \
                SessionLocal() as db:
            self.assertEqual(platform_version.record(db, out=lambda _: None), 0)
        self.assertEqual(self.gate(self.ann, platform_version.Version("b" * 40, None, self.depends))[0],
                         platform_version.GATE_NOTHING)


class Users(People):
    def admin_client(self) -> Client:
        return self.client(self.admin)

    def test_disabling_ends_a_live_session_and_refuses_sign_in_until_enabled(self):
        ann = self.client(self.ann)
        self.assertEqual(self.call(ann, self.ann, "GET", "/api/auth/me").status, 200)
        admin = self.admin_client()
        disabled = self.call(admin, self.admin, "POST", f"/api/users/{self.ids[self.ann[2]]}/disable")
        self.assertEqual(disabled.status, 200, disabled.body)
        self.assertFalse(disabled.json()["user"]["active"])

        ended = self.call(ann, self.ann, "GET", "/api/auth/me")
        self.assertEqual((ended.status, ended.code), (401, "SIGNED_OUT"))
        with on(self.ann[1], self.ann[0]):
            refused = Client(app).post("/api/auth/sign-in", {"login": self.ann[2], "password": PASSWORD})
        self.assertEqual((refused.status, refused.code), (401, "DISABLED"))
        self.assertIn("disabled", refused.json()["detail"][0]["message"])

        self.assertEqual(self.call(admin, self.admin, "POST", f"/api/users/{self.ids[self.ann[2]]}/enable").status, 200)
        self.client(self.ann)       # signs in again

    def test_disabling_keeps_their_repositories_and_deleting_is_refused_until_each_is_reassigned(self):
        with SessionLocal() as db:
            engagement = CommittedTestEngagement(db)
            repo = self.repository(db, self.ann[2], self.ann[1], f"C:\\shop-{self.tag}")
            name = repo.name
        self.addCleanup(engagement.remove)
        ann = self.client(self.ann)
        self.call(ann, self.ann, "GET", "/api/engagements")      # something she did, before she is deleted
        self.call(ann, self.ann, "POST", "/api/auth/sign-out")
        admin = self.admin_client()
        ann_id = str(self.ids[self.ann[2]])

        disabled = self.call(admin, self.admin, "POST", f"/api/users/{ann_id}/disable").json()
        self.assertEqual([r["name"] for r in disabled["owned_repositories"]], [name])

        refused = self.call(admin, self.admin, "DELETE", f"/api/users/{ann_id}")
        self.assertEqual((refused.status, refused.code), (409, "OWNS_REPOSITORIES"))
        self.assertIn(name, refused.json()["detail"][0]["message"])

        reassigned = self.call(admin, self.admin, "PUT", f"/api/repositories/{repo.id}/owner",
                               {"owner_user_id": str(self.ids[self.ben[2]])})
        self.assertEqual(reassigned.status, 200, reassigned.body)
        deleted = self.call(admin, self.admin, "DELETE", f"/api/users/{ann_id}")
        self.assertEqual(deleted.status, 204, deleted.body)
        with SessionLocal() as db:
            self.assertIsNone(db.get(models.User, uuid.UUID(ann_id)))
            # Everything she did still shows her name.
            hers = db.query(models.ActivityRecord).filter(models.ActivityRecord.actor == f"Ann ({self.ann[2]})").all()
            self.assertTrue(hers)
            self.assertTrue(all(r.user_id is None for r in hers))
            actions = {r.action for r in db.query(models.ActivityRecord).filter_by(subject_type="user", subject_id=ann_id)}
        self.assertTrue({"disable_user", "delete_user"} <= actions, actions)

    def test_nobody_disables_or_deletes_themselves_or_the_last_admin(self):
        admin = self.admin_client()
        boss_id = str(self.ids[self.admin[2]])
        for method, url in (("POST", f"/api/users/{boss_id}/disable"), ("DELETE", f"/api/users/{boss_id}")):
            refused = self.call(admin, self.admin, method, url)
            self.assertEqual((refused.status, refused.code), (409, "SELF"), refused.body)
        # A developer may do neither to anyone.
        ann = self.client(self.ann)
        self.assertEqual(self.call(ann, self.ann, "POST", f"/api/users/{self.ids[self.ben[2]]}/disable").status, 403)
        self.assertEqual(self.call(ann, self.ann, "DELETE", f"/api/users/{self.ids[self.ben[2]]}").status, 403)
        # The last admin, whoever asks: every other admin of this schema set aside for the check.
        nobody = actors.Actor(None, "system", "the platform", actors.ADMIN, None)
        with SessionLocal() as db:
            others = [u for u in db.query(models.User).filter(models.User.role == "admin", models.User.deactivated_at.is_(None))
                      if str(u.id) != boss_id]
            for other in others:
                other.deactivated_at = datetime.datetime.now(datetime.timezone.utc)
            db.flush()
            boss = db.get(models.User, uuid.UUID(boss_id))
            for act in (management.disable, management.delete):
                with self.assertRaises(service.Refused) as refused:
                    act(db, boss, nobody)
                self.assertEqual(refused.exception.code, "LAST_ADMIN")
            db.rollback()

    def test_removing_one_machine(self):
        admin = self.admin_client()
        ben_id = str(self.ids[self.ben[2]])
        laptop = f"LAPTOP-{self.tag}"
        self.call(admin, self.admin, "PUT", f"/api/users/{ben_id}", {"hosts": [self.ben[1], laptop]})
        removed = self.call(admin, self.admin, "DELETE", f"/api/users/{ben_id}/machines/{laptop}")
        self.assertEqual((removed.status, removed.json()["hosts"]), (200, [self.ben[1]]))
        last = self.call(admin, self.admin, "DELETE", f"/api/users/{ben_id}/machines/{self.ben[1]}")
        self.assertEqual((last.status, last.code), (409, "LAST_MACHINE"))

    def test_the_command_line_equivalents(self):
        # A command sets the person it acts as (cli_actor); put back whoever was acting, since Boss is deleted after.
        self.addCleanup(actors.reset, actors.set_current(actors.current()))

        def run(*argv):
            with on(self.admin[1], self.admin[0]), redirect_stdout(io.StringIO()) as said:
                self.assertEqual(users_cli.main(list(argv)), 0)
            return said.getvalue()

        ben = self.ben[2]
        laptop = f"LAPTOP-{self.tag}"
        with SessionLocal() as db:
            db.add(models.UserHost(user_id=self.ids[ben], hostname=laptop))
            db.commit()
        self.assertIn("Disabled Ben", run("disable", "--login", ben))
        self.assertIn("Enabled Ben", run("enable", "--login", ben))
        self.assertNotIn(laptop, run("remove-machine", "--login", ben, "--host", laptop))
        self.assertIn("Deleted Ben", run("delete", "--login", ben))
        with on(self.admin[1], self.admin[0]), redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as refused:
            users_cli.main(["delete", "--login", self.admin[2]])
        self.assertIn("yourself", str(refused.exception))
        with SessionLocal() as db:
            actions = [r.action for r in db.query(models.ActivityRecord).filter_by(subject_type="user", subject_id=str(self.ids[ben]))
                       .order_by(models.ActivityRecord.id)]
        self.assertEqual(actions[-4:], ["disable_user", "enable_user", "remove_user_machine", "delete_user"])


if __name__ == "__main__":
    unittest.main()
