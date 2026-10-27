import { api } from './client'
import type {
  EngagementStructureSummary,
  ProjectDetail,
  ProjectReference,
  RepositoryStructure,
} from '../types/structure'

/** warnings false: without parse_warnings (parse_warning_count still says how many), which the UI pages. */
export function getRepositoryStructure(repositoryId: string, warnings = true) {
  return api.get<RepositoryStructure>(`/api/repositories/${encodeURIComponent(repositoryId)}/structure${warnings ? '' : '?warnings=false'}`)
}

export function listRepositoryProjectReferences(repositoryId: string) {
  return api.get<ProjectReference[]>(`/api/repositories/${encodeURIComponent(repositoryId)}/project-references`)
}

export function getProjectDetail(projectId: string) {
  return api.get<ProjectDetail>(`/api/projects/${encodeURIComponent(projectId)}`)
}

export function getEngagementStructureSummary(engagementId: string) {
  return api.get<EngagementStructureSummary>(`/api/engagements/${encodeURIComponent(engagementId)}/structure-summary`)
}
