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

export interface DashboardTopPattern {
  pattern_id: string
  pattern_name: string
  count: number
}

export interface DashboardPatternCounts {
  projects_evaluated: number
  projects_matched: number
  projects_ambiguous: number
  projects_no_pattern_matched: number
  top_patterns: DashboardTopPattern[]
}

export interface DashboardCapabilities {
  application_count: boolean
  pattern_classification: boolean
  impact_map: boolean
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
  patterns: DashboardPatternCounts | null
  risk_tiers: Record<string, unknown> | null
  waves: Record<string, unknown> | null
  decisions: DashboardDecisionCounts
  capabilities: DashboardCapabilities
  recent_executions: DashboardRecentExecution[]
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
  patterns_identified: number | null
  highest_risk_tier: string | null
  wave: string | null
}

const NON_TERMINAL_BATCH_STATUSES = new Set(['STARTING', 'STARTED', 'STOPPING'])

export function isExecutionTerminal(batchStatus: string): boolean {
  return !NON_TERMINAL_BATCH_STATUSES.has(batchStatus)
}
