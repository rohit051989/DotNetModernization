"""impact-analysis — 33-IMPACT-ANALYSIS.md: the impact
rules as catalog data (Part D), stale marking when a decision changes
(Part C), dependency-and-context-map's client impact (Part B), the Python rollup (Part G) and
the Impact API (Part J).

Hermetic: the decision-coupling fixture (items, resolutions, projects,
occurrences) plus fixture impact rows, all inside one rolled-back
transaction. The traversal itself is impact-analysis's .NET code and is tested there
(steps/step-003-fingerprinting/tests/Fingerprinting.Tests/ImpactTests.cs).

Run from backend/:  python -m unittest tests.test_impact -v
"""

import unittest
import uuid
from pathlib import Path

import yaml

from app import models
from app.impact import client, conflicts, rollup, stale
from app.items import baseline, impact_rules
from app.routers import impact as impact_router
from tests.support import TEST_ENGAGEMENT_ID
from tests.test_decision_coupling import CouplingFixture

CATALOG_YAML = Path(__file__).resolve().parents[1] / "app" / "seed" / "data" / "catalog_items.yaml"

REST_RULES = [
    {"id": "impl", "from": "seed", "select": "self", "action": "rewrite"},
    {"id": "clients", "traverse": "client_call_sites", "action": "rewrite", "reason": "Callers move from the SOAP proxy to HTTP"},
]


class ImpactRulesTests(unittest.TestCase):
    def test_authored_rules_are_valid(self):
        data = yaml.safe_load(CATALOG_YAML.read_text(encoding="utf-8"))
        with_rules = 0
        for item in data["items"]:
            for resolution in item.get("resolutions", []):
                if "impact" in resolution:
                    with_rules += 1
                    self.assertEqual([], impact_rules.validate(resolution["impact"]), resolution["id"])
        self.assertGreaterEqual(with_rules, 13)   # Part K

    def test_part_k_resolutions_carry_rules(self):
        data = yaml.safe_load(CATALOG_YAML.read_text(encoding="utf-8"))
        rules = {r["id"]: r.get("impact") for i in data["items"] for r in i.get("resolutions", [])}
        for resolution_id in ("wcf-service-rest-rewrite", "wcf-service-corewcf", "wcf-service-grpc-rewrite",
                              "wcf-service-remain-windows-hosted", "wcf-host-aspnetcore-web-host",
                              "migrate-to-service-protocol", "call-http-binding"):
            self.assertTrue(rules[resolution_id], resolution_id)
        # Remain Windows-hosted: visible, implying no edits.
        self.assertEqual([{"id": "evidence", "from": "seed", "select": "self", "action": "review",
                           "reason": rules["wcf-service-remain-windows-hosted"][0]["reason"]}],
                         rules["wcf-service-remain-windows-hosted"])

    def test_invalid_rules_are_named(self):
        problems = impact_rules.validate([
            {"id": "a", "from": "seed", "traverse": "teleport", "action": "update"},
            {"id": "b", "from": "nowhere", "select": "self", "action": "obliterate"},
            {"id": "c", "create": "x", "for_each": "a", "action": "create"},
        ])
        text = "\n".join(problems)
        for fragment in ("teleport", "nowhere", "obliterate", "proposed_path"):
            self.assertIn(fragment, text)
        with self.assertRaises(ValueError):
            impact_rules.checked([{"id": "a", "action": "update"}], "t")

    def test_config_elements_never_delete_a_file(self):
        problems = impact_rules.validate([{"id": "cfg", "from": "seed", "traverse": "config_elements",
                                           "path": "system.serviceModel/services", "action": "delete"}])
        self.assertTrue(any("use action update" in p for p in problems), problems)

    def test_default_rule_is_evidence_update(self):
        self.assertEqual([{"id": "evidence", "from": "seed", "select": "self", "action": "update",
                           "reason": impact_rules.DEFAULT_RULES[0]["reason"]}], impact_rules.DEFAULT_RULES)

    def test_empty_rules_leave_the_baseline_hash_unchanged(self):
        # A resolution without rules hashes as it did before impact_rules existed,
        # so adding the column touched no existing baseline or export.
        row = models.ItemResolution(id="r", item_id="i", name="R", consumer_impact="none", effort="low", is_default=True,
                                    linux_compatible=True, container_ready=True, status="active", impact_rules=[])
        self.assertNotIn("impact_rules", baseline.content(row))
        row.impact_rules = [{"id": "x", "from": "seed", "select": "self", "action": "review"}]
        self.assertIn("impact_rules", baseline.content(row))


class ImpactFixture(CouplingFixture):
    """The coupling fixture with impact-analysis rows for t-svc on the service project,
    computed with no decision (t-svc-corewcf the default)."""

    HANDLER = "src/Services/OrderService.cs"

    def setUp(self):
        super().setUp()
        self.db.get(models.ItemResolution, "t-svc-rest").impact_rules = REST_RULES
        self.db.get(models.ItemResolution, "t-svc-corewcf").impact_rules = [
            {"id": "impl", "from": "seed", "select": "self", "action": "update"},
            {"id": "clients", "traverse": "client_call_sites", "action": "review"},
        ]
        self.db.add(models.EntryPoint(
            id="ep", repository_id=self.repo.id, project_id=self.service.id, kind="wcf_operation", handler_type="OrderService",
            handler_member="Get", file_path=self.HANDLER, line_start=1, line_end=2, detail={}, confidence=0.9))
        self.db.flush()

    def summary(self, resolution_id, roles, effective, decision=None, files=None):
        self.db.add(models.ImpactSummary(
            repository_id=self.repo.id, engagement_id=TEST_ENGAGEMENT_ID, item_id="t-svc", project_id=self.service.id,
            project_path=self.service.relative_path, resolution_id=resolution_id, roles=roles, effective=effective,
            counts={"update": 1}, changed=1, created=0, to_review=0, confirmed=1, possible=0, rules_source="explicit", known_limits=[],
            decision_resolution_id=decision))
        for path, action in (files or [(self.HANDLER, "update")]):
            self.db.add(models.WorkItemImpact(
                repository_id=self.repo.id, engagement_id=TEST_ENGAGEMENT_ID, item_id="t-svc", project_id=self.service.id,
                project_path=self.service.relative_path, resolution_id=resolution_id, file_repository_id=self.repo.id,
                file_path=path, action=action, certainty="confirmed",
                reasons=[{"ruleId": "impl", "action": action, "reason": "impl"}], rule_ids=["impl"],
                traversal_paths=[f"evidence {path}"], source="structural"))
        self.db.flush()

    def summaries(self):
        return {s.resolution_id: s for s in self.db.query(models.ImpactSummary).filter_by(repository_id=self.repo.id)}


class StaleTests(ImpactFixture):
    def test_a_decision_marks_impact_computed_without_one_stale_naming_the_resolution(self):
        self.summary("t-svc-corewcf", ["default"], True)
        self.decide("t-svc", resolution_id="t-svc-rest")
        summary = self.summaries()["t-svc-corewcf"]
        self.assertTrue(summary.stale)
        self.assertIn("t-svc-rest", summary.stale_reason)

    def test_changing_the_decision_back_clears_stale(self):
        self.summary("t-svc-corewcf", ["default"], False, decision="t-svc-rest")
        self.summary("t-svc-rest", ["chosen"], True, decision="t-svc-rest")
        decision = self.decide("t-svc", resolution_id="t-svc-corewcf")
        self.assertTrue(all(s.stale for s in self.summaries().values()))
        self.decide("t-svc", resolution_id="t-svc-rest")
        self.assertFalse(any(s.stale for s in self.summaries().values()))
        # Withdrawn: the default is effective again, and the reason says so.
        self.supersede(decision.id)
        self.assertIn("withdrawn", self.summaries()["t-svc-rest"].stale_reason)

    def test_a_derived_followers_impact_goes_stale_too(self):
        self.db.add(models.ImpactSummary(
            repository_id=self.repo.id, engagement_id=TEST_ENGAGEMENT_ID, item_id="t-host", project_id=self.host.id,
            project_path=self.host.relative_path, resolution_id="t-host-web", roles=["default"], effective=True,
            counts={}, changed=0, created=0, to_review=0, confirmed=0, possible=0, rules_source="default", known_limits=[]))
        self.db.flush()
        self.decide("t-svc", resolution_id="t-svc-corewcf")   # derives t-host -> t-host-web
        host = self.db.query(models.ImpactSummary).filter_by(item_id="t-host").one()
        self.assertTrue(host.stale)


class ClientImpactTests(ImpactFixture):
    def test_callers_of_an_impacted_handler_become_client_rows_for_each_computed_resolution(self):
        self.summary("t-svc-corewcf", ["default"], False, decision="t-svc-rest")
        self.summary("t-svc-rest", ["chosen"], True, decision="t-svc-rest")
        self.edge()   # Program.cs calls IOrders.Get, handled by entry point "ep"

        self.assertEqual({"client_rows": 2}, client.apply(self.db, TEST_ENGAGEMENT_ID))
        rows = {r.resolution_id: r for r in self.db.query(models.WorkItemImpact).filter_by(engagement_id=TEST_ENGAGEMENT_ID, source="client")}
        self.assertEqual({"t-svc-corewcf": "review", "t-svc-rest": "rewrite"}, {k: r.action for k, r in rows.items()})
        rest = rows["t-svc-rest"]
        self.assertEqual(("Program.cs", "confirmed", self.repo.id), (rest.file_path, rest.certainty, rest.file_repository_id))
        self.assertEqual(["Program.cs:1 calls IOrders.Get (soap_client, confidence 0.95) ← OrderService in src/Services/OrderService.cs"],
                         rest.traversal_paths)
        self.assertEqual("Callers move from the SOAP proxy to HTTP", rest.reasons[0]["reason"])
        # Changed and to review apart: REST rewrites the caller, CoreWCF asks for review.
        summaries = self.summaries()
        self.assertEqual((1, 0), (summaries["t-svc-rest"].client_changed, summaries["t-svc-rest"].client_review))
        self.assertEqual((0, 1), (summaries["t-svc-corewcf"].client_changed, summaries["t-svc-corewcf"].client_review))

        # Effective only in the rollup, labelled client.
        program = self.db.query(models.FileImpactRollup).filter_by(repository_id=self.repo.id, file_key="Program.cs").one()
        self.assertTrue(program.includes_client)
        self.assertEqual([("t-svc", "t-svc-rest", "rewrite", "client")],
                         [(i["itemId"], i["resolutionId"], i["action"], i["source"]) for i in program.work_items])

        # Each run replaces the client rows.
        client.apply(self.db, TEST_ENGAGEMENT_ID)
        self.assertEqual(2, self.db.query(models.WorkItemImpact).filter_by(engagement_id=TEST_ENGAGEMENT_ID, source="client").count())

    def test_low_confidence_edges_are_possible_and_no_rule_means_no_client_rows(self):
        self.db.get(models.ItemResolution, "t-svc-corewcf").impact_rules = []
        self.summary("t-svc-corewcf", ["default"], True)
        self.edge()
        self.db.query(models.IntegrationEdge).filter_by(engagement_id=TEST_ENGAGEMENT_ID).one().confidence = 0.6
        self.db.flush()
        self.assertEqual({"client_rows": 0}, client.apply(self.db, TEST_ENGAGEMENT_ID))

        self.db.get(models.ItemResolution, "t-svc-corewcf").impact_rules = REST_RULES
        self.db.flush()
        client.apply(self.db, TEST_ENGAGEMENT_ID)
        self.assertEqual("possible", self.db.query(models.WorkItemImpact).filter_by(engagement_id=TEST_ENGAGEMENT_ID, source="client").one().certainty)

    def test_a_file_already_impacted_structurally_stays_structural(self):
        self.summary("t-svc-rest", ["chosen"], True, decision="t-svc-rest", files=[(self.HANDLER, "rewrite"), ("Program.cs", "update")])
        self.edge()
        self.assertEqual({"client_rows": 0}, client.apply(self.db, TEST_ENGAGEMENT_ID))


class RollupTests(unittest.TestCase):
    def item(self, item_id, action, source="structural"):
        return {"itemId": item_id, "projectPath": "p.csproj", "resolutionId": item_id + "-r", "action": action, "source": source}

    def test_hotspots_and_conflicts(self):
        files = {f["fileKey"]: f for f in rollup.compute([
            ("a.cs", self.item("x", "update")), ("a.cs", self.item("y", "rewrite")), ("a.cs", self.item("z", "update", "client")),
            ("b.cs", self.item("x", "delete")), ("b.cs", self.item("y", "update")),
            ("create:n.cs", self.item("x", "create")), ("create:n.cs", self.item("y", "create")),
        ])}
        self.assertTrue(files["a.cs"]["hotspot"])
        self.assertEqual([], files["a.cs"]["conflicts"])
        self.assertEqual(["delete_with_change"], [c["kind"] for c in files["b.cs"]["conflicts"]])
        self.assertEqual(("x", "y"), (files["b.cs"]["conflicts"][0]["first"]["itemId"], files["b.cs"]["conflicts"][0]["second"]["itemId"]))
        self.assertEqual(["create_same_path"], [c["kind"] for c in files["create:n.cs"]["conflicts"]])

    def test_file_key(self):
        self.assertEqual("a.cs", rollup.file_key("a.cs", None))
        self.assertEqual("create:b.cs", rollup.file_key(None, "b.cs"))


class ConflictGroupingTests(unittest.TestCase):
    @staticmethod
    def side(item, project, rules, action):
        return {"itemId": item, "projectPath": project, "resolutionId": item + "-r", "action": action,
                "source": "structural", "ruleIds": rules}

    def conflict(self, repository, file_key, project, rules_b=("host",), swap=False):
        a = self.side("svc-item", project, ["svc"], "delete")
        b = self.side("host-item", project, list(rules_b), "rewrite")
        first, second = (b, a) if swap else (a, b)
        return (repository, file_key, [{"kind": "delete_with_change", "first": first, "second": second}])

    def test_one_rule_pair_on_several_pairs_of_work_items_is_one_rule_conflict(self):
        groups = conflicts.group([
            self.conflict("r1", "a/Order.svc", "a/A.csproj"),
            self.conflict("r1", "b/Order.svc", "b/B.csproj"),
            self.conflict("r2", "a/Order.svc", "a/A.csproj", swap=True),   # sides either way round: the same rule pair
        ])
        self.assertEqual(1, len(groups))
        g = groups[0]
        self.assertTrue(conflicts.is_rule_conflict(g))
        self.assertEqual((3, 6, 2, 3), (g["pairs"], g["work_items"], g["repositories"], len(g["instances"])))

    def test_a_single_pair_of_work_items_is_not_a_rule_conflict_even_on_two_files(self):
        g = conflicts.group([self.conflict("r1", "a/One.svc", "a/A.csproj"), self.conflict("r1", "a/Two.svc", "a/A.csproj")])[0]
        self.assertFalse(conflicts.is_rule_conflict(g))
        self.assertEqual(["a/One.svc", "a/Two.svc"], [i["file_key"] for i in g["instances"]])

    def test_a_different_rule_pair_is_a_different_key(self):
        groups = conflicts.group([self.conflict("r1", "a/Order.svc", "a/A.csproj"),
                                  self.conflict("r2", "a/Order.svc", "a/A.csproj", rules_b=("other",))])
        self.assertEqual(2, len(groups))
        self.assertFalse(any(conflicts.is_rule_conflict(g) for g in groups))


class EstateRuleConflictTests(ImpactFixture):
    """Classification across the estate: two repositories, each holding one
    instance of the same conflicting rule pair, are one catalog rule conflict
    across two repositories, though neither repository alone could show it."""

    @staticmethod
    def side(item, project, rules, action):
        return {"itemId": item, "projectPath": project, "resolutionId": f"{item}-r", "action": action,
                "source": "structural", "ruleIds": rules}

    def one_conflict(self, repository, project):
        conflict = {"kind": "delete_with_change", "first": self.side("t-svc", project, ["svc"], "delete"),
                    "second": self.side("t-host", project, ["host"], "rewrite")}
        self.db.add(models.FileImpactRollup(
            repository_id=repository.id, file_key=f"{project.rsplit('/', 1)[0]}/Order.svc",
            work_items=[conflict["first"], conflict["second"]], hotspot=False, conflicts=[conflict], includes_client=False))

    def setUp(self):
        super().setUp()
        tag = uuid.uuid4().hex[:8]
        self.other = models.Repository(
            engagement_id=TEST_ENGAGEMENT_ID, name=f"t-{tag}", root_folder_name=f"t-{tag}", slug=f"t-{tag}",
            local_path=f"C:/t-{tag}", local_path_normalised=f"c:/t-{tag}", source_type="local_path", ingest_status="scanned")
        self.db.add(self.other)
        self.db.flush()
        self.one_conflict(self.repo, "src/Services/Services.csproj")
        self.one_conflict(self.other, "src/Services/Services.csproj")
        self.summary("t-svc-corewcf", ["default"], True)   # so the repository has impact to show
        self.db.flush()

    def test_one_instance_per_repository_in_two_repositories_is_one_catalog_rule_conflict(self):
        # Per repository, each is a single pair of work items: a work-item conflict.
        before = impact_router.get_repository_impact(self.repo.id, db=self.db)
        self.assertEqual((0, 1), (before.totals.rule_conflicts, before.totals.work_item_conflicts))

        # The estate run aggregates the keys across the engagement.
        self.assertEqual({"rule_conflicts": 1, "work_items": 4}, conflicts.apply_estate(self.db, TEST_ENGAGEMENT_ID))
        row = self.db.query(models.ImpactRuleConflict).filter_by(engagement_id=TEST_ENGAGEMENT_ID).one()
        self.assertEqual((4, 2, 2), (row.work_items, row.repositories, len(row.instances)))
        self.assertEqual("delete_with_change|t-host:t-host-r:host|t-svc:t-svc-r:svc", row.rule_key)

        # Each repository now labels its single instance a catalog rule conflict across two repositories.
        for repository in (self.repo, self.other):
            if repository is self.other:
                self.db.add(models.ImpactSummary(
                    repository_id=self.other.id, engagement_id=TEST_ENGAGEMENT_ID, item_id="t-svc", project_path="x.csproj",
                    resolution_id="t-svc-corewcf", roles=["default"], effective=True, counts={}, changed=0, created=0,
                    to_review=0, confirmed=0, possible=0, rules_source="explicit", known_limits=[]))
                self.db.flush()
            after = impact_router.get_repository_impact(repository.id, db=self.db)
            self.assertEqual((1, 0), (after.totals.rule_conflicts, after.totals.work_item_conflicts))
            rule = after.rule_conflicts[0]
            self.assertEqual((4, 2, "estate", 1), (rule.work_items, rule.repositories, rule.classified_by, len(rule.instances)))

        # The Estate tab and the master catalog view show it once.
        estate = impact_router.get_engagement_rule_conflicts(TEST_ENGAGEMENT_ID, db=self.db)
        self.assertEqual([(4, 2)], [(r.work_items, r.repositories) for r in estate.rule_conflicts])
        self.assertEqual({self.repo.slug, self.other.slug}, {i.repository_slug for i in estate.rule_conflicts[0].instances})
        master = [m for m in impact_router.list_catalog_rule_conflicts(db=self.db) if m.rule_key == row.rule_key]
        self.assertEqual([TEST_ENGAGEMENT_ID], [e.engagement_id for e in master[0].engagements])

    def test_a_rule_pair_on_one_pair_of_work_items_across_the_estate_stays_a_work_item_conflict(self):
        self.db.query(models.FileImpactRollup).filter_by(repository_id=self.other.id).delete()
        self.db.flush()
        self.assertEqual({"rule_conflicts": 0, "work_items": 0}, conflicts.apply_estate(self.db, TEST_ENGAGEMENT_ID))
        repo = impact_router.get_repository_impact(self.repo.id, db=self.db)
        self.assertEqual((0, 1), (repo.totals.rule_conflicts, repo.totals.work_item_conflicts))


class ImpactApiTests(ImpactFixture):
    def test_repository_impact_and_the_side_by_side(self):
        self.summary("t-svc-corewcf", ["default"], False, decision="t-svc-rest")
        self.summary("t-svc-rest", ["chosen"], True, decision="t-svc-rest",
                     files=[(self.HANDLER, "rewrite"), ("src/Services/IOrders.cs", "delete")])
        self.edge()
        client.apply(self.db, TEST_ENGAGEMENT_ID)

        repo = impact_router.get_repository_impact(self.repo.id, db=self.db)
        self.assertEqual(1, repo.totals.work_items)
        t = repo.totals
        # handler rewrite, contract delete, Program.cs rewrite (client): 3 changes across 3 files.
        self.assertEqual((3, 3, 1), (t.changes, t.files_changed, t.client_changes))
        self.assertEqual(t.changes, t.by_action.rewrite + t.by_action.update + t.by_action.delete)
        self.assertEqual((0, 0, 0, 0), (t.creates, t.new_files, t.review_marks, t.files_to_review))
        self.assertEqual("t-svc-rest", repo.work_items[0].effective_resolution_id)
        self.assertEqual(["t-svc-corewcf", "t-svc-rest"], [r.resolution_id for r in repo.work_items[0].resolutions])

        detail = impact_router.get_work_item_impact(self.repo.id, item_id="t-svc", project_path=self.service.relative_path, db=self.db)
        self.assertEqual(["t-svc-corewcf", "t-svc-rest"], [r.resolution_id for r in detail.resolutions])
        rest = detail.resolutions[1]
        self.assertEqual([("delete", "structural"), ("rewrite", "structural"), ("rewrite", "client")],
                         [(e.action, e.source) for e in rest.entries])
        self.assertEqual(["t-svc-windows"], [p.resolution_id for p in detail.pending])
        self.assertEqual("Impact is analysed for the default resolution and the chosen one. Other resolutions are not analysed.",
                         detail.pending_note)

    def test_not_scanned_is_409(self):
        with self.assertRaises(Exception) as caught:
            impact_router.get_repository_impact(self.repo.id, db=self.db)
        self.assertEqual(409, caught.exception.status_code)


if __name__ == "__main__":
    unittest.main()
