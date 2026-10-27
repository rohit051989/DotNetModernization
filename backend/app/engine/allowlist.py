"""An engagement's engine allowlist (36-COPILOT-ENHANCED-CONVERSION Part I).

    python -m app.engine.allowlist show  --engagement test-client-a
    python -m app.engine.allowlist allow  --engagement test-client-a --provider github-copilot --organisation <org>
    python -m app.engine.allowlist revoke --engagement test-client-a --provider github-copilot --organisation <org>

Setting the list is a decision for the engagement: which engine and LLM providers its code may be sent
to, and under which organisation. It starts empty. Names only: there is no option for a credential.
"""
import argparse
import json
import sys

from app import models
from app.engine import boundary


def main(argv: list[str] | None = None) -> int:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(prog="python -m app.engine.allowlist", description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("show", "allow", "revoke"))
    parser.add_argument("--engagement", required=True)
    parser.add_argument("--provider", choices=sorted(boundary.PROVIDERS))
    parser.add_argument("--organisation", help="the organisation the engine must report; omit only for a provider without one")
    args = parser.parse_args(argv)
    db = SessionLocal()
    try:
        from app.auth import service as auth

        # An engagement's settings: changing them is for admins.
        auth.cli_actor(db, admin=args.command != "show")
        engagement = db.get(models.Engagement, args.engagement)
        if engagement is None or engagement.deleted_at is not None:
            print(f"no engagement {args.engagement}", file=sys.stderr)
            return 1
        if args.command != "show":
            if not args.provider:
                parser.error("--provider is required")
            change = boundary.allow if args.command == "allow" else boundary.revoke
            # The engagement's settings are a versioned record: the change names the version it was made on.
            change(db, engagement, args.provider, args.organisation, engagement.version)
            db.commit()
        print(json.dumps({"engagement": engagement.id, "engineAllowlist": boundary.allowlist(engagement)}, indent=2))
        return 0
    except (ValueError, boundary.CredentialRefused) as err:
        db.rollback()
        print(str(err), file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
