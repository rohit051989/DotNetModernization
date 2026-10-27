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

export interface UserInput {
  login: string
  name: string
  windows_account: string
  role: 'admin' | 'developer'
  hosts: string[]
  temporary_password: string
}

export interface UserUpdate {
  name?: string
  windows_account?: string
  role?: 'admin' | 'developer'
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
