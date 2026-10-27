"""Hard delete from the command line: the same plan and checks as the UI (app.deletion.service). The backend need not
be running; a job of what is being deleted must not be.

    python -m app.deletion.cli repository --engagement client-a --repository orderservice
    python -m app.deletion.cli engagement --engagement client-a
    python -m app.deletion.cli repository --engagement client-a --repository orderservice --dry-run
    python -m app.deletion.cli audit

It prints exactly what will go — rows by table, folders, worktrees, branches, and every conversion that has been run
(its agent's work lives only on its branch) — then asks for the repository's or engagement's name to be typed.
--confirm "<name>" types it for you (scripts); --dry-run shows the plan and deletes nothing.
"""
import argparse
import sys

from app import models
from app.auth import policy
from app.auth import service as auth
from app.db import SessionLocal
from app.deletion import service


def _mb(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB"


def show(plan: dict) -> None:
    what = f"repository {plan['repository']} ({plan['name']}) of engagement {plan['engagement']}" \
        if plan["kind"] == "repository" else f"engagement {plan['engagement']} ({plan['name']}), with " \
        f"{len(plan['repositories'])} repositor{'y' if len(plan['repositories']) == 1 else 'ies'}: {', '.join(plan['repositories']) or 'none'}"
    print(f"Hard delete of {what}. This cannot be undone.\n")
    print(f"Database rows ({sum(plan['rows'].values())}):")
    for table, n in plan["rows"].items():
        print(f"  {table:34} {n}")
    print("\nFolders under RUNS_DIR:")
    for f in plan["folders"] or [{"path": "(none)", "files": 0, "bytes": 0}]:
        print(f"  {f['path']}  ({f['files']} files, {_mb(f['bytes'])})")
    for c in plan["checkouts"]:
        print(f"\n{c['stays']}")
        print("What goes in it:")
        if not c["available"]:
            print("  not a git checkout here any more: nothing to remove in it")
            continue
        for w in c["worktrees"]:
            print(f"  worktree  {w['path']}  [{w['branch'] or 'detached'}]")
        for b in c["branches"]:
            print(f"  branch    {b['branch']}  ({b['source']}; {b['commits_only_here']} commit(s) on no other branch)")
        for k in c["kept"]:
            print(f"  kept      {k['branch']}  ({k['source']}): {k['why']}")
        if not (c["worktrees"] or c["branches"] or c["kept"]):
            print("  nothing the platform created")
    run = [r for c in plan["checkouts"] for r in c["run"]]
    if run:
        print("\nConversions that have been run — the agent's work lives only on these branches, and goes with them:")
        for r in run:
            print(f"  {r['repository']} conversion {r['number']}: {r['branch']}, {r['agent_commits']} commit(s) by the agent")
    print(f"\nKept: {plan['kept_shared']}.")
    if plan.get("estate_note"):
        print(f"Note: {plan['estate_note']}.")
    if plan["running"]:
        print("\nRefused while these run: " + ", ".join(f"{r['job']} ({r['status']} since {r['since'][:16]})"
                                                       for r in plan["running"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.deletion.cli", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("repository", "engagement"):
        p = sub.add_parser(name)
        p.add_argument("--engagement", required=True)
        if name == "repository":
            p.add_argument("--repository", required=True, help="the repository's slug")
        p.add_argument("--confirm", help="the name to type, for scripts")
        p.add_argument("--dry-run", action="store_true", help="show what would go; delete nothing")
    sub.add_parser("audit", help="list the deletions made")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        # A repository: its owner or an admin, on the machine it was registered on; an engagement: an admin.
        person = auth.cli_actor(db, admin=args.command == "engagement")
        if args.command == "audit":
            for a in db.query(models.DeletionAudit).order_by(models.DeletionAudit.deleted_at):
                print(f"{a.deleted_at:%Y-%m-%d %H:%M} UTC  {a.kind:10} {a.engagement_id}"
                      f"{'/' + a.repository_slug if a.repository_slug else ''} ({a.name})  by {a.deleted_by} via {a.via}")
            return 0
        engagement = db.get(models.Engagement, args.engagement)
        if engagement is None:
            print(f"No engagement {args.engagement}.", file=sys.stderr)
            return 1
        if args.command == "repository":
            repo = db.query(models.Repository).filter_by(engagement_id=engagement.id, slug=args.repository).one_or_none()
            if repo is None:
                print(f"No repository {args.repository} in engagement {engagement.id}.", file=sys.stderr)
                return 1
            if why := policy.machine_refusal(repo, person.hostname) or policy.repository_refusal(db, person, repo):
                print(f"Refused: {why}", file=sys.stderr)
                return 1
            plan = service.repository_plan(db, repo)
        else:
            plan = service.engagement_plan(db, engagement)
        show(plan)
        if args.dry_run:
            print("\nDry run: nothing deleted.")
            return 0
        typed = args.confirm if args.confirm is not None else input(
            f"\nType the {plan['kind']}'s name, \"{plan['confirm']}\", to delete it: ")
        try:
            summary = service.delete(db, plan, typed, via="command line")
        except (service.DeletionRefused, service.DeletionIncomplete) as e:
            print(str(e), file=sys.stderr)
            return 1
        print(f"\nDeleted: {sum(summary['rows'].values())} rows, {len(summary['folders'])} folder(s), "
              f"{len(summary['worktrees'])} worktree(s), {len(summary['branches'])} branch(es). Recorded in the "
              "deletion audit (python -m app.deletion.cli audit).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
