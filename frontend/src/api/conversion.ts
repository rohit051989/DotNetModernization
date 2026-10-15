import { api, apiUrl } from './client'
import type { Conversions, RepositoryConversion } from '../types/conversion'

/** The repository's conversion plan (the newest, or `planId`), its units in
 * order, and the test results before and after. 409 until a plan exists. */
export function getRepositoryConversion(repositoryId: string, planId?: string) {
  const query = planId ? `?plan_id=${encodeURIComponent(planId)}` : ''
  return api.get<RepositoryConversion>(`/api/repositories/${encodeURIComponent(repositoryId)}/conversion${query}`)
}

/** An evidence file's link: the server sends it only if it still has the recorded sha256. */
export function evidenceHref(url: string) {
  return apiUrl(url)
}

/** Every conversion of the repository, newest first, and where the next one would start. */
export function listConversions(repositoryId: string) {
  return api.get<Conversions>(`/api/repositories/${encodeURIComponent(repositoryId)}/conversions`)
}

/** Starts the next conversion: discovery runs, then prepares a new conversion. */
export function startNextConversion(repositoryId: string) {
  return api.post<{ job_execution_id: string }>(`/api/repositories/${encodeURIComponent(repositoryId)}/conversions`)
}

/** Verifies a conversion that has been run, as a workflow job. 409, with the reason, when refused. */
export function verifyConversion(repositoryId: string, number: number) {
  return api.post<{ job_execution_id: string }>(
    `/api/repositories/${encodeURIComponent(repositoryId)}/conversions/${number}/verify`,
  )
}
