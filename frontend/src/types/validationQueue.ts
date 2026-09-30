/** The human-gate queue — docs/27-STEP-006-PATTERN-VALIDATION.md Part B.
 *
 * Generic across gate types. Step 6 (`pattern_candidate`) is the first
 * consumer; steps 22, 38 and 50 add item types here without schema change,
 * which is why nothing below is pattern-specific except `PatternCandidatePayload`. */

export type QueueItemStatus = 'open' | 'decided' | 'superseded' | 'withdrawn'

export type ItemType =
  | 'pattern_candidate'
  | 'target_state_selection'
  | 'migration_plan'
  | 'code_review'
  | 'release_approval'

/** Step 6's outcomes. `defer` is not one — it goes through its own endpoint,
 * because deferring is a decision about *when* to decide, not what. */
export type PatternCandidateOutcome = 'create_pattern' | 'merge_into_pattern' | 'reject'

export interface PreviousDecision {
  outcome: string | null
  decision_note: string | null
  decided_by: string | null
  decided_at: string | null
  member_count_then: number | null
  coverage_then: number | null
}

export interface PatternCandidatePayload {
  cluster_id: string
  cluster_method: string
  member_count: number
  repository_count: number
  repository_distribution: Record<string, number>
  cohesion: number | null
  is_singleton: boolean
  canonical_signature: { facets: Record<string, string | null>; signals: string[] }
  similar_patterns: { pattern_id: string; similarity: number }[]
  suggested_name: string | null
  suggested_description: string | null
  naming_source: string
  sample_members: { project_path: string; repository_slug: string }[]
  /** What the reviewer could see when the question was raised. Mandatory on
   * every card — a two-member cluster at 24% coverage and the same cluster at
   * 90% are different evidence. */
  coverage_at_raise: {
    repositories_included: number
    repositories_pending: number
    coverage_ratio: number | null
  }
  is_rereview: boolean
  previous_decision: PreviousDecision | null
}

export interface QueueItem {
  id: string
  engagement_id: string
  job_execution_id: string
  step_execution_id: string
  step_name: string
  item_type: ItemType
  item_key: string
  title: string
  payload: PatternCandidatePayload | Record<string, unknown>
  status: QueueItemStatus
  outcome: string | null
  outcome_detail: Record<string, unknown> | null
  decision_note: string | null
  decided_by: string | null
  decided_at: string | null
  /** Open, but set aside until the evidence improves. Deferred items do not
   * block their gate. */
  is_deferred: boolean
  deferred_until_coverage: number | null
  deferred_until_member_count: number | null
  priority: number
  created_at: string
}

export interface QueueSummaryGroup {
  step_name: string
  item_type: ItemType
  open_count: number
  deferred_count: number
  decided_count: number
}

export interface BlockedExecution {
  job_execution_id: string
  batch_status: string
  exit_status: string
  open_item_count: number
}

export interface QueueSummary {
  engagement_id: string
  open_count: number
  deferred_count: number
  decided_count: number
  superseded_count: number
  withdrawn_count: number
  by_step: QueueSummaryGroup[]
  blocked_executions: BlockedExecution[]
}

export interface DraftPattern {
  cluster_id: string
  is_draft: boolean
  pattern: {
    id: string
    name: string
    rules_status: string
    anchor_signals: string[]
    detection_rules: {
      all: { id: string }[]
      supporting: { id: string; weight: number }[]
      metadata: { id: string; field: string; equals: string }[]
    }
  }
  anchor_ranking: {
    signal_name: string
    projects_with_signal: number
    engagement_project_count: number
    prevalence: number
  }[]
  notes: string[]
}

export interface MergeProposal {
  cluster_id: string
  pattern_id: string
  /** Always false — widening a master-catalog pattern is its own reviewed edit. */
  applied: boolean
  signals_missing_from_pattern: string[]
  signals_already_covered: string[]
  proposed_additions: {
    group: string
    id: string
    signal: { name: string }
    weight: number
    present_on_members: number
    of_members: number
  }[]
  impact: Record<string, unknown>
  notes: string[]
}
