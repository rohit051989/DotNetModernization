// The repository's dependency graph, as the Structure section reads it (37-DEPENDENCY-HIERARCHY.md Part E;
// backend/app/hierarchy/schemas.py).

export type HierarchyNodeType = 'project' | 'package' | 'assembly'
export type HierarchyShow = 'all' | 'internal' | 'external' | 'projects'
export type HierarchyEdgeKind =
  | 'project_reference'
  | 'package_reference'
  | 'central_package_version'
  | 'packages_config'
  | 'assembly_reference'
  | 'package_dependency'

export interface HierarchyView {
  transitive: boolean
  show: HierarchyShow
}

export interface HierarchyFindings {
  vulnerable: boolean
  vulnerability_max_severity: string | null
  outdated: boolean
  deprecated: boolean
  outcome: string | null
}

export interface HierarchyNode {
  id: string
  type: HierarchyNodeType
  name: string
  status: 'checked' | 'not_checked'
  not_checked_reason: string | null
  kind: 'application' | 'library' | 'test' | 'other' | null
  origin: 'internal' | 'external' | 'unknown' | null
  location: 'repository' | 'outside_repository' | 'gac' | 'framework' | null
  version: string | null
  target_frameworks: string[]
  legacy: boolean
  transitive: boolean
  findings: HierarchyFindings
  work_items: number
  referenced_by: number
  child_count: number
}

export interface HierarchyEdge {
  from_node: string
  to_node: string
  kind: HierarchyEdgeKind
  resolution: 'declared' | 'assets_file' | 'feed_metadata'
  version_requested: string | null
  frameworks: string[]
  closes_cycle: boolean
  declared_file: string | null
  declared_line: number | null
}

export interface HierarchyChild {
  edge: HierarchyEdge
  node: HierarchyNode
}

export interface HierarchySummary {
  project_count: number
  count_by_project_kind: Record<string, number>
  package_count: number
  internal_package_count: number
  external_package_count: number
  transitive_package_count: number
  assembly_count: number
  edge_count: number
  count_by_edge_kind: Record<string, number>
  cycle_count: number
  not_checked_count: number
}

export interface HierarchyOverview {
  repository_id: string
  step_execution_id: string | null
  summary: HierarchySummary
  roots: HierarchyNode[]
}

export interface HierarchyChildren {
  node_id: string
  total: number
  offset: number
  items: HierarchyChild[]
}

export interface HierarchyPathStep {
  node: HierarchyNode
  edge: HierarchyEdge | null
}

export interface HierarchySearchMatch {
  node: HierarchyNode
  path: HierarchyPathStep[] | null
  unreachable_reason: string | null
}

export interface HierarchySearch {
  query: string
  total: number
  matches: HierarchySearchMatch[]
}

export interface HierarchyWorkItem {
  item_id: string
  item_name: string
  project_path: string | null
  file_path: string | null
  value: string | null
}

export interface HierarchyNodeDetail {
  node: HierarchyNode
  detail: Record<string, unknown>
  parents_total: number
  parents: HierarchyChild[]
  work_items: HierarchyWorkItem[]
}
