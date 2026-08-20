import { api, apiUrl } from './client'
import type {
  ArtifactDetail,
  ArtifactSummary,
  JobDefinitionAdmin,
  JobDefinitionFull,
  JobDefinitionSummary,
  JobDefinitionView,
  JobExecution,
  JobExecutionDetail,
  JobParametersResponse,
  ListExecutionsFilters,
  StepExecution,
} from '../types/workflow'

export function listJobDefinitions() {
  return api.get<JobDefinitionSummary[]>('/api/workflow/jobs')
}

/** Every stored version of every job, active or not, valid or not — the
 * Workflow Administration tab's Job definitions section
 * (23-WORKFLOW-ADMINISTRATION.md Part C2). */
export function listAllJobDefinitions() {
  return api.get<JobDefinitionAdmin[]>('/api/workflow/jobs/all-versions')
}

/** One stored version's full detail (definition, validation errors, raw
 * YAML), active or not. */
export function getJobDefinitionVersion(jobName: string, version: number) {
  return api.get<JobDefinitionFull>(`/api/workflow/jobs/${encodeURIComponent(jobName)}/versions/${version}`)
}

/** Permanently discards a stored version — refused with 409 if it's active
 * or if any execution still references it (12-JOB-DEFINITION-FORMAT.md:
 * use validate, not store, for demonstrations and experiments). */
export function deleteJobDefinitionVersion(jobName: string, version: number) {
  return api.delete<void>(`/api/workflow/jobs/${encodeURIComponent(jobName)}/versions/${version}`)
}

export function getJobParameters(jobName: string) {
  return api.get<JobParametersResponse>(`/api/workflow/jobs/${encodeURIComponent(jobName)}/parameters`)
}

/** 22-STEP-SEQUENCING-AND-POLICY.md Part E — the active definition resolved
 * for display, with policy state merged in when `engagementId` is given. */
export function getJobDefinitionView(jobName: string, engagementId?: string) {
  const query = engagementId ? `?engagement_id=${encodeURIComponent(engagementId)}` : ''
  return api.get<JobDefinitionView>(`/api/workflow/jobs/${encodeURIComponent(jobName)}/definition${query}`)
}

export function launchJob(jobName: string, parameters: Record<string, unknown>) {
  return api.post<JobExecution>(`/api/workflow/jobs/${encodeURIComponent(jobName)}/launch`, { parameters })
}

export function listExecutions(filters: ListExecutionsFilters = {}) {
  const params = new URLSearchParams()
  if (filters.jobName) params.set('job_name', filters.jobName)
  if (filters.batchStatus) params.set('batch_status', filters.batchStatus)
  if (filters.engagementId) params.set('engagement_id', filters.engagementId)
  if (filters.repositoryId) params.set('repository_id', filters.repositoryId)
  if (filters.limit) params.set('limit', String(filters.limit))
  if (filters.offset) params.set('offset', String(filters.offset))
  const query = params.toString()
  return api.get<JobExecution[]>(`/api/workflow/executions${query ? `?${query}` : ''}`)
}

export function getExecution(executionId: string) {
  return api.get<JobExecutionDetail>(`/api/workflow/executions/${encodeURIComponent(executionId)}`)
}

export function getExecutionSteps(executionId: string) {
  return api.get<StepExecution[]>(`/api/workflow/executions/${encodeURIComponent(executionId)}/steps`)
}

export function resumeExecution(executionId: string) {
  return api.post<JobExecution>(`/api/workflow/executions/${encodeURIComponent(executionId)}/resume`)
}

export function stopExecution(executionId: string) {
  return api.post<JobExecution>(`/api/workflow/executions/${encodeURIComponent(executionId)}/stop`)
}

export function listExecutionArtifacts(executionId: string) {
  return api.get<ArtifactSummary[]>(`/api/workflow/executions/${encodeURIComponent(executionId)}/artifacts`)
}

export function getArtifact(artifactId: string) {
  return api.get<ArtifactDetail>(`/api/workflow/artifacts/${encodeURIComponent(artifactId)}`)
}

export function getArtifactContent(artifactId: string) {
  return api.get<unknown>(`/api/workflow/artifacts/${encodeURIComponent(artifactId)}/content`)
}

export function artifactDownloadUrl(artifactId: string): string {
  return apiUrl(`/api/workflow/artifacts/${encodeURIComponent(artifactId)}/download`)
}
