import { api, apiUrl } from './client'
import type { ConversionEngine } from '../types/catalog'
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

/** The repository's own conversion engine (its owner), or null for the engagement's default. A conversion not yet run
 * is prepared again for it. */
export function setConversionEngine(repositoryId: string, engine: ConversionEngine | null) {
  return api.put<{ engine: ConversionEngine; source: 'repository' | 'engagement'; note: string; reprepare_job_execution_id: string | null }>(
    `/api/repositories/${encodeURIComponent(repositoryId)}/conversion-engine`,
    { engine },
  )
}

/** Verifies a conversion that has been run, as a workflow job. 409, with the reason, when refused. */
export function verifyConversion(repositoryId: string, number: number) {
  return api.post<{ job_execution_id: string }>(
    `/api/repositories/${encodeURIComponent(repositoryId)}/conversions/${number}/verify`,
  )
}
