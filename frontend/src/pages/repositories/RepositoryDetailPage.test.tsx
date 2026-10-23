import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { useEffect } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/Toast'

// Each tab's content is a stand-in that counts how often it is mounted: a tab's content must load only when its tab is
// first opened, and stay loaded (hidden) after that.
const mounts = vi.hoisted(() => ({} as Record<string, number>))
function standIn(name: string) {
  return function StandIn() {
    useEffect(() => {
      mounts[name] = (mounts[name] ?? 0) + 1
    }, [])
    return <div data-testid={`content-${name}`}>{name}</div>
  }
}
vi.mock('./RepositorySurfaceSection', () => ({ RepositorySurfaceSection: standIn('surface') }))
vi.mock('./RepositoryStructureSection', () => ({ RepositoryStructureSection: standIn('projects') }))
vi.mock('./RepositoryImpactSection', () => ({ RepositoryImpactSection: standIn('impact') }))
vi.mock('./RepositoryTestsSection', () => ({ RepositoryTestsSection: standIn('tests') }))
vi.mock('./ConversionsPanel', () => ({ ConversionsPanel: standIn('conversion') }))
vi.mock('./structure/StructureSection', () => ({ StructureSection: standIn('dependency-graph') }))
vi.mock('../workflow/artifacts/renderers', () => ({
  DependenciesView: standIn('dependencies'),
  FingerprintView: standIn('fingerprint'),
  ItemOccurrencesView: standIn('work-list'),
  formatBytes: (n: number) => `${n} B`,
}))

const artifacts = vi.hoisted(() => ({
  'item-occurrences': { data: { summary: { found: 28, possible_only_found: 0, not_checked: 0 } }, executionId: 'e', createdAt: '2026-10-23T00:00:00Z' },
  'entry-point-inventory': { data: { summary: { requestEntryPointCount: 54 } }, executionId: 'e', createdAt: '2026-10-23T00:00:00Z' },
  'dependency-assessment': {
    data: { summary: { packageCount: 77, countByOutcome: { upgrade_safe: 58, upgrade_breaking: 5 }, vulnerableCount: 2 } },
    executionId: 'e',
    createdAt: '2026-10-23T00:00:00Z',
  },
}))
vi.mock('./useLatestArtifacts', () => ({ useLatestArtifacts: () => ({ artifacts, loading: false }) }))
vi.mock('../../api/repositories', () => ({
  getRepository: () =>
    Promise.resolve({
      id: 'r', name: 'shop', engagement_id: 'e', local_path: 'D:\\repos\\shop', source_type: 'local_path', clone_url: null, ingest_status: 'scanned',
      criticality: 'medium', clone_url_verification: 'verified', retirement_status: 'active', warnings: [], deleted_at: null, size_bytes: 1, file_count: 1,
      primary_languages: [], last_scanned_at: null, tags: [], technical_owner: null,
    }),
  listRepositoryExecutions: () => Promise.resolve([{ id: 'x1', batch_status: 'COMPLETED', exit_status: 'COMPLETED', started_at: '2026-10-23T00:00:00Z', step_summary: { completed: 1, not_implemented: 0, total: 1 } }]),
  rescanRepository: vi.fn(),
  restoreRepository: vi.fn(),
  updateRepository: vi.fn(),
  verifyRepositoryPath: vi.fn(),
}))
vi.mock('../../api/items', () => ({ getWorkListDecisions: () => Promise.resolve(null) }))
vi.mock('../../api/conversion', () => ({
  listConversions: () => Promise.resolve({ conversions: [{ number: 1, branch: 'conversion/1', state: 'prepared' }], next: { number: 2 } }),
}))
vi.mock('../../api/surface', () => ({ getRepositorySoapCompatibility: () => Promise.reject(new Error('none')) }))
vi.mock('../../api/deletion', () => ({ deleteRepositoryHard: vi.fn(), getRepositoryDeletionPlan: vi.fn() }))

import { RepositoryDetailPage } from './RepositoryDetailPage'

async function open(path: string) {
  window.history.replaceState({}, '', path)
  // The app scrolls a container (AppShell's <main>), not the window: the page finds its nearest scrolling ancestor.
  render(
    <ToastProvider>
      <div data-testid="scroller" style={{ overflowY: 'auto' }}>
        <RepositoryDetailPage repositoryId="r" refreshToken={0} onBack={() => {}} onChanged={() => {}} onDeleted={() => {}} onNavigateToExecution={() => {}} />
      </div>
    </ToastProvider>,
  )
  await screen.findByRole('heading', { name: 'shop' })
  await act(async () => {})
}

const groups = () => within(screen.getByRole('tablist', { name: 'Tab groups' }))
const tabs = () => within(screen.getByRole('tablist', { name: 'Tabs' }))
const shown = () => screen.getAllByRole('tabpanel').filter((p) => !p.hidden).map((p) => p.getAttribute('aria-label'))

async function click(element: HTMLElement) {
  await act(async () => {
    fireEvent.click(element)
  })
}

async function back() {
  await act(async () => {
    window.history.back()
    await new Promise((resolve) => window.addEventListener('popstate', resolve, { once: true }))
  })
}

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
  for (const key of Object.keys(mounts)) delete mounts[key]
})
afterEach(cleanup)

describe('RepositoryDetailPage tabs', () => {
  it('opens on Overview, alone in its group, with no second row, and names it in the address', async () => {
    await open('/repositories/r')
    expect(groups().getAllByRole('tab').map((t) => t.textContent)).toEqual(['Overview', 'Discovery', 'Modernization', 'Activity'])
    expect(screen.queryByRole('tablist', { name: 'Tabs' })).toBeNull()
    expect(shown()).toEqual(['Overview'])
    expect(window.location.pathname).toBe('/repositories/r/overview')
  })

  it('a group shows its tabs and opens its first; only the selected tab is shown', async () => {
    await open('/repositories/r')
    await click(groups().getByRole('tab', { name: 'Discovery' }))
    expect(tabs().getAllByRole('tab').map((t) => t.textContent)).toEqual([
      'Surface · 54', 'Projects & fingerprint', 'Dependencies · 63', 'Dependency graph', 'Impact', 'Tests',
    ])
    expect(shown()).toEqual(['Surface'])
    expect(window.location.pathname).toBe('/repositories/r/surface')
    await click(groups().getByRole('tab', { name: 'Modernization' }))
    expect(tabs().getAllByRole('tab').map((t) => t.textContent)).toEqual(['Work list · 28', 'Conversion · ready'])
    await click(groups().getByRole('tab', { name: 'Activity' }))
    expect(tabs().getAllByRole('tab').map((t) => t.textContent)).toEqual(['Executions · 1', 'Details'])
  })

  it('loads a tab only when it is first opened, and keeps it after that', async () => {
    await open('/repositories/r/surface')
    expect(mounts).toEqual({ surface: 1 })
    await click(tabs().getByRole('tab', { name: 'Tests' }))
    expect(mounts).toEqual({ surface: 1, tests: 1 })
    await click(tabs().getByRole('tab', { name: 'Surface · 54' }))
    await click(tabs().getByRole('tab', { name: 'Tests' }))
    expect(mounts).toEqual({ surface: 1, tests: 1 })
    expect(shown()).toEqual(['Tests'])
  })

  it('each tab has its own address, and a link opens the repository on it', async () => {
    await open('/repositories/r/work-list')
    expect(shown()).toEqual(['Work list'])
    expect(groups().getByRole('tab', { name: 'Modernization' }).getAttribute('aria-selected')).toBe('true')
  })

  it('Back and Forward move between tabs', async () => {
    await open('/repositories/r/overview')
    await click(groups().getByRole('tab', { name: 'Discovery' }))
    await click(tabs().getByRole('tab', { name: 'Impact' }))
    expect(window.location.pathname).toBe('/repositories/r/impact')
    await back()
    expect(shown()).toEqual(['Surface'])
    await back()
    expect(shown()).toEqual(['Overview'])
    await act(async () => {
      window.history.forward()
      await new Promise((resolve) => window.addEventListener('popstate', resolve, { once: true }))
    })
    expect(shown()).toEqual(['Surface'])
  })

  it('an old link to a section opens its tab, and the address becomes the tab’s', async () => {
    await open('/repositories/r#repo-hierarchy')
    expect(shown()).toEqual(['Dependency graph'])
    expect(window.location.pathname + window.location.hash).toBe('/repositories/r/dependency-graph')
  })

  it('remembers each repository’s last tab', async () => {
    await open('/repositories/r/conversion')
    cleanup()
    await open('/repositories/r')
    expect(shown()).toEqual(['Conversion'])
    expect(window.location.pathname).toBe('/repositories/r/conversion')
  })

  it('each tab keeps its scroll position', async () => {
    await open('/repositories/r/surface')
    // jsdom does not keep a scroll position: give the container one.
    const page = screen.getByTestId('scroller')
    let top = 0
    Object.defineProperty(page, 'scrollTop', { configurable: true, get: () => top, set: (value: number) => (top = value) })
    page.scrollTop = 300
    await click(tabs().getByRole('tab', { name: 'Tests' }))
    expect(page.scrollTop).toBe(0)
    await click(tabs().getByRole('tab', { name: 'Surface · 54' }))
    expect(page.scrollTop).toBe(300)
  })

  it('Overview’s key figures each open their tab', async () => {
    await open('/repositories/r')
    const figures = within(screen.getByRole('region', { name: 'Key figures' }))
    expect(figures.getByText('Work items').parentElement?.textContent).toContain('28')
    await click(figures.getByText('Dependencies needing change').closest('button')!)
    expect(shown()).toEqual(['Dependencies'])
    expect(window.location.pathname).toBe('/repositories/r/dependencies')
  })
})
