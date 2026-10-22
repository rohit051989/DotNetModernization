"""Response shapes for the repository's Structure section (37-DEPENDENCY-HIERARCHY.md Part E)."""
from pydantic import BaseModel, Field


class FindingsOut(BaseModel):
    vulnerable: bool = False
    vulnerability_max_severity: str | None = None
    outdated: bool = False
    deprecated: bool = False
    outcome: str | None = Field(default=None, description="dependency-assessment's outcome, for a package a project declares.")


class NodeOut(BaseModel):
    id: str
    type: str = Field(description="project, package or assembly.")
    name: str
    status: str = Field(description="checked or not_checked.")
    not_checked_reason: str | None = None
    kind: str | None = Field(default=None, description="A project's kind: application, library, test or other.")
    origin: str | None = Field(default=None, description="A package's origin: internal, external or unknown.")
    location: str | None = Field(default=None, description="An assembly reference's location: repository, outside_repository, gac or framework.")
    version: str | None = None
    target_frameworks: list[str] = []
    legacy: bool = Field(default=False, description="A legacy (non-SDK-style) project.")
    transitive: bool = Field(default=False, description="A package no project declares: only another package depends on it.")
    findings: FindingsOut = FindingsOut()
    work_items: int = Field(default=0, description="Work items item-detection found for it.")
    referenced_by: int = Field(description="How many nodes depend on it: its parents in the graph, each once.")
    child_count: int = Field(description="Its children under the current view (transitive packages, filter).")


class EdgeOut(BaseModel):
    from_node: str
    to_node: str
    kind: str
    resolution: str
    version_requested: str | None = None
    frameworks: list[str] = []
    closes_cycle: bool = False
    declared_file: str | None = None
    declared_line: int | None = None


class ChildOut(BaseModel):
    edge: EdgeOut
    node: NodeOut


class HierarchySummaryOut(BaseModel):
    project_count: int
    count_by_project_kind: dict[str, int]
    package_count: int
    internal_package_count: int
    external_package_count: int
    transitive_package_count: int
    assembly_count: int
    edge_count: int
    count_by_edge_kind: dict[str, int]
    cycle_count: int
    not_checked_count: int


class HierarchyOut(BaseModel):
    repository_id: str
    step_execution_id: str | None
    summary: HierarchySummaryOut
    roots: list[NodeOut] = Field(description="The projects no other project in the repository references.")


class ChildrenOut(BaseModel):
    node_id: str
    total: int = Field(description="Children under the current view; `items` is one page of them.")
    offset: int
    items: list[ChildOut]


class PathStepOut(BaseModel):
    node: NodeOut
    edge: EdgeOut | None = Field(description="The edge from the previous step; null for the root.")


class SearchMatchOut(BaseModel):
    node: NodeOut
    path: list[PathStepOut] | None = Field(description="A shortest path from a root under the current view; null when there is none.")
    unreachable_reason: str | None = None


class SearchOut(BaseModel):
    query: str
    total: int = Field(description="Every node whose name matches; `matches` holds the first 20.")
    matches: list[SearchMatchOut]


class WorkItemOut(BaseModel):
    item_id: str
    item_name: str
    project_path: str | None
    file_path: str | None
    value: str | None


class NodeDetailOut(BaseModel):
    node: NodeOut
    detail: dict = Field(description="The node as dependency-hierarchy's artifact records it.")
    parents_total: int
    parents: list[ChildOut] = Field(description="The first 20 nodes that depend on it, each with its edge.")
    work_items: list[WorkItemOut]
