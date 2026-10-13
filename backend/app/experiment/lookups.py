"""Frozen package lookups for an experiment (36-COPILOT-ENHANCED-CONVERSION Part L).

Package changes are most of each application's work items, and dependency-assessment answers them from live feeds:
a release published between two verifications shifts the comparison with nothing about the runs differing (eShopOnWeb
arm 3: 16 work items resolved at generation 2, 14 at generation 3, because System.Text.Json 10.0.13 was published).
The platform commit pins the code; this pins the feeds.

    python -m app.experiment.lookups freeze --engagement E --repository R --name N     (before `create`)
    python -m app.experiment.lookups check --config <experiment.yaml>

`freeze` writes `package-lookups.json` into the experiment's folder: every row of the lookup cache
(`package_lookup_cache`, Part B6 of 30-DEPENDENCY-ASSESSMENT) for the packages the repository's current dependency
assessment covers, and for their dependencies, which the conversion planner reads to couple package moves. That is
every lookup answer the experiment's inputs were built from. It refuses, saying which, when an answer is no longer
the one the assessment used (a row fetched after the assessment ran): it never substitutes a newer answer. It never
overwrites an existing snapshot without --force. `create` records the file's sha256 in experiment.yaml.

The verifier then loads this snapshot, and only it, into its throwaway database, and runs discovery with
`lookup_offline`: a package the snapshot does not answer is reported as not answered, never looked up live. Every
verification records the snapshot's sha256; `report` and `calibrate` flag one made against any other.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.experiment.location import experiment_dir

FILE = "package-lookups.json"
FORMAT = 1


class SnapshotError(RuntimeError):
    pass


def _repository(db: Session, engagement_id: str, slug: str) -> models.Repository:
    return (db.query(models.Repository).filter_by(engagement_id=engagement_id, slug=slug)
            .filter(models.Repository.deleted_at.is_(None)).one())


def _dependency_ids(metadata: dict) -> set[str]:
    ids = set()
    for version in (metadata or {}).values():
        for group in (version or {}).get("dependencies") or []:
            ids.update(p["id"].lower() for p in group.get("packages") or [])
    return ids


def snapshot_document(db: Session, repository: models.Repository) -> tuple[dict, list[str]]:
    """(the snapshot document, problems). Problems name answers that are no longer the ones the assessment used."""
    assessed = db.execute(text("""
        SELECT lower(package_id), max(assessed_at) FROM package_assessments WHERE repository_id = :r GROUP BY 1"""),
                          {"r": repository.id}).all()
    if not assessed:
        raise SnapshotError(f"{repository.slug} has no dependency assessment: run discovery first")
    assessed_at = max(a for _, a in assessed)
    ids = {i for i, _ in assessed}
    rows = db.query(models.PackageLookupCache).filter(text("lower(package_id) = ANY(:ids)")).params(ids=sorted(ids)).all()
    for row in rows:
        ids |= _dependency_ids(row.metadata_)
    rows = (db.query(models.PackageLookupCache).filter(text("lower(package_id) = ANY(:ids)")).params(ids=sorted(ids))
            .order_by(models.PackageLookupCache.package_id, models.PackageLookupCache.feed_url_normalised).all())
    problems = [f"{r.package_id} from {r.feed_url_normalised}: fetched {r.fetched_at.isoformat()}, after the assessment "
                f"({assessed_at.isoformat()}); the answer the inputs were built from is no longer available"
                for r in rows if r.fetched_at > assessed_at]
    looked_up = {(f, i) for f, i in db.execute(text("""
        SELECT DISTINCT feed_url, lower(package_id) FROM package_assessments
        WHERE repository_id = :r AND feed_url IS NOT NULL"""), {"r": repository.id})}
    have = {(r.feed_url_normalised, r.package_id.lower()) for r in rows}
    problems += [f"{i} from {f}: the assessment used it, and the lookup cache no longer holds it" for f, i in sorted(looked_up - have)]
    document = {
        "format": FORMAT,
        "repository": repository.slug,
        "assessedAt": assessed_at.isoformat(),
        "rows": [{"feed": r.feed_url_normalised, "package": r.package_id, "fetchedAt": r.fetched_at.isoformat(),
                  "versions": r.versions, "metadata": r.metadata_} for r in rows],
    }
    return document, problems


def render(document: dict) -> bytes:
    """Deterministic bytes: sorted keys, one indentation, a final newline. The sha256 is over these bytes."""
    return (json.dumps(document, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def freeze(db: Session, engagement_id: str, slug: str, name: str, force: bool = False) -> tuple[Path, str, dict]:
    target = experiment_dir(engagement_id, name) / FILE
    if target.exists() and not force:
        raise SnapshotError(f"{target} exists: a snapshot is never replaced without --force")
    document, problems = snapshot_document(db, _repository(db, engagement_id, slug))
    if problems:
        raise SnapshotError("not frozen: " + "; ".join(problems))
    data = render(document)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target, sha256(data), {"rows": len(document["rows"]), "packages": len({r["package"].lower() for r in document["rows"]})}


def recorded(config: dict) -> str | None:
    """The snapshot sha256 experiment.yaml records, or None."""
    return (config.get("package_lookups") or {}).get("sha256")


def load(config: dict) -> tuple[list[dict], str]:
    """The experiment's snapshot rows and their sha256, checked against experiment.yaml. Raises when the file is missing
    or differs from what was recorded: a verification never runs against an unrecorded snapshot."""
    path = experiment_dir(config["engagement"], config["experiment"]) / FILE
    if not path.exists():
        raise SnapshotError(f"{path} is missing: the experiment's package lookups cannot be answered")
    data = path.read_bytes()
    actual, expected = sha256(data), recorded(config)
    if actual != expected:
        raise SnapshotError(f"{path} has sha256 {actual[:12]}, but experiment.yaml records {(expected or 'none')[:12]}")
    return json.loads(data)["rows"], actual


def main(argv: list[str] | None = None) -> int:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(prog="python -m app.experiment.lookups", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--engagement", required=True)
    f.add_argument("--repository", required=True, help="repository slug")
    f.add_argument("--name", required=True, help="the experiment's folder name")
    f.add_argument("--force", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "check":
        import yaml
        config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
        try:
            rows, digest = load(config)
        except SnapshotError as error:
            print(str(error), file=sys.stderr)
            return 1
        print(f"{len(rows)} lookup answers, sha256 {digest}: matches experiment.yaml")
        return 0
    db = SessionLocal()
    try:
        path, digest, counts = freeze(db, args.engagement, args.repository, args.name, args.force)
    except SnapshotError as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        db.close()
    print(f"{path}: {counts['rows']} lookup answers for {counts['packages']} packages, sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
