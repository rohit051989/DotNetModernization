export type BatchStatus =
  | 'STARTING'
  | 'STARTED'
  | 'COMPLETED'
  | 'FAILED'
  | 'STOPPING'
  | 'STOPPED'
  | 'ABANDONED'
  | 'UNKNOWN'

export type ExitStatus = 'COMPLETED' | 'FAILED' | 'NOOP' | 'AWAITING_APPROVAL' | 'NOT_IMPLEMENTED' | 'SKIPPED' | string

/** Null unless exit_status is SKIPPED — see 22-STEP-SEQUENCING-AND-POLICY.md Part D. */
export type SkipReason = 'POLICY_DISABLED' | 'CONDITION_FALSE' | 'TIER_NOT_APPLICABLE' | 'UPSTREAM_SKIPPED' | 'CASCADED_POLICY'

export interface JobDefinitionSummary {
  job_name: string
  active_version: number
  description: string | null
  scope: 'per_repository' | 'per_engagement' | 'other'
  step_count: number
  implemented_step_count: number
  stub_step_count: number
}

export interface JobParameter {
  name: string
  type: string
  required: boolean
  default: unknown
  description: string | null
}

export interface JobParametersResponse {
  job_name: string
  definition_version: number
  parameters: JobParameter[]
}

export interface StepSummary {
  total: number
  completed: number
  not_implemented: number
  skipped: number
  failed: number
  pending: number
}

export interface JobExecution {
  id: string
  job_name: string
  job_instance_id: string
  job_definition_id: string
  job_definition_version: number
  execution_number: number
  batch_status: BatchStatus
  exit_status: ExitStatus | null
  exit_message: string | null
  execution_context: Record<string, unknown>
  parameters: Record<string, unknown>
  engine_version: string
  triggered_by: string | null
  started_at: string | null
  ended_at: string | null
  duration_seconds: number | null
  created_at: string
  resolved_context: Record<string, string>
  step_summary: StepSummary
  artifact_count: number
  can_restart: boolean
  can_resume: boolean
}

export interface DiagnosticEntry {
  level: 'info' | 'warning' | 'error'
  code: string
  message: string
  ref: string | null
}

export interface ResolvedInputRef {
  logical_name: string
  artifact_type: string
  artifact_version: string
  artifact_id: string
}

export interface ProducedOutputRef {
  artifact_id: string
  artifact_type: string
  artifact_version: string
}

export interface StepMetrics {
  read_count: number
  write_count: number
  skip_count: number
  commit_count: number
}

export interface StepExecution {
  step_execution_id: string
  job_execution_id: string
  step_name: string
  lifecycle_step_no: number | null
  display_name: string
  owner_code: string
  step_version: string
  adapter_type: string
  implementation_status: 'stub' | 'implemented' | 'deprecated'
  sequence: number
  partition_key: string | null
  attempt: number
  batch_status: BatchStatus
  exit_status: ExitStatus | null
  exit_message: string | null
  skip_reason: SkipReason | null
  metrics: StepMetrics
  started_at: string | null
  ended_at: string | null
  duration_seconds: number | null
  diagnostics: DiagnosticEntry[]
  inputs_resolved: ResolvedInputRef[]
  outputs_produced: ProducedOutputRef[]
  stdout_tail: string | null
  stderr_tail: string | null
  working_dir: string | null
  carried_forward: boolean
}

export interface JobExecutionDetail extends JobExecution {
  steps: StepExecution[]
}

export interface ArtifactSummary {
  id: string
  artifact_type: string
  artifact_version: string
  size_bytes: number | null
  checksum: string
  step_name: string
  step_execution_id: string
  created_at: string
}

export interface ArtifactDetail extends ArtifactSummary {
  job_execution_id: string
  uri: string
  resolved_path: string | null
  file_exists: boolean
  metadata: Record<string, unknown> | null
}

export interface ListExecutionsFilters {
  jobName?: string
  batchStatus?: string
  engagementId?: string
  repositoryId?: string
  limit?: number
  offset?: number
}

const NON_TERMINAL_BATCH_STATUSES = new Set(['STARTING', 'STARTED', 'STOPPING'])

export function isExecutionTerminal(batchStatus: string): boolean {
  return !NON_TERMINAL_BATCH_STATUSES.has(batchStatus)
}

// ---- Job definition viewer — 22-STEP-SEQUENCING-AND-POLICY.md Part E ----

export interface ArtifactRefView {
  artifact_type: string
  artifact_version: string | null
  version_range: string | null
  optional: boolean | null
}

export interface FlowStepPolicy {
  enabled: boolean
  source: 'default' | 'engagement'
  reason: string | null
}

export interface FlowStepView {
  sequence: number
  step_name: string
  lifecycle_step_no: number | null
  display_name: string
  owner_code: string
  adapter_type: string
  implementation_status: string
  step_version: string
  consumes: ArtifactRefView[]
  produces: ArtifactRefView[]
  inputs: Record<string, string>
  when: Record<string, unknown> | null
  when_description: string | null
  gate: Record<string, unknown> | null
  policy: FlowStepPolicy
}

export interface JobDefinitionView {
  job_name: string
  version: number
  is_active: boolean
  validation_status: string
  description: string | null
  implemented_step_count: number
  step_count: number
  parameters: JobParameter[]
  flow: FlowStepView[]
  raw_yaml: string | null
}
