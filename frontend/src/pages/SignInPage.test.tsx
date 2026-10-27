import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'

const api = vi.hoisted(() => ({
  signIn: vi.fn(),
  requestAccess: vi.fn(),
  request: null as unknown,
  machine: { windows_account: 'CORP\\alice', hostname: 'DEVBOX-A', first_admin_needed: false, registration: 'none' },
}))
vi.mock('../api/auth', () => ({
  getMachine: () => Promise.resolve(api.machine),
  getAccessRequest: () => Promise.resolve(api.request),
  requestAccess: api.requestAccess,
  signIn: api.signIn,
}))

import { SignInPage } from './SignInPage'

const ME = { id: 'u1', login: 'alice', name: 'Alice', role: 'developer', windows_account: 'CORP\\alice', hostname: 'DEVBOX-A', hosts: ['DEVBOX-A'], must_change_password: false }

async function fill(login: string, password: string) {
  fireEvent.change(screen.getByLabelText('Sign-in name'), { target: { value: login } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } })
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: /Sign in|Set the new password/ }))
  })
}

afterEach(() => {
  cleanup()
  api.signIn.mockReset()
  api.requestAccess.mockReset()
  api.request = null
  api.machine = { ...api.machine, registration: 'none' }
})

describe('SignInPage', () => {
  it('names the machine and the Windows account the sign-in is checked against', async () => {
    render(<SignInPage onSignedIn={() => {}} />)
    await act(async () => {})
    expect(screen.getByText('DEVBOX-A')).toBeTruthy()
    expect(screen.getByText('CORP\\alice')).toBeTruthy()
  })

  it('shows the backend\'s plain refusal, such as a machine the account is not registered for', async () => {
    api.signIn.mockRejectedValue(new ApiError(401, 'This account is not registered for this machine (DEVBOX-A) — ask the admin.', [],
      [{ code: 'NOT_REGISTERED_HERE' }]))
    const signedIn = vi.fn()
    render(<SignInPage onSignedIn={signedIn} />)
    await fill('alice', 'a-password-of-mine')
    expect(screen.getByRole('alert').textContent).toBe('This account is not registered for this machine (DEVBOX-A) — ask the admin.')
    expect(signedIn).not.toHaveBeenCalled()
  })

  it('a password set by an admin asks for a new one, then signs in with it', async () => {
    api.signIn
      .mockRejectedValueOnce(new ApiError(409, 'Your password was set by an admin: choose a new one to sign in.', [], [{ code: 'PASSWORD_CHANGE_REQUIRED' }]))
      .mockResolvedValueOnce(ME)
    const signedIn = vi.fn()
    render(<SignInPage onSignedIn={signedIn} />)
    await fill('alice', 'temporary-password-1')
    fireEvent.change(screen.getByLabelText('New password (12 characters or more)'), { target: { value: 'my-own-long-password' } })
    fireEvent.change(screen.getByLabelText('New password, again'), { target: { value: 'my-own-long-password' } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Set the new password and sign in' }))
    })
    expect(api.signIn).toHaveBeenLastCalledWith('alice', 'temporary-password-1', 'my-own-long-password')
    expect(signedIn).toHaveBeenCalledWith(ME)
  })

  it('before anyone is registered, says how the first admin is created', async () => {
    api.machine = { ...api.machine, first_admin_needed: true }
    render(<SignInPage onSignedIn={() => {}} />)
    await act(async () => {})
    expect(screen.getByRole('note').textContent).toContain('-m app.users create-first-admin')
    api.machine = { ...api.machine, first_admin_needed: false }
  })

  it('someone not registered asks for access, and is told it is pending', async () => {
    const pending = { kind: 'access', status: 'pending', login: 'alice', hostname: 'DEVBOX-A', reason: null, requested_at: '2026-10-27T10:00:00Z', decided_at: null }
    api.requestAccess.mockResolvedValue(pending)
    render(<SignInPage onSignedIn={() => {}} />)
    await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: 'Request access' }))
    fireEvent.change(screen.getByLabelText('Your full name'), { target: { value: 'Alice Example' } })
    fireEvent.change(screen.getByLabelText('Choose a password (12 characters or more)'), { target: { value: 'my-own-long-password' } })
    fireEvent.change(screen.getByLabelText('The password, again'), { target: { value: 'my-own-long-password' } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Request access' }))
    })
    expect(api.requestAccess).toHaveBeenCalledWith('Alice Example', 'my-own-long-password')
    expect(screen.getByRole('status').textContent).toContain('Your request for access is pending')
    expect(screen.queryByRole('button', { name: 'Request access' })).toBeNull()
  })

  it('a rejected request says why, and may be made again', async () => {
    api.request = { kind: 'access', status: 'rejected', login: 'alice', hostname: 'DEVBOX-A', reason: 'Not on this programme.', requested_at: '2026-10-27T10:00:00Z', decided_at: '2026-10-27T11:00:00Z' }
    render(<SignInPage onSignedIn={() => {}} />)
    await act(async () => {})
    expect(screen.getByRole('status').textContent).toContain(': Not on this programme.')
    expect(screen.getByRole('button', { name: 'Request access' })).toBeTruthy()
  })

  it('a registered user on a new machine asks to add it, with their password only', async () => {
    api.machine = { ...api.machine, registration: 'other_machines' }
    api.requestAccess.mockResolvedValue({ kind: 'machine', status: 'pending', login: 'alice', hostname: 'DEVBOX-A', reason: null, requested_at: '2026-10-27T10:00:00Z', decided_at: null })
    render(<SignInPage onSignedIn={() => {}} />)
    await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: 'Ask to add this machine' }))
    expect(screen.queryByLabelText('Your full name')).toBeNull()
    fireEvent.change(screen.getByLabelText('Your password'), { target: { value: 'my-own-long-password' } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Ask to add this machine' }))
    })
    expect(api.requestAccess).toHaveBeenCalledWith('', 'my-own-long-password')
    expect(screen.getByRole('status').textContent).toContain('to add DEVBOX-A to your registration is pending')
  })
})
