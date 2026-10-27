"""Create and list engagements from the command line: the same checks as the API (app/engagements/service.py), run in
this process, so the backend does not need to be running.

    python -m app.engagements.cli create --name "Client A" --target-framework net10.0
    python -m app.engagements.cli create --name "Client A" --target-framework net8.0 --id client-a --target-platform "OpenShift 4"
    python -m app.engagements.cli list

`--id` defaults to one made from the name ("Client A" -> client-a).
"""
import argparse
import sys

from app import models
from app.auth import activity
from app.auth import service as auth
from app.db import SessionLocal
from app.engagements import service


def create(args) -> int:
    engagement_id = args.id or service.id_from_name(args.name)
    with SessionLocal() as db:
        auth.cli_actor(db, admin=True)
        try:
            engagement = service.create(db, engagement_id, args.name, args.target_framework,
                                        description=args.description, target_platform=args.target_platform)
        except service.EngagementError as e:
            print(f"Not created: {e}", file=sys.stderr)
            return 1
        activity.record(db, "create_engagement", "engagement", engagement.id, f"Created {engagement.client_name}")
        db.commit()
        print(f"Created engagement '{engagement.id}': {engagement.client_name}, target framework {engagement.target_framework}")
    return 0


def list_engagements(_args) -> int:
    with SessionLocal() as db:
        auth.cli_actor(db)
        rows = db.query(models.Engagement).filter(models.Engagement.deleted_at.is_(None)).order_by(models.Engagement.id).all()
        if not rows:
            print("No engagements.")
        for e in rows:
            print(f"{e.id:30} {e.target_framework:10} {e.client_name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.engagements.cli", description="Create and list engagements.")
    commands = parser.add_subparsers(dest="command", required=True)
    c = commands.add_parser("create", help="Create an engagement.")
    c.add_argument("--name", required=True, help='The client name shown in the UI, e.g. "Client A".')
    c.add_argument("--target-framework", required=True, help="The .NET target framework the estate moves to, e.g. net10.0.")
    c.add_argument("--id", help="The engagement id (lower case, digits, hyphens). Default: made from the name.")
    c.add_argument("--description")
    c.add_argument("--target-platform", help='Where it will run, e.g. "OpenShift 4".')
    c.set_defaults(run=create)
    ls = commands.add_parser("list", help="List engagements.")
    ls.set_defaults(run=list_engagements)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
