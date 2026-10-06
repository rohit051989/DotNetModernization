"""Decision coupling — 28-ITEM-AND-CONVERSION-MODEL.md Part U.

Hermetic: fixture items, resolutions, derivation rows, projects, occurrences
and integration edges, all inside one rolled-back transaction; nothing read
from what the database happens to hold. The authored catalog data is checked
from catalog_items.yaml itself, not from the database."""

import datetime
import unittest
import uuid

from fastapi import Response

from app import models
from app.items import coupling, derivations
from app.items import schemas as s
from app.routers import catalog_items, item_decisions
from tests.support import TEST_ENGAGEMENT_ID
from tests.test_item_detection import DetectionTestCase

# Leading resolution -> dependent -> (action, dependent resolution, applies_to).
# The shape of the authored wcf-service table, on fixture items.
DERIVATIONS = {
    "t-svc-corewcf": {"t-host": ("derive", "t-host-web", "all"), "t-client": ("not_derived", None, "all"),
                      "t-retarget": ("subsume", None, "all")},
    "t-svc-rest": {"t-host": ("derive", "t-host-web", "all"), "t-client": ("derive", "t-client-migrate", "internal_clients"),
                   "t-retarget": ("subsume", None, "all")},
    "t-svc-windows": {"t-host": ("not_derived", None, "all"), "t-client": ("not_derived", None, "all"),
                      "t-retarget": ("not_subsumed", None, "all")},
}


class CouplingFixture(DetectionTestCase):
    """Fixture items, derivations, projects and occurrences; no tests of its own."""

    def setUp(self):
        super().setUp()
        menus = {
            "t-svc": [("t-svc-corewcf", "none"), ("t-svc-rest", "high"), ("t-svc-windows", "none")],
            "t-host": [("t-host-web", "low"), ("t-host-keep", "none")],
            "t-client": [("t-client-migrate", "low"), ("t-client-http", "none")],
            "t-retarget": [("t-retarget-net10", "low"), ("t-retarget-netstandard", "none")],
        }
        for item_id, menu in menus.items():
            catalog_items.create_item(s.CatalogItemCreate(
                id=item_id, name=item_id, scope="application", category="integration",
                detection={"match": {"all": [{"signal": {"name": "SVC_FILE"}}]}}), db=self.db)
            for resolution_id, impact in menu:
                catalog_items.create_resolution(item_id, s.ResolutionCreate(
                    id=resolution_id, name=resolution_id, consumer_impact=impact, effort="low"), db=self.db)
        for resolution_id, dependents in DERIVATIONS.items():
            for dependent, (action, dependent_resolution, applies_to) in dependents.items():
                self.db.add(models.ResolutionDerivation(
                    resolution_id=resolution_id, item_id="t-svc", dependent_item_id=dependent, action=action,
                    dependent_resolution_id=dependent_resolution, applies_to=applies_to, reason=f"{resolution_id} {action} {dependent}"))
        self.service = self.add_project("src/Services/Services.csproj")
        self.host = self.add_project("src/Host/Host.csproj", output_type="Exe")
        self.client = self.add_project("src/Client/Client.csproj", output_type="Exe")
        for project, item_id in ((self.service, "t-svc"), (self.service, "t-retarget"), (self.host, "t-host"), (self.client, "t-client")):
            self.db.add(models.ItemOccurrence(repository_id=self.repo.id, project_id=project.id, item_id=item_id, scope="application",
                                              signal_registry_version="test", detection_state="found"))
        self.db.flush()

    def edge(self):
        self.db.add(models.IntegrationEdge(
            engagement_id=TEST_ENGAGEMENT_ID, edge_id=uuid.uuid4().hex, mechanism="soap_client", caller_repository_id=self.repo.id,
            caller_project_id=self.client.id, invocation_id="inv", call_site_file="Program.cs", call_site_line=1, operation="IOrders.Get",
            callee_repository_id=self.repo.id, callee_project_id=self.service.id, entry_point_id="ep", match_method="contract_and_operation",
            confidence=0.95, same_repository=True))
        self.db.flush()

    def decide(self, item_id, **fields):
        return item_decisions.upsert_item_decision(TEST_ENGAGEMENT_ID, item_id, s.EngagementDecisionUpsert(**fields), Response(), db=self.db)

    def supersede(self, decision_id):
        return item_decisions.supersede_item_decision(uuid.UUID(str(decision_id)), db=self.db)

    def live(self, item_id):
        return coupling.live_decision(self.db, TEST_ENGAGEMENT_ID, item_id)

    def notes(self, project):
        work_list = item_decisions.get_work_list_decisions(self.repo.id, db=self.db)
        return next(p for p in work_list.projects if p.project_id == str(project.id)).items


class DerivationByResolutionTests(CouplingFixture):
    def test_a_rewrite_derives_the_host_and_an_internal_client(self):
        self.edge()
        leader = self.decide("t-svc", resolution_id="t-svc-rest")
        host, client = self.live("t-host"), self.live("t-client")
        self.assertEqual((host.source, host.resolution_id, str(host.derived_from_decision_id), host.derived_against_resolution_id),
                         ("derived", "t-host-web", leader.id, "t-svc-rest"))
        self.assertEqual((client.source, client.resolution_id, client.status), ("derived", "t-client-migrate", "pending"))
        self.assertIn("t-svc-rest derive t-host", host.rationale)
        self.assertIsNone(self.notes(self.service)["t-retarget"].applies)
        self.assertEqual(self.notes(self.service)["t-retarget"].subsumed_by["item_id"], "t-svc")

    def test_corewcf_derives_the_host_but_not_the_client(self):
        # The defect: CoreWCF keeps WCF, so the client is not migrated to a
        # new protocol — even an internal one.
        self.edge()
        self.decide("t-svc", resolution_id="t-svc-corewcf")
        self.assertEqual(self.live("t-host").resolution_id, "t-host-web")
        self.assertIsNone(self.live("t-client"))
        note = self.notes(self.client)["t-client"]
        self.assertEqual((note.follows, note.action, note.applies), ("t-svc", "not_derived", False))
        self.assertIn("t-svc-corewcf not_derived t-client", note.note)

    def test_switching_the_leader_to_corewcf_withdraws_the_derived_client(self):
        self.edge()
        self.decide("t-svc", resolution_id="t-svc-rest")
        self.assertEqual(self.live("t-client").source, "derived")
        self.decide("t-svc", resolution_id="t-svc-corewcf")
        self.assertIsNone(self.live("t-client"))
        self.assertEqual(self.live("t-host").derived_against_resolution_id, "t-svc-corewcf")

    def test_remain_windows_derives_nothing_and_subsumes_nothing(self):
        self.decide("t-svc", resolution_id="t-svc-windows")
        self.assertIsNone(self.live("t-host"))
        self.assertIsNone(self.live("t-client"))
        retarget = self.notes(self.service)["t-retarget"]
        self.assertIsNone(retarget.subsumed_by)
        self.assertEqual((retarget.action, retarget.applies), ("not_subsumed", False))
        self.assertEqual(self.notes(self.host)["t-host"].action, "not_derived")

    def test_a_client_of_no_service_in_the_migration_is_not_derived(self):
        self.decide("t-svc", resolution_id="t-svc-rest")
        self.assertIsNone(self.live("t-client"))
        self.assertEqual(self.live("t-host").source, "derived")
        self.assertIn("Calls no t-svc inside this migration", self.notes(self.client)["t-client"].note)

    def test_an_undecided_leader_is_awaited(self):
        note = self.notes(self.host)["t-host"]
        self.assertEqual((note.follows, note.applies), ("t-svc", None))

    def test_a_superseded_leader_supersedes_its_derived_dependents(self):
        self.edge()
        leader = self.decide("t-svc", resolution_id="t-svc-rest")
        self.supersede(leader.id)
        self.assertIsNone(self.live("t-host"))
        self.assertIsNone(self.live("t-client"))

    def test_both_decisions_show_the_dependency(self):
        self.edge()
        leader = self.decide("t-svc", resolution_id="t-svc-rest")
        leader_view = item_decisions._response(self.db, self.db.get(models.EngagementDecision, uuid.UUID(leader.id)))
        self.assertEqual(sorted(f.item_id for f in leader_view.followers), ["t-client", "t-host"])
        host_view = item_decisions._response(self.db, self.live("t-host"))
        self.assertEqual((host_view.source, host_view.derived_from.item_id, host_view.derived_from.derivation_reason),
                         ("derived", "t-svc", "t-svc-rest derive t-host"))


class OverrideReviewTests(CouplingFixture):
    def override_host(self):
        self.edge()
        leader = self.decide("t-svc", resolution_id="t-svc-rest")
        overridden = self.decide("t-host", resolution_id="t-host-keep")
        self.assertEqual((overridden.source, overridden.overrides_derivation, overridden.needs_review), ("manual", True, False))
        self.assertEqual(overridden.derived_from.decision_id, leader.id)
        return leader

    def test_an_override_is_flagged_when_the_leading_resolution_changes(self):
        self.override_host()
        self.decide("t-svc", resolution_id="t-svc-corewcf")
        host = self.live("t-host")
        # Kept, not discarded — and not kept silently.
        self.assertEqual((host.resolution_id, host.source, host.needs_review), ("t-host-keep", "manual", True))
        self.assertIn("against the t-svc decision (t-svc-rest)", host.review_note)
        self.assertIn("now t-svc-corewcf", host.review_note)
        self.assertIn("It would derive t-host-web", host.review_note)
        view = item_decisions._response(self.db, host)
        self.assertEqual((view.needs_review, view.derived_from.would_derive), (True, "t-host-web"))

    def test_saving_the_override_again_answers_the_review(self):
        self.override_host()
        self.decide("t-svc", resolution_id="t-svc-corewcf")
        kept = self.decide("t-host", rationale="still keeping it")
        self.assertEqual((kept.needs_review, kept.review_note, kept.overrides_derivation), (False, None, True))
        self.assertEqual(self.live("t-host").derived_against_resolution_id, "t-svc-corewcf")

    def test_the_flag_clears_when_the_leader_returns_to_what_it_was(self):
        self.override_host()
        self.decide("t-svc", resolution_id="t-svc-corewcf")
        self.decide("t-svc", resolution_id="t-svc-rest")
        self.assertFalse(self.live("t-host").needs_review)

    def test_an_override_is_flagged_when_the_leader_is_superseded_and_replaced(self):
        leader = self.override_host()
        self.supersede(leader.id)
        host = self.live("t-host")
        self.assertEqual((host.resolution_id, host.needs_review), ("t-host-keep", True))
        self.assertIn("superseded, with no decision in its place", host.review_note)

        self.decide("t-svc", resolution_id="t-svc-windows")
        host = self.live("t-host")
        self.assertTrue(host.needs_review)
        self.assertIn("now t-svc-windows", host.review_note)
        self.assertIn("does not settle this item", host.review_note)

    def test_superseding_an_override_takes_the_derived_decision(self):
        self.override_host()
        self.supersede(self.live("t-host").id)
        host = self.live("t-host")
        self.assertEqual((host.source, host.resolution_id), ("derived", "t-host-web"))


class DerivationDataTests(CouplingFixture):
    def rows(self):
        return [{"item_id": "t-svc", "resolution_id": r, "dependent_item_id": d, "action": a, "dependent_resolution_id": dr,
                 "applies_to": ap, "reason": "why"}
                for r, deps in DERIVATIONS.items() for d, (a, dr, ap) in deps.items()]

    def test_the_fixture_table_is_valid(self):
        self.assertEqual(derivations.validate(self.db, self.rows()), [])

    def test_a_resolution_that_forgets_a_dependent_is_rejected(self):
        rows = [r for r in self.rows() if not (r["resolution_id"] == "t-svc-windows" and r["dependent_item_id"] == "t-client")]
        self.assertEqual(derivations.validate(self.db, rows),
                         ["t-svc-windows: declares nothing for 't-client', which other t-svc resolutions do — "
                          "declare derive, not_derived, subsume or not_subsumed"])

    def test_a_derive_must_name_a_resolution_of_the_dependent(self):
        rows = self.rows()
        rows[0] = {**rows[0], "dependent_resolution_id": "t-client-migrate"}   # t-svc-corewcf -> t-host
        problems = derivations.validate(self.db, rows)
        self.assertEqual(problems, ["t-svc-corewcf -> t-host: resolution 't-client-migrate' belongs to 't-client'"])
        rows[1] = {**rows[1], "dependent_resolution_id": "t-client-http"}       # not_derived names one
        self.assertIn("t-svc-corewcf -> t-client: only derive names a resolution (not_derived does not)",
                      derivations.validate(self.db, rows))


class AuthoredDerivationTests(unittest.TestCase):
    """The authored table, read from catalog_items.yaml — no database."""

    def test_wcf_service_derives_by_resolution(self):
        table = {(r["resolution_id"], r["dependent_item_id"]): (r["action"], r["dependent_resolution_id"])
                 for r in derivations.authored() if r["item_id"] == "wcf-service"}
        expected = {
            "wcf-service-rest-rewrite": [("derive", "wcf-host-aspnetcore-web-host"), ("derive", "migrate-to-service-protocol"), ("subsume", None)],
            "wcf-service-grpc-rewrite": [("derive", "wcf-host-aspnetcore-web-host"), ("derive", "migrate-to-service-protocol"), ("subsume", None)],
            "wcf-service-corewcf": [("derive", "wcf-host-aspnetcore-web-host"), ("not_derived", None), ("subsume", None)],
            "wcf-service-remain-windows-hosted": [("not_derived", None), ("not_derived", None), ("not_subsumed", None)],
        }
        dependents = ("wcf-service-host", "wcf-nettcp-client", "fx47-class-library")
        self.assertEqual(table, {(r, d): v for r, values in expected.items() for d, v in zip(dependents, values)})

    def test_every_authored_leading_resolution_declares_every_dependent(self):
        from app.seed.seed_data import _load

        rows = derivations.authored()
        for item in _load("catalog_items.yaml")["items"]:
            dependents = {r["dependent_item_id"] for r in rows if r["item_id"] == item["id"]}
            for resolution in item.get("resolutions", []) if dependents else []:
                declared = {r["dependent_item_id"] for r in rows if r["resolution_id"] == resolution["id"]}
                self.assertEqual(declared, dependents, resolution["id"])

    def test_remain_windows_hosted_is_not_linux_compatible(self):
        from app.seed.seed_data import authored_item

        resolution = next(r for r in authored_item("wcf-service")["resolutions"] if r["id"] == "wcf-service-remain-windows-hosted")
        self.assertEqual((resolution["linux_compatible"], resolution["container_ready"]), (False, False))


class ReplacementTests(CouplingFixture):
    """Part T: insert new, repoint, soft-delete — decisions survive. The
    soft-delete is the replaced item's factory default (pattern migration);
    replace_item repoints once it holds."""

    REPLACEMENT = {"old": "t-retarget", "new": "t-host", "resolutions": {"t-retarget-net10": "t-host-web"}, "reason": "fixture"}

    def replace(self):
        import datetime

        from app.items import architecture_items

        report = {"repointed_decisions": [], "moved_scope_rows": 0}
        architecture_items.replace_item(self.db, self.REPLACEMENT, report, datetime.datetime.now(datetime.timezone.utc))
        self.db.flush()
        return report

    def test_decisions_on_the_replaced_item_move_with_their_id_and_mapped_resolution(self):
        old = self.decide("t-retarget", resolution_id="t-retarget-net10", forcing_perspective="SECURITY", forcing_rationale="fixture")
        self.db.get(models.CatalogItem, "t-retarget").deleted_at = datetime.datetime.now(datetime.timezone.utc)
        report = self.replace()

        moved = self.db.get(models.EngagementDecision, uuid.UUID(old.id))
        self.assertEqual((moved.item_id, moved.resolution_id, moved.forcing_perspective), ("t-host", "t-host-web", "SECURITY"))
        self.assertIn("Moved from t-retarget to t-host", moved.evaluation_notes)
        self.assertEqual(report["repointed_decisions"], [old.id])
        self.assertEqual(self.replace()["repointed_decisions"], [])   # idempotent

    def test_a_replaced_item_the_team_restored_keeps_its_decisions(self):
        old = self.decide("t-retarget", resolution_id="t-retarget-net10")
        self.assertEqual(self.replace()["repointed_decisions"], [])
        self.assertEqual(self.db.get(models.EngagementDecision, uuid.UUID(old.id)).item_id, "t-retarget")


if __name__ == "__main__":
    unittest.main()
