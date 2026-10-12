"""The repository page's Conversion section — 34-CONVERSION-ARCHITECTURE.md C4
and Part E: a plan, its units in order with status, commit, failure reason
and evidence links, and the unit tests before (the baseline) and after (the
latest committed unit).

Evidence is files under the plan's directory, each recorded with its sha256
(app/conversion/evidence.py). The evidence endpoint serves only a path the
plan records, and only while the file still has the recorded hash — a link is
never more than the evidence it points at.
"""

import mimetypes
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.conversion import evidence as evidence_files
from app.db import get_db
from app.errors import ErrorResponse, error

router = APIRouter(prefix="/api", tags=["Conversion"])


class EvidenceLinkOut(BaseModel):
    kind: str
    path: str
    sha256: str
    url: str
    project: str | None = None


class TestTotalsOut(BaseModel):
    total: int
    passed: int
    failed: int
    skipped: int
    failed_tests: list[str]


class TestRunOut(BaseModel):
    commit: str | None
    sequence: int | None
    framework: str | None
    tests: dict[str, TestTotalsOut]
    total: int
    passed: int
    evidence: list[EvidenceLinkOut]


class BaselineOut(TestRunOut):
    passed_baseline: bool
    failure: str | None


class UnitDependencyOut(BaseModel):
    sequence: int
    reason: str


class ConversionUnitOut(BaseModel):
    sequence: int
    unit_id: str
    recipe_id: str
    step_id: str
    approach_id: str
    approach_version: str
    automation_class: str
    title: str
    # For packages that move as one unit: why they only resolve together.
    together_because: str | None
    status: str
    status_reason: str | None
    order_reason: str
    depends_on: list[UnitDependencyOut]
    commit_sha: str | None
    tests: dict[str, str] | None
    evidence: list[EvidenceLinkOut]


class PlanOut(BaseModel):
    id: uuid.UUID
    status: str
    status_reason: str | None
    branch: str
    worktree_path: str
    legacy_commit: str
    from_framework: str | None
    target_framework: str
    tip_framework: str | None
    tip_commit: str | None
    created_at: str
    completed_at: str | None
    exclusions: list[dict]


class PlanSummaryOut(BaseModel):
    id: uuid.UUID
    status: str
    created_at: str


class RepositoryConversionOut(BaseModel):
    plan: PlanOut
    counts: dict[str, int]
    automation: dict[str, int]
    baseline: BaselineOut | None
    latest: TestRunOut | None
    units: list[ConversionUnitOut]
    plans: list[PlanSummaryOut]


def _links(plan: models.ConversionPlan, records: list[dict]) -> list[EvidenceLinkOut]:
    return [EvidenceLinkOut(kind=r["kind"], path=r["path"], sha256=r["sha256"], project=r.get("project"),
                            url=f"/api/conversion/plans/{plan.id}/evidence?path={quote(r['path'])}")
            for r in records if r.get("path") and r.get("sha256")]


def _tests(records: list[dict]) -> dict[str, TestTotalsOut]:
    return {r["project"]: TestTotalsOut(total=r["total"], passed=r["passed"], failed=r["failed"], skipped=r["skipped"],
                                        failed_tests=r.get("failed_tests") or [])
            for r in records if r.get("kind") == "test_results"}


def _title(unit: models.ConversionUnit) -> str:
    """The target's title (plans from this change on), or one built from it."""
    t = unit.target or {}
    if t.get("title"):
        return t["title"]
    if unit.approach_id == "retarget-tfm":
        return f"Retarget {t.get('from')} -> {t.get('to')}"
    return f"{t.get('package_id')} {t.get('from')} -> {t.get('to')} ({t.get('project')})"


def _repository(db: Session, repository_id: uuid.UUID) -> models.Repository:
    repo = db.get(models.Repository, repository_id)
    if repo is None or repo.deleted_at is not None:
        raise error(404, f"Repository '{repository_id}' not found", code="NOT_FOUND")
    return repo


@router.get(
    "/repositories/{repository_id}/conversion",
    response_model=RepositoryConversionOut,
    summary="A repository's conversion plan, its units and the tests before and after",
    operation_id="get_repository_conversion",
    responses={404: {"model": ErrorResponse, "description": "Repository or plan not found."},
               409: {"model": ErrorResponse, "description": "No conversion plan for this repository yet."}},
)
def get_repository_conversion(repository_id: uuid.UUID, plan_id: uuid.UUID | None = Query(None), db: Session = Depends(get_db)):
    _repository(db, repository_id)
    plans = (db.query(models.ConversionPlan).filter_by(repository_id=repository_id)
             .order_by(models.ConversionPlan.created_at.desc()).all())
    if not plans:
        raise error(409, "No conversion plan for this repository yet.", code="NO_PLAN")
    plan = next((p for p in plans if p.id == plan_id), None) if plan_id else plans[0]
    if plan is None:
        raise error(404, f"Plan '{plan_id}' is not a plan of this repository", code="NOT_FOUND")

    units = db.query(models.ConversionUnit).filter_by(plan_id=plan.id).order_by(models.ConversionUnit.sequence).all()
    ordering = plan.ordering or {}
    counts: dict[str, int] = {}
    automation: dict[str, int] = {}
    out_units = []
    for u in units:
        counts[u.status] = counts.get(u.status, 0) + 1
        automation[u.automation_class] = automation.get(u.automation_class, 0) + 1
        tests = _tests(u.evidence or [])
        out_units.append(ConversionUnitOut(
            sequence=u.sequence, unit_id=u.unit_id, recipe_id=u.recipe_id, step_id=u.step_id, approach_id=u.approach_id,
            approach_version=u.approach_version, automation_class=u.automation_class, title=_title(u),
            together_because=(u.target or {}).get("group_reason"), status=u.status,
            status_reason=u.status_reason, order_reason=u.order_reason,
            depends_on=[UnitDependencyOut(**d) for d in (u.depends_on or [])], commit_sha=u.commit_sha,
            tests={p: f"{t.passed}/{t.total}" for p, t in tests.items()} or None, evidence=_links(plan, u.evidence or [])))

    baseline = None
    if plan.baseline:
        b = plan.baseline
        tests = _tests(b.get("evidence") or [])
        baseline = BaselineOut(
            commit=b.get("commit"), sequence=None, framework=ordering.get("from"), tests=tests,
            total=sum(t.total for t in tests.values()), passed=sum(t.passed for t in tests.values()),
            evidence=_links(plan, b.get("evidence") or []), passed_baseline=bool(b.get("passed")), failure=b.get("failure"))

    committed = [u for u in units if u.status == "committed"]
    retargeted = any(u.approach_id == "retarget-tfm" and u.status == "committed" for u in units)
    tip_framework = ordering.get("to") if retargeted else ordering.get("from")
    latest = None
    if committed:
        last = committed[-1]
        tests = _tests(last.evidence or [])
        latest = TestRunOut(commit=last.commit_sha, sequence=last.sequence, framework=tip_framework, tests=tests,
                            total=sum(t.total for t in tests.values()), passed=sum(t.passed for t in tests.values()),
                            evidence=_links(plan, [r for r in last.evidence or [] if r.get("kind") in ("test_results", "test_log")]))

    return RepositoryConversionOut(
        plan=PlanOut(id=plan.id, status=plan.status, status_reason=plan.status_reason, branch=plan.branch,
                     worktree_path=plan.worktree_path, legacy_commit=plan.legacy_commit, from_framework=ordering.get("from"),
                     target_framework=plan.target_framework, tip_framework=tip_framework if committed else None,
                     tip_commit=committed[-1].commit_sha if committed else None, created_at=plan.created_at.isoformat(),
                     completed_at=plan.completed_at.isoformat() if plan.completed_at else None, exclusions=plan.exclusions or []),
        counts=counts, automation=automation, baseline=baseline, latest=latest, units=out_units,
        plans=[PlanSummaryOut(id=p.id, status=p.status, created_at=p.created_at.isoformat()) for p in plans])


@router.get(
    "/conversion/plans/{plan_id}/evidence",
    summary="One evidence file of a conversion plan, if it still has its recorded sha256",
    operation_id="get_conversion_evidence",
    responses={404: {"model": ErrorResponse, "description": "No such plan, or the path is not evidence it records, or the file is gone."},
               409: {"model": ErrorResponse, "description": "The file no longer has the recorded sha256."}},
)
def get_conversion_evidence(plan_id: uuid.UUID, path: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    plan = db.get(models.ConversionPlan, plan_id)
    if plan is None:
        raise error(404, f"Plan '{plan_id}' not found", code="NOT_FOUND")
    records = list((plan.baseline or {}).get("evidence") or [])
    for unit in db.query(models.ConversionUnit).filter_by(plan_id=plan.id):
        records.extend(unit.evidence or [])
    record = next((r for r in records if r.get("path") == path), None)
    if record is None:
        raise error(404, f"'{path}' is not evidence this plan records", code="NOT_EVIDENCE")
    plan_dir = Path(plan.worktree_path).parent
    file = (plan_dir / record["path"]).resolve()
    if plan_dir.resolve() not in file.parents or not file.is_file():
        raise error(404, f"Evidence file is missing: {record['path']}", code="EVIDENCE_FILE_MISSING")
    if not evidence_files.verify(record, plan_dir):
        raise error(409, f"{record['path']} no longer has the recorded sha256 {record['sha256']}", code="CHECKSUM_MISMATCH")
    media = {".log": "text/plain", ".diff": "text/plain", ".trx": "application/xml", ".json": "application/json"}.get(
        file.suffix.lower()) or mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    return FileResponse(file, media_type=f"{media}; charset=utf-8" if media.startswith("text/") else media,
                        headers={"Content-Disposition": f'inline; filename="{file.name}"'})
