"""python -m app.toolchain report [--json]

Every registered repository checked against this machine (Part P): which runtimes and build tools its baseline needs
that this machine lacks. Read-only: nothing is recorded, so a repository registered on another machine keeps what its
own machine found. scripts\\preflight.py runs it with --json.
"""
import argparse
import json
import sys

from app.auth import machine as host_machine


def report() -> dict:
    from app import models
    from app.db import SessionLocal
    from app.toolchain import machine, service

    facts = machine.facts()
    out, missing = [], {}
    with SessionLocal() as db:
        repositories = (db.query(models.Repository).filter(models.Repository.deleted_at.is_(None))
                        .order_by(models.Repository.engagement_id, models.Repository.slug).all())
        for repository in repositories:
            result = service.check(db, repository, facts)
            name = f"{repository.engagement_id}/{repository.slug}"
            here = not repository.registered_host or host_machine.same(repository.registered_host, host_machine.hostname())
            out.append({"repository": name, "here": here, "ready": result["ready"], "summary": result["summary"]})
            for m in result["missing"]:
                missing.setdefault(m["label"], {"label": m["label"], "for": m["for"], "detail": m["detail"],
                                                "repositories": []})["repositories"].append(name)
    return {"dotnet": (facts.get("dotnet") or {}).get("root"), "repositories": out,
            "missing": sorted(missing.values(), key=lambda m: m["label"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.toolchain", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("report", help="every registered repository against this machine")
    r.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    found = report()
    if args.json:
        print(json.dumps(found, indent=2))
        return 0
    print(f"The platform builds with {found['dotnet'] or 'no dotnet on PATH'}.")
    for repo in found["repositories"]:
        print(f"  {repo['repository']}{'' if repo['here'] else ' (registered on another machine)'}: {repo['summary']}")
    for m in found["missing"]:
        print(f"MISSING {m['label']}, for {m['for']}: {', '.join(m['repositories'])}. {m['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
