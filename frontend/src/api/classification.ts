import { api } from './client'
import type {
  CatalogCoverage,
  ClassificationListItem,
  ClassificationSummary,
  PatternDistribution,
  PendingSignalPromotion,
  ProjectClassificationDetail,
} from '../types/classification'

export function getRepositoryClassificationSummary(repositoryId: string) {
  return api.get<ClassificationSummary>(
    `/api/repositories/${encodeURIComponent(repositoryId)}/classification-summary`,
  )
}

export interface ListClassificationsFilters {
  status?: string
  pattern_id?: string
  role?: string
}

export function listRepositoryClassifications(repositoryId: string, filters: ListClassificationsFilters = {}) {
  const params = new URLSearchParams()
  if (filters.status) params.set('status', filters.status)
  if (filters.pattern_id) params.set('pattern_id', filters.pattern_id)
  if (filters.role) params.set('role', filters.role)
  const query = params.toString()
  return api
    .get<{ repository_id: string; projects: ClassificationListItem[] }>(
      `/api/repositories/${encodeURIComponent(repositoryId)}/classifications${query ? `?${query}` : ''}`,
    )
    .then((result) => result.projects)
}

export function getProjectClassification(projectId: string) {
  return api.get<ProjectClassificationDetail>(`/api/projects/${encodeURIComponent(projectId)}/classification`)
}

export function getPatternDistribution(engagementId: string) {
  return api.get<PatternDistribution>(`/api/engagements/${encodeURIComponent(engagementId)}/pattern-distribution`)
}

export function getCatalogCoverage(engagementId: string) {
  return api.get<CatalogCoverage>(`/api/engagements/${encodeURIComponent(engagementId)}/catalog-coverage`)
}

export function getPendingSignalPromotions() {
  return api.get<PendingSignalPromotion[]>('/api/catalog/pending-signals')
}
