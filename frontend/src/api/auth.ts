import { api } from './client'

/** This machine and the Windows account its platform runs under: who and where a sign-in is made. */
export interface MachineInfo {
  windows_account: string
  hostname: string
  /** True until the first admin is created (python -m app.users create-first-admin). */
  first_admin_needed: boolean
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
}

export function getMachine() {
  return api.get<MachineInfo>('/api/auth/machine')
}

/** 401 with a plain message when the name, password, Windows account or machine does not match; 409
 * PASSWORD_CHANGE_REQUIRED when the password was set by an admin and `newPassword` is needed. */
export function signIn(login: string, password: string, newPassword?: string) {
  return api.post<Me>('/api/auth/sign-in', { login, password, new_password: newPassword ?? null })
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
