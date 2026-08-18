import { api } from './client'
import type {
  EngagementStructureSummary,
  ProjectDetail,
  ProjectReference,
  ProjectSummary,
  RepositoryArtifact,
  RepositoryStructure,
  Solution,
} from '../types/structure'

export function getRepositoryStructure(repositoryId: string) {
  return api.get<RepositoryStructure>(`/api/repositories/${encodeURIComponent(repositoryId)}/structure`)
}

export function listRepositorySolutions(repositoryId: string) {
  return api.get<Solution[]>(`/api/repositories/${encodeURIComponent(repositoryId)}/solutions`)
}

export function listRepositoryProjects(repositoryId: string) {
  return api.get<ProjectSummary[]>(`/api/repositories/${encodeURIComponent(repositoryId)}/projects`)
}

export function listRepositoryProjectReferences(repositoryId: string) {
  return api.get<ProjectReference[]>(`/api/repositories/${encodeURIComponent(repositoryId)}/project-references`)
}

export function listRepositoryArtifacts(repositoryId: string) {
  return api.get<RepositoryArtifact[]>(`/api/repositories/${encodeURIComponent(repositoryId)}/artifacts`)
}

export function getProjectDetail(projectId: string) {
  return api.get<ProjectDetail>(`/api/projects/${encodeURIComponent(projectId)}`)
}

export function getEngagementStructureSummary(engagementId: string) {
  return api.get<EngagementStructureSummary>(`/api/engagements/${encodeURIComponent(engagementId)}/structure-summary`)
}
