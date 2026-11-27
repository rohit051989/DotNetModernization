"""Every active catalog item, on one generated repository (tests/fixtures/coverage_repository.py) scanned by the real
discovery job:

1. every item is detected, at the places the fixture expects;
2. every resolution with engine guidance, chosen in turn, has its work item in both engines' inputs with its guidance,
   in the order the phases and the dependency graph give, and preparation reports no gap for it;
3. a catalog item with no occurrence in the fixture fails, naming its id (CoverageIsComplete, in every tier): a new
   item cannot be added without its fixture occurrence, as the guidance allow-list test does for guidance;
4. a coverage table (item, detected, work item in each engine, guidance rendered) is printed at the end and written to
   the temporary folder (catalog-coverage.md).

The scan and the resolutions run in the full tier (tests/tiers.py). Runs in this run's own schema.
Run from backend/:  python -m unittest tests.test_catalog_coverage -v
"""
import datetime
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from sqlalchemy import text

from app import models
from app.config import settings
from app.db import SessionLocal
from app.engine import engines, inputs
from app.engine.inputs import claude, collect, render
from tests.fixtures import coverage_repository as fixture
from tests.tiers import slow

# Resolutions with guidance that cannot reach a work item on this fixture, with why. Reported in the table; kept empty
# unless the reason is a property of the resolution, not of the fixture.
CANNOT_TRIGGER: dict[tuple[str, str], str] = {}

GAPS = ("resolution", "default", "phase", "conflict")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@client-a.example", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def _flat(value: str) -> str:
    return " ".join(value.split())


def _first_words(value: str) -> str:
    return " ".join(value.split()[:12])


def active_items(db) -> list[models.CatalogItem]:
    return (db.query(models.CatalogItem).filter(models.CatalogItem.status == "active", models.CatalogItem.deleted_at.is_(None))
            .order_by(models.CatalogItem.id).all())


def guided_resolutions(db, item_id: str) -> list[models.ItemResolution]:
    return (db.query(models.ItemResolution).filter_by(item_id=item_id, status="active")
            .filter(models.ItemResolution.deleted_at.is_(None)).order_by(models.ItemResolution.id).all())


class CoverageIsComplete(unittest.TestCase):
    """Fast, in every tier: each active catalog item has its occurrence in the coverage fixture, and the fixture names
    no item the catalog does not have."""

    def test_every_active_item_has_a_fixture_occurrence(self):
        db = SessionLocal()
        try:
            ids = {i.id for i in active_items(db)}
        finally:
            db.close()
        missing = sorted(ids - set(fixture.EXPECTED))
        self.assertEqual(missing, [], "active catalog items with no occurrence in tests/fixtures/coverage_repository.py "
                                      f"(add one, triggered by the item's real signals): {', '.join(missing)}")
        self.assertEqual(sorted(set(fixture.EXPECTED) - ids), [], "the coverage fixture names items the catalog does not have")


@slow
class CatalogCoverageOnAScannedRepository(unittest.TestCase):
    TAG = uuid.uuid4().hex[:6]
    ENGAGEMENT = f"t-coverage-{TAG}"
    FEED = fixture.FEED.format(tag=TAG)
    rows: dict[str, dict] = {}

    @classmethod
    def setUpClass(cls):
        from app.repositories import service as repositories_service
        from app.repositories.schemas import RegisterLocalPathRequest
        from app.workflow.runtime import service as runtime

        cls.tmp = Path(tempfile.mkdtemp(prefix="coverage-"))
        cls.root = cls.tmp / "coverage-estate"
        fixture.write(cls.root, cls.TAG)
        _git(cls.root, "init", "-q", "-b", "main")
        _git(cls.root, "add", "-A", "-f")
        _git(cls.root, "commit", "-qm", "a made-up estate with every catalog item")
        cls.db = SessionLocal()
        now = datetime.datetime.now(datetime.timezone.utc)
        cls.public_ids = []
        for feed, lookups in ((cls.FEED, fixture.LOOKUPS), (fixture.NUGET_ORG, fixture.PUBLIC)):
            for package_id, versions in lookups.items():
                if feed == fixture.NUGET_ORG and cls.db.execute(text(
                        "select 1 from package_lookup_cache where feed_url_normalised = :f and package_id = :p"),
                        {"f": feed, "p": package_id}).first():
                    continue
                cls.db.add(models.PackageLookupCache(feed_url_normalised=feed, package_id=package_id, versions=list(versions),
                                                     metadata_=versions, fetched_at=now, lookup_rule=2))
                if feed == fixture.NUGET_ORG:
                    cls.public_ids.append(package_id)
        cls.db.add(models.Engagement(id=cls.ENGAGEMENT, client_name="Test engagement (catalog coverage)",
                                     target_platform="Linux / OpenShift Container Platform 4", default_posture="lift-and-shift"))
        cls.db.commit()
        cls.repo = repositories_service.register_local_path(cls.db, cls.db.get(models.Engagement, cls.ENGAGEMENT),
                                                            RegisterLocalPathRequest(source_type="local_path", local_path=str(cls.root)))
        cls.db.commit()
        # The public feed is compared (a package newer on nuget.org than in the client feed), from the cache only.
        with mock.patch.object(settings, "compare_public_nuget_feed", True):
            token = repositories_service.start_rescan(cls.repo)
            cls.db.commit()
            cls.execution = runtime.launch_job(cls.db, "phase0-repository-discovery", {
                "engagement_id": cls.ENGAGEMENT, "repository_id": str(cls.repo.id), "ingest_token": token,
                "lookup_offline": True, "prepare_conversion": False}, triggered_by="manual")
            cls.db.commit()
        cls.db.refresh(cls.repo)
        cls.items = {i.id: i for i in active_items(cls.db)}
        cls.rows = {item_id: {"detected": False, "resolutions": {}} for item_id in cls.items}

    @classmethod
    def tearDownClass(cls):
        from app.deletion import service as deletion

        report = cls.table()
        out = Path(tempfile.gettempdir()) / "catalog-coverage.md"
        out.write_text(report, encoding="utf-8")
        print(f"\n{report}\n(written to {out})", file=sys.stderr)
        cls.db.rollback()
        cls.db.execute(text("delete from package_lookup_cache where feed_url_normalised = :f"), {"f": cls.FEED})
        for package_id in cls.public_ids:
            cls.db.execute(text("delete from package_lookup_cache where feed_url_normalised = :f and package_id = :p"),
                           {"f": fixture.NUGET_ORG, "p": package_id})
        cls.db.commit()
        engagement = cls.db.get(models.Engagement, cls.ENGAGEMENT)
        if engagement is not None:
            with mock.patch.object(deletion, "_remove_files", return_value={"worktrees": [], "branches": [], "folders": []}):
                deletion.delete(cls.db, deletion.engagement_plan(cls.db, engagement), engagement.client_name, via="test")
        cls.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def table(cls) -> str:
        """Item | detected | resolution | work item (GitHub Copilot) | work item (Claude Code) | guidance rendered."""
        lines = ["# Catalog coverage", "", "| Item | Detected | Resolution | Work item: GitHub Copilot | Work item: Claude Code "
                 "| Guidance rendered | Note |", "|---|---|---|---|---|---|---|"]
        for item_id in sorted(cls.rows):
            row = cls.rows[item_id]
            detected = "yes" if row["detected"] else "**no**"
            if not row["resolutions"]:
                lines.append(f"| {item_id} | {detected} | (no active resolution) | - | - | - | |")
            for resolution_id, r in sorted(row["resolutions"].items()):
                mark = lambda v: "yes" if v else "**no**"   # noqa: E731
                if r.get("skip"):
                    lines.append(f"| {item_id} | {detected} | {resolution_id} | - | - | - | {r['note']} |")
                    continue
                lines.append(f"| {item_id} | {detected} | {resolution_id} | {mark(r.get('copilot'))} | {mark(r.get('claude'))} "
                             f"| {mark(r.get('guidance'))} | {r.get('note', '')} |")
        return "\n".join(lines) + "\n"

    def decide(self, choices: dict[str, str]) -> None:
        self.db.query(models.EngagementDecision).filter_by(engagement_id=self.ENGAGEMENT).delete()
        for item_id, resolution_id in choices.items():
            self.db.add(models.EngagementDecision(engagement_id=self.ENGAGEMENT, item_id=item_id, resolution_id=resolution_id,
                                                  status="approved", approver_name="Test", rationale="chosen for the test"))
        self.db.commit()

    # ---- the tests

    def test_1_every_item_is_detected_at_its_places(self):
        self.assertEqual(self.execution.batch_status, "COMPLETED", self.execution.exit_message)
        found: dict[str, set] = {}
        for o, project in (self.db.query(models.ItemOccurrence, models.Project.relative_path)
                           .join(models.Project, models.Project.id == models.ItemOccurrence.project_id)
                           .filter(models.ItemOccurrence.repository_id == self.repo.id,
                                   models.ItemOccurrence.detection_state == "found")):
            found.setdefault(o.item_id, set()).add((project, o.file_path))
            found[o.item_id].add((project, None))                # an occurrence counts for its project too
        missing = []
        for item_id, places in sorted(fixture.EXPECTED.items()):
            absent = sorted((p, f or "") for p, f in places if (p, f) not in found.get(item_id, set()))
            if item_id in self.rows:
                self.rows[item_id]["detected"] = item_id in found and not absent
            if absent:
                missing.append(f"{item_id}: not at {absent}; found at {sorted((p, f or '') for p, f in found.get(item_id, set()))}")
        self.assertEqual(missing, [], "\n".join(missing))

    def test_2_every_resolution_with_guidance_reaches_both_engines_in_plan_order_with_no_gap(self):
        failures = []
        for item_id in sorted(fixture.EXPECTED):
            if item_id not in self.items:
                continue
            allowed = render.allowlist()
            for resolution in guided_resolutions(self.db, item_id):
                row = self.rows[item_id]["resolutions"].setdefault(resolution.id, {})
                if not (resolution.engine_guidance or "").strip():
                    # Not an instruction the engines follow: listed, with the allow-list's reason, never a failure.
                    row.update(skip=True, note=f"no guidance yet (allow-list): {allowed.get(resolution.id, 'no reason recorded')}")
                    continue
                why = CANNOT_TRIGGER.get((item_id, resolution.id))
                if why:
                    row["note"] = f"cannot trigger: {why}"
                    continue
                with self.subTest(item=item_id, resolution=resolution.id):
                    problem = self.check_one(item_id, resolution, row)
                    if problem:
                        row["note"] = problem
                        failures.append(f"{item_id} / {resolution.id}: {problem}")
        self.decide({})
        self.assertEqual(failures, [], "\n".join(failures))

    def check_one(self, item_id: str, resolution: models.ItemResolution, row: dict) -> str | None:
        self.decide({item_id: resolution.id})
        model = collect.collect(self.db, self.repo)
        item = next((i for i in model["items"] if i["id"] == item_id), None)
        if item is None:
            return "not in the conversion's model"
        if (item["resolution"] or {}).get("id") != resolution.id:
            return f"the model chose {(item['resolution'] or {}).get('id')}"
        plan = render.work_items(model)
        entry = next((w for w in plan if w["item"]["id"] == item_id), None)
        if entry is None:
            unresolved = sorted({u["why"] for u in render.plan_item(item)["unresolved"]})
            return "no work item" + (f": every place unresolved ({'; '.join(unresolved)})" if unresolved else "")
        phases = [w["phase"] for w in plan]
        if phases != sorted(phases):
            return f"the plan is not in phase order: {phases}"
        if resolution.phase and entry["phase"] != min(resolution.phase, entry["phase"]):
            return f"placed in phase {entry['phase']}, its resolution's is {resolution.phase}"
        # Within a phase, a work item on a project this one's projects reference comes first (the dependency graph).
        names = [w["name"] for w in plan]
        mine = {o["project"] for o in item["occurrences"]}
        below = render._referenced(model, mine)
        for other in plan:
            theirs = {o["project"] for o in other["item"]["occurrences"]}
            if other["phase"] == entry["phase"] and other["name"] != entry["name"] and theirs & below \
                    and not (mine & render._referenced(model, theirs)) and names.index(other["name"]) > names.index(entry["name"]):
                return f"before `{other['name']}`, which changes a project this one references, in the same phase"
        gaps = [m for m in render.without_guidance(model) if m["item"] == item_id and m["missing"] in GAPS]
        if gaps:
            return "a gap: " + "; ".join(f"{m['missing']} {m.get('why') or ''}".strip() for m in gaps)
        files = {engine: inputs.build(model, Path(self.repo.local_path), [], engine) for engine in engines.ENGINES}
        name = render.skill_name(resolution.id)
        copilot = files[engines.COPILOT].get(f".github/upgrades/skills/{name}.md")
        claude_text = files[engines.CLAUDE].get(claude.skill_path(name))
        row["copilot"], row["claude"] = copilot is not None, claude_text is not None
        row["guidance"] = all(t is not None and _first_words(resolution.engine_guidance) in _flat(t) for t in (copilot, claude_text))
        if not (row["copilot"] and row["claude"]):
            return "its work item is missing from " + " and ".join(
                e for e, t in ((engines.COPILOT, copilot), (engines.CLAUDE, claude_text)) if t is None)
        if not row["guidance"]:
            return "its guidance is not in the work item"
        return None


if __name__ == "__main__":
    unittest.main()
