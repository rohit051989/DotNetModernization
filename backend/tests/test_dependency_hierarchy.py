"""The Structure section's reads of a repository's dependency graph (app.hierarchy, 37-DEPENDENCY-HIERARCHY.md Part E):
children a page at a time, the view's filters, shared nodes, search with a path from a root, and a node's details.

The graph is written straight into hierarchy_nodes / hierarchy_edges, as the dependency-hierarchy step writes it.
Uses stdlib unittest, same rationale as test_repository_ingest.py.
"""

import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import text

from app import models
from app.db import SessionLocal
from app.hierarchy import service
from app.repositories import service as repositories_service
from app.repositories.schemas import RegisterLocalPathRequest
from tests.support import CommittedTestEngagement


def project(path, kind="library", root=False):
    return dict(node_id=f"project:{path}", node_type="project", name=Path(path).stem, is_root=root,
                detail={"id": f"project:{path}", "type": "project", "name": Path(path).stem, "status": "checked",
                        "project": {"path": path, "kind": kind, "kindBasis": "test", "targetFrameworks": ["net8.0"],
                                    "projectFormat": "sdk_style", "packageManagement": "packagereference"}})


def package(package_id, version, origin="external", transitive=False, findings=None):
    node_id = f"package:{package_id.lower()}@{version}"
    return dict(node_id=node_id, node_type="package", name=package_id, is_root=False,
                detail={"id": node_id, "type": "package", "name": package_id, "status": "checked",
                        "package": {"packageId": package_id, "version": version, "origin": origin, "originBasis": "test",
                                    "transitive": transitive, "findings": findings}})


def edge(from_node, to_node, kind, line=None):
    return dict(from_node=from_node, to_node=to_node, kind=kind, resolution="declared",
                detail={"from": from_node, "to": to_node, "kind": kind, "versionRequested": None, "frameworks": [],
                        "declaredAt": {"filePath": from_node.split(":", 1)[1], "line": line} if line else None})


class HierarchyReadTests(unittest.TestCase):
    """Web and Worker both reference Shared (a shared library); Web declares 25 packages; one internal package depends
    on an external one."""

    def setUp(self):
        self.db = SessionLocal()
        self.tmp = tempfile.TemporaryDirectory()
        self.test_engagement = CommittedTestEngagement(self.db)
        folder = Path(self.tmp.name) / "repo"
        folder.mkdir()
        (folder / "x.txt").write_text("x\n", encoding="utf-8")
        self.repo = repositories_service.register_local_path(
            self.db, self.test_engagement.engagement, RegisterLocalPathRequest(source_type="local_path", local_path=str(folder)))
        self.db.commit()
        self.rid = self.repo.id

        web, worker, shared = "src/Web/Web.csproj", "src/Worker/Worker.csproj", "src/Shared/Shared.csproj"
        nodes = [project(web, "application", root=True), project(worker, "application", root=True), project(shared)]
        edges = [edge(f"project:{web}", f"project:{shared}", "project_reference", line=7),
                 edge(f"project:{worker}", f"project:{shared}", "project_reference", line=9)]
        for i in range(25):
            nodes.append(package(f"External.P{i:02d}", "1.0.0"))
            edges.append(edge(f"project:{web}", f"package:external.p{i:02d}@1.0.0", "package_reference", line=20 + i))
        nodes.append(package("Acme.Common", "2.0.0", origin="internal", findings={"outcome": "upgrade_safe", "outdated": True, "vulnerable": False}))
        nodes.append(package("Deep.Dependency", "3.0.0", transitive=True))
        edges.append(edge(f"project:{shared}", "package:acme.common@2.0.0", "package_reference", line=5))
        edges.append(edge("package:acme.common@2.0.0", "package:deep.dependency@3.0.0", "package_dependency"))
        for n in nodes:
            self.db.execute(text("""INSERT INTO hierarchy_nodes (repository_id, node_id, node_type, name, status, is_root, detail)
                                    VALUES (:rid, :node_id, :node_type, :name, 'checked', :is_root, CAST(:detail AS jsonb))"""),
                            {"rid": self.rid, **n, "detail": json.dumps(n["detail"])})
        for e in edges:
            self.db.execute(text("""INSERT INTO hierarchy_edges (repository_id, from_node, to_node, kind, resolution, detail)
                                    VALUES (:rid, :from_node, :to_node, :kind, :resolution, CAST(:detail AS jsonb))"""),
                            {"rid": self.rid, **e, "detail": json.dumps(e["detail"])})
        self.db.commit()

    def tearDown(self):
        row = self.db.get(models.Repository, self.rid)
        if row is not None:
            self.db.delete(row)
        self.db.commit()
        self.test_engagement.remove()
        self.db.close()
        self.tmp.cleanup()

    def test_it_opens_on_the_roots_with_the_graph_s_summary(self):
        out = service.overview(self.db, self.rid, service.View())
        self.assertEqual([r.name for r in out.roots], ["Web", "Worker"])
        self.assertEqual((out.summary.project_count, out.summary.package_count, out.summary.internal_package_count,
                          out.summary.transitive_package_count), (3, 27, 1, 1))
        web = out.roots[0]
        self.assertEqual((web.kind, web.child_count, web.referenced_by), ("application", 26, 0))

    def test_children_come_twenty_at_a_time_projects_first(self):
        first = service.children(self.db, self.rid, "project:src/Web/Web.csproj", service.View())
        self.assertEqual((first.total, len(first.items)), (26, 20))
        self.assertEqual(first.items[0].node.name, "Shared")
        self.assertEqual((first.items[0].edge.kind, first.items[0].edge.declared_line), ("project_reference", 7))
        rest = service.children(self.db, self.rid, "project:src/Web/Web.csproj", service.View(), offset=20)
        self.assertEqual(len(rest.items), 6)
        self.assertFalse({i.node.id for i in first.items} & {i.node.id for i in rest.items})

    def test_a_shared_library_is_one_node_that_says_how_many_reference_it(self):
        from_web = service.children(self.db, self.rid, "project:src/Web/Web.csproj", service.View(), limit=1).items[0].node
        from_worker = service.children(self.db, self.rid, "project:src/Worker/Worker.csproj", service.View()).items[0].node
        self.assertEqual(from_web.id, from_worker.id)
        self.assertEqual(from_web.referenced_by, 2)

    def test_transitive_packages_are_hidden_until_asked_for(self):
        acme = "package:acme.common@2.0.0"
        self.assertEqual(service.children(self.db, self.rid, acme, service.View()).total, 0)
        shown = service.children(self.db, self.rid, acme, service.View(transitive=True))
        self.assertEqual([i.node.name for i in shown.items], ["Deep.Dependency"])
        self.assertTrue(shown.items[0].node.transitive)

    def test_filters_keep_projects_and_the_chosen_packages(self):
        shared = "project:src/Shared/Shared.csproj"
        web = "project:src/Web/Web.csproj"
        self.assertEqual(service.children(self.db, self.rid, shared, service.View(show="internal")).total, 1)
        self.assertEqual(service.children(self.db, self.rid, shared, service.View(show="external")).total, 0)
        self.assertEqual(service.children(self.db, self.rid, web, service.View(show="projects")).total, 1)
        self.assertEqual(service.children(self.db, self.rid, web, service.View(show="external")).total, 26)

    def test_badges_carry_dependency_assessment_s_findings(self):
        acme = service.children(self.db, self.rid, "project:src/Shared/Shared.csproj", service.View()).items[0].node
        self.assertEqual((acme.origin, acme.findings.outdated, acme.findings.outcome), ("internal", True, "upgrade_safe"))

    def test_search_reveals_a_node_with_its_path_from_a_root(self):
        out = service.search(self.db, self.rid, "acme", service.View())
        match = out.matches[0]
        self.assertEqual([step.node.name for step in match.path], ["Web", "Shared", "Acme.Common"])
        self.assertIsNone(match.path[0].edge)
        self.assertEqual(match.path[2].edge.kind, "package_reference")

    def test_search_says_why_a_transitive_package_is_not_reachable_in_the_view(self):
        hidden = service.search(self.db, self.rid, "Deep.Dependency", service.View()).matches[0]
        self.assertIsNone(hidden.path)
        self.assertIn("turn on Transitive packages", hidden.unreachable_reason)
        shown = service.search(self.db, self.rid, "Deep.Dependency", service.View(transitive=True)).matches[0]
        self.assertEqual([s.node.name for s in shown.path], ["Web", "Shared", "Acme.Common", "Deep.Dependency"])

    def test_a_node_s_details_list_its_parents_and_where_each_declares_it(self):
        detail = service.node_detail(self.db, self.rid, "project:src/Shared/Shared.csproj", service.View())
        self.assertEqual(detail.parents_total, 2)
        self.assertEqual([(p.node.name, p.edge.declared_line) for p in detail.parents], [("Web", 7), ("Worker", 9)])

    def test_an_unknown_node_and_an_unscanned_repository_are_refused(self):
        with self.assertRaises(service.NodeNotFound):
            service.children(self.db, self.rid, "project:nowhere", service.View())
        self.db.execute(text("DELETE FROM hierarchy_edges WHERE repository_id = :rid"), {"rid": self.rid})
        self.db.execute(text("DELETE FROM hierarchy_nodes WHERE repository_id = :rid"), {"rid": self.rid})
        self.db.commit()
        with self.assertRaises(service.NotScanned):
            service.overview(self.db, self.rid, service.View())


if __name__ == "__main__":
    unittest.main()
