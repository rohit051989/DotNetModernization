"""Item catalog: readiness, detection validation and decisions —
28-ITEM-AND-CONVERSION-MODEL.md Parts C to H, against its acceptance
criteria.

Uses stdlib unittest, same as the other backend tests. Route handlers are
plain functions, so they are called directly with a session rather than
through an HTTP client (no httpx dependency). Every test runs inside one
outer transaction that is rolled back, so the handlers' own commits become
savepoints and nothing persists. Needs the database migrated and seeded
(`python -m app.seed`) so the 91 step 3 signals are registered.

Run from backend/:  python -m unittest tests.test_item_catalog -v
"""

import datetime
import unittest

from fastapi import HTTPException, Response
from sqlalchemy.orm import Session

from app import models
from app.db import engine
from tests.support import TEST_ENGAGEMENT_ID, TEST_NON_LINUX_ENGAGEMENT_ID, ensure_non_linux_engagement, ensure_test_engagement
from app.items import schemas as s
from app.routers import catalog_items, item_decisions, signal_registry

# Test-only names: real anticipated signals (e.g. SERILOG_FILE_SINK_CONFIG)
# are registered by the seed, so tests must not reuse them.
WIN_SVC = "T_WIN_SVC_INVOCATION"
FILE_SINK = "T_FILE_SINK_CONFIG"
UNUSED_READY = "FUNCTION_NAME_ATTRIBUTE"  # ready, and referenced by no seeded item


class ItemCatalogTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.outer = self.connection.begin()
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")
        ensure_test_engagement(self.db)

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.connection.close()

    # ---- helpers ----

    def assert_http(self, expected_status: int, code: str, fn, *args, **kwargs) -> HTTPException:
        with self.assertRaises(HTTPException) as ctx:
            fn(*args, **kwargs)
        self.assertEqual(ctx.exception.status_code, expected_status)
        codes = [d.get("code") for d in ctx.exception.detail]
        self.assertIn(code, codes, ctx.exception.detail)
        return ctx.exception

    def create_item(self, item_id: str, scope: str, detection: dict, category: str = "hosting"):
        payload = s.CatalogItemCreate(id=item_id, name=item_id, scope=scope, category=category, detection=detection)
        return catalog_items.create_item(payload, db=self.db)

    def declare(self, name: str, status: str, emits: list[str]):
        return signal_registry.upsert_extractor(
            name, s.ExtractorDeclaration(status=status, emits=emits), db=self.db
        )

    def register_signal(self, name: str, extractor: str, evidence_kind: str = "FILE"):
        payload = s.SignalRegistration(
            name=name,
            category="CONFIGURATION_INDICATOR",
            type="CONFIG_ELEMENT",
            extractor=extractor,
            evidence_kind=evidence_kind,
            signal_introduced_in_version="9.9.0",
        )
        return signal_registry.register_signal(payload, db=self.db)


class DetectionValidationTests(ItemCatalogTestCase):
    def test_occurrence_scope_without_occurrence_source_is_rejected(self):
        self.assert_http(
            422, "OCCURRENCE_SOURCE_REQUIRED",
            self.create_item, "t-occ", "occurrence", {"match": {"all": [{"signal": {"name": "SVC_FILE"}}]}},
        )

    def test_application_scope_with_occurrence_source_is_rejected(self):
        self.assert_http(
            422, "OCCURRENCE_SOURCE_NOT_ALLOWED",
            self.create_item, "t-app", "application",
            {"match": {"all": [{"signal": {"name": "SVC_FILE"}}]}, "occurrence_source": {"signal": "SVC_FILE"}},
        )

    def test_occurrence_source_must_appear_in_match(self):
        self.assert_http(
            422, "OCCURRENCE_SOURCE_NOT_IN_MATCH",
            self.create_item, "t-occ", "occurrence",
            {"match": {"all": [{"signal": {"name": "SVC_FILE"}}]}, "occurrence_source": {"signal": "ASPX_FILE"}},
        )

    def test_occurrence_source_in_none_group_does_not_count(self):
        self.assert_http(
            422, "OCCURRENCE_SOURCE_NOT_IN_MATCH",
            self.create_item, "t-occ", "occurrence",
            {"match": {"none": [{"signal": {"name": "SVC_FILE"}}]}, "occurrence_source": {"signal": "SVC_FILE"}},
        )

    def test_supporting_group_and_weights_are_not_in_the_grammar(self):
        self.assert_http(
            422, "INVALID_DETECTION",
            self.create_item, "t-app", "application",
            {"match": {"supporting": [{"signal": {"name": "SVC_FILE"}, "weight": 10}]}},
        )
        self.assert_http(
            422, "INVALID_DETECTION",
            self.create_item, "t-app", "application",
            {"match": {"none": [{"signal": {"name": "SVC_FILE"}, "penalty": 5}]}},
        )

    def test_state_cannot_be_supplied(self):
        with self.assertRaises(ValueError):
            s.CatalogItemCreate(
                id="t-app", name="x", scope="application", category="hosting", detection={}, state="ready"
            )

    def test_rule_ids_are_backfilled_positionally(self):
        result = self.create_item("t-app", "application", {"match": {"any": [{"signal": {"name": "SVC_FILE"}}]}})
        self.assertEqual(result.item.detection["match"]["any"][0]["id"], "any[0]")


class ReadinessTests(ItemCatalogTestCase):
    def test_item_on_registered_signals_is_ready(self):
        result = self.create_item("t-app", "application", {"match": {"all": [{"signal": {"name": "SVC_FILE"}}]}})
        self.assertEqual(result.item.state, "ready")
        self.assertIsNone(result.item.state_reason)

    def test_metadata_only_item_is_ready(self):
        """Step 2 metadata counts as mapped: step 2 always runs."""
        result = self.create_item("t-app", "application", {"match": {"metadata": [{"field": "outputType", "equals": "Exe"}]}})
        self.assertEqual(result.item.state, "ready")

    def test_item_with_nothing_to_match_is_signal_mapping_pending(self):
        result = self.create_item("t-app", "application", {"match": {}})
        self.assertEqual(result.item.state, "not_ready")
        self.assertEqual(result.item.state_reason["reason_code"], "signal_mapping_pending")

    def test_planned_signal_on_implemented_extractor_promotes_when_moved_to_emits(self):
        current = self.db.get(models.Extractor, "ConfigurationExtractor")
        emits = [n for n in current.emits]
        planned = [n for n in current.planned_emits if n != "T_PLANNED_CONFIG"]
        signal_registry.upsert_extractor(
            "ConfigurationExtractor",
            s.ExtractorDeclaration(status="implemented", emits=emits, planned_emits=[*planned, "T_PLANNED_CONFIG"]),
            db=self.db,
        )
        self.register_signal("T_PLANNED_CONFIG", "ConfigurationExtractor")
        item = self.create_item(
            "t-occ", "occurrence",
            {"match": {"all": [{"signal": {"name": "T_PLANNED_CONFIG"}}]}, "occurrence_source": {"signal": "T_PLANNED_CONFIG"}},
            category="configuration",
        ).item
        self.assertEqual(item.state, "not_ready")
        self.assertEqual(item.state_reason["blocking_signals"][0]["reason_code"], "extractor_not_implemented")

        moved = signal_registry.upsert_extractor(
            "ConfigurationExtractor",
            s.ExtractorDeclaration(status="implemented", emits=[*emits, "T_PLANNED_CONFIG"], planned_emits=planned),
            db=self.db,
        )
        self.assertIn(("t-occ", "ready"), [(c.item_id, c.to) for c in moved.propagation.items_changed])

    def test_signal_cannot_be_both_emitted_and_planned(self):
        with self.assertRaises(ValueError):
            s.ExtractorDeclaration(status="implemented", emits=["X"], planned_emits=["X"])

    def test_unregistered_signal_is_accepted_and_keeps_item_not_ready(self):
        result = self.create_item("t-app", "application", {"match": {"any": [{"signal": {"name": WIN_SVC}}]}})
        self.assertEqual(result.item.state, "not_ready")
        self.assertEqual(result.item.state_reason["blocking_signals"][0]["reason_code"], "signal_not_registered")
        self.assertTrue(result.warnings)

    def test_signal_nobody_claims_is_a_hard_error(self):
        # The expected extractor exists but does not declare the signal.
        self.assert_http(422, "SIGNAL_UNCLAIMED", self.register_signal, FILE_SINK, "ConfigurationExtractor")
        # The expected extractor does not exist at all.
        self.assert_http(422, "SIGNAL_UNCLAIMED", self.register_signal, FILE_SINK, "LoggingExtractor")

    def test_extractor_may_not_drop_a_registered_signal(self):
        current = self.db.get(models.Extractor, "EntryPointExtractor")
        self.assert_http(422, "SIGNAL_UNCLAIMED", self.declare, "EntryPointExtractor", "implemented", current.emits[1:])

    def test_item_promotes_when_last_blocking_signal_becomes_ready(self):
        """Part C: nobody edits the item. Two blocking signals from two
        planned extractors; the item promotes only when the second lands."""
        self.declare("LoggingExtractor", "planned", [FILE_SINK])
        self.declare("HostingExtractor", "planned", [WIN_SVC])
        self.register_signal(FILE_SINK, "LoggingExtractor")
        self.register_signal(WIN_SVC, "HostingExtractor", evidence_kind="FILE")

        created = self.create_item(
            "t-occ", "occurrence",
            {
                "match": {"all": [{"signal": {"name": FILE_SINK}}, {"signal": {"name": WIN_SVC}}]},
                "occurrence_source": {"signal": FILE_SINK},
            },
            category="logging",
        )
        self.assertEqual(created.item.state, "not_ready")
        blocking = {b["signal"]: b for b in created.item.state_reason["blocking_signals"]}
        self.assertEqual(blocking[FILE_SINK]["reason_code"], "extractor_not_implemented")
        self.assertEqual(blocking[FILE_SINK]["expected_extractor"], "LoggingExtractor")
        version_before = created.item.version

        first = self.declare("LoggingExtractor", "implemented", [FILE_SINK])
        self.assertEqual([c.signal for c in first.propagation.signals_changed], [FILE_SINK])
        self.assertEqual(first.propagation.items_changed, [])  # still blocked on WIN_SVC
        self.assertEqual(self.db.get(models.CatalogItem, "t-occ").state, "not_ready")

        second = self.declare("HostingExtractor", "implemented", [WIN_SVC])
        self.assertEqual([(c.item_id, c.to) for c in second.propagation.items_changed], [("t-occ", "ready")])
        item = self.db.get(models.CatalogItem, "t-occ")
        self.assertEqual(item.state, "ready")
        self.assertEqual(item.version, version_before)  # promotion is not an edit

        # And it drops back when an extractor is withdrawn.
        third = self.declare("HostingExtractor", "planned", [WIN_SVC])
        self.assertEqual([(c.item_id, c.to) for c in third.propagation.items_changed], [("t-occ", "not_ready")])

    def test_registering_a_signal_unblocks_items_waiting_on_its_name(self):
        self.create_item("t-app", "application", {"match": {"any": [{"signal": {"name": WIN_SVC}}]}})
        self.declare("HostingExtractor", "implemented", [WIN_SVC])
        result = self.register_signal(WIN_SVC, "HostingExtractor")
        self.assertEqual([(c.item_id, c.to) for c in result.propagation.items_changed], [("t-app", "ready")])


class CoverageTests(ItemCatalogTestCase):
    def test_backlog_orders_extractors_by_items_unblocked(self):
        self.declare("LoggingExtractor", "planned", [FILE_SINK])
        self.register_signal(FILE_SINK, "LoggingExtractor")
        self.create_item(
            "t-occ-1", "occurrence",
            {"match": {"all": [{"signal": {"name": FILE_SINK}}]}, "occurrence_source": {"signal": FILE_SINK}},
            category="logging",
        )
        self.create_item(
            "t-occ-2", "occurrence",
            {"match": {"all": [{"signal": {"name": FILE_SINK}}]}, "occurrence_source": {"signal": FILE_SINK}},
            category="logging",
        )
        self.create_item("t-app", "application", {"match": {"any": [{"signal": {"name": WIN_SVC}}]}})

        backlog = signal_registry.extractor_backlog(db=self.db).entries
        mine = [e for e in backlog if e.expected_extractor in ("LoggingExtractor", None)]
        self.assertEqual(mine[0].expected_extractor, "LoggingExtractor")
        self.assertEqual(mine[0].items_unblocked, ["t-occ-1", "t-occ-2"])

        coverage = signal_registry.item_coverage(db=self.db)
        by_id = {e.item_id: e for e in coverage.not_ready}
        self.assertEqual(by_id["t-occ-1"].blocking_by_extractor, {"LoggingExtractor": [FILE_SINK]})
        self.assertEqual(by_id["t-app"].blocking_by_extractor, {"(none declared)": [WIN_SVC]})

    def test_signal_coverage_lists_ready_signals_no_item_references(self):
        before = {u.name for u in signal_registry.signal_coverage(db=self.db).unreferenced}
        self.assertIn(UNUSED_READY, before)
        self.create_item("t-app", "application", {"match": {"all": [{"signal": {"name": UNUSED_READY}}]}})
        after = {u.name for u in signal_registry.signal_coverage(db=self.db).unreferenced}
        self.assertNotIn(UNUSED_READY, after)


class DecisionTests(ItemCatalogTestCase):
    def setUp(self):
        super().setUp()
        self.create_item("t-app", "application", {"match": {"all": [{"signal": {"name": "SVC_FILE"}}]}})
        for rid, impact, linux in (("t-low", "low", True), ("t-high", "high", True), ("t-win", "low", False)):
            catalog_items.create_resolution(
                "t-app",
                s.ResolutionCreate(id=rid, name=rid, consumer_impact=impact, effort="low", linux_compatible=linux),
                db=self.db,
            )

    def upsert(self, engagement: str, **fields):
        return item_decisions.upsert_item_decision(
            engagement, "t-app", s.EngagementDecisionUpsert(**fields), Response(), db=self.db
        )

    def approved(self, **fields):
        return dict(
            status="approved", rationale="because", approver_name="A. Approver",
            decision_date=datetime.date(2026, 9, 29), **fields,
        )

    def test_higher_impact_choice_requires_forcing_perspective(self):
        self.assert_http(
            422, "FORCING_PERSPECTIVE_AND_RATIONALE_REQUIRED",
            self.upsert, TEST_ENGAGEMENT_ID, **self.approved(resolution_id="t-high"),
        )
        # The perspective alone is not enough: it is a pair (spec 25 A1).
        err = self.assert_http(
            422, "FORCING_PERSPECTIVE_AND_RATIONALE_REQUIRED",
            self.upsert, TEST_ENGAGEMENT_ID, **self.approved(resolution_id="t-high", forcing_perspective="SECURITY"),
        )
        self.assertEqual([d["field"] for d in err.detail], ["forcing_rationale"])
        ok = self.upsert(
            TEST_ENGAGEMENT_ID,
            **self.approved(resolution_id="t-high", forcing_perspective="SECURITY", forcing_rationale="binding unsupported"),
        )
        self.assertEqual((ok.forcing_perspective, ok.forcing_rationale), ("SECURITY", "binding unsupported"))

    def test_in_review_and_candidates_are_kept(self):
        d = self.upsert(TEST_ENGAGEMENT_ID, resolution_id="t-low", status="in_review", candidates_considered=["t-low", "t-high"])
        self.assertEqual((d.status, d.candidates_considered), ("in_review", ["t-low", "t-high"]))

    def test_lowest_impact_choice_needs_no_forcing_perspective(self):
        ok = self.upsert(TEST_ENGAGEMENT_ID, **self.approved(resolution_id="t-low"))
        self.assertEqual(ok.status, "approved")

    def test_approval_requires_selection_and_approver(self):
        err = self.assert_http(422, "APPROVAL_REQUIRES_SELECTION", self.upsert, TEST_ENGAGEMENT_ID, status="approved")
        self.assertIn("APPROVAL_REQUIRES_APPROVER", [d["code"] for d in err.detail])

    def test_linux_incompatible_resolution_warns_on_linux_engagement_only(self):
        linux = self.upsert(TEST_ENGAGEMENT_ID, resolution_id="t-win")  # target_platform: Linux / OpenShift
        self.assertEqual(len(linux.warnings), 1)
        ensure_non_linux_engagement(self.db)
        aks = self.upsert(TEST_NON_LINUX_ENGAGEMENT_ID, resolution_id="t-win")  # Azure Kubernetes Service
        self.assertEqual(aks.warnings, [])

    def test_resolution_from_another_item_is_rejected(self):
        self.create_item("t-other", "application", {"match": {"all": [{"signal": {"name": "ASPX_FILE"}}]}})
        catalog_items.create_resolution(
            "t-other", s.ResolutionCreate(id="t-other-r", name="r", consumer_impact="low", effort="low"), db=self.db
        )
        self.assert_http(422, "RESOLUTION_WRONG_ITEM", self.upsert, TEST_ENGAGEMENT_ID, resolution_id="t-other-r")

    def test_one_default_per_item(self):
        catalog_items.create_resolution(
            "t-app", s.ResolutionCreate(id="t-d1", name="d1", consumer_impact="low", effort="low", is_default=True),
            db=self.db,
        )
        self.assert_http(
            409, "DEFAULT_ALREADY_SET", catalog_items.create_resolution, "t-app",
            s.ResolutionCreate(id="t-d2", name="d2", consumer_impact="low", effort="low", is_default=True),
            db=self.db,
        )

    def test_item_with_live_decision_cannot_be_soft_deleted(self):
        self.upsert(TEST_ENGAGEMENT_ID, resolution_id="t-low")
        self.assert_http(409, "REFERENCED_BY_DECISIONS", catalog_items.delete_item, "t-app", db=self.db)


class OccurrenceTableTests(ItemCatalogTestCase):
    def test_file_path_only_on_found_occurrence_rows(self):
        from sqlalchemy.exc import IntegrityError

        project = self.db.query(models.Project).first()
        if project is None:
            self.skipTest("no projects discovered in this database")
        self.create_item("t-app", "application", {"match": {"all": [{"signal": {"name": "SVC_FILE"}}]}})
        row = models.ItemOccurrence(
            repository_id=project.repository_id, project_id=project.id, item_id="t-app", scope="application",
            file_path="x/y.cs", signal_registry_version="1.3.0", detection_state="found",
        )
        self.db.add(row)
        with self.assertRaises(IntegrityError):
            self.db.flush()



class PatternMigrationTests(ItemCatalogTestCase):
    """Part Q. Needs the migration already applied (python -m app.seed runs it)."""

    def test_revert_then_migrate_round_trips(self):
        from app.items import pattern_migration

        if self.db.get(models.CatalogItem, "windows-service") is None:
            self.skipTest("pattern migration not applied in this database")
        before = {i.id: (i.detection, i.state) for i in self.db.query(models.CatalogItem).filter(
            models.CatalogItem.id.in_(pattern_migration.MIGRATED))}

        # Once step 6 has written occurrences for migrated items, revert must
        # refuse: work is built on them. Clear them (inside this rolled-back
        # transaction only) to exercise the round trip itself.
        occurrences = self.db.query(models.ItemOccurrence).filter(
            models.ItemOccurrence.item_id.in_(pattern_migration.MIGRATED))
        if occurrences.count():
            self.assert_http(409, "REVERT_BLOCKED", pattern_migration.revert, self.db)
            occurrences.delete(synchronize_session=False)
            self.db.flush()

        reverted = pattern_migration.revert(self.db)
        self.assertEqual(reverted["items"], len(pattern_migration.MIGRATED))
        self.assertIsNone(self.db.get(models.CatalogItem, "windows-service"))
        # The source tables are untouched by either direction.
        self.assertIsNotNone(self.db.get(models.Pattern, "windows-service"))

        report = pattern_migration.migrate(self.db)
        self.assertEqual(len(report["items"]), len(pattern_migration.MIGRATED))
        after = {i.id: (i.detection, i.state) for i in self.db.query(models.CatalogItem).filter(
            models.CatalogItem.id.in_(pattern_migration.MIGRATED))}
        self.assertEqual(before, after)

    def test_every_migrated_item_is_application_scope_without_supporting(self):
        from app.items import pattern_migration

        for item_id in pattern_migration.MIGRATED:
            item = self.db.get(models.CatalogItem, item_id)
            if item is None:
                self.skipTest("pattern migration not applied in this database")
            self.assertEqual(item.scope, "application")
            self.assertNotIn("occurrence_source", item.detection)
            self.assertNotIn("supporting", item.detection["match"])
            self.assertEqual(item.excluded_roles, [])

    def test_forcing_pairs_survive(self):
        decisions = self.db.query(models.EngagementDecision).filter(
            models.EngagementDecision.forcing_perspective.isnot(None)).all()
        for decision in decisions:
            record = self.db.get(models.DecisionRecord, decision.id)
            self.assertEqual(
                (decision.forcing_perspective, decision.forcing_rationale),
                (record.forcing_perspective, record.forcing_rationale),
            )

    def test_revert_refuses_once_work_is_built_on_top(self):
        from app.items import pattern_migration

        if self.db.get(models.CatalogItem, "windows-service") is None:
            self.skipTest("pattern migration not applied in this database")
        catalog_items.create_resolution(
            "windows-service", s.ResolutionCreate(id="t-added-later", name="later", consumer_impact="low", effort="low"),
            db=self.db,
        )
        self.assert_http(409, "REVERT_BLOCKED", pattern_migration.revert, self.db)


class AuthoredItemTests(unittest.TestCase):
    """catalog_items.yaml: the authored (not migrated) master catalog."""

    OCCURRENCE = {
        "serilog-file-sink", "hardcoded-windows-path", "encoding-default", "datetime-now-usage",
        "system-drawing-common", "windows-auth-connection-string", "registry-access",
        "directory-services-usage", "sensitive-config-key",
    }
    ABSENCE = {"missing-dockerfile", "missing-health-endpoint", "missing-ocp4-manifests"}
    HOSTING = {"windows-service-hosting", "modern-worker-service"}
    APPLICATION_WORK = {"wcf-nettcp-client", "msmq-usage", "asmx-service"}
    # Hard Linux blockers: "stay on Windows" is a legitimate answer and must
    # be on the menu, Linux-incompatible, so the decision warning fires.
    LINUX_BLOCKERS = {"registry-access", "directory-services-usage", "msmq-usage"}

    # Precedence chains, most specific first (docs/28 Part E "Overlapping
    # items"). Each later item must exclude every positive signal of each
    # earlier one. Add a chain here when two items become alternatives.
    PRECEDENCE_CHAINS = [
        ["windows-service-hosting", "modern-worker-service", "console-batch-job"],
    ]

    def _items(self):
        from app.seed.seed_data import _load

        return {data["id"]: data for data in _load("catalog_items.yaml")["items"]}

    def test_every_authored_item_has_a_menu_and_no_computed_state(self):
        items = self._items()
        self.assertEqual(set(items), self.OCCURRENCE | self.ABSENCE | self.HOSTING | self.APPLICATION_WORK)
        for item_id, data in items.items():
            with self.subTest(item=item_id):
                self.assertNotIn("state", data)
                self.assertGreaterEqual(len(data["resolutions"]), 2)
                self.assertEqual(sum(1 for r in data["resolutions"] if r.get("is_default")), 1)

    def test_occurrence_items_project_from_one_signal(self):
        from app.items.detection import validate_detection

        for item_id in self.OCCURRENCE:
            data = self._items()[item_id]
            with self.subTest(item=item_id):
                self.assertEqual(data["scope"], "occurrence")
                detection, _ = validate_detection("occurrence", data["detection"], {})
                self.assertIn("occurrence_source", detection)

    def test_system_drawing_does_not_key_on_the_namespace(self):
        from app.items.detection import referenced_signal_names

        detection = self._items()["system-drawing-common"]["detection"]
        self.assertNotIn("SYSTEM_DRAWING_NAMESPACE", referenced_signal_names(detection))
        self.assertEqual(detection["occurrence_source"]["signal"], "SYSTEM_DRAWING_USAGE")

    def test_absence_items_are_application_scope_none_conditions(self):
        from app.items.detection import validate_detection

        for item_id in self.ABSENCE:
            data = self._items()[item_id]
            with self.subTest(item=item_id):
                self.assertEqual(data["scope"], "application")
                detection, _ = validate_detection("application", data["detection"], {})
                self.assertTrue(detection["match"]["none"])
                self.assertNotIn("occurrence_source", detection)

    def test_resolution_ids_are_globally_unique(self):
        """item_resolutions.id is a global key: a reused id silently merged six
        remain-windows-hosted options into one row before the seed guarded it."""
        from app.db import SessionLocal

        ids = [r["id"] for data in self._items().values() for r in data["resolutions"]]
        self.assertEqual(len(ids), len(set(ids)), sorted({i for i in ids if ids.count(i) > 1}))
        db = SessionLocal()
        try:
            migrated = {row.id for row in db.query(models.TargetStateOption.id)}
        finally:
            db.close()
        self.assertFalse(set(ids) & migrated)

    def test_application_scope_work_items(self):
        from app.items.detection import validate_detection

        for item_id in self.APPLICATION_WORK | self.HOSTING:
            data = self._items()[item_id]
            with self.subTest(item=item_id):
                self.assertEqual(data["scope"], "application")
                detection, _ = validate_detection("application", data["detection"], {})
                self.assertNotIn("occurrence_source", detection)

    def test_linux_blockers_offer_remaining_on_windows(self):
        for item_id in self.LINUX_BLOCKERS:
            with self.subTest(item=item_id):
                stay = [r for r in self._items()[item_id]["resolutions"] if r["id"] == f"{item_id}-remain-windows-hosted"]
                self.assertEqual(len(stay), 1)
                self.assertIs(stay[0]["linux_compatible"], False)
                self.assertFalse(stay[0].get("is_default", False))

    def _detection(self, item_id: str) -> dict:
        """Authored items from the YAML; migrated ones as the migration
        produces them (pattern rules plus AMENDMENTS)."""
        from app.db import SessionLocal
        from app.items.pattern_migration import MIGRATED, item_detection

        if item_id in self._items():
            return self._items()[item_id]["detection"]
        self.assertIn(item_id, MIGRATED)
        db = SessionLocal()
        try:
            return item_detection(db.get(models.Pattern, item_id).detection_rules, item_id)
        finally:
            db.close()

    def test_wcf_nettcp_client_is_exact(self):
        """A project hosting a NetTcp SERVICE while calling an HTTP client must
        not match. The signal set below is exactly what step 3 emits for that
        fixture (pinned by ExtractorBatch2Tests.
        Config_NetTcpServiceWithHttpClient_IsNotANetTcpClient). The item uses
        only `any` over value-exact conditions, so checking each condition
        against it is the whole evaluation; step 6's evaluator will run the
        same case end to end."""
        detection = self._items()["wcf-nettcp-client"]["detection"]
        match = detection["match"]
        self.assertEqual(set(match), {"any"}, "the proof below assumes an any-only match")

        conditions = {(c["signal"]["name"], c["signal"]["value"]["equals"]) for c in match["any"]}
        self.assertEqual(conditions, {
            ("WCF_CLIENT_BINDING_CONFIG", "netTcpBinding"),
            ("WCF_CLIENT_BINDING_USAGE", "System.ServiceModel.NetTcpBinding"),
        })

        nettcp_service_http_client = {
            ("WCF_SERVICE_ENDPOINT_CONFIG", "IOrders"),
            ("WCF_BINDING_CONFIG", "netTcpBinding"),
            ("WCF_BINDING_CONFIG", "basicHttpBinding"),
            ("WCF_CLIENT_ENDPOINT_CONFIG", "ILedger"),
            ("WCF_CLIENT_BINDING_CONFIG", "basicHttpBinding"),
            # svcutil adds the NetTcp package to every client: must not count.
            ("WCF_CLIENT_PACKAGE", "System.ServiceModel.NetTcp"),
        }
        self.assertFalse(conditions & nettcp_service_http_client)

        nettcp_client = {("WCF_CLIENT_BINDING_CONFIG", "netTcpBinding")}
        self.assertTrue(conditions & nettcp_client)

    def test_conversion_ordering_is_recorded_on_both_sides(self):
        items = self._items()
        for first, then in (
            ("windows-auth-connection-string", "sensitive-config-key"),
            ("serilog-file-sink", "hardcoded-windows-path"),
        ):
            with self.subTest(first=first, then=then):
                self.assertIn(f"BEFORE {then}", items[first]["description"])
                self.assertIn(f"AFTER {first}", items[then]["description"])

    def test_windows_service_offers_remaining_on_windows(self):
        """Migrated item: its second option is a migration amendment."""
        from app.items.pattern_migration import AMENDMENTS

        stay = AMENDMENTS["windows-service"]["resolutions"]
        self.assertEqual([r["id"] for r in stay], ["windows-service-remain-windows-hosted"])
        self.assertIs(stay[0]["linux_compatible"], False)
        self.assertIs(stay[0]["is_default"], False)

    def test_precedence_chains_are_mutually_exclusive(self):
        from app.items.detection import positive_signal_names

        for chain in self.PRECEDENCE_CHAINS:
            for i, specific in enumerate(chain):
                specific_signals = positive_signal_names(self._detection(specific)["match"])
                for general in chain[i + 1:]:
                    with self.subTest(specific=specific, general=general):
                        excluded = {c["signal"]["name"] for c in self._detection(general)["match"].get("none", [])}
                        self.assertTrue(
                            specific_signals <= excluded,
                            f"{general} must exclude {sorted(specific_signals - excluded)} so it cannot match alongside {specific}",
                        )


if __name__ == "__main__":
    unittest.main()
