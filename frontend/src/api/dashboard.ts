import { api } from './client'
import type { DashboardRepositoryRow, DashboardSummary } from '../types/dashboard'

export function getDashboard(engagementId: string) {
  return api.get<DashboardSummary>(`/api/engagements/${encodeURIComponent(engagementId)}/dashboard`)
}

export function getDashboardRepositories(engagementId: string) {
  return api
    .get<{ repositories: DashboardRepositoryRow[] }>(
      `/api/engagements/${encodeURIComponent(engagementId)}/dashboard/repositories`,
    )
    .then((result) => result.repositories)
}
