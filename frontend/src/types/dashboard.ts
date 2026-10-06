export interface DashboardRepositoryCounts {
  total: number
  registered: number
  scanned: number
  scan_failed: number
  path_missing: number
  total_size_bytes: number
  with_git_history: number
}

export interface DashboardDiscoveryCounts {
  not_started: number
  in_progress: number
  completed: number
  failed: number
  awaiting_approval: number
}

export interface DashboardDecisionCounts {
  total_patterns_in_scope: number
  approved: number
  in_review: number
  parked: number
  deferred: number
}

export interface DashboardStructureCounts {
  repositories_scanned: number
  solution_count: number
  project_file_count: number
  standalone_project_count: number
  unresolved_reference_count: number
  legacy_project_count: number
  sdk_project_count: number
  framework_families: Record<string, number>
}

export interface DashboardRepositoryStructureBrief {
  scan_status: 'complete' | 'partial' | 'failed'
  solution_count: number | null
  project_file_count: number | null
  standalone_project_count: number | null
  framework_families: Record<string, number>
}

export interface DashboardTopItem {
  item_id: string
  item_name: string
  projects: number
  occurrences: number
}

/** Item detection roll-up for the engagement. `null` on the summary until
 * item detection is implemented — never fabricated zeros. */
export interface DashboardItemCounts {
  projects_evaluated: number
  projects_with_findings: number
  items_found: number
  /** Excludes possible occurrences (ambiguous evidence only) unless include_possible is set. */
  occurrences_found: number
  occurrences_possible: number
  projects_needing_rescan: number
  top_items: DashboardTopItem[]
}

export interface DashboardCapabilities {
  application_count: boolean
  item_detection: boolean
  test_coverage: boolean
  risk_tier: boolean
  wave_planning: boolean
}

export interface DashboardRecentExecution {
  job_execution_id: string
  job_name: string
  repository_slug: string | null
  batch_status: string
  exit_status: string | null
  steps_completed: number
  steps_total: number
  started_at: string | null
  ended_at: string | null
}

export interface DashboardSummary {
  engagement_id: string
  client_name: string
  generated_at: string
  repositories: DashboardRepositoryCounts
  discovery: DashboardDiscoveryCounts
  structure: DashboardStructureCounts
  applications: Record<string, unknown> | null
  items: DashboardItemCounts | null
  risk_tiers: Record<string, unknown> | null
  waves: Record<string, unknown> | null
  decisions: DashboardDecisionCounts
  capabilities: DashboardCapabilities
  recent_executions: DashboardRecentExecution[]
  /** Master catalog: items changed since the last export into the repository's catalog/items/. */
  catalog_export: { is_current: boolean; changed: number; last_exported_at: string | null }
}

export interface DashboardStepBrief {
  step_name: string
  display_name: string
  batch_status: string
  exit_status: string | null
  skip_reason: string | null
}

export interface DashboardLatestExecution {
  job_execution_id: string
  batch_status: string
  exit_status: string | null
  steps_completed: number
  steps_not_implemented: number
  steps_skipped: number
  steps_failed: number
  steps_total: number
  current_step: string | null
  steps: DashboardStepBrief[]
  started_at: string | null
  ended_at: string | null
}

export interface DashboardRepositoryRow {
  repository_id: string
  slug: string
  name: string
  source_type: string
  provider: string | null
  ingest_status: string
  has_git_history: boolean
  ingest_commit_sha: string | null
  size_bytes: number | null
  file_count: number | null
  last_ingested_at: string | null
  latest_execution: DashboardLatestExecution | null
  structure: DashboardRepositoryStructureBrief | null
  application_count: number | null
  /** Distinct catalog items found in this repository; null until item
   * detection is implemented. */
  items_found: number | null
  highest_risk_tier: string | null
  wave: string | null
}

const NON_TERMINAL_BATCH_STATUSES = new Set(['STARTING', 'STARTED', 'STOPPING'])

export function isExecutionTerminal(batchStatus: string): boolean {
  return !NON_TERMINAL_BATCH_STATUSES.has(batchStatus)
}
