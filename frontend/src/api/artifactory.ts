import { api } from './client'

/** An Artifactory repository an engagement's scans ask. Never a credential (docs/39-ARTIFACTORY.md). */
export interface EngagementArtifactory {
  id: string
  name: string
  url: string
  created_by: string | null
  created_at: string
  /** The version an edit names (If-Match). */
  version: number
  updated_by?: string | null
  updated_at?: string | null
  /** What looks wrong with the URL, if anything: a scan will not get packages from it. */
  warning?: string | null
}

/** What an artifactory's service index answered, asked from this machine's own backend with its login. Never a value. */
export interface ConnectionResult {
  ok: boolean
  url: string
  /** "answered", "rejected ARTIFACTORY_TOKEN (401)", "answered 404", "could not be reached: ..." */
  answer: string
  /** "token", "username and password", "token rejected, used username and password", "token rejected" or "none". */
  login: string
  machine: string
  warning?: string | null
}

export function listArtifactories(engagementId: string) {
  return api.get<EngagementArtifactory[]>(`/api/engagements/${encodeURIComponent(engagementId)}/artifactories`)
}

export function addArtifactory(engagementId: string, artifactory: { url: string; name?: string }) {
  return api.post<EngagementArtifactory>(`/api/engagements/${encodeURIComponent(engagementId)}/artifactories`, artifactory)
}

/** An admin changes a saved artifactory's URL or name; the edit names the version it was made on. */
export function editArtifactory(engagementId: string, artifactory: EngagementArtifactory, change: { url: string; name?: string }) {
  return api.put<EngagementArtifactory>(
    `/api/engagements/${encodeURIComponent(engagementId)}/artifactories/${encodeURIComponent(artifactory.id)}`,
    change,
    { version: artifactory.version },
  )
}

/** Asks the URL's service index from this machine's backend, with this machine's login (a saved URL or one not yet added). */
export function testArtifactoryConnection(engagementId: string, url: string) {
  return api.post<ConnectionResult>(`/api/engagements/${encodeURIComponent(engagementId)}/artifactory/test-connection`, { url })
}

export function removeArtifactory(engagementId: string, artifactoryId: string) {
  return api.delete<void>(`/api/engagements/${encodeURIComponent(engagementId)}/artifactories/${encodeURIComponent(artifactoryId)}`)
}

/** Which artifactory login this machine's backend has: a token, a username and password, or none; never a value. */
export function getCredentialsStatus(engagementId: string) {
  return api.get<{ machine_login: boolean; method?: 'token' | 'username and password' | 'none' }>(`/api/engagements/${encodeURIComponent(engagementId)}/artifactory/credentials-status`)
}
