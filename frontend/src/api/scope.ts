import { api } from './client'
import type { ConversionScope, ScopeSaved } from '../types/scope'

/** The repository's conversion scope: its solutions and projects, which are excluded, and the totals. */
export function getConversionScope(repositoryId: string) {
  return api.get<ConversionScope>(`/api/repositories/${encodeURIComponent(repositoryId)}/scope`)
}

/** Saves the scope: every project left out, and why. Refused (422 SCOPE_INVALID) with every problem listed, or when
 * someone else saved first (409 STALE_COPY). `version`: the scope's version the edit was made on. */
export function saveConversionScope(repositoryId: string, excluded: string[], reason: string | null, version: number) {
  return api.put<ScopeSaved>(`/api/repositories/${encodeURIComponent(repositoryId)}/scope`, { excluded, reason }, { version })
}
