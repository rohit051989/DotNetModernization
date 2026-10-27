"""Identity and ownership with two simulated machines against one database (app.auth; docs/VDI-SETUP.md, "Users and
sign-in"). Each machine is a hostname and the Windows account its backend runs under (app.auth.machine, patched);
the app is called as a server would call it (tests.asgi_client), through the real sign-in guard and policy.

- each user signs in only from their registered machine, under their own Windows account;
- A registers and scans a repository; B sees it read-only, and the backend refuses B's rescan and deletions;
- A's job never runs on B's runner, and B's startup never fails A's running job;
- two simultaneous edits of one decision: one is saved, the other refused as made from a stale copy;
- a second backend on the same machine is refused; backends on two machines run side by side, both online.

Runs in this test run's own schema (tests/__init__.py). Uses stdlib unittest, same rationale as test_repository_ingest.py.
"""
import contextlib
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest import mock

from app import heartbeat, models
from app.auth import machine, passwords, policy, service
from app.db import SessionLocal
from app.main import app, _reconcile_orphaned_executions
from app.workflow.runtime import executor
from app.workflow.runtime import service as runtime
from tests.asgi_client import Client
from tests.support import CommittedTestEngagement

MACHINE_A, MACHINE_B, MACHINE_C = "DEVBOX-A", "DEVBOX-B", "DEVBOX-C"
ALICE, BOB, CAROL = r"CORP\alice", r"CORP\bob", r"CORP\carol"
PASSWORD = "alice-long-password"
# The real runner, kept before setUp replaces it for registrations: the foreign-job test hands a job to it.
REAL_RUN = runtime.run_execution_in_background


@contextlib.contextmanager
def on(host: str, account: str):
    """This process, as the backend on `host` running under `account`."""
    with mock.patch.object(machine, "hostname", return_value=host), \
            mock.patch.object(machine, "windows_account", return_value=account):
        yield


def no_background_run(*_args, **_kwargs):
    """Registration and rescans queue their discovery job; running it is not what these tests are about."""


class TwoMachines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tag = uuid.uuid4().hex[:6]
        with SessionLocal() as db:
            cls.alice = service.create_user(db, login=f"alice-{cls.tag}", name="Alice", windows_account=ALICE + cls.tag,
                                            role="developer", host_names=[MACHINE_A], password=PASSWORD,
                                            must_change_password=False)
            cls.bob = service.create_user(db, login=f"bob-{cls.tag}", name="Bob", windows_account=BOB + cls.tag,
                                          role="developer", host_names=[MACHINE_B], password=PASSWORD,
                                          must_change_password=False)
            cls.carol = service.create_user(db, login=f"carol-{cls.tag}", name="Carol", windows_account=CAROL + cls.tag,
                                            role="admin", host_names=[MACHINE_A, MACHINE_C], password=PASSWORD,
                                            must_change_password=False)
            db.commit()
            cls.ids = {name: getattr(cls, name).id for name in ("alice", "bob", "carol")}

    def setUp(self):
        self.db = SessionLocal()
        self.engagement = CommittedTestEngagement(self.db)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(runtime, "run_execution_in_background", side_effect=no_background_run)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.db.rollback()
        for repo in self.db.query(models.Repository).filter(models.Repository.engagement_id == self.engagement.engagement.id,
                                                             models.Repository.name.like(f"%{self.tag}%")):
            self.db.delete(repo)
        self.db.commit()
        self.db.close()

    # ---- helpers

    def signed_in(self, who: str, host: str) -> Client:
        user = getattr(self, who)
        client = Client(app)
        with on(host, user.windows_account):
            answer = client.post("/api/auth/sign-in", {"login": user.login, "password": PASSWORD})
        self.assertEqual(answer.status, 200, answer.body)
        return client

    def as_(self, who: str, host: str):
        return on(host, getattr(self, who).windows_account)

    def register(self, client: Client, who: str, host: str) -> str:
        folder = Path(self.tmp.name) / f"Repo{self.tag}{uuid.uuid4().hex[:4]}"
        folder.mkdir()
        (folder / "Program.cs").write_text("class Program {}\n")
        with self.as_(who, host):
            answer = client.post(f"/api/engagements/{self.engagement.engagement.id}/repositories/register",
                                 {"source_type": "local_path", "local_path": str(folder), "name": f"Repo {self.tag} {folder.name}"})
        self.assertEqual(answer.status, 202, answer.body)
        return answer.json()["repository_id"]

    # ---- sign-in

    def test_each_user_signs_in_only_from_their_registered_machine_under_their_own_account(self):
        client = Client(app)
        with on(MACHINE_A, self.alice.windows_account):
            ok = client.post("/api/auth/sign-in", {"login": self.alice.login, "password": PASSWORD})
            self.assertEqual(ok.status, 200, ok.body)
            self.assertEqual(client.get("/api/auth/me").json()["hostname"], MACHINE_A)
        # Alice's account and password on Bob's machine, where Alice is not registered.
        with on(MACHINE_B, self.alice.windows_account):
            refused = Client(app).post("/api/auth/sign-in", {"login": self.alice.login, "password": PASSWORD})
        self.assertEqual((refused.status, refused.code), (401, "NOT_REGISTERED_HERE"))
        self.assertEqual(refused.message, f"This account is not registered for this machine ({MACHINE_B}) — ask the admin.")
        # Alice's name and password on Bob's own platform, which runs under Bob's account: shared credentials.
        with on(MACHINE_B, self.bob.windows_account):
            refused = Client(app).post("/api/auth/sign-in", {"login": self.alice.login, "password": PASSWORD})
        self.assertEqual(refused.code, "NOT_REGISTERED_HERE")
        self.assertIn(f"registered for the Windows account {self.alice.windows_account}", refused.message)
        # A wrong password says nothing about which part was wrong.
        with on(MACHINE_A, self.alice.windows_account):
            wrong = Client(app).post("/api/auth/sign-in", {"login": self.alice.login, "password": "not-the-password"})
        self.assertEqual((wrong.status, wrong.code), (401, "WRONG_PASSWORD"))

    def test_every_call_needs_a_live_session_and_signing_out_ends_it(self):
        anonymous = Client(app)
        with on(MACHINE_A, self.alice.windows_account):
            self.assertEqual(anonymous.get("/api/engagements").code, "SIGNED_OUT")
            self.assertEqual(anonymous.get("/api/health").status, 200)                 # open
            self.assertEqual(anonymous.get("/api/auth/machine").json()["hostname"], MACHINE_A)
        client = self.signed_in("alice", MACHINE_A)
        self.assertIn("mp_session", client.cookies)
        with self.as_("alice", MACHINE_A):
            self.assertEqual(client.get("/api/engagements").status, 200)
            # The cookie on another machine's backend is not a session there.
        with self.as_("alice", MACHINE_B):
            self.assertEqual(client.get("/api/engagements").code, "SIGNED_OUT")
        with self.as_("alice", MACHINE_A):
            # Unused past SESSION_IDLE_MINUTES: it has ended.
            with mock.patch.object(service.settings, "session_idle_minutes", 0):
                self.assertEqual(client.get("/api/engagements").code, "SIGNED_OUT")
        client = self.signed_in("alice", MACHINE_A)
        with self.as_("alice", MACHINE_A):
            self.assertEqual(client.post("/api/auth/sign-out").status, 204)
            self.assertEqual(client.get("/api/engagements").code, "SIGNED_OUT")

    def test_an_admin_reset_password_is_replaced_at_the_next_sign_in(self):
        admin = self.signed_in("carol", MACHINE_C)
        with self.as_("carol", MACHINE_C):
            reset = admin.post(f"/api/users/{self.bob.id}/reset-password", {"temporary_password": "temporary-password-1"})
        self.assertEqual(reset.status, 200, reset.body)
        self.assertTrue(reset.json()["must_change_password"])
        with self.as_("bob", MACHINE_B):
            needed = Client(app).post("/api/auth/sign-in", {"login": self.bob.login, "password": "temporary-password-1"})
            self.assertEqual((needed.status, needed.code), (409, "PASSWORD_CHANGE_REQUIRED"))
            client = Client(app)
            done = client.post("/api/auth/sign-in", {"login": self.bob.login, "password": "temporary-password-1",
                                                      "new_password": PASSWORD})
            self.assertEqual(done.status, 200, done.body)
            self.assertFalse(done.json()["must_change_password"])
        with SessionLocal() as db:
            stored = db.get(models.User, self.bob.id).password_hash
        self.assertTrue(stored.startswith("scrypt$") and PASSWORD not in stored)
        self.assertTrue(passwords.verify(PASSWORD, stored))

    def test_a_developer_cannot_manage_users(self):
        client = self.signed_in("alice", MACHINE_A)
        with self.as_("alice", MACHINE_A):
            refused = client.post("/api/users", {"login": "x", "name": "X", "windows_account": r"CORP\x", "role": "admin",
                                                  "hosts": [MACHINE_A], "temporary_password": "temporary-password-1"})
        self.assertEqual((refused.status, refused.code), (403, "NOT_ALLOWED"))

    # ---- ownership

    def test_the_owner_acts_on_a_repository_and_everyone_else_sees_it_read_only(self):
        alice = self.signed_in("alice", MACHINE_A)
        repository_id = self.register(alice, "alice", MACHINE_A)
        with self.as_("alice", MACHINE_A):
            mine = alice.get(f"/api/repositories/{repository_id}").json()
            self.assertEqual((mine["owner_name"], mine["registered_host"], mine["can_act"]), ("Alice", MACHINE_A, True))
            self.assertEqual(alice.post(f"/api/repositories/{repository_id}/rescan").status, 202)
        bob = self.signed_in("bob", MACHINE_B)
        with self.as_("bob", MACHINE_B):
            seen = bob.get(f"/api/repositories/{repository_id}")
            self.assertEqual(seen.status, 200)                                  # B sees it
            self.assertFalse(seen.json()["can_act"])
            for method, url in (("POST", f"/api/repositories/{repository_id}/rescan"),
                                ("DELETE", f"/api/repositories/{repository_id}"),
                                ("POST", f"/api/repositories/{repository_id}/deletion"),
                                ("PUT", f"/api/repositories/{repository_id}")):
                refused = bob.request(method, url, {"confirm": "x"} if method != "DELETE" else None)
                self.assertEqual((refused.status, refused.code), (403, "NOT_ALLOWED"), (method, url, refused.body))
        # Bob on his own machine is told it is the owner's: the same reason the UI shows on the disabled actions.
        self.assertEqual(refused.message, "Only this repository's owner, Alice, or an admin may do this.")
        with self.as_("bob", MACHINE_B):
            self.assertEqual(seen.json()["cannot_act_reason"],
                             f"This repository was registered on {MACHINE_A}: its folder and run output are on that "
                             "machine, so do this from the platform there.")
        # Recorded: who registered and rescanned it, from which machine.
        with SessionLocal() as db:
            done = {(r.action, r.actor, r.hostname) for r in db.query(models.ActivityRecord)
                    .filter_by(subject_type="repository", subject_id=repository_id)}
        self.assertIn(("register_repository", f"Alice ({self.alice.login})", MACHINE_A), done)
        self.assertIn(("rescan_repository", f"Alice ({self.alice.login})", MACHINE_A), done)

    def test_an_admin_acts_on_any_repository_but_only_on_its_own_machine(self):
        alice = self.signed_in("alice", MACHINE_A)
        repository_id = self.register(alice, "alice", MACHINE_A)
        carol_here = self.signed_in("carol", MACHINE_A)
        with self.as_("carol", MACHINE_A):
            self.assertEqual(carol_here.post(f"/api/repositories/{repository_id}/rescan").status, 202)
        carol_there = self.signed_in("carol", MACHINE_C)
        with self.as_("carol", MACHINE_C):
            refused = carol_there.post(f"/api/repositories/{repository_id}/rescan")
            self.assertEqual(refused.code, "NOT_ALLOWED")
            self.assertIn(f"registered on {MACHINE_A}", refused.message)
            # Ownership is the admin's to assign, from any machine.
            moved = carol_there.put(f"/api/repositories/{repository_id}/owner", {"owner_user_id": str(self.bob.id)})
            self.assertEqual(moved.json()["owner_name"], "Bob")

    def test_a_repository_from_before_sign_in_is_the_admins_until_one_assigns_an_owner(self):
        alice = self.signed_in("alice", MACHINE_A)
        repository_id = self.register(alice, "alice", MACHINE_A)
        with SessionLocal() as db:                        # as the migration leaves an existing repository
            repo = db.get(models.Repository, uuid.UUID(repository_id))
            repo.owner_user_id, repo.registered_host = None, None
            db.commit()
        with self.as_("alice", MACHINE_A):
            refused = alice.post(f"/api/repositories/{repository_id}/rescan")
        self.assertEqual(refused.code, "NOT_ALLOWED")
        self.assertIn("no owner yet", refused.message)
        carol = self.signed_in("carol", MACHINE_A)
        with self.as_("carol", MACHINE_A):
            self.assertEqual(carol.put(f"/api/repositories/{repository_id}/owner",
                                       {"owner_user_id": str(self.alice.id)}).status, 200)
        with self.as_("alice", MACHINE_A):
            self.assertEqual(alice.post(f"/api/repositories/{repository_id}/rescan").status, 202)

    # ---- jobs stay on their machine

    def test_a_job_queued_on_one_machine_never_runs_on_another(self):
        alice = self.signed_in("alice", MACHINE_A)
        repository_id = self.register(alice, "alice", MACHINE_A)
        with SessionLocal() as db:
            instance = next(i for i in db.query(models.WfJobInstance) if i.parameters.get("repository_id") == repository_id)
            execution = db.query(models.WfJobExecution).filter_by(job_instance_id=instance.id).one()
            self.assertEqual((execution.queued_by_host, execution.queued_by_user_id, execution.batch_status),
                             (MACHINE_A, self.alice.id, "STARTING"))
            definition = db.get(models.WfJobDefinition, execution.job_definition_id).definition
        # Bob's runner is handed Alice's job: it does not run it, and leaves it exactly as it is.
        with on(MACHINE_B, self.bob.windows_account):
            REAL_RUN(execution.id, instance.id, definition)
            with SessionLocal() as db:
                with self.assertRaises(executor.ForeignJob):
                    executor.ensure_local(db.get(models.WfJobExecution, execution.id))
            # Bob's backend starting up does not fail Alice's running job either.
            _reconcile_orphaned_executions()
        with SessionLocal() as db:
            self.assertEqual(db.get(models.WfJobExecution, execution.id).batch_status, "STARTING")
        # Alice's backend restarting does: it was its own.
        with on(MACHINE_A, self.alice.windows_account):
            _reconcile_orphaned_executions()
        with SessionLocal() as db:
            after = db.get(models.WfJobExecution, execution.id)
            self.assertEqual((after.batch_status, after.exit_message), ("FAILED", "orphaned by engine restart"))

    # ---- shared records: a stale copy is refused

    def test_two_simultaneous_edits_of_one_decision_end_with_a_stale_copy_refusal(self):
        pattern_id = self.db.query(models.Pattern.id).order_by(models.Pattern.id).first()[0]
        url = f"/api/engagements/{self.engagement.engagement.id}/patterns/{pattern_id}/decision"
        carol_a = self.signed_in("carol", MACHINE_A)
        with self.as_("carol", MACHINE_A):
            created = carol_a.put(url, {"status": "parked", "rationale": "first"}, headers={"If-Match": "0"})
        self.assertIn(created.status, (200, 201), created.body)
        version = created.json()["version"]
        self.addCleanup(self._remove_decision, created.json()["id"])
        # Two sessions, each with the copy at that version, save at the same moment. (One simulated machine: the
        # machine is patched for the whole process, so two threads cannot be two machines at once.)
        second = self.signed_in("carol", MACHINE_A)
        answers = {}

        def save(name, client, rationale):
            answers[name] = client.put(url, {"status": "parked", "rationale": rationale},
                                       headers={"If-Match": str(version)})

        with self.as_("carol", MACHINE_A):
            threads = [threading.Thread(target=save, args=("first", carol_a, "edited in one session")),
                       threading.Thread(target=save, args=("second", second, "edited in another"))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        statuses = sorted(a.status for a in answers.values())
        self.assertEqual(statuses, [200, 409], {k: v.body for k, v in answers.items()})
        refused = next(a for a in answers.values() if a.status == 409)
        self.assertEqual(refused.code, "STALE_COPY")
        self.assertIn("someone else changed this decision first", refused.message)
        self.assertIn("Nothing was overwritten", refused.message)
        saved = next(a for a in answers.values() if a.status == 200).json()
        self.assertEqual(saved["version"], version + 1)
        with SessionLocal() as db:
            self.assertEqual(db.get(models.DecisionRecord, uuid.UUID(saved["id"])).rationale, saved["rationale"])
        # A developer may not edit decisions at all.
        alice = self.signed_in("alice", MACHINE_A)
        with self.as_("alice", MACHINE_A):
            self.assertEqual(alice.put(url, {"status": "parked"}, headers={"If-Match": str(version + 1)}).code, "NOT_ALLOWED")

    def test_an_edit_that_does_not_say_which_version_it_changes_is_refused_with_428(self):
        pattern_id = self.db.query(models.Pattern.id).order_by(models.Pattern.id.desc()).first()[0]
        url = f"/api/engagements/{self.engagement.engagement.id}/patterns/{pattern_id}/decision"
        carol = self.signed_in("carol", MACHINE_A)
        with self.as_("carol", MACHINE_A):
            missing = carol.put(url, {"status": "parked", "rationale": "no version"})
            self.assertEqual((missing.status, missing.code), (428, "VERSION_REQUIRED"))
            self.assertIn("does not say which version", missing.message)
            # Reverting a matrix confirmation names the confirmation it saw, or is refused the same way.
            revert = carol.post(f"/api/engagements/{self.engagement.engagement.id}/estate/matrix-confirmations/revert",
                                {"entry_id": "some-entry", "by": "Carol", "reason": "test"})
            self.assertEqual((revert.status, revert.code), (428, "VERSION_REQUIRED"))
        with SessionLocal() as db:
            self.assertEqual(db.query(models.DecisionRecord).filter_by(engagement_id=self.engagement.engagement.id,
                                                                       pattern_id=pattern_id).count(), 0)

    def _remove_decision(self, decision_id: str):
        with SessionLocal() as db:
            row = db.get(models.DecisionRecord, uuid.UUID(decision_id))
            if row is not None:
                db.delete(row)
                db.commit()

    # ---- one backend per machine

    def test_a_second_backend_on_the_same_machine_is_refused_and_two_machines_run_side_by_side(self):
        on_a = heartbeat.Me(uuid.uuid4(), MACHINE_A, "alice", 1001, r"C:\MP\a", 8001)
        again_a = heartbeat.Me(uuid.uuid4(), MACHINE_A, "alice", 1002, r"C:\MP\a", 8001)
        on_b = heartbeat.Me(uuid.uuid4(), MACHINE_B, "bob", 2001, r"C:\MP\b", 8001)
        try:
            heartbeat.claim(on_a, alive=lambda pid: True)
            with self.assertRaises(heartbeat.AnotherPlatform) as refused:
                heartbeat.claim(again_a, alive=lambda pid: True)
            self.assertIn(f"already running on this machine ({MACHINE_A.lower()})", str(refused.exception))
            heartbeat.claim(on_b, alive=lambda pid: True)                       # another machine: side by side
            self.signed_in("bob", MACHINE_B)
            with SessionLocal() as db:
                online = {entry["host"]: entry["user_name"] for entry in heartbeat.online(db)}
            self.assertIn(MACHINE_A.lower(), online)
            self.assertEqual(online[MACHINE_B.lower()], "Bob")             # who is online, and where
        finally:
            heartbeat.release(on_a)
            heartbeat.release(on_b)

    # ---- the policy covers every route

    def test_every_change_is_admins_only_unless_the_policy_names_it(self):
        routes = {(method, route.path) for route in app.routes for method in getattr(route, "methods", ()) or ()
                  if method not in policy.READ_METHODS}
        self.assertFalse(set(policy.RULES) - routes, "the policy names routes that do not exist")
        developer = service.actors.Actor(self.alice.id, self.alice.login, "Alice", "developer", MACHINE_A)
        with SessionLocal() as db:
            open_to_developers = {key for key in routes if policy.refusal(db, developer, key[0], key[1], {}) is None}
        # Without a repository to look at, an owner's route is not refused here: the guard checks the repository named.
        self.assertEqual(open_to_developers, {k for k, rule in policy.RULES.items() if rule in (policy.ANY, policy.OWNER)})


class CommandLineIdentity(unittest.TestCase):
    def test_a_command_acts_as_the_registered_user_of_this_account_and_machine_and_refuses_otherwise(self):
        with SessionLocal() as db:
            with on("NOWHERE-1", r"CORP\nobody"):
                with self.assertRaises(SystemExit) as refused:
                    service.cli_actor(db)
            self.assertIn(r"No user is registered for the Windows account CORP\nobody", str(refused.exception))
            person = service.cli_actor(db)                     # this machine's test admin (tests/__init__.py)
            self.assertTrue(person.is_admin)


if __name__ == "__main__":
    unittest.main()
