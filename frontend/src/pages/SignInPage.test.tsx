import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'

const api = vi.hoisted(() => ({ signIn: vi.fn(), machine: { windows_account: 'CORP\\alice', hostname: 'DEVBOX-A', first_admin_needed: false } }))
vi.mock('../api/auth', () => ({ getMachine: () => Promise.resolve(api.machine), signIn: api.signIn }))

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
})
