import { api } from './client'

/** An Artifactory repository an engagement's scans ask. Never a credential (docs/39-ARTIFACTORY.md). */
export interface EngagementArtifactory {
  id: string
  name: string
  url: string
  created_by: string | null
  created_at: string
}

export function listArtifactories(engagementId: string) {
  return api.get<EngagementArtifactory[]>(`/api/engagements/${encodeURIComponent(engagementId)}/artifactories`)
}

export function addArtifactory(engagementId: string, artifactory: { url: string; name?: string }) {
  return api.post<EngagementArtifactory>(`/api/engagements/${encodeURIComponent(engagementId)}/artifactories`, artifactory)
}

export function removeArtifactory(engagementId: string, artifactoryId: string) {
  return api.delete<void>(`/api/engagements/${encodeURIComponent(engagementId)}/artifactories/${encodeURIComponent(artifactoryId)}`)
}

/** Whether this machine's backend has ARTIFACTORY_USERNAME and ARTIFACTORY_PASSWORD; never their values. */
export function getCredentialsStatus(engagementId: string) {
  return api.get<{ machine_login: boolean }>(`/api/engagements/${encodeURIComponent(engagementId)}/artifactory/credentials-status`)
}
