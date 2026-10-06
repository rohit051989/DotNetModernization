import { api } from './client'
import type { EntryPointBackend, EntryPointCapabilities, EntryPointInventory, OutboundInventory } from '../types/surface'

/** 409 until step 4 (entry-point-inventory) has run for the repository. */
export function getRepositoryEntryPoints(repositoryId: string) {
  return api.get<EntryPointInventory>(`/api/repositories/${encodeURIComponent(repositoryId)}/entry-points`)
}

/** Step 4's capability manifest: every kind it detects, what it does not,
 * and how often each kind is found across the estate. */
export function getEntryPointCapabilities() {
  return api.get<EntryPointCapabilities>('/api/workflow/steps/entry-point-inventory/capabilities')
}

/** 409 until step 5 (outbound-invocation-inventory) has run for the repository. */
export function getRepositoryOutboundInvocations(repositoryId: string) {
  return api.get<OutboundInventory>(`/api/repositories/${encodeURIComponent(repositoryId)}/outbound-invocations`)
}

/** Step 5 1.3.0: per application, every inbound operation and the backend calls it reaches. 409 until step 5 has run. */
export function getRepositoryEntryPointBackend(repositoryId: string) {
  return api.get<EntryPointBackend>(`/api/repositories/${encodeURIComponent(repositoryId)}/entry-point-backend`)
}
