"""The repository Compatibility tab's Linux list (app.routers.compatibility_pages).

Hermetic: fixture items, resolutions, projects, occurrences and package assessments inside one rolled-back
transaction, called as functions."""
import unittest
import uuid
from pathlib import Path

import yaml

from app import models
from app.items import schemas as s
from app.results.paging import PageParams
from app.routers import catalog_items, compatibility_pages as pages
from tests.test_item_detection import DetectionTestCase


def paging(q: str = "", offset: int = 0, limit: int = 20) -> PageParams:
    return PageParams(q=q, offset=offset, limit=limit)


class CompatibilityPagesTest(DetectionTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.add_project("src/App/App.csproj")
        self.other = self.add_project("src/Lib/Lib.csproj")
        for item_id, category in (("t-win", "integration"), ("t-cont", "hosting"), ("t-other", "framework"),
                                  ("t-unlisted", "integration")):
            self.item(item_id, category)
        data = pages._data()
        data["treatments"].update({"t-win": "blocker", "t-cont": "container", "t-other": "other"})
        self.addCleanup(lambda: [data["treatments"].pop(k) for k in ("t-win", "t-cont", "t-other")])
        for project, item_id in ((self.project, "t-win"), (self.other, "t-win"), (self.project, "t-cont"),
                                 (self.project, "t-other"), (self.project, "t-unlisted")):
            self.found(project, item_id)
        # Not found: never listed.
        self.found(self.other, "t-cont", state="checked_absent")
        self.package(self.project, "System.Drawing.Common", "4.7.0", "upgrade_safe")
        self.package(self.project, "Newtonsoft.Json", "12.0.1", "upgrade_breaking", members=[{"member": "A.B"}])
        self.package(self.other, "Microsoft.Office.Interop.Excel", "15.0.0", "upgrade_safe")
        self.db.flush()

    def item(self, item_id, category):
        catalog_items.create_item(s.CatalogItemCreate(
            id=item_id, name=item_id, scope="application", category=category,
            detection={"match": {"all": [{"signal": {"name": "SVC_FILE"}}]}}), db=self.db)
        catalog_items.create_resolution(item_id, s.ResolutionCreate(
            id=f"{item_id}-fix", name=f"{item_id}-fix", consumer_impact="low", effort="low", is_default=True), db=self.db)

    def found(self, project, item_id, state="found"):
        self.db.add(models.ItemOccurrence(repository_id=self.repo.id, project_id=project.id, item_id=item_id,
                                          scope="application", signal_registry_version="test", detection_state=state))

    def package(self, project, package_id, version, outcome, members=None):
        self.db.add(models.PackageAssessment(
            id=uuid.uuid4().hex, repository_id=self.repo.id, project_id=project.id, package_id=package_id,
            current_version=version, outcome=outcome, confidence=1, breaking_members=members or []))

    def scanned(self):
        self.scan("test")
        self.db.flush()

    def test_not_scanned_is_a_409(self):
        with self.assertRaises(Exception) as caught:
            pages.list_linux_compatibility(self.repo.id, paging(), db=self.db)
        self.assertEqual(getattr(caught.exception, "status_code", None), 409)

    def test_unknown_repository_is_a_404(self):
        with self.assertRaises(Exception) as caught:
            pages.list_linux_compatibility(uuid.uuid4(), paging(), db=self.db)
        self.assertEqual(getattr(caught.exception, "status_code", None), 404)

    def test_routes_are_registered(self):
        from app.main import app
        paths = {r.path for r in app.routes}
        for suffix in ("summary", "linux"):
            self.assertIn("/api/repositories/{repository_id}/compatibility/" + suffix, paths)
        # Method/API compatibility repeated the Dependencies tab and the Work list: it has no route.
        self.assertNotIn("/api/repositories/{repository_id}/compatibility/api", paths)

    def test_linux_lists_listed_items_and_windows_only_packages_with_a_badge(self):
        self.scanned()
        result = pages.list_linux_compatibility(self.repo.id, paging(), db=self.db)
        rows = [(i["treatment"], i["itemName"]) for i in result.items]
        self.assertEqual(sorted(rows), sorted([
            ("blocker", "t-win"), ("blocker", "t-win"), ("blocker", "System.Drawing.Common"),
            ("blocker", "Microsoft.Office.Interop.Excel"), ("container", "t-cont"), ("other", "t-other")]))
        self.assertEqual(result.total, 6)
        # Blockers first, then container, then other.
        self.assertEqual([i["treatment"] for i in result.items], ["blocker"] * 4 + ["container", "other"])
        item = next(i for i in result.items if i["itemName"] == "t-win")
        self.assertEqual(item["whatToDo"], "t-win-fix")
        package = next(i for i in result.items if i.get("packageId") == "System.Drawing.Common")
        self.assertIn("Windows-only", package["whyBlocked"])

    def test_filter_matches_the_badge_and_narrows_matching_not_total(self):
        self.scanned()
        result = pages.list_linux_compatibility(self.repo.id, paging(q="container"), db=self.db)
        self.assertEqual((result.total, result.matching), (6, 1))
        result = pages.list_linux_compatibility(self.repo.id, paging(q="interop"), db=self.db)
        self.assertEqual((result.total, result.matching), (6, 1))

    def test_a_breaking_upgrade_is_not_a_linux_finding(self):
        self.scanned()
        result = pages.list_linux_compatibility(self.repo.id, paging(), db=self.db)
        self.assertNotIn("Newtonsoft.Json", [i["itemName"] for i in result.items])

    def test_summary_counts_each_badge(self):
        self.scanned()
        summary = pages.get_compatibility_summary(self.repo.id, db=self.db)
        self.assertEqual((summary.linux, summary.linux_items, summary.linux_packages), (6, 4, 2))
        self.assertEqual((summary.linux_blockers, summary.linux_container, summary.linux_other), (4, 1, 1))
        self.assertFalse(hasattr(summary, "api"))

    def test_soft_deleted_item_is_left_out(self):
        self.scanned()
        self.db.get(models.CatalogItem, "t-win").deleted_at = models.func.now()
        self.db.flush()
        result = pages.list_linux_compatibility(self.repo.id, paging(), db=self.db)
        self.assertNotIn("t-win", [i["itemName"] for i in result.items])


class CommittedListTest(unittest.TestCase):
    """The committed list names only items the catalog has, and only the three badges."""

    def test_every_treated_item_exists_and_badges_are_known(self):
        catalog = Path(__file__).resolve().parents[2] / "catalog" / "items"
        known = {p.stem for p in catalog.glob("*.yaml")}
        treatments = yaml.safe_load(pages._DATA.read_text(encoding="utf-8"))["treatments"]
        self.assertEqual(sorted(set(treatments) - known), [])
        self.assertLessEqual(set(treatments.values()), set(pages._RANK))


if __name__ == "__main__":
    unittest.main()
