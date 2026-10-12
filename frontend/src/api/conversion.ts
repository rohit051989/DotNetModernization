import { api, apiUrl } from './client'
import type { RepositoryConversion } from '../types/conversion'

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
