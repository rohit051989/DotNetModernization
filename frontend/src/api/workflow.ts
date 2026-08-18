import { api, apiUrl } from './client'
import type {
  ArtifactDetail,
  ArtifactSummary,
  JobDefinitionSummary,
  JobExecution,
  JobExecutionDetail,
  JobParametersResponse,
  ListExecutionsFilters,
  StepExecution,
} from '../types/workflow'

export function listJobDefinitions() {
  return api.get<JobDefinitionSummary[]>('/api/workflow/jobs')
}

export function getJobParameters(jobName: string) {
  return api.get<JobParametersResponse>(`/api/workflow/jobs/${encodeURIComponent(jobName)}/parameters`)
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
