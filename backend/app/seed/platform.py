"""Platform configuration from the repository — implemented step
registrations and job definitions.

Until now an implemented step was registered by POSTing its declaration to
the running backend, and a job definition by POSTing its YAML, so a fresh
database seeded from the repository came up with every step a stub and no
jobs. These are the repository's copies, seeded after the lifecycle stubs:

- step registrations: `steps/*/registration/*.json` and
  `backend/app/steps/*.registration.json` (a StepDeclaration each);
- job definitions: `backend/app/jobs/*.yaml`.

Like every reseed (CLAUDE.md rule 10), this never undoes work and never
overwrites something newer:

| Live row | Repository file | Outcome |
|---|---|---|
| missing, or a lifecycle stub | — | registered / stored and activated |
| identical | — | unchanged |
| older version | newer version | upgraded (registration) / stored and activated (job) |
| newer version | older version | left as is, reported: the repository is behind this machine |
| same version, different content | — | left as is, reported as a conflict |
| retired (soft-deleted or deprecated) | — | left as is: un-retiring is a deliberate act |

`python -m app.seed.reproduce` proves the result: a scratch database seeded
from the repository alone, compared with the live one.
"""

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app import models
from app.db import SessionLocal
from app.workflow import registration
from app.workflow.definition import service as definitions
from app.workflow.definition.loader import compute_checksum, parse_job_definition
from app.workflow.schemas import StepDeclaration

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRATION_GLOBS = ("steps/*/registration/*.json", "backend/app/steps/*.registration.json")
JOBS_DIR = REPO_ROOT / "backend" / "app" / "jobs"


def _semver(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def registration_files() -> list[Path]:
    return sorted({path for pattern in REGISTRATION_GLOBS for path in REPO_ROOT.glob(pattern)})


def declaration_of(row: models.WfStepRegistration) -> dict:
    """A live registration as the declaration that would produce it."""
    return StepDeclaration(**{field: getattr(row, field) for field in StepDeclaration.model_fields}).model_dump(mode="json")


def seed_step_registrations(db: Session) -> dict:
    """Flushes; the caller commits."""
    report = {"registered": [], "upgraded": [], "unchanged": [], "retired_skipped": [], "repository_behind": [], "conflicts": []}
    for path in registration_files():
        declaration = StepDeclaration(**json.loads(path.read_text(encoding="utf-8")))
        wanted = declaration.model_dump(mode="json")
        name = declaration.step_name
        row = db.get(models.WfStepRegistration, name)
        where = f"{name} ({path.relative_to(REPO_ROOT).as_posix()})"
        if row is not None and (row.deleted_at is not None or row.implementation_status == "deprecated"):
            report["retired_skipped"].append(where)
            continue
        if row is None or row.implementation_status == "stub":
            registration.register_step(db, declaration)
            report["registered"].append(f"{where} {declaration.version}")
            continue
        live = declaration_of(row)
        if live == wanted:
            report["unchanged"].append(name)
        elif _semver(declaration.version) > _semver(row.version):
            registration.register_step(db, declaration)
            report["upgraded"].append(f"{where} {row.version} -> {declaration.version}")
        elif _semver(declaration.version) < _semver(row.version):
            report["repository_behind"].append(f"{where}: live {row.version}, repository {declaration.version}")
        else:
            fields = sorted(k for k in wanted if wanted[k] != live[k])
            report["conflicts"].append(f"{where}: version {row.version} differs in {', '.join(fields)}")
    db.flush()
    return report


def seed_job_definitions(db: Session) -> dict:
    """Flushes; the caller commits."""
    report = {"stored": [], "activated": [], "unchanged": [], "repository_behind": [], "conflicts": [], "invalid": []}
    for path in sorted(JOBS_DIR.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        definition = parse_job_definition(text)
        name, version = definition.job_name, definition.version
        label = f"{name} v{version} ({path.name})"
        active = definitions.get_active_definition(db, name)
        stored = definitions.get_definition_version(db, name, version)
        if active is not None and active.version > version:
            report["repository_behind"].append(f"{label}: v{active.version} is active on this machine")
            continue
        if stored is not None:
            if stored.checksum != compute_checksum(text):
                report["conflicts"].append(f"{label}: stored with different content")
            elif stored.is_active:
                report["unchanged"].append(label)
            elif stored.validation_status == "valid":
                definitions.activate_definition(db, name, version)
                report["activated"].append(label)
            else:
                report["invalid"].append(f"{label}: stored invalid; not activated")
            continue
        row, errors = definitions.store_definition(db, text, activate=True)
        if errors:
            report["invalid"].append(f"{label}: {'; '.join(e.detail for e in errors)}")
        else:
            report["stored"].append(label)
    db.flush()
    return report


def seed_platform() -> dict:
    db = SessionLocal()
    try:
        result = {"registrations": seed_step_registrations(db), "jobs": seed_job_definitions(db)}
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def print_platform_summary(result: dict) -> None:
    regs, jobs = result["registrations"], result["jobs"]
    print(f"Step registrations from the repository: {len(regs['registered'])} registered, {len(regs['upgraded'])} upgraded, "
          f"{len(regs['unchanged'])} unchanged, {len(regs['repository_behind'])} behind this machine, "
          f"{len(regs['conflicts'])} conflict(s)")
    print(f"Job definitions from the repository: {len(jobs['stored'])} stored, {len(jobs['activated'])} activated, "
          f"{len(jobs['unchanged'])} unchanged, {len(jobs['repository_behind'])} behind this machine, "
          f"{len(jobs['conflicts'])} conflict(s), {len(jobs['invalid'])} invalid")
    for key in ("repository_behind", "conflicts"):
        for line in regs[key] + jobs[key]:
            print(f"  {key}: {line}")
    for line in jobs["invalid"]:
        print(f"  invalid: {line}")
