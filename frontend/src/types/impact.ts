// impact-analysis — 33-IMPACT-ANALYSIS.md Part J.
// Mirrors backend/app/impact/schemas.py.

export type ImpactAction = 'rewrite' | 'update' | 'delete' | 'create' | 'review'
export type ImpactSource = 'structural' | 'client'

export type ActionCounts = Record<ImpactAction, number>

export interface RollupWorkItem {
  item_id: string
  item_name: string
  project_path: string
  resolution_id: string
  resolution_name: string
  action: ImpactAction
  source: ImpactSource
  /** The rules that put this work item on the file. */
  rule_ids: string[]
}

/** A work-item conflict: one pair of work items, for a person to decide. */
export interface ImpactConflict {
  file_key: string
  kind: 'delete_with_change' | 'create_same_path'
  first: RollupWorkItem
  second: RollupWorkItem
}

export interface RuleSide {
  item_id: string
  item_name: string
  resolution_id: string
  resolution_name: string
  rule_ids: string[]
  action: ImpactAction
}

/** A catalog rule conflict as one repository sees it: the rule pair
 * conflicts on more than one pair of work items across the estate. */
export interface RuleConflict {
  rule_key: string
  kind: 'delete_with_change' | 'create_same_path'
  first: RuleSide
  second: RuleSide
  /** Across the estate. */
  work_items: number
  repositories: number
  /** estate: from the last estate run; repository: recurs here, not yet seen by an estate run. */
  classified_by: 'estate' | 'repository'
  /** This repository's instances. */
  instances: ImpactConflict[]
}

export interface EstateRuleConflict {
  rule_key: string
  kind: 'delete_with_change' | 'create_same_path'
  first: RuleSide
  second: RuleSide
  work_items: number
  repositories: number
  computed_at: string
  instances: { repository_id: string; repository_slug: string | null; file_key: string; first_project_path: string; second_project_path: string }[]
}

export interface EngagementRuleConflicts {
  engagement_id: string
  rule_conflicts: EstateRuleConflict[]
  note: string
}

export interface MasterRuleConflict {
  rule_key: string
  kind: 'delete_with_change' | 'create_same_path'
  first: RuleSide
  second: RuleSide
  work_items: number
  repositories: number
  engagements: { engagement_id: string; client_name: string; work_items: number; repositories: number }[]
}

export interface FileRollup {
  /** The file's path, or "create:" and a proposed path. */
  file_key: string
  work_items: RollupWorkItem[]
  hotspot: boolean
  conflicts: number
  includes_client: boolean
}

export interface ResolutionSummary {
  resolution_id: string
  name: string
  /** default, presumptive (an item with no default), chosen. */
  roles: string[]
  effective: boolean
  rules_source: 'explicit' | 'default'
  counts: ActionCounts
  /** Existing files updated, rewritten or deleted — the headline. */
  changed: number
  /** New files. */
  created: number
  /** Files a person should check. Never added to `changed`. */
  to_review: number
  client_changed: number
  client_review: number
  confirmed: number
  possible: number
  known_limits: string[]
  stale: boolean
  stale_reason: string | null
}

export interface WorkItemSummary {
  item_id: string
  item_name: string
  project_path: string
  effective_resolution_id: string
  stale: boolean
  resolutions: ResolutionSummary[]
}

export interface RepositoryImpact {
  /** Every figure reconciles: changes = rewrite + update + delete across
   * files_changed distinct files; creates at new_files paths; review marks on
   * files_to_review files nothing changes. */
  totals: {
    work_items: number
    changes: number
    files_changed: number
    by_action: ActionCounts
    creates: number
    new_files: number
    review_marks: number
    files_to_review: number
    client_changes: number
    hotspots: number
    /** Instances, file by file: rule conflicts' instances plus work-item conflicts. */
    conflicts: number
    rule_conflicts: number
    rule_conflict_work_items: number
    work_item_conflicts: number
    stale_work_items: number
  }
  hotspots: FileRollup[]
  rule_conflicts: RuleConflict[]
  work_item_conflicts: ImpactConflict[]
  work_items: WorkItemSummary[]
  files: FileRollup[]
  client_impact_note: string
}

export interface ImpactEntry {
  /** Set when the file is in another repository (a client). */
  file_repository_slug: string | null
  file_path: string | null
  proposed_path: string | null
  description: string | null
  action: ImpactAction
  certainty: 'confirmed' | 'possible'
  source: ImpactSource
  reasons: { ruleId: string; action: ImpactAction; reason: string }[]
  traversal_paths: string[]
  /** What happens within the file: the config element an update edits, the types it loses. */
  details: string[]
}

export interface ResolutionImpact extends ResolutionSummary {
  entries: ImpactEntry[]
}

export interface WorkItemImpact {
  item_id: string
  item_name: string
  project_path: string
  effective_resolution_id: string
  resolutions: ResolutionImpact[]
  pending: { resolution_id: string; name: string }[]
  pending_note: string
}
