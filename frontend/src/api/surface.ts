import { api } from './client'
import type { EntryPointCapabilities, EntryPointInventory } from '../types/surface'

/** 409 until step 4 (entry-point-inventory) has run for the repository. */
export function getRepositoryEntryPoints(repositoryId: string) {
  return api.get<EntryPointInventory>(`/api/repositories/${encodeURIComponent(repositoryId)}/entry-points`)
}

/** Step 4's capability manifest: every kind it detects, what it does not,
 * and how often each kind is found across the estate. */
export function getEntryPointCapabilities() {
  return api.get<EntryPointCapabilities>('/api/workflow/steps/entry-point-inventory/capabilities')
}
