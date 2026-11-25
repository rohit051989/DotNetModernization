"""Engagement guidance and field-by-field seeding (2026-11-26).

- Seeding works field by field (rule 10): a field nobody changed is seeded even on a row with other edited fields; a
  field an admin changed is kept, and reported only when the default changed too. A resolution edited in the UI before
  field baselines existed, with no phase, gets its phase and keeps its edited text.
- An engagement's note on a resolution: saved with a version check and an activity record, refused when not
  self-contained or holding a secret; rendered after the master guidance in both engines, saying it takes precedence.
- An engagement's conventions: the same checks; carried in the top-level instructions of both engines, and the design
  questions never ask about them.
- A resolution without master guidance still warns with a note; a resolution without a phase says "phase not set".

Runs in this run's own schema, its catalog imported from the export. End to end on a scanned repository (another
engagement, a master text change): tests/test_guidance_fixtures.py, test 13.
"""
import unittest

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models
from app.db import engine
from app.engine import engines
from app.engine.inputs import claude, render
from app.items import baseline
from app.routers import engagement_guidance as routes
from tests.test_engine_inputs import _item, model

NOTE = "Log through the client's own logging package, never Console.WriteLine."
CONVENTIONS = "- Log through ILogger, structured, to standard output.\n- Report errors as RFC 7807 problem details."


class Savepoint(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.outer = self.connection.begin()
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.connection.close()


class SeedingFieldByField(Savepoint):
    def desired(self, row, **changes):
        return {**baseline.values(row), **changes}

    def test_a_resolution_edited_before_field_baselines_with_no_phase_gets_its_phase_and_keeps_its_text(self):
        """The upgrade case: an admin edited the guidance in the UI before 5a1a719, so the row has a whole-row hash only,
        and no phase. The factory now gives it a phase and changed its guidance."""
        row = self.db.get(models.ItemResolution, "ocp4-cronjob-container")
        row.phase = None
        row.engine_guidance = "The client's own CronJob steps."
        row.seeded_fields = None
        row.seeded_hash = baseline.digest(baseline.content(row) | {"engine_guidance": "the guidance as it was seeded"})
        self.db.flush()
        report = baseline.new_report()
        _, outcome = baseline.seed_row(self.db, models.ItemResolution, {"id": row.id},
                                       self.desired(row, phase=4, engine_guidance="The factory's new CronJob steps."), report)
        self.assertEqual(outcome, "updated")
        self.assertEqual(row.phase, 4)
        self.assertEqual(row.engine_guidance, "The client's own CronJob steps.")
        self.assertEqual([c["row"] for c in report["conflicts"]], ["ocp4-cronjob-container"])
        self.assertEqual(sorted(report["conflicts"][0]["fields"]), ["engine_guidance"])
        self.assertIn("which side changed is unknown", report["conflicts"][0]["reason"])
        self.assertEqual(baseline.edit_state(row), "edited")

    def test_an_edited_field_is_kept_and_an_unedited_one_seeded_on_the_same_row(self):
        row = self.db.get(models.ItemResolution, "netstandard20-bridge")
        report = baseline.new_report()
        baseline.seed_row(self.db, models.ItemResolution, {"id": row.id}, self.desired(row), report)   # field baselines
        self.assertTrue(row.seeded_fields)
        row.name = "The bridge, as the client calls it"               # the admin's edit
        self.db.flush()
        self.assertEqual(baseline.edit_state(row), "edited")
        report = baseline.new_report()
        _, outcome = baseline.seed_row(self.db, models.ItemResolution, {"id": row.id},
                                       self.desired(row, name="Bridge (factory name)", description="New factory words.",
                                                    phase=2), report)
        self.assertEqual((outcome, row.description, row.name), ("updated", "New factory words.", "The bridge, as the client calls it"))
        self.assertEqual(sorted(report["conflicts"][0]["fields"]), ["name"])
        self.assertIn("edited since seeding, and the seed's default changed too", report["conflicts"][0]["reason"])
        # The default for the edited field unchanged since: kept, nothing reported.
        report = baseline.new_report()
        _, outcome = baseline.seed_row(self.db, models.ItemResolution, {"id": row.id},
                                       self.desired(row, name="Bridge (factory name)", description="Newer factory words."), report)
        self.assertEqual((outcome, row.description), ("updated", "Newer factory words."))
        self.assertEqual(report["conflicts"][0]["fields"].keys(), {"name"})

    def test_an_unedited_row_takes_every_new_default(self):
        row = self.db.get(models.ItemResolution, "path-combine")
        report = baseline.new_report()
        _, outcome = baseline.seed_row(self.db, models.ItemResolution, {"id": row.id},
                                       self.desired(row, description="Reworded.", phase=5), report)
        self.assertEqual((outcome, row.description, report["conflicts"]), ("updated", "Reworded.", []))
        self.assertEqual(baseline.edit_state(row), "unedited")


class NotesAndConventionsAreSavedWithTheirChecks(Savepoint):
    def setUp(self):
        super().setUp()
        for eid in ("t-eg-a", "t-eg-b"):
            self.db.add(models.Engagement(id=eid, client_name=f"Test engagement ({eid})", default_posture="lift-and-shift"))
        self.db.flush()

    def refused(self, code, call):
        with self.assertRaises(HTTPException) as caught:
            call()
        self.assertEqual(caught.exception.detail[0]["code"], code)
        return caught.exception.detail[0]

    def put_note(self, text, version="0", engagement="t-eg-a"):
        return routes.put_note(engagement, "csharp-worker-container", routes.NoteWrite(note=text), self.db, if_match=version)

    def test_a_note_names_its_version_is_checked_and_recorded(self):
        self.refused("VERSION_REQUIRED", lambda: self.put_note(NOTE, version=None))
        saved = self.put_note(NOTE)
        self.assertEqual((saved.note, saved.version, saved.item_id), (NOTE, 1, "ssis-package"))
        self.refused("STALE_COPY", lambda: self.put_note("other", version="0"))
        self.assertEqual(self.put_note(NOTE + " Always.", version="1").version, 2)
        record = (self.db.query(models.ActivityRecord)
                  .filter_by(subject_type="engagement_resolution_note", subject_id="t-eg-a/csharp-worker-container")
                  .order_by(models.ActivityRecord.id.desc()).first())
        self.assertEqual(record.action, "engagement_note.edit")
        self.assertEqual([n.resolution_id for n in routes.list_notes("t-eg-a", self.db)], ["csharp-worker-container"])
        self.assertEqual(routes.list_notes("t-eg-b", self.db), [])
        # The master catalog is untouched (rules 6 and 9).
        self.assertNotIn(NOTE, self.db.get(models.ItemResolution, "csharp-worker-container").engine_guidance or "")

    def test_a_note_or_conventions_that_are_not_self_contained_or_hold_a_secret_are_refused_as_field_errors(self):
        loose = self.refused("NOT_SELF_CONTAINED", lambda: self.put_note("As docs/36-COPILOT-ENHANCED-CONVERSION.md says."))
        self.assertEqual(loose["field"], "note")
        secret = self.refused("SECRET_VALUE", lambda: self.put_note("Connect with Password=Hunter2Secret!; then load."))
        self.assertEqual(secret["field"], "note")
        engagement = self.db.get(models.Engagement, "t-eg-a")
        bad = self.refused("SECRET_VALUE", lambda: routes.put_conventions(
            "t-eg-a", routes.ConventionsWrite(conventions="api_key = 'sk-live-0123456789abcdef0123456789'"), self.db,
            if_match=str(engagement.version)))
        self.assertEqual(bad["field"], "conventions")

    def test_conventions_are_saved_with_the_engagement_settings_version(self):
        engagement = self.db.get(models.Engagement, "t-eg-a")
        version = engagement.version
        self.refused("STALE_COPY", lambda: routes.put_conventions("t-eg-a", routes.ConventionsWrite(conventions=CONVENTIONS),
                                                                  self.db, if_match=str(version + 5)))
        saved = routes.put_conventions("t-eg-a", routes.ConventionsWrite(conventions=CONVENTIONS), self.db, if_match=str(version))
        self.assertEqual((saved.conventions, saved.version), (CONVENTIONS, version + 1))
        self.assertIsNone(routes.get_conventions("t-eg-b", self.db).conventions)

    def test_editing_is_for_admins(self):
        from app.auth import policy

        for route in (("PUT", "/api/engagements/{engagement_id}/resolutions/{resolution_id}/note"),
                      ("PUT", "/api/engagements/{engagement_id}/conventions")):
            self.assertNotIn(route, policy.RULES)


class RenderedForBothEngines(unittest.TestCase):
    def files(self, m):
        return {engine: render.render(m, engine) for engine in engines.ENGINES}

    def test_the_master_guidance_then_the_engagement_note_saying_it_takes_precedence(self):
        item = _item("datetime-now-usage", "container-local-timezone")
        item["resolution"]["engagement_note"] = NOTE
        files = self.files(model([item]))
        for text in (files[engines.COPILOT][".github/upgrades/skills/applying-container-local-timezone.md"],
                     files[engines.CLAUDE][claude.skill_path("applying-container-local-timezone")]):
            todo = text.split("## What to do", 1)[1].split("\n## ", 1)[0]
            self.assertLess(todo.index("Do the thing."), todo.index("**For this engagement:**"))
            self.assertLess(todo.index("**For this engagement:**"), todo.index(NOTE))
            self.assertIn("Where this note and the steps above disagree, follow this note", todo)
        plain = self.files(model([_item("datetime-now-usage", "container-local-timezone")]))
        self.assertNotIn("For this engagement", plain[engines.COPILOT][".github/upgrades/skills/applying-container-local-timezone.md"])

    def test_the_conventions_are_in_the_top_level_instructions_and_the_design_questions_leave_them_alone(self):
        flagged = _item("wcf-service", "wcf-service-rest-rewrite")
        flagged["resolution"]["confirm_design"] = True
        m = model([flagged])
        m["engagement"]["conventions"] = CONVENTIONS
        files = self.files(m)
        for text in (files[engines.COPILOT][".github/copilot-instructions.md"], files[engines.CLAUDE][claude.instructions_path(m)]):
            self.assertIn("## This engagement's conventions", text)
            self.assertIn(CONVENTIONS, text)
            self.assertIn("nor about anything this engagement's conventions decide", " ".join(text.split()))
        none = self.files(model([flagged]))
        self.assertNotIn("This engagement's conventions", none[engines.COPILOT][".github/copilot-instructions.md"])

    def test_a_note_does_not_stand_in_for_missing_master_guidance(self):
        item = _item("encoding-default", "explicit-utf8", steps=False)
        item["resolution"]["engagement_note"] = NOTE
        m = model([item])
        self.assertTrue(any(x["missing"] == "resolution" and x["item"] == "encoding-default" for x in render.without_guidance(m)))
        self.assertNotIn(".github/upgrades/skills/applying-explicit-utf8.md", render.render(m))
        self.assertTrue(any("has no instruction yet" in d for d in render.incomplete(m)["details"]))

    def test_a_resolution_without_a_phase_says_phase_not_set(self):
        item = _item("datetime-now-usage", "container-local-timezone")
        item["resolution"]["phase"] = None
        m = model([item])
        files = self.files(m)
        work = files[engines.COPILOT][".github/upgrades/skills/applying-container-local-timezone.md"]
        self.assertIn("Phase not set in the catalog for this approach: placed with phase 5", work)
        plan = files[engines.CLAUDE][claude.instructions_path(m)]
        self.assertIn("(phase not set: placed with phase 5)", plan)
        self.assertIn("phase not set: placed with phase 5", files[engines.COPILOT][".github/platform-inputs/decision-sheet.md"])
        self.assertTrue(any("has no phase set in the catalog" in d for d in render.incomplete(m)["details"]))
        item["resolution"]["phase"] = 5
        self.assertFalse(any("phase" in d for d in (render.incomplete(model([item])) or {}).get("details", [])))


if __name__ == "__main__":
    unittest.main()
