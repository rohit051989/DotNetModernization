"""An item an engagement decided is not applicable (28-ITEM-AND-CONVERSION-MODEL.md Part F, "Not applicable";
app.items.applicability).

- A not-applicable decision chooses no resolution, and approving it needs a rationale, an approver and a date, never the
  forcing pair.
- Only an approved one takes effect. Its item is no work: not in the model either engine's inputs are rendered from,
  nor in any file of either engine's inputs; its findings are kept apart for the verifier, which counts them separately
  (rediscovery.work_items(model, "not_applicable")); the dashboard counts it as no work.
- Superseding the decision brings the item back, with nothing rescanned: the findings were never dropped.

Fixture items and rows in one rolled-back transaction (tests/test_item_detection.DetectionTestCase).
Run from backend/:  python -m unittest tests.test_not_applicable -v
"""
import datetime
import unittest
import uuid

from fastapi import HTTPException, Response

from app import models
from app.engine import engines
from app.engine.inputs import render
from app.engine.inputs.collect import collect
from app.engine.verifier import rediscovery
from app.items import applicability
from app.items import schemas as s
from app.routers import catalog_items, dashboard, item_decisions
from tests.support import TEST_ENGAGEMENT_ID, item_decision_version
from tests.test_item_detection import DetectionTestCase

NA_ITEM, KEPT_ITEM = "t-na-item", "t-kept-item"
NA_NAME = "Fixture item that this engagement does not want"


class NotApplicable(DetectionTestCase):
    def setUp(self):
        super().setUp()
        for item_id, name in ((NA_ITEM, NA_NAME), (KEPT_ITEM, "Fixture item that stays work")):
            catalog_items.create_item(s.CatalogItemCreate(
                id=item_id, name=name, scope="occurrence", category="configuration",
                detection={"match": {"all": [{"signal": {"name": "SVC_FILE"}}]},
                           "occurrence_source": {"signal": "SVC_FILE", "group_by": "source_path"}}), db=self.db)
            catalog_items.create_resolution(item_id, s.ResolutionCreate(
                id=f"{item_id}-fix", name=f"{item_id} fix", consumer_impact="none", effort="low", is_default=True), db=self.db)
            catalog_items.create_resolution(item_id, s.ResolutionCreate(
                id=f"{item_id}-big", name=f"{item_id} big", consumer_impact="high", effort="high"), db=self.db)
        project = self.add_project("src/App/App.csproj")
        for item_id in (NA_ITEM, KEPT_ITEM):
            self.db.add(models.ItemOccurrence(repository_id=self.repo.id, project_id=project.id, item_id=item_id, scope="occurrence",
                                              file_path=f"src/App/{item_id}.json", signal_registry_version="test",
                                              detection_state="found"))
        self.db.flush()

    def decide(self, item_id, **fields):
        return item_decisions.upsert_item_decision(TEST_ENGAGEMENT_ID, item_id, s.EngagementDecisionUpsert(**fields), Response(),
                                                   db=self.db, if_match=item_decision_version(self.db, TEST_ENGAGEMENT_ID, item_id))

    def not_applicable(self, **extra):
        return self.decide(NA_ITEM, outcome="not_applicable", status="approved", rationale="Not wanted by this engagement.",
                           approver_name="Reviewer", decision_date=datetime.date(2026, 11, 23), **extra)

    def codes(self, fn, *args, **kwargs) -> list[str]:
        with self.assertRaises(HTTPException) as raised:
            fn(*args, **kwargs)
        self.assertEqual(raised.exception.status_code, 422)
        return [d.get("code") for d in raised.exception.detail]

    # ---- the decision

    def test_a_not_applicable_decision_chooses_no_resolution(self):
        self.assertIn("NOT_APPLICABLE_HAS_RESOLUTION", self.codes(self.not_applicable, resolution_id=f"{NA_ITEM}-fix"))

    def test_approving_it_needs_a_rationale_an_approver_and_a_date_never_the_forcing_pair(self):
        missing = self.codes(self.decide, NA_ITEM, outcome="not_applicable", status="approved")
        self.assertEqual(sorted(missing), ["APPROVAL_REQUIRES_APPROVER", "APPROVAL_REQUIRES_DATE", "APPROVAL_REQUIRES_RATIONALE"])
        decided = self.not_applicable()
        self.assertEqual((decided.outcome, decided.status, decided.resolution_id), ("not_applicable", "approved", None))

    def test_only_an_approved_decision_takes_effect(self):
        self.decide(NA_ITEM, outcome="not_applicable", rationale="Proposed.")
        self.assertEqual(applicability.not_applicable(self.db, TEST_ENGAGEMENT_ID), {})
        self.not_applicable()
        self.assertEqual(applicability.not_applicable(self.db, TEST_ENGAGEMENT_ID)[NA_ITEM]["approver"], "Reviewer")

    # ---- no work

    def test_the_item_is_in_neither_engines_inputs_and_the_verifier_counts_it_apart(self):
        self.not_applicable()
        model = collect(self.db, self.repo)
        self.assertEqual([i["id"] for i in model["items"]], [KEPT_ITEM])
        self.assertEqual([(n["id"], len(n["occurrences"])) for n in model["not_applicable"]], [(NA_ITEM, 1)])
        for engine in (engines.COPILOT, engines.CLAUDE):
            files = render.render(model, engine)
            self.assertTrue(files)
            leaked = [path for path, body in files.items() if NA_ITEM in body or NA_NAME in body or NA_ITEM in path]
            self.assertEqual(leaked, [], engine)
            self.assertTrue(any(KEPT_ITEM in body or KEPT_ITEM in path for path, body in files.items()), engine)
        self.assertEqual(list(rediscovery.work_items(model)), [("src/App/App.csproj", KEPT_ITEM)])
        self.assertEqual(list(rediscovery.work_items(model, "not_applicable")), [("src/App/App.csproj", NA_ITEM)])

    def test_the_dashboard_counts_it_as_no_work(self):
        before = dashboard._item_counts(self.db, [self.repo.id])
        self.not_applicable()
        after = dashboard._item_counts(self.db, [self.repo.id])
        self.assertEqual((before.items_found, after.items_found), (2, 1))
        self.assertEqual([t.item_id for t in after.top_items], [KEPT_ITEM])

    def test_superseding_the_decision_brings_it_back_with_nothing_rescanned(self):
        decided = self.not_applicable()
        item_decisions.supersede_item_decision(uuid.UUID(decided.id), db=self.db, if_match=str(decided.version))
        model = collect(self.db, self.repo)
        self.assertEqual(sorted(i["id"] for i in model["items"]), [KEPT_ITEM, NA_ITEM])
        self.assertEqual(model["not_applicable"], [])

    def test_the_master_catalog_is_untouched(self):
        before = (self.db.get(models.CatalogItem, NA_ITEM).updated_at, self.db.get(models.CatalogItem, NA_ITEM).deleted_at)
        self.not_applicable()
        item = self.db.get(models.CatalogItem, NA_ITEM)
        self.assertEqual((item.updated_at, item.deleted_at, item.status), (*before, "active"))


if __name__ == "__main__":
    unittest.main()
