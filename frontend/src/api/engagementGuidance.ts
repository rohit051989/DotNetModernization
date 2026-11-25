import { api } from './client'

/** One engagement's note on one catalog resolution: carried after the master guidance in its work items. */
export interface ResolutionNote {
  resolution_id: string
  item_id: string
  note: string | null
  /** The version an edit names (If-Match); 0 when no note was ever saved. */
  version: number
  updated_by: string | null
  updated_at: string | null
}

/** One engagement's conventions, carried in the top-level instructions of every conversion of its repositories. */
export interface EngagementConventions {
  conventions: string | null
  /** The engagement's settings version: an edit names it (If-Match). */
  version: number
}

const base = (engagementId: string) => `/api/engagements/${encodeURIComponent(engagementId)}`

export function listResolutionNotes(engagementId: string) {
  return api.get<ResolutionNote[]>(`${base(engagementId)}/resolution-notes`)
}

export function putResolutionNote(engagementId: string, resolutionId: string, note: string | null, version: number) {
  return api.put<ResolutionNote>(`${base(engagementId)}/resolutions/${encodeURIComponent(resolutionId)}/note`, { note }, { version })
}

export function getConventions(engagementId: string) {
  return api.get<EngagementConventions>(`${base(engagementId)}/conventions`)
}

export function putConventions(engagementId: string, conventions: string | null, version: number) {
  return api.put<EngagementConventions>(`${base(engagementId)}/conventions`, { conventions }, { version })
}
