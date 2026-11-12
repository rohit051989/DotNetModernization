// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const asked: string[] = []
const summaryReads = { n: 0 }
const finding = (kind: string, name: string, treatment: string | null = null) => ({ kind, treatment, id: name, itemId: null, itemName: name, category: 'dependencies', project: 'src/App/App.csproj', file: 'src/App/Program.cs', value: '1.0', certainty: 'confirmed', whatToDo: 'Replace it' })
const page = (name: string, items: unknown[]) => () => {
  asked.push(name)
  return Promise.resolve({ total: items.length, matching: items.length, offset: 0, items })
}

vi.mock('../../api/results', () => ({
  getSoapSummary: () => Promise.resolve({ repository_id: 'r', engagement_id: 'e', scanned_at: null, estate_run_at: null, estate_stale: false, estate_note: null,
                                          target_wcf_client_version: null, unused_count: 0, calls: 3, environments: 1, need_change: 1, undecided: 0 }),
  soapCalls: () => page('soap', []),
  getCompatibilitySummary: () => (summaryReads.n++, Promise.resolve({ linux: 2, linux_items: 1, linux_packages: 1, linux_blockers: 1, linux_container: 1, linux_other: 0, scanned_at: null })),
  linuxCompatibility: () => page('linux', [finding('package', 'System.Drawing.Common', 'blocker'), finding('item', 'missing-dockerfile', 'container')]),
}))

import { ToastProvider } from '../../components/Toast'
vi.mock('../../api/editors', () => ({
  listEditors: () => Promise.resolve({ editors: [{ id: 'vscode', kind: 'vscode', label: 'VS Code', opens_at_line: true }] }),
}))

import { RepositoryCompatibilityPanel } from './RepositoryCompatibilityPanel'

afterEach(() => {
  cleanup()
  window.localStorage.clear()
  asked.length = 0
  summaryReads.n = 0
})

describe('RepositoryCompatibilityPanel', () => {
  it('has a tab each for SOAP and Linux, with counts, and loads a list only when its tab is open', async () => {
    await act(async () => {
      render(
        <ToastProvider>
          <RepositoryCompatibilityPanel repositoryId="r" localPath="D:\repos\shop" refreshToken={0} />
        </ToastProvider>,
      )
    })
    const names = screen.getAllByRole('tab').map((t) => t.textContent)
    expect(names).toEqual(['SOAP · 3 calls', 'Linux · 2 findings'])
    expect(asked).toEqual(['soap'])
    await act(async () => {
      fireEvent.click(screen.getByRole('tab', { name: 'Linux · 2 findings' }))
    })
    expect(screen.getByText('System.Drawing.Common')).toBeTruthy()
    expect(screen.getByText('missing-dockerfile')).toBeTruthy()
    // The file opens in the editor (a vscode:// link), as on every other tab.
    expect(screen.getAllByText('src/App/Program.cs')[0].closest('a')?.getAttribute('href')).toContain('vscode://file/')
    expect(screen.getByText('Blocker')).toBeTruthy()
    expect(screen.getByText('Needs container change')).toBeTruthy()
  })

  it('shows SOAP alone, with no tab bar and no Linux read, when the repository is not moving from Windows to Linux', async () => {
    await act(async () => {
      render(
        <ToastProvider>
          <RepositoryCompatibilityPanel repositoryId="r" localPath="D:\repos\shop" refreshToken={0} showLinux={false} />
        </ToastProvider>,
      )
    })
    expect(screen.queryAllByRole('tab')).toEqual([])
    expect(screen.queryByText(/Linux · /)).toBeNull()
    // The note that says why is bold and amber, so it is not missed.
    const note = screen.getByText('The Linux list is shown only for a move from Windows to Linux hosting.')
    expect(note.tagName).toBe('STRONG')
    expect(note.className).toContain('text-amber-700')
    expect(summaryReads.n).toBe(0)
    expect(asked).toEqual(['soap'])
  })

  it('opens on SOAP when the remembered tab is Linux but the repository no longer shows it', async () => {
    window.localStorage.setItem('compat-tab:r', 'linux')
    await act(async () => {
      render(
        <ToastProvider>
          <RepositoryCompatibilityPanel repositoryId="r" localPath="D:\repos\shop" refreshToken={0} showLinux={false} />
        </ToastProvider>,
      )
    })
    expect(asked).toEqual(['soap'])
    expect(screen.queryByText('System.Drawing.Common')).toBeNull()
  })

  it('opens on SOAP when the remembered tab is the removed Method/API one', async () => {
    window.localStorage.setItem('compat-tab:r', 'api')
    await act(async () => {
      render(
        <ToastProvider>
          <RepositoryCompatibilityPanel repositoryId="r" localPath="D:\repos\shop" refreshToken={0} />
        </ToastProvider>,
      )
    })
    expect(screen.getByRole('tab', { name: 'SOAP · 3 calls' }).getAttribute('aria-selected')).toBe('true')
  })

  it('remembers the tab it was left on', async () => {
    await act(async () => {
      render(
        <ToastProvider>
          <RepositoryCompatibilityPanel repositoryId="r" localPath="D:\repos\shop" refreshToken={0} />
        </ToastProvider>,
      )
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('tab', { name: 'Linux · 2 findings' }))
    })
    cleanup()
    await act(async () => {
      render(
        <ToastProvider>
          <RepositoryCompatibilityPanel repositoryId="r" localPath="D:\repos\shop" refreshToken={0} />
        </ToastProvider>,
      )
    })
    expect(screen.getByRole('tab', { name: 'Linux · 2 findings' }).getAttribute('aria-selected')).toBe('true')
  })
})
