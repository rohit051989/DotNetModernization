import { api } from './client'
import type {
  CatalogItem,
  CatalogItemCreateInput,
  CatalogItemWriteInput,
  CatalogItemWriteResult,
  CatalogSignal,
  EngagementDecision,
  EngagementDecisionUpsertInput,
  ExtractorBacklog,
  ItemCoverage,
  ItemResolution,
  ItemScope,
  ItemSignal,
  ReadinessState,
  ItemStatus,
  ResolutionCreateInput,
  ResolutionWriteInput,
  SignalCoverage,
  SignalIndexEntry,
  WorkListDecisions,
  SoftDeleteResult,
} from '../types/items'

const enc = encodeURIComponent

function itemPath(itemId: string) {
  return `/api/catalog/items/${enc(itemId)}`
}

// ---------- items (master catalog) ----------

export function listCatalogItems(
  params: { state?: ReadinessState; scope?: ItemScope; status?: ItemStatus; includeDeleted?: boolean } = {},
) {
  const query = new URLSearchParams()
  if (params.state) query.set('state', params.state)
  if (params.scope) query.set('scope', params.scope)
  if (params.status) query.set('status', params.status)
  if (params.includeDeleted) query.set('include_deleted', 'true')
  const qs = query.toString()
  return api.get<CatalogItem[]>(`/api/catalog/items${qs ? `?${qs}` : ''}`)
}

export function getCatalogItem(itemId: string, includeDeleted = false) {
  return api.get<CatalogItem>(`${itemPath(itemId)}${includeDeleted ? '?include_deleted=true' : ''}`)
}

export function createCatalogItem(payload: CatalogItemCreateInput) {
  return api.post<CatalogItemWriteResult>('/api/catalog/items', payload)
}

export function updateCatalogItem(itemId: string, payload: CatalogItemWriteInput) {
  return api.put<CatalogItemWriteResult>(itemPath(itemId), payload)
}

export function deleteCatalogItem(itemId: string, deletedBy?: string) {
  const qs = deletedBy ? `?deleted_by=${enc(deletedBy)}` : ''
  return api.delete<SoftDeleteResult>(`${itemPath(itemId)}${qs}`)
}

export function restoreCatalogItem(itemId: string) {
  return api.post<SoftDeleteResult>(`${itemPath(itemId)}/restore`)
}

// ---------- resolutions (master catalog) ----------

export function listResolutions(itemId: string, includeDeleted = false) {
  return api.get<ItemResolution[]>(
    `${itemPath(itemId)}/resolutions${includeDeleted ? '?include_deleted=true' : ''}`,
  )
}

export function createResolution(itemId: string, payload: ResolutionCreateInput) {
  return api.post<ItemResolution>(`${itemPath(itemId)}/resolutions`, payload)
}

export function updateResolution(itemId: string, resolutionId: string, payload: ResolutionWriteInput) {
  return api.put<ItemResolution>(`${itemPath(itemId)}/resolutions/${enc(resolutionId)}`, payload)
}

export function deleteResolution(itemId: string, resolutionId: string, deletedBy?: string) {
  const qs = deletedBy ? `?deleted_by=${enc(deletedBy)}` : ''
  return api.delete<SoftDeleteResult>(`${itemPath(itemId)}/resolutions/${enc(resolutionId)}${qs}`)
}

/** Moves the item's default to this resolution in one transaction. Returns
 * the item's live resolutions after the move. 409 NOT_ACTIVE when the
 * resolution is deprecated. */
export function makeResolutionDefault(itemId: string, resolutionId: string) {
  return api.post<ItemResolution[]>(`${itemPath(itemId)}/resolutions/${enc(resolutionId)}/make-default`)
}

export function restoreResolution(itemId: string, resolutionId: string) {
  return api.post<SoftDeleteResult>(`${itemPath(itemId)}/resolutions/${enc(resolutionId)}/restore`)
}

// ---------- signals and coverage ----------

export function listCatalogSignals() {
  return api.get<CatalogSignal[]>('/api/catalog/signals')
}

/** Every signal with the items that reference it and how. `referenced`
 * omitted returns all signals. */
export function getSignalIndex(referenced?: boolean) {
  const qs = referenced === undefined ? '' : `?referenced=${referenced}`
  return api.get<SignalIndexEntry[]>(`/api/catalog/signal-index${qs}`)
}

export function listItemSignals(itemId: string) {
  return api.get<ItemSignal[]>(`${itemPath(itemId)}/signals`)
}

export function getExtractorBacklog() {
  return api.get<ExtractorBacklog>('/api/catalog/extractor-backlog')
}

export function getItemCoverage() {
  return api.get<ItemCoverage>('/api/catalog/item-coverage')
}

export function getSignalCoverage() {
  return api.get<SignalCoverage>('/api/catalog/signal-coverage')
}

// ---------- engagement decisions (client catalog) ----------

export function listItemDecisions(engagementId: string) {
  return api.get<EngagementDecision[]>(`/api/engagements/${enc(engagementId)}/item-decisions`)
}

export function upsertItemDecision(engagementId: string, itemId: string, payload: EngagementDecisionUpsertInput) {
  return api.put<EngagementDecision>(
    `/api/engagements/${enc(engagementId)}/items/${enc(itemId)}/decision`,
    payload,
  )
}

/** Per repository: the live decision behind each work-list item, and per
 * project what is subsumed or follows another decision (Part S). */
export function getWorkListDecisions(repositoryId: string) {
  return api.get<WorkListDecisions>(`/api/repositories/${enc(repositoryId)}/work-list-decisions`)
}

export function supersedeItemDecision(decisionId: string) {
  return api.post<EngagementDecision>(`/api/item-decisions/${enc(decisionId)}/supersede`)
}
