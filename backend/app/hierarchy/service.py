"""Reads a repository's dependency graph for the Dependency graph tab (37-DEPENDENCY-HIERARCHY.md Part E).

The dependency-hierarchy step writes `hierarchy_nodes` and `hierarchy_edges`; nothing here writes. The UI asks for the
roots, then a node's children each time one is expanded, a page at a time — never the whole graph — so a repository of
hundreds of projects and their package trees stays quick to open.

A view is what the person has chosen to see:
- `transitive`: a package's own dependencies (package to package edges). Off by default, so the graph shows what the
  projects declare.
- `show`: all; internal (projects and internal packages); external (projects and external packages); projects (only
  projects). Assembly references are shown under all.
"""
import uuid
from collections import deque
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.hierarchy.schemas import (
    ChildOut,
    ChildrenOut,
    EdgeOut,
    FindingsOut,
    HierarchyOut,
    HierarchySummaryOut,
    NodeDetailOut,
    NodeOut,
    PathStepOut,
    SearchMatchOut,
    SearchOut,
    WorkItemOut,
)

SHOWS = ("all", "internal", "external", "projects")
PAGE = 20
TYPE_ORDER = {"project": 0, "package": 1, "assembly": 2}


@dataclass(frozen=True)
class View:
    transitive: bool = False
    show: str = "all"


class NotScanned(Exception):
    """dependency-hierarchy has not run for the repository."""


class NodeNotFound(Exception):
    pass


# An edge is visible when the view keeps both its kind and its target.
_VISIBLE = """
    (:transitive OR e.kind <> 'package_dependency')
    AND (:show = 'all'
         OR t.node_type = 'project'
         OR (:show IN ('internal', 'external') AND t.node_type = 'package' AND t.detail->'package'->>'origin' = :show))
"""
_PARENT_VISIBLE = "(:transitive OR e.kind <> 'package_dependency')"


def _params(repository_id: uuid.UUID, view: View, **extra) -> dict:
    return {"rid": repository_id, "transitive": view.transitive, "show": view.show, **extra}


def _like_prefix(value: str) -> str:
    return value.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _nodes_out(db: Session, repository_id: uuid.UUID, rows: list, view: View) -> dict[str, NodeOut]:
    """NodeOut for each (node_id, node_type, name, status, detail, project_id) row, with its counts under the view."""
    ids = [r.node_id for r in rows]
    if not ids:
        return {}
    children = dict(db.execute(text(f"""
        SELECT e.from_node, count(*) FROM hierarchy_edges e
        JOIN hierarchy_nodes t ON t.repository_id = e.repository_id AND t.node_id = e.to_node
        WHERE e.repository_id = :rid AND e.from_node = ANY(:ids) AND {_VISIBLE}
        GROUP BY 1"""), _params(repository_id, view, ids=ids)).all())
    parents = dict(db.execute(text(f"""
        SELECT e.to_node, count(*) FROM hierarchy_edges e
        WHERE e.repository_id = :rid AND e.to_node = ANY(:ids) AND {_PARENT_VISIBLE}
        GROUP BY 1"""), _params(repository_id, view, ids=ids)).all())

    # Work items: a project's found occurrences; a package's are the package items whose value names it and its version.
    project_ids = [r.project_id for r in rows if r.project_id is not None]
    by_project = dict(db.execute(text("""
        SELECT project_id, count(*) FROM item_occurrences
        WHERE repository_id = :rid AND project_id = ANY(:pids) AND detection_state = 'found' AND certainty <> 'possible'
        GROUP BY 1"""), {"rid": repository_id, "pids": project_ids}).all()) if project_ids else {}
    package_rows = [r for r in rows if r.node_type == "package" and (r.detail.get("package") or {}).get("version")]
    by_package: dict[str, int] = {}
    if package_rows:
        keys = [r.node_id for r in package_rows]
        prefixes = [_like_prefix(f"{r.detail['package']['packageId']} {r.detail['package']['version']}") for r in package_rows]
        by_package = dict(db.execute(text("""
            SELECT p.key, count(o.id) FROM unnest(CAST(:keys AS text[]), CAST(:prefixes AS text[])) AS p(key, prefix)
            JOIN item_occurrences o ON o.repository_id = :rid AND o.detection_state = 'found' AND o.item_id LIKE 'package-%'
                                   AND lower(o.value) LIKE p.prefix
            GROUP BY 1"""), {"rid": repository_id, "keys": keys, "prefixes": prefixes}).all())

    out = {}
    for r in rows:
        detail = r.detail or {}
        project = detail.get("project") or {}
        package = detail.get("package") or {}
        assembly = detail.get("assembly") or {}
        findings = package.get("findings") or {}
        out[r.node_id] = NodeOut(
            id=r.node_id,
            type=r.node_type,
            name=r.name,
            status=r.status,
            not_checked_reason=detail.get("notCheckedReason"),
            kind=project.get("kind"),
            origin=package.get("origin"),
            location=assembly.get("location"),
            version=package.get("version") or assembly.get("version"),
            target_frameworks=project.get("targetFrameworks") or [],
            legacy=project.get("projectFormat") == "legacy_msbuild",
            transitive=bool(package.get("transitive")),
            findings=FindingsOut(
                vulnerable=bool(findings.get("vulnerable") or package.get("vulnerabilityMaxSeverity")),
                vulnerability_max_severity=findings.get("vulnerabilityMaxSeverity") or package.get("vulnerabilityMaxSeverity"),
                outdated=bool(findings.get("outdated")),
                deprecated=bool(findings.get("deprecated")),
                outcome=findings.get("outcome"),
            ),
            work_items=by_project.get(r.project_id, 0) if r.node_type == "project" else by_package.get(r.node_id, 0),
            referenced_by=parents.get(r.node_id, 0),
            child_count=children.get(r.node_id, 0),
        )
    return out


def _edge_out(row) -> EdgeOut:
    detail = row.edge_detail or {}
    declared = detail.get("declaredAt") or {}
    return EdgeOut(
        from_node=row.from_node,
        to_node=row.to_node,
        kind=row.kind,
        resolution=row.resolution,
        version_requested=detail.get("versionRequested"),
        frameworks=detail.get("frameworks") or [],
        closes_cycle=row.closes_cycle,
        declared_file=declared.get("filePath"),
        declared_line=declared.get("line"),
    )


_NODE_COLUMNS = "n.node_id, n.node_type, n.name, n.status, n.detail, n.project_id"


def _require_scanned(db: Session, repository_id: uuid.UUID) -> None:
    if not db.execute(text("SELECT 1 FROM hierarchy_nodes WHERE repository_id = :rid LIMIT 1"), {"rid": repository_id}).first():
        raise NotScanned()


def overview(db: Session, repository_id: uuid.UUID, view: View) -> HierarchyOut:
    _require_scanned(db, repository_id)
    counts = db.execute(text("""
        SELECT
          count(*) FILTER (WHERE node_type = 'project'),
          count(*) FILTER (WHERE node_type = 'package'),
          count(*) FILTER (WHERE node_type = 'package' AND detail->'package'->>'origin' = 'internal'),
          count(*) FILTER (WHERE node_type = 'package' AND detail->'package'->>'origin' = 'external'),
          count(*) FILTER (WHERE node_type = 'package' AND (detail->'package'->>'transitive')::boolean),
          count(*) FILTER (WHERE node_type = 'assembly'),
          count(*) FILTER (WHERE status = 'not_checked'),
          max(step_execution_id::text)
        FROM hierarchy_nodes WHERE repository_id = :rid"""), {"rid": repository_id}).one()
    kinds = dict(db.execute(text("""
        SELECT detail->'project'->>'kind', count(*) FROM hierarchy_nodes
        WHERE repository_id = :rid AND node_type = 'project' GROUP BY 1"""), {"rid": repository_id}).all())
    edges = dict(db.execute(text("SELECT kind, count(*) FROM hierarchy_edges WHERE repository_id = :rid GROUP BY 1"), {"rid": repository_id}).all())
    cycles = db.execute(text("SELECT count(*) FROM hierarchy_edges WHERE repository_id = :rid AND closes_cycle"), {"rid": repository_id}).scalar()
    roots = db.execute(text(f"SELECT {_NODE_COLUMNS} FROM hierarchy_nodes n WHERE n.repository_id = :rid AND n.is_root ORDER BY lower(n.name), n.node_id"),
                       {"rid": repository_id}).all()
    nodes = _nodes_out(db, repository_id, roots, view)
    return HierarchyOut(
        repository_id=str(repository_id),
        step_execution_id=counts[7],
        summary=HierarchySummaryOut(
            project_count=counts[0],
            count_by_project_kind={k: v for k, v in sorted(kinds.items()) if k},
            package_count=counts[1],
            internal_package_count=counts[2],
            external_package_count=counts[3],
            transitive_package_count=counts[4],
            assembly_count=counts[5],
            edge_count=sum(edges.values()),
            count_by_edge_kind=dict(sorted(edges.items())),
            cycle_count=cycles,
            not_checked_count=counts[6],
        ),
        roots=[nodes[r.node_id] for r in roots],
    )


def children(db: Session, repository_id: uuid.UUID, node_id: str, view: View, offset: int = 0, limit: int = PAGE) -> ChildrenOut:
    _require_scanned(db, repository_id)
    if not db.execute(text("SELECT 1 FROM hierarchy_nodes WHERE repository_id = :rid AND node_id = :id"), {"rid": repository_id, "id": node_id}).first():
        raise NodeNotFound(node_id)
    query = f"""
        FROM hierarchy_edges e
        JOIN hierarchy_nodes t ON t.repository_id = e.repository_id AND t.node_id = e.to_node
        WHERE e.repository_id = :rid AND e.from_node = :id AND {_VISIBLE}"""
    params = _params(repository_id, view, id=node_id, offset=offset, limit=limit)
    total = db.execute(text(f"SELECT count(*) {query}"), params).scalar()
    rows = db.execute(text(f"""
        SELECT e.from_node, e.to_node, e.kind, e.resolution, e.closes_cycle, e.detail AS edge_detail,
               t.node_id, t.node_type, t.name, t.status, t.detail, t.project_id
        {query}
        ORDER BY CASE t.node_type WHEN 'project' THEN 0 WHEN 'package' THEN 1 ELSE 2 END, lower(t.name), t.node_id, e.kind
        OFFSET :offset LIMIT :limit"""), params).all()
    nodes = _nodes_out(db, repository_id, rows, view)
    return ChildrenOut(node_id=node_id, total=total, offset=offset, items=[ChildOut(edge=_edge_out(r), node=nodes[r.node_id]) for r in rows])


def search(db: Session, repository_id: uuid.UUID, query: str, view: View) -> SearchOut:
    """Nodes whose name contains the query — exact matches first, then projects, packages, assemblies — each with a
    shortest path from a root under the view, so the UI can reveal it. Paths are found over the repository's edges in
    memory: a few thousand rows even for a large repository."""
    _require_scanned(db, repository_id)
    pattern = "%" + query.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    total = db.execute(text("SELECT count(*) FROM hierarchy_nodes WHERE repository_id = :rid AND lower(name) LIKE :p"),
                       {"rid": repository_id, "p": pattern}).scalar()
    rows = db.execute(text(f"""
        SELECT {_NODE_COLUMNS} FROM hierarchy_nodes n WHERE n.repository_id = :rid AND lower(n.name) LIKE :p
        ORDER BY (lower(n.name) = :exact) DESC, CASE n.node_type WHEN 'project' THEN 0 WHEN 'package' THEN 1 ELSE 2 END, lower(n.name), n.node_id
        LIMIT :limit"""), {"rid": repository_id, "p": pattern, "exact": query.strip().lower(), "limit": PAGE}).all()
    if not rows:
        return SearchOut(query=query, total=total, matches=[])

    edges = db.execute(text("""
        SELECT e.from_node, e.to_node, e.kind, e.resolution, e.closes_cycle, e.detail AS edge_detail,
               t.node_type, t.name, t.detail->'package'->>'origin' AS origin
        FROM hierarchy_edges e JOIN hierarchy_nodes t ON t.repository_id = e.repository_id AND t.node_id = e.to_node
        WHERE e.repository_id = :rid
        ORDER BY e.from_node, CASE t.node_type WHEN 'project' THEN 0 WHEN 'package' THEN 1 ELSE 2 END, lower(t.name), e.to_node"""),
        {"rid": repository_id}).all()
    roots = [r for (r,) in db.execute(text("SELECT node_id FROM hierarchy_nodes WHERE repository_id = :rid AND is_root ORDER BY lower(name), node_id"),
                                       {"rid": repository_id})]

    def visible(edge, v: View) -> bool:
        if edge.kind == "package_dependency" and not v.transitive:
            return False
        return (v.show == "all" or edge.node_type == "project"
                or (v.show in ("internal", "external") and edge.node_type == "package" and edge.origin == v.show))

    def reach(v: View) -> dict[str, object]:
        """Breadth first from every root: for each reachable node, the edge it was first reached by (None for a root)."""
        outgoing: dict[str, list] = {}
        for edge in edges:
            if visible(edge, v):
                outgoing.setdefault(edge.from_node, []).append(edge)
        came: dict[str, object] = {root: None for root in roots}
        queue = deque(roots)
        while queue:
            node = queue.popleft()
            for edge in outgoing.get(node, []):
                if edge.to_node not in came:
                    came[edge.to_node] = edge
                    queue.append(edge.to_node)
        return came

    came = reach(view)
    everything = reach(View(transitive=True, show="all"))
    path_ids: dict[str, list[str]] = {}
    for row in rows:
        if row.node_id in came:
            chain, node = [], row.node_id
            while node is not None:
                chain.append(node)
                edge = came[node]
                node = edge.from_node if edge is not None else None
            path_ids[row.node_id] = list(reversed(chain))

    on_paths = {n for chain in path_ids.values() for n in chain}
    node_rows = db.execute(text(f"SELECT {_NODE_COLUMNS} FROM hierarchy_nodes n WHERE n.repository_id = :rid AND n.node_id = ANY(:ids)"),
                           {"rid": repository_id, "ids": list(on_paths | {r.node_id for r in rows})}).all()
    nodes = _nodes_out(db, repository_id, node_rows, view)

    matches = []
    for row in rows:
        chain = path_ids.get(row.node_id)
        if chain is None:
            if row.node_id in everything and not view.transitive:
                reason = "only another package depends on it: turn on Transitive packages to see it"
            elif row.node_id in everything:
                reason = "the filter hides a node on every path to it: show all to see it"
            else:
                reason = "no root reaches it"
            matches.append(SearchMatchOut(node=nodes[row.node_id], path=None, unreachable_reason=reason))
            continue
        steps = [PathStepOut(node=nodes[chain[0]], edge=None)]
        steps += [PathStepOut(node=nodes[n], edge=_edge_out(came[n])) for n in chain[1:]]
        matches.append(SearchMatchOut(node=nodes[row.node_id], path=steps))
    return SearchOut(query=query, total=total, matches=matches)


def node_detail(db: Session, repository_id: uuid.UUID, node_id: str, view: View) -> NodeDetailOut:
    _require_scanned(db, repository_id)
    row = db.execute(text(f"SELECT {_NODE_COLUMNS} FROM hierarchy_nodes n WHERE n.repository_id = :rid AND n.node_id = :id"),
                     {"rid": repository_id, "id": node_id}).first()
    if row is None:
        raise NodeNotFound(node_id)
    node = _nodes_out(db, repository_id, [row], view)[node_id]

    parent_query = f"""
        FROM hierarchy_edges e JOIN hierarchy_nodes n ON n.repository_id = e.repository_id AND n.node_id = e.from_node
        WHERE e.repository_id = :rid AND e.to_node = :id AND {_PARENT_VISIBLE}"""
    params = _params(repository_id, view, id=node_id)
    parents_total = db.execute(text(f"SELECT count(*) {parent_query}"), params).scalar()
    parent_rows = db.execute(text(f"""
        SELECT e.from_node, e.to_node, e.kind, e.resolution, e.closes_cycle, e.detail AS edge_detail, {_NODE_COLUMNS}
        {parent_query}
        ORDER BY CASE n.node_type WHEN 'project' THEN 0 WHEN 'package' THEN 1 ELSE 2 END, lower(n.name), n.node_id
        LIMIT {PAGE}"""), params).all()
    parent_nodes = _nodes_out(db, repository_id, parent_rows, view)

    detail = row.detail or {}
    if row.node_type == "project" and row.project_id is not None:
        items = db.execute(text("""
            SELECT o.item_id, c.name, p.relative_path, o.file_path, o.value FROM item_occurrences o
            JOIN catalog_items c ON c.id = o.item_id LEFT JOIN projects p ON p.id = o.project_id
            WHERE o.repository_id = :rid AND o.project_id = :pid AND o.detection_state = 'found' AND o.certainty <> 'possible'
            ORDER BY c.name, o.file_path NULLS FIRST, o.value NULLS FIRST LIMIT 200"""), {"rid": repository_id, "pid": row.project_id}).all()
    elif row.node_type == "package" and (detail.get("package") or {}).get("version"):
        package = detail["package"]
        items = db.execute(text("""
            SELECT o.item_id, c.name, p.relative_path, o.file_path, o.value FROM item_occurrences o
            JOIN catalog_items c ON c.id = o.item_id LEFT JOIN projects p ON p.id = o.project_id
            WHERE o.repository_id = :rid AND o.detection_state = 'found' AND o.item_id LIKE 'package-%' AND lower(o.value) LIKE :prefix
            ORDER BY c.name, p.relative_path LIMIT 200"""),
            {"rid": repository_id, "prefix": _like_prefix(f"{package['packageId']} {package['version']}")}).all()
    else:
        items = []

    return NodeDetailOut(
        node=node,
        detail=detail,
        parents_total=parents_total,
        parents=[ChildOut(edge=_edge_out(r), node=parent_nodes[r.node_id]) for r in parent_rows],
        work_items=[WorkItemOut(item_id=i[0], item_name=i[1], project_path=i[2], file_path=i[3], value=i[4]) for i in items],
    )
