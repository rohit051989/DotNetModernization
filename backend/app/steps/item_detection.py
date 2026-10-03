"""Lifecycle step 7 — item-detection. 17-LIFECYCLE-STEPS.md step 7;
28-ITEM-AND-CONVERSION-MODEL.md Parts C to G.

Matches every READY catalog item against every project of one repository,
using the signals recorded in fingerprint_signals — step 3's, and the
PACKAGE_* signals step 6 (dependency-assessment) adds under its own
extractor name, read the same way — and writes the result to
`item_occurrences`: the work list's raw rows. Produces occurrences, not a
classification. There is no election and no score: an item applies to a
project or it does not, and many items can apply to one project.

Per item per project, exactly one detection_state:

- `found`: the detection holds. Application scope writes one row with no
  file; occurrence scope writes one row per distinct location projected
  from the occurrence_source signal's evidence, or one unlocated row if the
  item holds but nothing locates it.
- `checked_absent`: evaluated, and the detection does not hold. Genuinely
  clean.
- `not_checked`: the scan could not have seen what the item needs — the
  repository's fingerprint was produced under a signal registry older than a
  referenced signal's `signal_introduced_in_version`, step 3 failed on the
  project or never reached it, or a project metadata field the item's
  conditions read (frameworkFamily, outputType, projectSdk, ...) is unknown
  for the project. Never reported as checked_absent: that would silently call
  unknown code clean.

A project step 3 deliberately skipped as out of scope (a .dcproj, a .sfproj,
a Node.js project) is not a rescan case: no rescan will ever fingerprint it.
Items that need its signals do not apply and write no row; items detected
purely by step 2 metadata are still evaluated. The artifact records the
project as skipped.

An item whose `excluded_roles` contains the project's computed role (Part D,
app/items/roles.py) does not apply and writes no row. Items that are not
ready are inert (Part C) and write nothing.

Repository-level signals (step 3's `repositorySignals`, project_id null) are
part of every project's signal set when evaluating, per Part E, so a root
k8s/ folder counts for every project in the repository. They never locate
an occurrence.

Replaced wholesale per repository on each run, like steps 2 and 3. Reads
and writes the database directly (its inputs are step 2 and 3 rows); the
wired application-fingerprint artifact is recorded, not re-parsed.
"""

import datetime
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import models
from app.items import evaluation, roles
from app.items.detection import referenced_signal_names
from app.items.registry import version_key
from app.workflow.adapters.base import compute_checksum
from app.workflow.contract import StepContext, StepOutput, StepResult

STEP_NAME = "item-detection"
ARTIFACT_TYPE = "item-occurrences"
ARTIFACT_VERSION = "1.1.0"


def _open_session(database_url: str):
    engine = create_engine(database_url)
    return sessionmaker(bind=engine)(), engine


# ---------- loading ----------


def _signal_row(signal: models.FingerprintSignal) -> dict:
    return {
        "signal_category": signal.signal_category,
        "signal_type": signal.signal_type,
        "value": signal.value,
        "source_type": signal.source_type,
        "source_path": signal.source_path,
        "occurrence_count": signal.occurrence_count,
        "extraction_confidence": float(signal.extraction_confidence),
        "evidence": signal.evidence,
        "repository_level": signal.project_id is None,
    }


def _metadata(project: models.Project, fingerprint: models.ProjectFingerprint | None) -> dict:
    """Part E metadata-condition fields, as the old engine named them."""
    return {
        "outputType": project.output_type,
        "projectFormat": project.project_format,
        "frameworkFamily": project.framework_family,
        "frameworkVersion": project.framework_version,
        # Step 2's declared SDK; step 3's evaluated value when it ever exists.
        "projectSdk": project.project_sdk or (fingerprint.project_sdk if fingerprint else None),
        "structuralType": project.structural_type,
        "extension": project.extension,
        "fingerprintStatus": (fingerprint.fingerprint_status.upper() if fingerprint else "SKIPPED"),
    }


# ---------- detection ----------


def detect_repository(db: Session, repository: models.Repository, step_execution_id=None) -> dict:
    """Evaluates every ready item against every project of `repository`,
    replaces its item_occurrences, and returns the artifact body. Flushes;
    the caller commits."""
    scan = db.get(models.FingerprintScan, repository.id)
    scan_version = scan.signal_registry_version if scan else None

    items = (
        db.query(models.CatalogItem)
        .filter(
            models.CatalogItem.state == "ready",
            models.CatalogItem.status == "active",
            models.CatalogItem.deleted_at.is_(None),
        )
        .order_by(models.CatalogItem.id)
        .all()
    )
    introduced = {s.name: s.signal_introduced_in_version for s in db.query(models.SignalRegistryEntry)}

    projects = (
        db.query(models.Project)
        .filter(models.Project.repository_id == repository.id)
        .order_by(models.Project.relative_path)
        .all()
    )
    fingerprints = {
        f.project_id: f
        for f in db.query(models.ProjectFingerprint).filter(models.ProjectFingerprint.repository_id == repository.id)
    }
    packages: dict = {}
    for package in db.query(models.ProjectPackage).join(models.Project).filter(models.Project.repository_id == repository.id):
        packages.setdefault(package.project_id, []).append(package.package_name)

    project_signals: dict = {}
    repository_signals: dict[str, list[dict]] = {}
    for signal in db.query(models.FingerprintSignal).filter(models.FingerprintSignal.repository_id == repository.id):
        target = repository_signals if signal.project_id is None else project_signals.setdefault(signal.project_id, {})
        target.setdefault(signal.signal_name, []).append(_signal_row(signal))

    db.query(models.ItemOccurrence).filter(models.ItemOccurrence.repository_id == repository.id).delete(
        synchronize_session=False
    )

    now = datetime.datetime.now(datetime.timezone.utc)
    results = []
    # possible_occurrence_rows (1.1.0): found rows resting only on ambiguous
    # evidence. Counted apart, and left out of work totals by default.
    counts = {"found": 0, "checked_absent": 0, "not_checked": 0, "excluded": 0, "skipped": 0, "occurrence_rows": 0,
              "possible_occurrence_rows": 0, "possible_only_found": 0}

    for project in projects:
        fingerprint = fingerprints.get(project.id)
        fingerprinted = fingerprint is not None and fingerprint.fingerprint_status in ("complete", "partial")
        skipped_by_step3 = fingerprint is not None and fingerprint.fingerprint_status in ("skipped", "not_supported")
        own = project_signals.get(project.id, {})
        role, role_reason = roles.derive_role(
            {"structural_type": project.structural_type, "extension": project.extension,
             "output_type": project.output_type, "fingerprinted": fingerprinted},
            sorted(packages.get(project.id, [])),
            set(own),
            {name for name, rows in own.items() if any(r["signal_category"] == "ENTRY_POINT" for r in rows)},
        )

        # Own rows plus the repository's, per Part E.
        visible: dict[str, list[dict]] = {name: list(rows) for name, rows in own.items()}
        for name, rows in repository_signals.items():
            visible.setdefault(name, []).extend(rows)
        metadata = _metadata(project, fingerprint)

        item_results = []
        for item in items:
            if role in item.excluded_roles:
                counts["excluded"] += 1
                continue

            referenced = referenced_signal_names(item.detection)
            if referenced and skipped_by_step3:
                counts["skipped"] += 1
                continue
            state, reason, rows = _detect(item, referenced, fingerprinted, scan_version, introduced, visible, metadata)
            counts[state] += 1
            if state == "found" and all(r.get("certainty") == "possible" for r in rows):
                # Found only on ambiguous evidence: still found, but not work
                # a total should count by default.
                counts["possible_only_found"] += 1

            for row in rows:
                db.add(models.ItemOccurrence(
                    repository_id=repository.id,
                    project_id=project.id,
                    item_id=item.id,
                    scope=item.scope,
                    file_path=row.get("file_path"),
                    value=row.get("value"),
                    evidence=row.get("evidence"),
                    signal_registry_version=scan_version or "none",
                    detection_state=state,
                    certainty=row.get("certainty", "confirmed"),
                    step_execution_id=step_execution_id,
                    detected_at=now,
                ))
                counts["occurrence_rows"] += 1
                if state == "found" and row.get("certainty") == "possible":
                    counts["possible_occurrence_rows"] += 1

            item_results.append({
                "itemId": item.id,
                "itemVersion": item.version,
                "scope": item.scope,
                "detectionState": state,
                "reason": reason,
                "occurrences": [
                    {"filePath": r.get("file_path"), "value": r.get("value"), "evidence": r.get("evidence") or [],
                     "certainty": r.get("certainty", "confirmed")}
                    for r in rows if state == "found"
                ],
            })

        results.append({
            "projectId": str(project.id),
            "projectPath": project.relative_path,
            "role": role,
            "roleReason": role_reason,
            "fingerprintStatus": fingerprint.fingerprint_status if fingerprint else None,
            "items": item_results,
        })

    db.flush()
    return {
        "artifactType": ARTIFACT_TYPE,
        "artifactVersion": ARTIFACT_VERSION,
        "repositoryId": str(repository.id),
        "repositorySlug": repository.slug,
        "signalRegistryVersion": scan_version,
        "catalog": [{"itemId": i.id, "version": i.version, "scope": i.scope} for i in items],
        "summary": counts,
        "projects": results,
    }


def _detect(item, referenced, fingerprinted, scan_version, introduced, visible, metadata) -> tuple[str, str | None, list[dict]]:
    """(detection_state, reason, rows to write). Every state writes at least
    one row, so each (item, project) pair has a recorded answer."""
    project_row = [{"file_path": None, "value": None, "evidence": None}]

    if referenced and not fingerprinted:
        return "not_checked", "step 3 failed on this project or has not reached it", project_row

    # A condition on a metadata field the project has no value for cannot be
    # evaluated honestly — an exclusion (`notEquals`) would pass and a positive
    # condition would fail, either way claiming knowledge the scan lacks.
    unknown = sorted({c["field"] for c in item.detection["match"].get("metadata", []) if metadata.get(c["field"]) is None})
    if unknown:
        return "not_checked", "project metadata unknown: " + ", ".join(unknown), project_row

    unseen = sorted(
        name for name in referenced
        if name in introduced and (scan_version is None or version_key(introduced[name]) > version_key(scan_version))
    )
    if unseen:
        return (
            "not_checked",
            f"fingerprint registry {scan_version} predates: " + ", ".join(f"{n} ({introduced[n]})" for n in unseen),
            project_row,
        )

    holds, held = evaluation.evaluate_match(item.detection["match"], visible, metadata)
    if not holds:
        return "checked_absent", None, project_row

    if item.scope == "application":
        return "found", None, [{"file_path": None, "value": None, "evidence": evaluation.application_evidence(held)}]

    located = evaluation.project_occurrences(item.detection, visible)
    if not located:
        # Holds, but nothing it holds on has a location (e.g. a package).
        return "found", "no located occurrence", [{"file_path": None, "value": None, "evidence": evaluation.application_evidence(held)}]
    return "found", None, located


# ---------- step entry point ----------


def run(context: StepContext) -> StepResult:
    repository_id = context.parameters.get("repository_id")
    if not repository_id:
        return StepResult(exit_status="FAILED", exit_message="parameters.repository_id is required for item-detection")
    if not context.database_url:
        return StepResult(exit_status="FAILED", exit_message="database_url is required")

    db, engine = _open_session(context.database_url)
    try:
        repository = db.get(models.Repository, repository_id)
        if repository is None:
            return StepResult(exit_status="FAILED", exit_message=f"repository '{repository_id}' does not exist")

        artifact = detect_repository(db, repository, step_execution_id=context.step_execution_id)
        db.commit()

        output_dir = Path(context.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "item-occurrences.json"
        # Deterministic: sorted keys, sorted collections, no timestamps.
        output_path.write_text(json.dumps(artifact, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        summary = artifact["summary"]
        return StepResult(
            exit_status="COMPLETED",
            exit_message=(
                f"Evaluated {len(artifact['catalog'])} ready item(s) over {len(artifact['projects'])} project(s): "
                f"{summary['found']} found, {summary['checked_absent']} checked absent, "
                f"{summary['not_checked']} not checked, {summary['occurrence_rows']} occurrence row(s), "
                f"{summary['possible_occurrence_rows']} of them possible (ambiguous evidence only)."
            ),
            metrics={
                "read_count": len(artifact["projects"]),
                "write_count": summary["occurrence_rows"],
                "skip_count": summary["excluded"] + summary["skipped"],
                "commit_count": 1,
            },
            outputs=[
                StepOutput(
                    artifact_type=ARTIFACT_TYPE,
                    artifact_version=ARTIFACT_VERSION,
                    uri=output_path.as_uri(),
                    checksum=compute_checksum(output_path.as_uri()),
                    metadata={"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()},
                )
            ],
        )
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    _context = StepContext.model_validate(json.load(sys.stdin))
    try:
        _result = run(_context)
    except Exception as exc:  # a "process"-style invocation must still emit valid JSON
        _result = StepResult(exit_status="FAILED", exit_message=f"{type(exc).__name__}: {exc}")
    sys.stdout.write(_result.model_dump_json())
