"""Users from the command line (docs/VDI-SETUP.md, "Users and sign-in").

    python -m app.users create-first-admin --login jdoe --name "Jane Doe"
    python -m app.users add --login asmith --name "Alex Smith" --windows-account CORP\\asmith --host DEVBOX-07
    python -m app.users list
    python -m app.users requests [--all]
    python -m app.users approve --request 3f2a9c1e
    python -m app.users reject --request 3f2a9c1e [--reason "..."]
    python -m app.users promote --login asmith
    python -m app.users reset-password --login asmith
    python -m app.users set --login asmith [--role developer] [--host DEVBOX-07 --host LAPTOP-12] [--windows-account CORP\\asmith] [--deactivate | --activate]
    python -m app.users owners [--engagement test-client-a]
    python -m app.users assign-owner --engagement test-client-a --repository orderservice --login asmith

create-first-admin is run once, at installation, before anyone can sign in: it registers the person running it as an
admin, with this machine's Windows account and hostname unless --windows-account and --host say otherwise, and
refuses once an admin exists. After that nobody becomes an admin except by `promote`, an admin's action, recorded:
`add` and an approved access request register developers. People ask for access from their own platform's sign-in
page; `requests` lists the requests, `approve` and `reject` decide them (app.auth.requests). Every other command acts
as the registered user whose Windows account and machine run it, and is for admins (`list` and `owners` for anyone
registered). Passwords are asked for without echo; for a script,
--password-env NAME reads one from that environment variable instead. A password set here for someone else is
temporary: they choose their own at their first sign-in.
"""
import argparse
import getpass
import os
import sys

from sqlalchemy import String, func

from app import models
from app.auth import activity, machine, requests, service
from app.auth import actor as actors


def _password(args, prompt: str) -> str:
    if getattr(args, "password_env", None):
        value = os.environ.get(args.password_env)
        if not value:
            raise SystemExit(f"The environment variable {args.password_env} is empty.")
        return value
    first = getpass.getpass(f"{prompt}: ")
    if getpass.getpass("Again: ") != first:
        raise SystemExit("The two passwords differ. Nothing was changed.")
    return first


def _user(db, login: str) -> models.User:
    user = service.by_login(db, login)
    if user is None:
        raise SystemExit(f"No user signs in as '{login}'.")
    return user


def _request(db, given: str) -> models.AccessRequest:
    rows = [r for r in db.query(models.AccessRequest) if str(r.id).startswith(given.strip().lower())]
    if len(rows) != 1:
        raise SystemExit(f"No access request starts with '{given}'." if not rows else
                         f"'{given}' starts {len(rows)} requests: give more of its id.")
    return rows[0]


def _repository(db, engagement: str, repository: str) -> models.Repository:
    found = (db.query(models.Repository)
             .filter(models.Repository.engagement_id == engagement, models.Repository.deleted_at.is_(None),
                     (func.lower(models.Repository.slug) == repository.lower()) | (models.Repository.id.cast(String) == repository))
             .one_or_none())
    if found is None:
        raise SystemExit(f"No repository '{repository}' in engagement '{engagement}'.")
    return found


def _show(db, user: models.User) -> str:
    state = "" if user.deactivated_at is None else "  (deactivated)"
    reset = "  (must set a new password)" if user.must_change_password else ""
    return (f"{user.login:16} {user.role:10} {user.name}  {user.windows_account}  on {', '.join(service.hosts(db, user))}"
            f"{state}{reset}")


def main(argv: list[str] | None = None) -> int:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(prog="python -m app.users", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    first = sub.add_parser("create-first-admin", help="register the first admin, once, at installation")
    add = sub.add_parser("add", help="register a user (admins)")
    for p in (first, add):
        p.add_argument("--login", required=True)
        p.add_argument("--name", required=True)
        p.add_argument("--windows-account", help="DOMAIN\\user (default for create-first-admin: this account)")
        p.add_argument("--host", action="append", help="a machine they sign in from; repeat for several "
                                                       "(default for create-first-admin: this machine)")
        p.add_argument("--password-env", help="read the password from this environment variable instead of asking")
    # Accepted as before, so a script that names it still works; an admin is made with promote.
    add.add_argument("--role", choices=[actors.DEVELOPER], help="always developer: make an admin with promote")
    sub.add_parser("list", help="every registered user")
    listing = sub.add_parser("requests", help="access requests, pending first (admins)")
    listing.add_argument("--all", action="store_true", help="decided ones too")
    approving = sub.add_parser("approve", help="approve an access request, as a developer (admins)")
    approving.add_argument("--request", required=True, help="its id, or the first characters of it")
    rejecting = sub.add_parser("reject", help="reject an access request (admins)")
    rejecting.add_argument("--request", required=True, help="its id, or the first characters of it")
    rejecting.add_argument("--reason", help="shown to the requester on their sign-in page")
    promoting = sub.add_parser("promote", help="make a user an admin (admins)")
    promoting.add_argument("--login", required=True)
    reset = sub.add_parser("reset-password", help="set a temporary password (admins)")
    reset.add_argument("--login", required=True)
    reset.add_argument("--password-env")
    change = sub.add_parser("set", help="change a user (admins)")
    change.add_argument("--login", required=True)
    change.add_argument("--name")
    change.add_argument("--role", choices=actors.ROLES)
    change.add_argument("--windows-account")
    change.add_argument("--host", action="append", help="replaces their machines; repeat for several")
    change.add_argument("--deactivate", action="store_true")
    change.add_argument("--activate", action="store_true")
    owners = sub.add_parser("owners", help="repositories and their owners; those with none first")
    owners.add_argument("--engagement")
    assign = sub.add_parser("assign-owner", help="give a repository its owner (admins)")
    assign.add_argument("--engagement", required=True)
    assign.add_argument("--repository", required=True, help="its slug, or its id")
    assign.add_argument("--login", required=True, help="the owner's sign-in name, or 'none' to leave it ownerless")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        try:
            if args.command == "create-first-admin":
                if service.admins_exist(db):
                    raise SystemExit("An admin exists already: create-first-admin runs once. Everyone else asks for access "
                                     "from their own platform's sign-in page, and an admin approves it (python -m "
                                     "app.users requests, or Users in the UI).")
                user = service.create_user(
                    db, login=args.login, name=args.name, windows_account=args.windows_account or machine.windows_account(),
                    role=actors.ADMIN, host_names=args.host or [machine.hostname()],
                    password=_password(args, "Your password (12 characters or more)"), must_change_password=False)
                activity.record(db, "create_first_admin", "user", str(user.id), f"Created the first admin, {user.name}",
                                actor=actors.of(user, machine.hostname()))
                db.commit()
                print(f"Created the first admin:\n  {_show(db, user)}\nSign in to the platform with '{user.login}' "
                      f"from {', '.join(service.hosts(db, user))}.")
                return 0
            if args.command == "add":
                service.cli_actor(db, admin=True)
                if not args.windows_account or not args.host:
                    raise SystemExit("add needs --windows-account and at least one --host.")
                user = service.create_user(db, login=args.login, name=args.name, windows_account=args.windows_account,
                                           role=actors.DEVELOPER, host_names=args.host,
                                           password=_password(args, f"A temporary password for {args.name}"))
                activity.record(db, "create_user", "user", str(user.id), f"Registered {user.name}")
                db.commit()
                print(f"Registered:\n  {_show(db, user)}\nThey choose their own password at their first sign-in.")
                return 0
            if args.command == "list":
                service.cli_actor(db)
                for user in db.query(models.User).order_by(func.lower(models.User.login)):
                    print(_show(db, user))
                return 0
            if args.command == "requests":
                service.cli_actor(db, admin=True)
                query = db.query(models.AccessRequest)
                if not args.all:
                    query = query.filter(models.AccessRequest.status == requests.PENDING)
                rows = query.order_by(models.AccessRequest.status != requests.PENDING, models.AccessRequest.requested_at.desc()).all()
                if not rows:
                    print("No access request is pending." if not args.all else "No access request.")
                for row in rows:
                    what = "access" if row.kind == requests.ACCESS else "add machine"
                    reason = f"  ({row.reason})" if row.reason else ""
                    print(f"{str(row.id)[:8]}  {row.status:8} {what:11} {row.name} as {row.login}  {row.windows_account} on "
                          f"{row.hostname}  {row.requested_at:%Y-%m-%d %H:%M}{reason}")
                return 0
            if args.command in ("approve", "reject"):
                admin = service.cli_actor(db, admin=True)
                row = _request(db, args.request)
                if args.command == "approve":
                    user = requests.approve(db, row, admin)
                    db.commit()
                    print(f"Approved: {user.name} signs in as '{user.login}' from {row.hostname}, as a "
                          f"{user.role}." if row.kind == requests.ACCESS else f"Approved: {row.hostname} added to {user.name}'s machines.")
                else:
                    requests.reject(db, row, admin, args.reason)
                    db.commit()
                    print(f"Rejected {row.name}'s request." + (f" Reason: {row.reason}" if row.reason else ""))
                return 0
            if args.command == "promote":
                admin = service.cli_actor(db, admin=True)
                user = _user(db, args.login)
                requests.promote(db, user, admin)
                db.commit()
                print(f"{user.name} is an admin now.")
                return 0
            if args.command == "reset-password":
                service.cli_actor(db, admin=True)
                user = _user(db, args.login)
                service.reset_password(db, user, _password(args, f"A temporary password for {user.name}"))
                activity.record(db, "reset_user_password", "user", str(user.id), f"Reset {user.name}'s password")
                db.commit()
                print(f"Reset. {user.name} sets a new password at their next sign-in; their sessions have ended.")
                return 0
            if args.command == "set":
                service.cli_actor(db, admin=True)
                user = _user(db, args.login)
                active = True if args.activate else False if args.deactivate else None
                service.update_user(db, user, name=args.name, role=args.role, windows_account=args.windows_account,
                                    host_names=args.host, active=active)
                activity.record(db, "update_user", "user", str(user.id), f"Changed {user.name}")
                db.commit()
                print(_show(db, user))
                return 0
            if args.command == "owners":
                service.cli_actor(db)
                query = db.query(models.Repository).filter(models.Repository.deleted_at.is_(None))
                if args.engagement:
                    query = query.filter(models.Repository.engagement_id == args.engagement)
                rows = sorted(query, key=lambda r: (r.owner_user_id is not None, r.engagement_id, r.slug))
                for repo in rows:
                    owner = db.get(models.User, repo.owner_user_id) if repo.owner_user_id else None
                    print(f"{repo.engagement_id:20} {repo.slug:30} {owner.login if owner else '(no owner: admins only)'}")
                return 0
            if args.command == "assign-owner":
                service.cli_actor(db, admin=True)
                repo = _repository(db, args.engagement, args.repository)
                owner = None if args.login.lower() == "none" else _user(db, args.login)
                repo.owner_user_id = owner.id if owner else None
                activity.record(db, "assign_repository_owner", "repository", str(repo.id),
                                f"Owner: {owner.name if owner else 'none'}")
                db.commit()
                print(f"{repo.engagement_id}/{repo.slug}: owned by {owner.name if owner else 'nobody (admins only)'}")
                return 0
        except service.Refused as refused:
            db.rollback()
            raise SystemExit(refused.message) from None
    return 1


if __name__ == "__main__":
    sys.exit(main())
