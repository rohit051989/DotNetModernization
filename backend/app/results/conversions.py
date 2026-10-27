"""A repository's conversions in the database (app.results): what the Conversion tab shows, as its owner's machine
last saw them, for everyone on another machine.

A conversion lives on the machine its repository was registered on: its record, worktree, runbook and VERIFICATION.md
are files under that machine's RUNS_DIR, and its state comes from git there. The owner's platform publishes them here
whenever it reads them (the tab), prepares a conversion or verifies one; every other platform shows what was
published, saying whose machine it is on and as of when. Evidence files and worktrees stay on the owner's machine.
"""
import datetime
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app import models
from app.auth import machine


def _verification(rec: dict, s: dict) -> dict | None:
    from app.engine import convert

    v = s["verification"]
    if not v:
        return None
    md = convert.planner.RUNS / rec["engagement"] / rec["repository"] / "verification" / v["label"] / "VERIFICATION.md"
    return {"verdict": v["verdict"], "reasons": v["reasons"], "verifiedAt": v["verifiedAt"], "tip": v["tip"],
            "markdown": md.read_text(encoding="utf-8") if md.exists() else "", "current": s["verificationIsCurrent"]}


def local_snapshot(repo: models.Repository) -> dict:
    """The conversions as this machine's files and git have them: one entry per conversion record, newest first, with
    its runbook and VERIFICATION.md; the last preparation attempt; and the commit the next conversion would start
    from."""
    from app.conversion import gitops
    from app.engine import convert
    from app.steps.conversion_preparation import LAST_PREPARE

    entries = []
    for rec in reversed(convert.records(repo.engagement_id, repo.slug)):
        s = convert.status(rec)
        runbook = Path(rec["runbook"])
        entries.append({
            "number": rec["number"], "branch": rec["branch"], "state": s["state"], "baseline": rec["baseline"],
            "baseline_from": rec.get("baselineFrom"), "scanned_at": rec.get("scannedAt"), "head": s["head"],
            "commits_beyond_inputs": s["commitsBeyondInputs"], "uncommitted": s["uncommitted"], "worktree": rec["worktree"],
            "prepared_at": rec.get("preparedAt"), "runbook_path": str(runbook),
            "runbook": runbook.read_text(encoding="utf-8") if runbook.exists() else None,
            "opening_message": convert.opening_message(rec["goal"], rec.get("solution")),
            "package_step": rec.get("packageStep") or {}, "left_for_agent": rec.get("leftForAgent") or {},
            "verify_refusal": convert.verify_refusal(rec), "verification": _verification(rec, s),
            "plan_id": rec.get("planId"),
        })
    root = Path(repo.local_path)
    head = gitops.git(root, "rev-parse", "HEAD", check=False).strip() if root.exists() else ""
    subject = gitops.git(root, "log", "-1", "--format=%s", check=False).strip() if head else ""
    last = convert.conversions_dir(repo.engagement_id, repo.slug) / LAST_PREPARE
    return {
        "entries": entries,
        "next": {"starts_from": head or None, "starts_from_subject": subject or None},
        "last_prepare": json.loads(last.read_text(encoding="utf-8")) if last.exists() else None,
    }


def publish(db: Session, repo: models.Repository, snapshot: dict | None = None) -> dict:
    """Stores this machine's view of the repository's conversions, when it differs from what is stored. The caller
    commits."""
    snapshot = snapshot if snapshot is not None else local_snapshot(repo)
    row = db.get(models.ConversionResult, repo.id)
    conversions = {"entries": snapshot["entries"], "next": snapshot["next"]}
    if row is None:
        db.add(models.ConversionResult(repository_id=repo.id, conversions=conversions,
                                       last_prepare=snapshot["last_prepare"], published_host=machine.hostname()))
    elif row.conversions != conversions or row.last_prepare != snapshot["last_prepare"]:
        row.conversions, row.last_prepare = conversions, snapshot["last_prepare"]
        row.published_host = machine.hostname()
        row.published_at = datetime.datetime.now(datetime.timezone.utc)
    db.flush()
    return snapshot


def stored_snapshot(db: Session, repo: models.Repository) -> tuple[dict, models.ConversionResult | None]:
    """What the owner's machine last published, or nothing yet."""
    row = db.get(models.ConversionResult, repo.id)
    if row is None:
        return {"entries": [], "next": {"starts_from": None, "starts_from_subject": None}, "last_prepare": None}, None
    return {**row.conversions, "last_prepare": row.last_prepare}, row


def publish_after_step(db: Session, repo: models.Repository) -> None:
    """At the end of a preparation or a verification: everyone else sees it without its owner opening the tab."""
    try:
        publish(db, repo)
        db.commit()
    except Exception:   # never fails the step: the tab publishes again when its owner opens it
        db.rollback()
