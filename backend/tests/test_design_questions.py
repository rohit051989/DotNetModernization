"""Design questions before converting (36-COPILOT-ENHANCED-CONVERSION "Design questions before converting").

- A catalog resolution carries "confirm the design before implementing" (confirm_design), set on the factory
  resolutions that change the design or the architecture, editable by admins with the version check, exported only
  where set.
- For each work item whose chosen resolution carries it, both engines' instructions hold the rule (ask 3 to 5 questions
  per flagged work item, in one round, before changing any code; "use the defaults"; record them in
  CONVERSION-DECISIONS.md) and the list of flagged work items, and no question.
- RUNBOOK.md opens with a line pointing each engine's users to their section, and each section says to expect the
  questions first.
- The verifier reports a gap when a flagged work item was changed and no answer is recorded, and VERIFICATION.md shows
  the answers.

Run from backend/:  python -m unittest tests.test_design_questions -v
"""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models
from app.conversion import gitops
from app.db import engine
from app.engine import convert, engines, paths, verifier
from app.engine.inputs import claude, render
from app.items import baseline, catalog_export
from app.items import schemas as s
from app.routers import catalog_items
from tests.test_baseline_test_ids import _report
from tests.test_engine_inputs import _item, model

FLAGGED = "applying-rest-net10"


def flagged_model() -> dict:
    m = model()
    rest = _item("wcf-iis-servicemodel", "rest-net10", file="src/A/OrderService.svc.cs")
    rest["resolution"]["confirm_design"] = True
    m["items"].append(rest)
    m["vocabulary"]["item_ids"].append("wcf-iis-servicemodel")
    m["vocabulary"]["resolution_ids"].append("rest-net10")
    return m


def _section(text: str) -> str:
    return text.split(render.DESIGN_HEADING, 1)[1].split("\n## ", 1)[0]


class Catalog(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.outer = self.connection.begin()
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.connection.close()

    def test_the_factory_flags_exactly_the_resolutions_that_change_the_design(self):
        listed = set(yaml.safe_load(baseline.CONFIRM_DESIGN_FILE.read_text(encoding="utf-8"))["resolutions"])
        rows = {r.id: r.confirm_design for r in self.db.query(models.ItemResolution)}
        self.assertEqual(listed - set(rows), set(), "every listed resolution exists")
        self.assertEqual({rid for rid, flag in rows.items() if flag}, listed)
        self.assertTrue(rows["rest-net10"] and rows["wcf-service-rest-rewrite"])
        self.assertFalse(rows["corewcf-net10"] or rows["utc-everywhere"])

    def test_the_export_carries_it_only_where_set(self):
        files = catalog_export.export_files(self.db)
        self.assertIn("confirm_design: true", files["wcf-iis-servicemodel.yaml"])
        self.assertNotIn("confirm_design", files["datetime-now-usage.yaml"])

    def test_an_admin_sets_and_clears_it_with_the_version_check(self):
        item = self.db.get(models.CatalogItem, "datetime-now-usage")
        r = self.db.get(models.ItemResolution, "utc-everywhere")
        payload = s.ResolutionWrite(name=r.name, description=r.description, target_description=r.target_description,
                                    consumer_impact=r.consumer_impact, effort=r.effort, is_default=r.is_default,
                                    linux_compatible=r.linux_compatible, container_ready=r.container_ready,
                                    notes=r.notes, status=r.status, confirm_design=True)
        version = str(item.edit_version)
        out = catalog_items.update_resolution("datetime-now-usage", "utc-everywhere", payload, db=self.db, if_match=version)
        self.assertTrue(out.confirm_design)
        # A copy made before that edit is stale: refused.
        with self.assertRaises(HTTPException) as stale:
            catalog_items.update_resolution("datetime-now-usage", "utc-everywhere", payload, db=self.db, if_match=version)
        self.assertEqual(stale.exception.status_code, 409)
        # Omitted: unchanged. Then cleared.
        self.db.refresh(item)
        out = catalog_items.update_resolution("datetime-now-usage", "utc-everywhere",
                                              payload.model_copy(update={"confirm_design": None}), db=self.db,
                                              if_match=str(item.edit_version))
        self.assertTrue(out.confirm_design)
        self.db.refresh(item)
        out = catalog_items.update_resolution("datetime-now-usage", "utc-everywhere",
                                              payload.model_copy(update={"confirm_design": False}), db=self.db,
                                              if_match=str(item.edit_version))
        self.assertFalse(out.confirm_design)

    def test_a_row_edited_in_the_ui_is_never_changed_by_the_seed(self):
        r = self.db.get(models.ItemResolution, "corewcf-net10")
        r.confirm_design = True                                          # an admin's edit
        self.db.flush()
        self.assertEqual(baseline.edit_state(r), "edited")

    def test_only_admins_may_change_it(self):
        from app.auth import actor, policy

        developer = actor.Actor(user_id=None, login="dev", name="Dev", role="developer", hostname="pc-1")
        path = "/api/catalog/items/{item_id}/resolutions/{resolution_id}"
        self.assertIn("Only an admin may do this", policy.refusal(self.db, developer, "PUT", path, {}))
        admin = actor.Actor(user_id=None, login="adm", name="Adm", role="admin", hostname="pc-1")
        self.assertIsNone(policy.refusal(self.db, admin, "PUT", path, {}))


class Inputs(unittest.TestCase):
    def setUp(self):
        self.copilot = render.render(flagged_model(), engines.COPILOT)
        self.claude = render.render(flagged_model(), engines.CLAUDE)

    def test_both_engines_list_the_flagged_work_items_and_the_rule(self):
        for text in (self.copilot[paths.COPILOT_INSTRUCTIONS], self.claude[claude.INSTRUCTIONS]):
            section = _section(text)
            self.assertEqual(render.design_items_in(text), [FLAGGED])
            self.assertIn(f"- `{FLAGGED}`: Rest net10 (Wcf iis servicemodel)", section)
            for rule in ("before changing any code", "3 to 5 questions for each work item above, all of them in one "
                         "message", "names the default you will use", "Do not ask about anything these instructions",
                         "\"Use the defaults\" is an answer", "without stopping again for these questions",
                         f"`{paths.DESIGN_DECISIONS}`", "`| Question | Default | Answer |`",
                         "Commit it with the first work item"):
                self.assertIn(rule, " ".join(section.split()), rule)
            # The rule only: no question is written into the instructions.
            self.assertNotIn("?", section)
        self.assertIn("ask the developer the questions \"Design questions before converting\" below describes",
                      self.claude[claude.INSTRUCTIONS])
        # The same text for both, but for the mechanics table.
        self.assertEqual(claude.neutral(_section(self.claude[claude.INSTRUCTIONS])), _section(self.copilot[paths.COPILOT_INSTRUCTIONS]))

    def test_without_a_flagged_work_item_there_is_no_section(self):
        files = render.render(model(), engines.CLAUDE)
        self.assertNotIn(render.DESIGN_HEADING, files[claude.INSTRUCTIONS])
        self.assertNotIn("Design questions", files[claude.INSTRUCTIONS])
        self.assertEqual(render.design_items_in(render.render(model())[paths.COPILOT_INSTRUCTIONS]), [])


class Runbook(unittest.TestCase):
    def test_it_opens_with_each_engines_section_and_says_to_expect_the_questions(self):
        record = {"repository": "r", "branch": "conversion/1", "worktree": "D:/runs/wt", "baseline": "b" * 40,
                  "head": "c" * 40, "platform": {}, "targetFramework": "net10.0", "engagement": "e", "number": 1,
                  "engines": {e: {"prepared": True, "usable": True} for e in engines.ENGINES}}
        with mock.patch.object(convert, "design_work_items", return_value=[FLAGGED]), \
                mock.patch.object(convert, "work_item_names", return_value=[FLAGGED]), \
                mock.patch.object(convert, "opening_for", return_value="first message"), \
                mock.patch.object(convert.instrument, "describe", return_value="platform x"):
            text = convert.render_runbook(record)
        self.assertEqual(text.splitlines()[2], "**GitHub Copilot users: follow section A. Claude Code users: follow section B.**")
        self.assertEqual(text.count("**Expect questions first.**"), 2)                 # sections A and B
        self.assertIn(f"about how to implement each of these work items, all in one round: `{FLAGGED}`", text)
        self.assertIn("`Use the defaults.`", text)
        with mock.patch.object(convert, "design_work_items", return_value=[]):
            self.assertEqual(convert.runbook_design(record), "")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@client-a.example", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


DECISIONS = f"""# Design decisions

## `{FLAGGED}`

| Question | Default | Answer |
|---|---|---|
| Expose an OpenAPI description? | Yes, at /swagger | Use the defaults |
| Logging | ILogger to standard output | Use the defaults |
| Validate inputs with data annotations? | Yes | No: keep the service's own checks |
"""


class Verifier(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        _git(self.root, "init", "-q", "-b", "main")
        (self.root / "src").mkdir()
        (self.root / "src" / "OrderService.svc.cs").write_text("class OrderService {}\n", encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-qm", "legacy")
        self.base = _git(self.root, "rev-parse", "HEAD")
        files = render.render(flagged_model())
        for path in (paths.COPILOT_INSTRUCTIONS,):
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text(files[path], encoding="utf-8")
        _git(self.root, "add", "-A")
        subprocess.run(["git", "-C", str(self.root), *gitops.PLATFORM_IDENTITY, "commit", "-qm", "inputs"], check=True)
        self.inputs = _git(self.root, "rev-parse", "HEAD")

    def change(self, with_decisions: bool) -> str:
        (self.root / "src" / "OrderService.svc.cs").write_text("class OrderService { /* REST */ }\n", encoding="utf-8")
        if with_decisions:
            (self.root / paths.DESIGN_DECISIONS).write_text(DECISIONS, encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-qm", f"{FLAGGED}: the service as a REST API")
        return _git(self.root, "rev-parse", "HEAD")

    def test_a_flagged_work_item_changed_without_answers_is_a_gap(self):
        tip = self.change(with_decisions=False)
        check, record = verifier.design_check(self.root, self.inputs, self.base, tip, None)
        self.assertEqual((check["id"], check["state"]), ("design", "gap"))
        self.assertIn(f"no answer to their design questions recorded in {paths.DESIGN_DECISIONS}: {FLAGGED}", check["detail"])
        self.assertEqual(record["missing"], [FLAGGED])
        self.assertEqual(verifier.verdict([check])[0], "PARTLY PROVEN")
        self.assertIn(f"No `{paths.DESIGN_DECISIONS}` on the branch.", verifier.markdown(_report(designDecisions=record)))

    def test_with_the_decisions_file_its_answers_are_in_verification_md(self):
        tip = self.change(with_decisions=True)
        check, record = verifier.design_check(self.root, self.inputs, self.base, tip, None)
        self.assertEqual(check["state"], "pass")
        rows = record["decisions"][FLAGGED]
        self.assertEqual([r["answer"] for r in rows], ["Use the defaults", "Use the defaults", "No: keep the service's own checks"])
        md = verifier.markdown(_report(designDecisions=record))
        self.assertIn("## Design decisions", md)
        self.assertIn(f"### {FLAGGED}", md)
        self.assertIn("| Validate inputs with data annotations? | Yes | No: keep the service's own checks |", md)

    def test_no_check_without_flagged_work_items_and_none_before_a_change(self):
        self.assertEqual(verifier.design_check(self.root, self.base, self.base, self.base, None), (None, None))
        check, _ = verifier.design_check(self.root, self.inputs, self.base, self.inputs, None)
        self.assertEqual(check["state"], "info")

    def test_the_decisions_file_is_a_record_not_a_change(self):
        self.assertTrue(any(paths.DESIGN_DECISIONS.startswith(p) for p in paths.EXCLUDED_FROM_COMPARISON))


if __name__ == "__main__":
    unittest.main()
