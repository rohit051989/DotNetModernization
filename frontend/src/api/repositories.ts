import { api } from './client'
import type {
  InspectPathResult,
  InspectUrlResult,
  RegisterGitCloneInput,
  JobExecution,
  RegisterLocalPathInput,
  RegisterRepositoryResult,
  RepositoryDetail,
  RepositorySummary,
  RepositoryUpdateInput,
  RescanResult,
  VerifyPathResult,
  WorkflowCapabilities,
} from '../types/repositories'

export function inspectPath(engagementId: string, localPath: string) {
  return api.post<InspectPathResult>(
    `/api/engagements/${encodeURIComponent(engagementId)}/repositories/inspect-path`,
    { local_path: localPath },
  )
}

export function inspectUrl(engagementId: string, cloneUrl: string, targetFolder: string | null) {
  return api.post<InspectUrlResult>(
    `/api/engagements/${encodeURIComponent(engagementId)}/repositories/inspect-url`,
    { clone_url: cloneUrl, target_folder: targetFolder },
  )
}

export function registerRepository(engagementId: string, payload: RegisterLocalPathInput | RegisterGitCloneInput) {
  return api.post<RegisterRepositoryResult>(
    `/api/engagements/${encodeURIComponent(engagementId)}/repositories/register`,
    payload,
  )
}

export interface ListRepositoriesFilters {
  ingestStatus?: string
  criticality?: string
  retirementStatus?: string
  q?: string
  includeDeleted?: boolean
}

export function listRepositories(engagementId: string, filters: ListRepositoriesFilters = {}) {
  const params = new URLSearchParams()
  if (filters.ingestStatus) params.set('ingest_status', filters.ingestStatus)
  if (filters.criticality) params.set('criticality', filters.criticality)
  if (filters.retirementStatus) params.set('retirement_status', filters.retirementStatus)
  if (filters.q) params.set('q', filters.q)
  if (filters.includeDeleted) params.set('include_deleted', 'true')
  const query = params.toString()
  return api.get<RepositorySummary[]>(
    `/api/engagements/${encodeURIComponent(engagementId)}/repositories${query ? `?${query}` : ''}`,
  )
}

export function getRepository(repositoryId: string) {
  return api.get<RepositoryDetail>(`/api/repositories/${encodeURIComponent(repositoryId)}`)
}

export function updateRepository(repositoryId: string, payload: RepositoryUpdateInput) {
  return api.put<RepositoryDetail>(`/api/repositories/${encodeURIComponent(repositoryId)}`, payload)
}

export function deleteRepository(repositoryId: string) {
  return api.delete<{ id: string; deleted_at: string }>(
    `/api/repositories/${encodeURIComponent(repositoryId)}`,
  )
}

export function restoreRepository(repositoryId: string) {
  return api.post<{ id: string; deleted_at: null }>(
    `/api/repositories/${encodeURIComponent(repositoryId)}/restore`,
  )
}

export function rescanRepository(repositoryId: string) {
  return api.post<RescanResult>(`/api/repositories/${encodeURIComponent(repositoryId)}/rescan`)
}

export function verifyRepositoryPath(repositoryId: string) {
  return api.post<VerifyPathResult>(`/api/repositories/${encodeURIComponent(repositoryId)}/verify-path`)
}

export function listRepositoryExecutions(repositoryId: string) {
  return api.get<JobExecution[]>(`/api/repositories/${encodeURIComponent(repositoryId)}/executions`)
}

export function getWorkflowCapabilities() {
  return api.get<WorkflowCapabilities>('/api/workflow/capabilities')
}
