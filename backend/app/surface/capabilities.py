"""Step 4's capability manifest — what entry-point kinds it detects.

Step 4 ships the manifest as versioned files
(steps/step-003-fingerprinting/schemas/entry-point-capabilities-X.Y.Z.json),
as step 3 ships its signal registry. This reads the highest version and adds
how often each kind is found across the estate, so a kind with none found is
a result (it was looked for), and a pattern under notCovered is a declared
gap (it was not).
"""

import json
import re
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.catalog_rules import _registry_dir
from app.surface.schemas import CapabilityKind, EntryPointCapabilitiesOut, NotCoveredPattern

_MANIFEST_RE = re.compile(r"^entry-point-capabilities-(\d+)\.(\d+)\.(\d+)\.json$")

# Mirrors AuthDeclared.Scope in the scanner; every view of auth_declared
# carries it.
AUTH_DECLARED_SCOPE = (
    "auth_declared reports authentication as declared in source and config only. Gateway, reverse-proxy and "
    "header-based authentication (an API gateway, an access manager injecting identity headers) are not visible "
    "to static analysis, so none_declared is a prompt to review how the entry point is protected, not a security finding."
)


def latest_manifest_path() -> Path:
    candidates = [
        (tuple(int(g) for g in m.groups()), path)
        for path in _registry_dir().glob("entry-point-capabilities-*.json")
        if (m := _MANIFEST_RE.match(path.name))
    ]
    if not candidates:
        raise FileNotFoundError(f"No entry-point-capabilities-*.json under {_registry_dir()}")
    return max(candidates)[1]


def manifest_with_estate_counts(db: Session) -> EntryPointCapabilitiesOut:
    manifest = json.loads(latest_manifest_path().read_text(encoding="utf-8"))

    live_repository = (
        db.query(models.Repository.id).filter(models.Repository.deleted_at.is_(None)).subquery()
    )
    counts = dict(
        db.query(models.EntryPoint.kind, func.count())
        .filter(models.EntryPoint.repository_id.in_(live_repository.select()))
        .group_by(models.EntryPoint.kind)
        .all()
    )
    repositories = dict(
        db.query(models.EntryPoint.kind, func.count(func.distinct(models.EntryPoint.repository_id)))
        .filter(models.EntryPoint.repository_id.in_(live_repository.select()))
        .group_by(models.EntryPoint.kind)
        .all()
    )
    scans = db.query(models.EntryPointScan).filter(models.EntryPointScan.repository_id.in_(live_repository.select())).all()

    return EntryPointCapabilitiesOut(
        manifest_version=manifest["manifestVersion"],
        scanner_version=manifest["scannerVersion"],
        description=manifest["description"],
        auth_declared_scope=manifest["authDeclaredScope"],
        kinds=[
            CapabilityKind(
                kind=k["kind"],
                label=k["label"],
                detects=k["detects"],
                identified_by=k["identifiedBy"],
                auth_declared=k["authDeclared"],
                added_in=k["addedIn"],
                entry_class=k.get("entryClass", "request"),
                found_in_estate=counts.get(k["kind"], 0),
                repositories_with_kind=repositories.get(k["kind"], 0),
            )
            for k in manifest["kinds"]
        ],
        not_covered=[NotCoveredPattern(**p) for p in manifest["notCovered"]],
        repositories_scanned=len(scans),
        repositories_on_this_manifest=sum(
            1 for s in scans if (s.capabilities or {}).get("manifestVersion") == manifest["manifestVersion"]
        ),
    )
