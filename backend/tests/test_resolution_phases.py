"""Every catalog resolution has a phase, and the plan goes by phase, then by the project dependency graph (2026-11-25,
36-COPILOT-ENHANCED-CONVERSION "Phases"; the review hand-off's gap 1).

The catalog checked is this run's own, imported from the export (catalog/items/) as a new environment is.
"""
import unittest

import yaml
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import models
from app.db import engine
from app.engine.inputs import render
from app.items import baseline, catalog_export
from app.items import schemas as item_schemas
from app.seed.seed_data import _load


def _item(item_id: str, resolution_id: str, phase: int | None, project: str, ordering=()) -> dict:
    return {"id": item_id, "name": item_id, "ordering": list(ordering), "decided": False,
            "resolution": {"id": resolution_id, "name": resolution_id, "guidance": "Do it.", "phase": phase},
            "occurrences": [{"project": project, "file": None, "value": None, "certainty": "confirmed", "lines": []}],
            "impact": []}


class EveryResolutionHasAPhase(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.outer = self.connection.begin()
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.connection.close()

    def test_every_active_resolution_in_the_database_has_a_phase(self):
        rows = (self.db.query(models.ItemResolution.id, models.ItemResolution.phase)
                .join(models.CatalogItem, models.CatalogItem.id == models.ItemResolution.item_id)
                .filter(models.CatalogItem.status == "active", models.CatalogItem.deleted_at.is_(None),
                        models.ItemResolution.status == "active", models.ItemResolution.deleted_at.is_(None)).all())
        self.assertGreater(len(rows), 100)
        self.assertEqual(sorted(r for r, phase in rows if phase not in render.PHASES), [])

    def test_every_resolution_in_the_export_has_the_factory_phase(self):
        for path in sorted(catalog_export.DEFAULT_DIR.glob("*.yaml")):
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            for r in doc.get("resolutions") or []:
                self.assertIn(r.get("phase"), render.PHASES, f"{doc['id']}/{r['id']}")
                self.assertEqual(r["phase"], baseline.factory_phase(doc["id"], r["id"]), f"{doc['id']}/{r['id']}")

    def test_every_phase_entry_names_a_catalog_item_or_resolution(self):
        data = yaml.safe_load(baseline.PHASES_FILE.read_text(encoding="utf-8"))
        items = {yaml.safe_load(p.read_text(encoding="utf-8"))["id"]: p for p in catalog_export.DEFAULT_DIR.glob("*.yaml")}
        items |= {i["id"]: None for i in _load("catalog_items.yaml")["items"]}
        self.assertEqual(sorted(set(data["items"]) - set(items)), [])
        resolutions = {r["id"] for p in catalog_export.DEFAULT_DIR.glob("*.yaml")
                       for r in yaml.safe_load(p.read_text(encoding="utf-8")).get("resolutions") or []}
        self.assertEqual(sorted(set(data["resolutions"]) - resolutions), [])
        self.assertTrue(all(v in render.PHASES for v in list(data["items"].values()) + list(data["resolutions"].values())))

    def test_the_api_takes_a_phase_from_1_to_6(self):
        base = dict(name="x", consumer_impact="low", effort="low")
        self.assertEqual(item_schemas.ResolutionWrite(**base, phase=4).phase, 4)
        self.assertIsNone(item_schemas.ResolutionWrite(**base).phase)
        for bad in (0, 7):
            with self.assertRaises(ValidationError):
                item_schemas.ResolutionWrite(**base, phase=bad)


class ThePlanGoesByPhaseThenByTheDependencyGraph(unittest.TestCase):
    def model(self, items, references):
        return {"items": items, "references": references, "projects": [], "engagement": {"target_framework": "net10.0"}}

    def test_phase_first_then_referenced_projects_first_then_the_models_order(self):
        items = [
            _item("app-host", "move-app", 4, "App/App.csproj"),
            _item("platform", "timezone", 5, "App/App.csproj"),
            _item("lib-a", "bridge-a", 2, "LibA/LibA.csproj"),
            _item("lib-b", "bridge-b", 2, "LibB/LibB.csproj"),
            _item("decide", "decide-later", 6, "App/App.csproj"),
            _item("ssis", "worker", 3, "App/App.csproj"),
            _item("project-file", "sdk-style", 1, "App/App.csproj"),
            _item("unset", "no-phase", None, "App/App.csproj"),
        ]
        # LibA references LibB: LibB's bridge first, though the model lists LibA first.
        work = render.work_items(self.model(items, {"App/App.csproj": ["LibA/LibA.csproj"],
                                                    "LibA/LibA.csproj": ["LibB/LibB.csproj"]}))
        self.assertEqual([w["name"] for w in work], ["applying-sdk-style", "applying-bridge-b", "applying-bridge-a",
                                                     "applying-worker", "applying-move-app", "applying-timezone",
                                                     "applying-no-phase", "applying-decide-later"])
        self.assertEqual([w["phase"] for w in work], [1, 2, 2, 3, 4, 5, 5, 6])
        follows = {w["name"]: [(f["name"], f["why"]) for f in w["follows"]] for w in work}
        self.assertEqual(follows["applying-bridge-a"], [("applying-bridge-b", "it changes a project this one references")])
        self.assertIn(("applying-bridge-a", "it changes a project this one references"), follows["applying-move-app"])
        self.assertIn(("applying-worker", "it changes the same project first"), follows["applying-move-app"])
        self.assertEqual(follows["applying-bridge-b"], [])

    def test_a_rule_holds_within_a_phase_never_across_one(self):
        items = [_item("later", "second", 5, "A/A.csproj"),
                 _item("earlier", "first", 5, "B/B.csproj", ordering=[{"relation": "before", "item": "later"}]),
                 _item("lower", "lower", 2, "C/C.csproj", ordering=[{"relation": "after", "item": "later"}])]
        names = [w["name"] for w in render.work_items(self.model(items, {}))]
        self.assertEqual(names, ["applying-lower", "applying-first", "applying-second"])

    def test_each_instruction_names_its_phase_and_what_it_follows(self):
        items = [_item("lib", "bridge", 2, "Lib/Lib.csproj"), _item("app", "move", 4, "App/App.csproj")]
        model = self.model(items, {"App/App.csproj": ["Lib/Lib.csproj"]})
        entry = next(w for w in render.work_items(model) if w["name"] == "applying-move")
        lines = render._prerequisites(items[1], {"lib", "app"}, {i["id"]: i for i in items}, entry)
        self.assertEqual(lines, ["- Phase 4 of 6, retarget and host applications: apply it after every work item of the "
                                 "phases before it.",
                                 "- Apply after `applying-bridge` (bridge (lib)): it changes a project this one references."])


if __name__ == "__main__":
    unittest.main()
