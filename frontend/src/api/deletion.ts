import { api } from './client'
import type { DeletionPlan, DeletionSummary } from '../types/deletion'

/** What a hard delete of the repository would remove (nothing is removed). */
export function getRepositoryDeletionPlan(repositoryId: string) {
  return api.get<DeletionPlan>(`/api/repositories/${encodeURIComponent(repositoryId)}/deletion`)
}

/** Hard deletes the repository from its engagement. 409 when refused, with the reason. */
export function deleteRepositoryHard(repositoryId: string, confirm: string) {
  return api.post<DeletionSummary>(`/api/repositories/${encodeURIComponent(repositoryId)}/deletion`, { confirm })
}

/** What a hard delete of the engagement would remove (nothing is removed). */
export function getEngagementDeletionPlan(engagementId: string) {
  return api.get<DeletionPlan>(`/api/engagements/${encodeURIComponent(engagementId)}/deletion`)
}

/** Hard deletes the engagement and every repository in it. 409 when refused, with the reason. */
export function deleteEngagementHard(engagementId: string, confirm: string) {
  return api.post<DeletionSummary>(`/api/engagements/${encodeURIComponent(engagementId)}/deletion`, { confirm })
}
