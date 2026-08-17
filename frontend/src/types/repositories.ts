export type Criticality = 'low' | 'medium' | 'high' | 'critical'
export type RetirementStatus = 'active' | 'slated_for_retirement' | 'decommissioned'
export type CloneUrlVerification = 'verified' | 'mismatch' | 'unverifiable'
export type IngestStatus = 'registered' | 'scanned' | 'scan_failed' | 'path_missing'
export type SourceType = 'local_path' | 'git_clone'

export interface JobExecution {
  id: string
  job_name: string
  job_instance_id: string
  job_definition_id: string
  execution_number: number
  batch_status: string
  exit_status: string | null
  exit_message: string | null
  execution_context: Record<string, unknown>
  engine_version: string
  triggered_by: string | null
  started_at: string | null
  ended_at: string | null
  created_at: string
}

export interface StepExecution {
  id: string
  job_execution_id: string
  step_name: string
  step_version: string
  partition_key: string | null
  attempt: number
  batch_status: string
  exit_status: string | null
  exit_message: string | null
  read_count: number
  write_count: number
  skip_count: number
  commit_count: number
  started_at: string | null
  ended_at: string | null
}

export interface RepositorySummary {
  id: string
  engagement_id: string
  name: string
  root_folder_name: string
  slug: string
  source_type: SourceType
  provider: string | null
  criticality: Criticality
  retirement_status: RetirementStatus
  ingest_status: IngestStatus
  has_git_history: boolean
  clone_url_verification: CloneUrlVerification
  size_bytes: number | null
  file_count: number | null
  last_scanned_at: string | null
  deleted_at: string | null
}

export interface RepositoryDetail extends RepositorySummary {
  local_path: string
  clone_url: string
  detected_clone_url: string | null
  default_branch: string | null
  description: string | null
  technical_owner: string | null
  tags: string[]
  notes: string | null
  ingest_commit_sha: string | null
  ingest_error: string | null
  ingest_token: string | null
  first_registered_at: string | null
  created_at: string
  updated_at: string
  deleted_by: string | null
  latest_execution: JobExecution | null
}

export interface DuplicateConflict {
  matched_on: 'clone_url' | 'root_folder_name' | 'local_path'
  repository_id: string
  slug: string
  message: string
}

export interface InspectPathResult {
  exists: boolean
  is_directory: boolean
  root_folder_name: string | null
  suggested_name: string | null
  suggested_slug: string | null
  has_git: boolean
  detected_clone_url: string | null
  detected_provider: string | null
  detected_branch: string | null
  detected_commit_sha: string | null
  estimated_file_count: number | null
  estimated_size_bytes: number | null
  solution_files_found: number | null
  project_files_found: number | null
  duplicate_conflict: DuplicateConflict | null
  warnings: string[]
}

export interface RegisterLocalPathInput {
  source_type: 'local_path'
  local_path: string
  name?: string | null
  clone_url: string
  description?: string | null
  technical_owner?: string | null
  criticality: Criticality
  retirement_status: RetirementStatus
  default_branch?: string | null
  tags: string[]
  notes?: string | null
}

export interface RegisterRepositoryResult {
  repository_id: string
  slug: string
  ingest_token: string
  job_execution_id: string
  clone_url_verification: CloneUrlVerification
  status: 'processing'
}

export interface RepositoryUpdateInput {
  name: string
  description: string | null
  technical_owner: string | null
  criticality: Criticality
  retirement_status: RetirementStatus
  tags: string[]
  notes: string | null
  default_branch: string | null
}

export interface RescanResult {
  repository_id: string
  ingest_token: string
  job_execution_id: string
  status: 'processing'
}

export interface VerifyPathResult {
  repository_id: string
  exists: boolean
  ingest_status: IngestStatus
}

export interface WorkflowCapabilities {
  implemented_steps: string[]
  metrics_available: {
    repository_count: boolean
    application_count: boolean
    pattern_classification: boolean
    impact_map: boolean
    test_coverage: boolean
    risk_tier: boolean
  }
}
