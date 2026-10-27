import { api } from './client'

/** This machine and the Windows account its platform runs under: who and where a sign-in is made. */
export interface MachineInfo {
  windows_account: string
  hostname: string
  /** True until the first admin is created (python -m app.users create-first-admin). */
  first_admin_needed: boolean
  /** This Windows account's registration: none, registered but not for this machine, or for this machine. */
  registration: 'none' | 'other_machines' | 'this_machine'
}

/** A request for access from this machine (app.auth.requests), as it stands. */
export interface AccessRequestStatus {
  /** access: to be registered; machine: to add this machine to a registration. */
  kind: 'access' | 'machine'
  status: 'pending' | 'approved' | 'rejected'
  /** The name to sign in with once approved. */
  login: string
  hostname: string
  reason: string | null
  requested_at: string
  decided_at: string | null
}

export interface Me {
  id: string
  login: string
  name: string
  role: 'admin' | 'developer'
  windows_account: string
  /** The machine this session is on. */
  hostname: string
  hosts: string[]
  must_change_password: boolean
  /** For an admin: access requests waiting for a decision. Null for anyone else. */
  pending_access_requests?: number | null
}

export function getMachine() {
  return api.get<MachineInfo>('/api/auth/machine')
}

/** 401 with a plain message when the name, password, Windows account or machine does not match; 409
 * PASSWORD_CHANGE_REQUIRED when the password was set by an admin and `newPassword` is needed. */
export function signIn(login: string, password: string, newPassword?: string) {
  return api.post<Me>('/api/auth/sign-in', { login, password, new_password: newPassword ?? null })
}

/** The newest request from this machine's Windows account, or null. Open without a session. */
export function getAccessRequest() {
  return api.get<AccessRequestStatus | null>('/api/auth/access-request')
}

/** Asks for access from this machine: the Windows account and hostname are taken from it, never typed. To add this
 * machine to a registration, `password` is the current one and `name` is not needed. */
export function requestAccess(name: string, password: string) {
  return api.post<AccessRequestStatus>('/api/auth/access-request', { name, password })
}

export function signOut() {
  return api.post<void>('/api/auth/sign-out')
}

export function getMe() {
  return api.get<Me>('/api/auth/me')
}

export function changePassword(currentPassword: string, newPassword: string) {
  return api.post<void>('/api/auth/password', { current_password: currentPassword, new_password: newPassword })
}
