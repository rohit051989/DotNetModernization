// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// The register form's hosting fields: where the application is hosted now and where it is going. Only an admin sees
// them and sends them; everyone else registers with the server's defaults (the backend refuses anything else).
const who = vi.hoisted(() => ({ admin: true }))
const registered = vi.hoisted(() => ({ calls: [] as Record<string, unknown>[] }))

vi.mock('../../auth/AuthContext', () => ({ useIsAdmin: () => who.admin }))
vi.mock('../../api/repositories', () => ({
  inspectPath: vi.fn(),
  inspectUrl: () =>
    Promise.resolve({ problems: [], suggested_name: 'Orders', repos_dir: null, target_folder: null, target_action: 'clone', target_message: null, duplicate_conflict: null }),
  registerRepository: (_engagementId: string, payload: Record<string, unknown>) => {
    registered.calls.push(payload)
    return Promise.resolve({ repository_id: 'r1', slug: 'orders', ingest_token: 't', job_execution_id: 'j', clone_url_verification: 'unverifiable', status: 'processing' })
  },
}))

import { ToastProvider } from '../../components/Toast'
import { RegisterRepositoryDrawer } from './RegisterRepositoryDrawer'

beforeEach(() => {
  who.admin = true
  registered.calls = []
})
afterEach(cleanup)

const selectFor = (label: string) => screen.getByText(label).nextElementSibling as HTMLSelectElement

async function open() {
  await act(async () => {
    render(
      <ToastProvider>
        <RegisterRepositoryDrawer engagementId="e" onClose={() => {}} onRegistered={() => {}} />
      </ToastProvider>,
    )
  })
}

async function register() {
  fireEvent.change(screen.getByPlaceholderText(/git\.client-a\.example/), { target: { value: 'https://git.client-a.example/team/orders.git' } })
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: /Register, clone/ }))
  })
}

describe('RegisterRepositoryDrawer hosting fields', () => {
  it('shows an admin both, set to Windows now and Linux next, and sends what they choose', async () => {
    await open()
    expect(selectFor('Current hosting').value).toBe('windows')
    expect(selectFor('Target hosting').value).toBe('linux')
    await act(async () => {
      fireEvent.change(selectFor('Target hosting'), { target: { value: 'windows' } })
    })
    await register()
    expect(registered.calls).toHaveLength(1)
    expect(registered.calls[0]).toMatchObject({ current_hosting_os: 'windows', target_hosting_os: 'windows' })
  })

  it('sends the defaults for an admin who changes nothing', async () => {
    await open()
    await register()
    expect(registered.calls[0]).toMatchObject({ current_hosting_os: 'windows', target_hosting_os: 'linux' })
  })

  it('hides both from anyone else and sends neither, so the server uses its defaults', async () => {
    who.admin = false
    await open()
    expect(screen.queryByText('Current hosting')).toBeNull()
    expect(screen.queryByText('Target hosting')).toBeNull()
    await register()
    expect(registered.calls).toHaveLength(1)
    expect(registered.calls[0]).not.toHaveProperty('current_hosting_os')
    expect(registered.calls[0]).not.toHaveProperty('target_hosting_os')
  })
})
