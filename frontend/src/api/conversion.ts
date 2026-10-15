import { api, apiUrl } from './client'
import type { CurrentConversion, RepositoryConversion } from '../types/conversion'

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

/** The repository's current conversion: status, worktree, branch, runbook, opening message and verification. */
export function getCurrentConversion(repositoryId: string) {
  return api.get<CurrentConversion>(`/api/repositories/${encodeURIComponent(repositoryId)}/conversions/current`)
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
