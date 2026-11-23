"""The repository's Compatibility tab, a page at a time (app.results.paging): what in a legacy .NET repository will
not work, or needs a change, on the modern stack in a Linux/OpenShift container. SOAP compatibility has its own
endpoints (app.routers.surface_pages); this adds the Linux list. Read-only, from the database only.

- Linux compatibility: the found catalog items that app/compatibility/windows_only_packages.yaml lists under
  `treatments`, each with a badge (blocker, container, other), and the direct packages that only work on Windows
  (always a blocker).

Package upgrades that break the code, and packages that need replacing, are not repeated here: the Dependencies tab
and the Work list show them.
"""
import functools
import json
import uuid
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error
from app.results.paging import PageOut, PageParams, page

router = APIRouter(prefix="/api", tags=["Compatibility"])

_RESPONSES = {404: {"model": ErrorResponse, "description": "No repository exists with this id."},
              409: {"model": ErrorResponse, "description": "The repository has not been fingerprinted yet."}}

_DATA = Path(__file__).resolve().parent.parent / "compatibility" / "windows_only_packages.yaml"

# The badge's order in the list: what must change first.
_RANK = {"blocker": 1, "container": 2, "other": 3}


class CompatibilitySummaryOut(BaseModel):
    linux: int = Field(description="Linux findings: listed items found, plus Windows-only packages.")
    linux_items: int
    linux_packages: int
    linux_blockers: int = Field(description="Findings badged blocker (every Windows-only package is one).")
    linux_container: int
    linux_other: int
    scanned_at: str | None = None


@functools.lru_cache(maxsize=1)
def _data() -> dict:
    with open(_DATA, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _package_why(package_id: str) -> dict | None:
    lowered = package_id.lower()
    for rule in _data()["packages"]:
        wanted = rule["id"].lower()
        if (rule["match"] == "exact" and lowered == wanted) or (rule["match"] == "prefix" and lowered.startswith(wanted)):
            return rule
    return None


def _linux_params() -> dict:
    rules = _data()["packages"]
    return {"exact": [r["id"].lower() for r in rules if r["match"] == "exact"],
            "prefix": [r["id"].lower() for r in rules if r["match"] == "prefix"],
            "treatments": json.dumps(_data()["treatments"])}


def _repository(db: Session, repository_id: uuid.UUID) -> models.Repository:
    repo = db.get(models.Repository, repository_id)
    if repo is None or repo.deleted_at is not None:
        raise error(404, f"Repository '{repository_id}' not found", code="NOT_FOUND")
    return repo


def _scan(db: Session, repository_id: uuid.UUID) -> models.FingerprintScan:
    scan = db.get(models.FingerprintScan, repository_id)
    if scan is None:
        raise error(409, "The application fingerprint has not run yet for this repository.", code="NOT_SCANNED")
    return scan


# The item's badge, from the committed list; an item the list does not name is left out of the Linux list.
_TREATMENT = "(cast(:treatments as jsonb) ->> i.id)"
_LISTED = "(cast(:treatments as jsonb) ? i.id)"
_RANK_SQL = f"case {_TREATMENT} " + " ".join(f"when '{name}' then {n}" for name, n in _RANK.items()) + " else 9 end"


def _item_rows(where: str) -> str:
    """Found occurrences of catalog items, one row per occurrence, shaped for the list, each with its badge."""
    badge = _TREATMENT
    rank = _RANK_SQL
    return f"""
        select jsonb_build_object('kind', 'item', 'id', o.id::text, 'itemId', i.id, 'itemName', i.name,
                                  'treatment', {badge}, 'category', i.category, 'project', p.relative_path,
                                  'file', o.file_path, 'value', o.value, 'certainty', o.certainty,
                                  'whatToDo', d.name, 'whatToDoDetail', d.description) as item,
               {rank} as k_rank, p.relative_path as k_project, coalesce(o.file_path, '') as k_name,
               o.id::text as k_id,
               lower(concat_ws(' ', i.id, i.name, i.category, p.relative_path, o.file_path, o.value, {badge},
                               (select string_agg(concat_ws(' ', e->>'member', e->>'declaring_type'), ' ')
                                from jsonb_array_elements(coalesce(o.evidence, '[]'::jsonb)) e))) as search
        from item_occurrences o
        join catalog_items i on i.id = o.item_id and i.deleted_at is null
        join projects p on p.id = o.project_id
        left join item_resolutions d on d.item_id = i.id and d.is_default and d.deleted_at is null
        where o.repository_id = :r and o.detection_state = 'found' and {where}
    """


def _windows_package_rows() -> str:
    return """
        select jsonb_build_object('kind', 'package', 'id', a.id, 'itemId', null, 'itemName', a.package_id,
                                  'treatment', 'blocker', 'category', 'dependencies', 'project', p.relative_path,
                                  'file', null, 'value', a.current_version, 'certainty', 'confirmed',
                                  'packageId', a.package_id, 'currentVersion', a.current_version) as item,
               1 as k_rank, p.relative_path as k_project, a.package_id as k_name, a.id as k_id,
               lower(concat_ws(' ', a.package_id, p.relative_path, 'blocker')) as search
        from package_assessments a
        join projects p on p.id = a.project_id
        where a.repository_id = :r
          and (lower(a.package_id) = any(:exact)
               or exists (select 1 from unnest(cast(:prefix as text[])) pre where lower(a.package_id) like pre || '%'))
    """


def _linux_source() -> str:
    return f"select * from ({_item_rows(_LISTED)} union all {_windows_package_rows()}) u"


_ORDER = 'k_rank, k_project collate "C", k_name collate "C", k_id collate "C"'


@router.get("/repositories/{repository_id}/compatibility/summary", response_model=CompatibilitySummaryOut,
            summary="Count a repository's Linux compatibility findings",
            operation_id="get_repository_compatibility_summary", responses=_RESPONSES)
def get_compatibility_summary(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    _repository(db, repository_id)
    scan = _scan(db, repository_id)
    params = {"r": repository_id, **_linux_params()}
    by_treatment = dict(db.execute(
        text(f"select item->>'treatment', count(*) from ({_linux_source()}) s group by 1"), params).all())
    packages = db.execute(text(f"select count(*) from ({_windows_package_rows()}) s"), params).scalar_one()
    total = sum(by_treatment.values())
    return CompatibilitySummaryOut(
        linux=total, linux_items=total - packages, linux_packages=packages,
        linux_blockers=by_treatment.get("blocker", 0), linux_container=by_treatment.get("container", 0),
        linux_other=by_treatment.get("other", 0),
        scanned_at=scan.scanned_at.isoformat() if scan.scanned_at else None)


def _enrich_linux(result: PageOut) -> PageOut:
    for row in result.items:
        if row["kind"] == "package":
            rule = _package_why(row["packageId"])
            row["whyBlocked"] = rule["why"] if rule else None
            row["whatToDo"] = rule["replacement"] if rule else None
    return result


@router.get("/repositories/{repository_id}/compatibility/linux", response_model=PageOut,
            summary="Get a page of what a repository needs to run on Linux in a container",
            operation_id="list_repository_linux_compatibility", responses=_RESPONSES)
def list_linux_compatibility(repository_id: uuid.UUID, paging: PageParams = Depends(), db: Session = Depends(get_db)):
    """Items with `kind` 'item' (a listed catalog item that was found) or 'package' (a Windows-only package), each
    with `treatment`: blocker, container or other. The filter matches the item, its category, the project, the file,
    the value, the badge, and the method and type the finding was found in."""
    _repository(db, repository_id)
    _scan(db, repository_id)
    return _enrich_linux(page(db, _linux_source(), {"r": repository_id, **_linux_params()}, paging, order=_ORDER))
