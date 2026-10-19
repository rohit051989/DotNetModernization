import type { JobExecution } from './workflow'

export type { JobExecution }

export type Criticality = 'low' | 'medium' | 'high' | 'critical'
export type RetirementStatus = 'active' | 'slated_for_retirement' | 'decommissioned'
export type CloneUrlVerification = 'verified' | 'mismatch' | 'unverifiable' | 'not_applicable'
export type IngestStatus = 'registered' | 'cloning' | 'scanned' | 'scan_failed' | 'path_missing'
export type SourceType = 'local_path' | 'git_clone'
export type SourceStatus = 'active' | 'archived' | 'disabled' | 'inaccessible'
export type SourceControlStatus = 'GIT' | 'NONE'

export interface PrimaryLanguage {
  language: string
  file_count: number
  percentage: number
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
  /** git's latest progress line while the repository is cloned or fetched (ingest_status 'cloning'). */
  clone_progress: string | null
  ingest_error: string | null
}

export interface RepositoryDetail extends RepositorySummary {
  local_path: string
  clone_url: string | null
  source_control_status: SourceControlStatus
  detected_clone_url: string | null
  default_branch: string | null
  description: string | null
  technical_owner: string | null
  tags: string[]
  notes: string | null
  ingest_commit_sha: string | null
  ingest_token: string | null
  first_registered_at: string | null
  created_at: string
  updated_at: string
  deleted_by: string | null
  organization: string | null
  last_commit_date: string | null
  primary_languages: PrimaryLanguage[] | null
  source_status: SourceStatus | null
  latest_execution: JobExecution | null
  /** Existing data a later rule would refuse, reported and left working. */
  warnings: string[]
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
  source_control_status: SourceControlStatus
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
  clone_url?: string | null
  description?: string | null
  technical_owner?: string | null
  criticality: Criticality
  retirement_status: RetirementStatus
  default_branch?: string | null
  tags: string[]
  notes?: string | null
}

/** Registering by git URL: the discovery job clones it (docs/VDI-SETUP.md: Registering a client repository). */
export interface RegisterGitCloneInput {
  source_type: 'git_clone'
  clone_url: string
  branch?: string | null
  target_folder?: string | null
  name?: string | null
  description?: string | null
  technical_owner?: string | null
  criticality: Criticality
  retirement_status: RetirementStatus
  tags: string[]
  notes?: string | null
}

export interface InspectUrlResult {
  problems: string[]
  suggested_name: string | null
  repos_dir: string | null
  target_folder: string | null
  target_action: 'clone' | 'reuse' | 'refuse' | null
  target_message: string | null
  duplicate_conflict: DuplicateConflict | null
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
    item_detection: boolean
    test_coverage: boolean
    risk_tier: boolean
  }
}
