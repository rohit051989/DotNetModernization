import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { EngagementArtifactory } from '../api/artifactory'
import { ToastProvider } from '../components/Toast'
import { ArtifactoryPage } from './ArtifactoryPage'

const api = vi.hoisted(() => ({
  list: vi.fn(),
  add: vi.fn(),
  edit: vi.fn(),
  remove: vi.fn(),
  test: vi.fn(),
}))
vi.mock('../api/artifactory', () => ({
  listArtifactories: api.list,
  addArtifactory: api.add,
  editArtifactory: api.edit,
  removeArtifactory: api.remove,
  testArtifactoryConnection: api.test,
  getCredentialsStatus: () => Promise.resolve({ machine_login: true, method: 'token' }),
}))
const admin = vi.hoisted(() => ({ is: true }))
vi.mock('../auth/AuthContext', () => ({ useIsAdmin: () => admin.is, ADMIN_ONLY: 'Only an admin can do this.' }))

const UI = 'https://host.client-a.example/ui/packages'
const SAVED: EngagementArtifactory = {
  id: 'a1',
  name: 'nuget-private',
  url: UI,
  created_by: 'Ann',
  created_at: '2026-11-19T20:03:00Z',
  version: 1,
  warning: 'This is the Artifactory web page, not a NuGet feed.',
}

function page() {
  return render(
    <ToastProvider>
      <ArtifactoryPage engagementId="e1" />
    </ToastProvider>,
  )
}

beforeEach(() => {
  admin.is = true
  api.list.mockResolvedValue([SAVED])
  api.test.mockResolvedValue({ ok: false, url: UI, answer: 'refused the login (401)', login: 'token', machine: 'DEVBOX-A', warning: null })
})
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('the Artifactory tab', () => {
  it('names a saved web UI address as one, and Test connection says what it answered with which login, from which machine', async () => {
    page()
    expect((await screen.findByTestId('url-warning')).textContent).toContain('web page')
    // The first is the add form's; the second, the saved artifactory's.
    fireEvent.click(screen.getAllByRole('button', { name: 'Test connection' })[1])
    const answer = await screen.findByTestId('connection-answer')
    expect(answer.textContent).toBe('Refused the login (401) · login: token · asked from DEVBOX-A')
    expect(api.test).toHaveBeenCalledWith('e1', UI)
  })

  it('tests a URL before it is added', async () => {
    api.test.mockResolvedValue({ ok: true, url: 'https://h/api/nuget/v3/x/index.json', answer: 'answered', login: 'token', machine: 'DEVBOX-A' })
    page()
    fireEvent.change(screen.getByLabelText('Artifactory URL'), { target: { value: 'https://h/api/nuget/v3/x/index.json' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Test connection' })[0])
    expect((await screen.findByTestId('connection-answer')).textContent).toContain('Answered · login: token')
  })

  it('an admin edits a saved URL, sending the version it was made on', async () => {
    api.edit.mockResolvedValue({ ...SAVED, url: 'https://h/api/nuget/v3/x/index.json', version: 2, warning: null })
    page()
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    fireEvent.change(screen.getByLabelText('URL of nuget-private'), { target: { value: 'https://h/api/nuget/v3/x/index.json' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(api.edit).toHaveBeenCalledWith('e1', SAVED, { url: 'https://h/api/nuget/v3/x/index.json', name: 'nuget-private' }))
  })

  it('a developer cannot edit', async () => {
    admin.is = false
    page()
    const edit = await screen.findByRole('button', { name: 'Edit' })
    expect((edit as HTMLButtonElement).disabled).toBe(true)
    expect(edit.getAttribute('title')).toBe('Only an admin can do this.')
  })
})
