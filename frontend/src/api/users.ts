import { api } from './client'

export interface User {
  id: string
  login: string
  name: string
  windows_account: string
  role: 'admin' | 'developer'
  hosts: string[]
  active: boolean
  /** True after an admin set the password, until the user replaces it at their next sign-in. */
  must_change_password: boolean
  last_sign_in_at: string | null
  repositories_owned: number
}

/** A new user is a developer: an admin makes someone an admin with promoteUser, an action of its own. */
export interface UserInput {
  login: string
  name: string
  windows_account: string
  hosts: string[]
  temporary_password: string
}

export interface AccessRequest {
  id: string
  kind: 'access' | 'machine'
  status: 'pending' | 'approved' | 'rejected'
  name: string
  login: string
  windows_account: string
  hostname: string
  reason: string | null
  requested_at: string
  decided_at: string | null
  decided_by: string | null
}

export interface UserUpdate {
  name?: string
  windows_account?: string
  /** Only to make an admin a developer: making an admin is promoteUser's. */
  role?: 'developer'
  hosts?: string[]
  active?: boolean
}

export interface OnlineEntry {
  host: string
  user_name: string | null
  user_login: string | null
  since: string
  last_seen: string
}

export function listUsers() {
  return api.get<User[]>('/api/users')
}

/** Admins only. */
export function createUser(payload: UserInput) {
  return api.post<User>('/api/users', payload)
}

/** Admins only. Only the fields given change. */
export function updateUser(userId: string, payload: UserUpdate) {
  return api.put<User>(`/api/users/${encodeURIComponent(userId)}`, payload)
}

/** Admins only. The password works once: the user sets their own at their next sign-in. */
export function resetPassword(userId: string, temporaryPassword: string) {
  return api.post<User>(`/api/users/${encodeURIComponent(userId)}/reset-password`, { temporary_password: temporaryPassword })
}

/** Admins only. Makes the user an admin: the one way anyone but the first admin becomes one, recorded. */
export function promoteUser(userId: string) {
  return api.post<User>(`/api/users/${encodeURIComponent(userId)}/promote`)
}

/** A window event: an access request was decided, so the header's count is stale. */
export const ACCESS_REQUESTS_CHANGED = 'access-requests-changed'

/** Admins only: pending first, then the rest, newest first. */
export function listAccessRequests() {
  return api.get<AccessRequest[]>('/api/access-requests')
}

/** Admins only. Always as a developer. */
export function approveAccessRequest(requestId: string) {
  return api.post<AccessRequest>(`/api/access-requests/${encodeURIComponent(requestId)}/approve`)
}

/** Admins only. The reason, if given, is shown on the requester's sign-in page. */
export function rejectAccessRequest(requestId: string, reason: string | null) {
  return api.post<AccessRequest>(`/api/access-requests/${encodeURIComponent(requestId)}/reject`, { reason })
}

/** The machines with a running platform, and who is signed in on each. */
export function listOnline() {
  return api.get<OnlineEntry[]>('/api/platform/online')
}

/** Admins only. null leaves the repository with no owner (admins only act on it). */
export function assignOwner(repositoryId: string, ownerUserId: string | null) {
  return api.put<{ repository_id: string; owner_user_id: string | null; owner_name: string | null }>(
    `/api/repositories/${encodeURIComponent(repositoryId)}/owner`,
    { owner_user_id: ownerUserId },
  )
}
