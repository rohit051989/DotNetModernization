"""Signal index, clearing decision fields, and moving the default resolution —
28-ITEM-AND-CONVERSION-MODEL.md Parts F and H.

stdlib unittest; every test runs in one rolled-back transaction, so the
handlers' commits become savepoints and nothing persists. Needs the database
migrated and seeded (`python -m app.seed`).

Run from backend/:  python -m unittest tests.test_catalog_governance -v
"""

import datetime
import unittest
from unittest import mock

from fastapi import HTTPException, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.db import engine
from tests.support import TEST_ENGAGEMENT_ID, ensure_test_engagement
from app.items import schemas as s
from app.routers import catalog_items, item_decisions, signal_registry


class GovernanceTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.outer = self.connection.begin()
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")
        ensure_test_engagement(self.db)

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.connection.close()

    def defaults(self, item_id):
        self.db.expire_all()
        return sorted(
            r.id for r in self.db.query(models.ItemResolution).filter_by(item_id=item_id, is_default=True, deleted_at=None)
        )


class SignalIndexTests(GovernanceTestCase):
    def index(self, referenced=None):
        # Called directly, so pass the query parameter explicitly: its
        # FastAPI default is a Query() marker, not None.
        return {r["name"]: r for r in signal_registry.get_signal_index(referenced=referenced, db=self.db)}

    def test_every_signal_is_listed_with_its_references(self):
        index = self.index()
        registered = self.db.query(models.SignalRegistryEntry).count()
        self.assertGreaterEqual(len(index), registered)
        referenced = {n for n, r in index.items() if r["referenced"]}
        self.assertEqual(set(self.index(referenced=True)), referenced)
        self.assertEqual(set(self.index(referenced=False)), set(index) - referenced)

    def test_usage_distinguishes_match_none_and_occurrence_source(self):
        index = self.index()
        sink = {r["item_id"]: r["usages"] for r in index["SERILOG_FILE_SINK_CONFIG"]["referenced_by"]}
        self.assertEqual(sink["serilog-file-sink"], ["match", "occurrence_source"])
        # A Dockerfile only ever stops an absence item applying.
        docker = index["DOCKERFILE_FILE"]
        self.assertEqual(docker["usages"], ["none"])
        self.assertTrue(docker["exclusion_only"])
        self.assertIn("missing-dockerfile", {r["item_id"] for r in docker["referenced_by"]})

    def test_item_lists_its_signals_the_reverse_way(self):
        signals = {x["name"]: x["usages"] for x in catalog_items.list_item_signals("missing-dockerfile", db=self.db)}
        self.assertEqual(signals["DOCKERFILE_FILE"], ["none"])
        self.assertEqual(signals["WEB_APPLICATION_CREATE_BUILDER_ENTRY_POINT"], ["match"])
        # Both directions agree.
        index = self.index()
        for name, usages in signals.items():
            ref = {r["item_id"]: r["usages"] for r in index[name]["referenced_by"]}
            self.assertEqual(ref["missing-dockerfile"], usages)


class ClearingDecisionFieldsTests(GovernanceTestCase):
    def upsert(self, body: dict):
        return item_decisions.upsert_item_decision(
            TEST_ENGAGEMENT_ID, "msmq-usage", s.EngagementDecisionUpsert.model_validate(body), Response(), db=self.db
        )

    def test_moving_back_to_the_default_can_shed_the_forcing_perspective(self):
        approved = dict(
            status="approved", rationale="broker already runs Kafka", approver_name="A. Approver",
            decision_date=datetime.date(2026, 9, 30).isoformat(),
        )
        first = self.upsert({**approved, "resolution_id": "migrate-to-message-broker",
                             "forcing_perspective": "EVOLUTION", "forcing_rationale": "MSMQ has no Linux future"})
        self.assertEqual(first.forcing_perspective, "EVOLUTION")

        # Omitted fields are kept...
        kept = self.upsert({"evaluation_notes": "reviewed"})
        self.assertEqual((kept.forcing_perspective, kept.forcing_rationale), ("EVOLUTION", "MSMQ has no Linux future"))

        # ...explicit nulls are cleared.
        cleared = self.upsert({"resolution_id": "msmq-usage-remain-windows-hosted",
                               "forcing_perspective": None, "forcing_rationale": None})
        self.assertIsNone(cleared.forcing_perspective)
        self.assertIsNone(cleared.forcing_rationale)
        self.assertEqual(cleared.resolution_id, "msmq-usage-remain-windows-hosted")

    def test_resolution_and_date_can_be_cleared_on_a_pending_decision(self):
        self.upsert({"resolution_id": "migrate-to-message-broker", "decision_date": "2026-09-30"})
        cleared = self.upsert({"resolution_id": None, "decision_date": None})
        self.assertIsNone(cleared.resolution_id)
        self.assertIsNone(cleared.decision_date)

    def test_clearing_what_an_approval_needs_is_rejected(self):
        self.upsert(dict(status="approved", resolution_id="migrate-to-message-broker", rationale="r",
                         approver_name="A", decision_date="2026-09-30",
                         forcing_perspective="EVOLUTION", forcing_rationale="f"))
        with self.assertRaises(HTTPException) as ctx:
            self.upsert({"forcing_perspective": None})
        self.assertEqual(ctx.exception.status_code, 422)

    def test_status_cannot_be_null(self):
        with self.assertRaises(ValueError):
            s.EngagementDecisionUpsert.model_validate({"status": None})


class MakeDefaultTests(GovernanceTestCase):
    ITEM = "system-drawing-common"

    def test_moves_the_default_in_one_call(self):
        self.assertEqual(self.defaults(self.ITEM), ["imagesharp-replacement"])
        catalog_items.make_default(self.ITEM, "skiasharp-replacement", db=self.db)
        self.assertEqual(self.defaults(self.ITEM), ["skiasharp-replacement"])

    def test_a_failure_between_the_two_statements_changes_nothing(self):
        """Unset succeeds, set fails: the transaction rolls back and the old
        default stands. No moment with no default is ever committed."""
        real_flush = self.db.flush
        calls = {"n": 0}

        def failing_flush(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:  # after the unset, before the set lands
                raise RuntimeError("simulated failure mid-move")
            return real_flush(*args, **kwargs)

        savepoint = self.db.begin_nested()
        with mock.patch.object(self.db, "flush", side_effect=failing_flush):
            with self.assertRaises(RuntimeError):
                catalog_items.make_default(self.ITEM, "skiasharp-replacement", db=self.db)
        savepoint.rollback()
        self.assertEqual(self.defaults(self.ITEM), ["imagesharp-replacement"])

    def test_deprecated_or_deleted_resolution_cannot_become_default(self):
        target = self.db.get(models.ItemResolution, "skiasharp-replacement")
        target.status = "deprecated"
        self.db.flush()
        with self.assertRaises(HTTPException) as ctx:
            catalog_items.make_default(self.ITEM, "skiasharp-replacement", db=self.db)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self.defaults(self.ITEM), ["imagesharp-replacement"])

    def test_database_refuses_a_second_default(self):
        """uq_item_resolutions_one_default: guaranteed by the database, not
        only by the endpoint."""
        second = self.db.get(models.ItemResolution, "skiasharp-replacement")
        second.is_default = True
        with self.assertRaises(IntegrityError):
            self.db.flush()


if __name__ == "__main__":
    unittest.main()
