"""Access requests (app.auth.requests; docs/VDI-SETUP.md, "Users and sign-in"), with simulated machines against one
database: each machine is a hostname and the Windows account its backend runs under (app.auth.machine, patched), and
the app is called as a server would call it (tests.asgi_client), through the real guard and policy.

- a request, then its approval: the requester signs in as a developer;
- a rejection with a reason, shown to the requester, who may then ask again;
- a second request from the same account while one is pending, refused;
- a registered user's request for a new machine: approving it adds the machine;
- a non-admin approving, or promoting, refused; an admin's promotion recorded; no other route makes an admin;
- until approved, the requester reaches nothing;
- create-first-admin refused once an admin exists.

Runs in this test run's own schema (tests/__init__.py). Uses stdlib unittest, same rationale as test_repository_ingest.py.
"""
import contextlib
import io
import unittest
import uuid
from contextlib import redirect_stdout
from unittest import mock

from app import models
from app import users as users_cli
from app.auth import machine, service
from app.db import SessionLocal
from app.main import app
from tests.asgi_client import Client

PASSWORD = "a-long-enough-password"


@contextlib.contextmanager
def on(host: str, account: str):
    with mock.patch.object(machine, "hostname", return_value=host), \
            mock.patch.object(machine, "windows_account", return_value=account):
        yield


class AccessRequests(unittest.TestCase):
    def setUp(self):
        self.tag = uuid.uuid4().hex[:6]
        self.admin_account, self.admin_host = rf"CORP\boss{self.tag}", f"ADMIN-{self.tag}"
        with SessionLocal() as db:
            self.admin = service.create_user(db, login=f"boss-{self.tag}", name="Boss", windows_account=self.admin_account,
                                             role="admin", host_names=[self.admin_host], password=PASSWORD,
                                             must_change_password=False)
            db.commit()
            self.admin_login = self.admin.login
        self.made: list[str] = []

    def tearDown(self):
        with SessionLocal() as db:
            accounts = [self.admin_account.lower()] + [a.lower() for a in self.made]
            db.query(models.AccessRequest).filter(models.AccessRequest.windows_account.in_(
                [a for a in [self.admin_account] + self.made])).delete(synchronize_session=False)
            for user in db.query(models.User).all():
                if user.windows_account.lower() in accounts:
                    db.query(models.ActivityRecord).filter_by(user_id=user.id).update({"user_id": None})
                    db.delete(user)
            db.commit()

    # ---- helpers

    def account(self, name: str) -> str:
        account = rf"CORP\{name}{self.tag}"
        self.made.append(account)
        return account

    def sign_in(self, login: str, host: str, account: str, password: str = PASSWORD):
        client = Client(app)
        with on(host, account):
            answer = client.post("/api/auth/sign-in", {"login": login, "password": password})
        return client, answer

    def admin_client(self) -> Client:
        client, answer = self.sign_in(self.admin_login, self.admin_host, self.admin_account)
        self.assertEqual(answer.status, 200, answer.body)
        return client

    def ask(self, host: str, account: str, name: str = "New Person", password: str = PASSWORD):
        with on(host, account):
            return Client(app).post("/api/auth/access-request", {"name": name, "password": password})

    def status(self, host: str, account: str):
        with on(host, account):
            return Client(app).get("/api/auth/access-request").json()

    def as_admin(self, client: Client, method: str, url: str, body=None):
        with on(self.admin_host, self.admin_account):
            return client.request(method, url, body)

    def activity(self, request_id: str) -> list[str]:
        with SessionLocal() as db:
            return [r.action for r in db.query(models.ActivityRecord).filter_by(subject_type="access_request",
                                                                                 subject_id=request_id).order_by(models.ActivityRecord.id)]

    # ---- the tests

    def test_a_request_then_its_approval_lets_the_requester_in_as_a_developer(self):
        account, host = self.account("ann"), f"DEVBOX-{self.tag}"
        asked = self.ask(host, account, name="Ann Example")
        self.assertEqual(asked.status, 201, asked.body)
        self.assertEqual((asked.json()["status"], asked.json()["login"]), ("pending", f"ann{self.tag}"))

        # Until approved, the requester reaches nothing, and is told it is pending.
        _, refused = self.sign_in(f"ann{self.tag}", host, account)
        self.assertEqual(refused.status, 401)
        with on(host, account):
            self.assertEqual(Client(app).get("/api/engagements").status, 401)
        self.assertEqual(self.status(host, account)["status"], "pending")

        admin = self.admin_client()
        me = self.as_admin(admin, "GET", "/api/auth/me").json()
        self.assertGreaterEqual(me["pending_access_requests"], 1)
        listed = self.as_admin(admin, "GET", "/api/access-requests?status=pending").json()
        request = next(r for r in listed if r["windows_account"] == account)
        self.assertEqual(request["hostname"], host)
        approved = self.as_admin(admin, "POST", f"/api/access-requests/{request['id']}/approve")
        self.assertEqual(approved.status, 200, approved.body)
        self.assertEqual(approved.json()["decided_by"], "Boss")

        client, signed_in = self.sign_in(f"ann{self.tag}", host, account)
        self.assertEqual(signed_in.status, 200, signed_in.body)
        self.assertEqual((signed_in.json()["role"], signed_in.json()["name"]), ("developer", "Ann Example"))
        self.assertEqual(self.status(host, account)["status"], "approved")
        self.assertEqual(self.activity(request["id"]), ["request_access", "approve_access_request"])

    def test_a_rejection_says_why_and_the_requester_may_ask_again(self):
        account, host = self.account("rob"), f"DEVBOX-{self.tag}"
        asked = self.ask(host, account)
        admin = self.admin_client()
        request_id = next(r["id"] for r in self.as_admin(admin, "GET", "/api/access-requests").json() if r["windows_account"] == account)
        rejected = self.as_admin(admin, "POST", f"/api/access-requests/{request_id}/reject", {"reason": "Not on this programme."})
        self.assertEqual(rejected.status, 200, rejected.body)
        shown = self.status(host, account)
        self.assertEqual((shown["status"], shown["reason"]), ("rejected", "Not on this programme."))
        self.assertEqual(self.as_admin(admin, "POST", f"/api/access-requests/{request_id}/approve").status, 409)
        self.assertEqual(self.ask(host, account).status, 201)
        self.assertEqual(self.status(host, account)["status"], "pending")
        self.assertEqual(self.activity(request_id), ["request_access", "reject_access_request"])
        self.assertEqual(asked.status, 201)

    def test_a_second_request_from_the_same_account_while_one_is_pending_is_refused(self):
        account = self.account("dup")
        self.assertEqual(self.ask(f"ONE-{self.tag}", account).status, 201)
        again = self.ask(f"TWO-{self.tag}", account)
        self.assertEqual((again.status, again.code), (409, "REQUEST_PENDING"))

    def test_a_registered_user_on_a_new_machine_asks_to_add_it_and_approval_adds_it(self):
        account, home, laptop = self.account("mia"), f"HOME-{self.tag}", f"LAPTOP-{self.tag}"
        with SessionLocal() as db:
            service.create_user(db, login=f"mia-{self.tag}", name="Mia", windows_account=account, role="developer",
                                host_names=[home], password=PASSWORD, must_change_password=False)
            db.commit()
        _, refused = self.sign_in(f"mia-{self.tag}", laptop, account)
        self.assertEqual(refused.status, 401)
        self.assertEqual(self.ask(laptop, account, password="not-the-password-at-all").status, 401)
        self.assertEqual(self.ask(home, account).code, "ALREADY_REGISTERED")
        asked = self.ask(laptop, account, name="")
        self.assertEqual((asked.status, asked.json()["kind"]), (201, "machine"))
        admin = self.admin_client()
        request_id = next(r["id"] for r in self.as_admin(admin, "GET", "/api/access-requests").json() if r["windows_account"] == account)
        self.assertEqual(self.as_admin(admin, "POST", f"/api/access-requests/{request_id}/approve").status, 200)
        client, signed_in = self.sign_in(f"mia-{self.tag}", laptop, account)
        self.assertEqual(signed_in.status, 200, signed_in.body)
        self.assertEqual(sorted(signed_in.json()["hosts"]), sorted([home, laptop]))

    def test_only_an_admin_approves_or_promotes_and_nothing_else_makes_an_admin(self):
        account, host = self.account("dev"), f"DEV-{self.tag}"
        with SessionLocal() as db:
            dev = service.create_user(db, login=f"dev-{self.tag}", name="Dev", windows_account=account, role="developer",
                                      host_names=[host], password=PASSWORD, must_change_password=False)
            db.commit()
            dev_id = str(dev.id)
        other = self.account("oth")
        self.ask(f"OTH-{self.tag}", other)
        admin = self.admin_client()
        request_id = next(r["id"] for r in self.as_admin(admin, "GET", "/api/access-requests").json() if r["windows_account"] == other)

        developer, answer = self.sign_in(f"dev-{self.tag}", host, account)
        self.assertEqual(answer.status, 200, answer.body)
        with on(host, account):
            self.assertEqual(developer.post(f"/api/access-requests/{request_id}/approve").status, 403)
            self.assertEqual(developer.post(f"/api/users/{dev_id}/promote").status, 403)
            self.assertEqual(developer.put(f"/api/users/{dev_id}", {"role": "admin"}).status, 403)
            self.assertEqual(developer.get("/api/access-requests").status, 403)
        # An admin, too, makes an admin only by promoting.
        self.assertEqual(self.as_admin(admin, "PUT", f"/api/users/{dev_id}", {"role": "admin"}).code, "PROMOTE_SEPARATELY")
        made = self.as_admin(admin, "POST", "/api/users", {"login": f"x-{self.tag}", "name": "X", "windows_account": self.account("x"),
                                                           "role": "admin", "hosts": ["X"], "temporary_password": PASSWORD})
        self.assertEqual(made.code, "PROMOTE_SEPARATELY")
        promoted = self.as_admin(admin, "POST", f"/api/users/{dev_id}/promote")
        self.assertEqual((promoted.status, promoted.json()["role"]), (200, "admin"))
        with SessionLocal() as db:
            record = db.query(models.ActivityRecord).filter_by(action="promote_user", subject_id=dev_id).one()
            self.assertEqual(record.actor, f"Boss (boss-{self.tag})")

    def test_create_first_admin_is_refused_once_an_admin_exists(self):
        with self.assertRaises(SystemExit) as refused, redirect_stdout(io.StringIO()):
            users_cli.main(["create-first-admin", "--login", f"again-{self.tag}", "--name", "Again", "--password-env", "UNUSED"])
        self.assertIn("An admin exists already", str(refused.exception))
