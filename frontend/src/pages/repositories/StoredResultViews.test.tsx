import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/Toast'

// The stored-result views (backend app.results), against a server that pages: they render what each page holds and
// ask for nested lists only when they are opened.
const server = vi.hoisted(() => {
  const page = <T,>(items: T[], total = items.length) => Promise.resolve({ total, matching: total, offset: 0, items })
  const work = Array.from({ length: 25 }, (_, i) => ({
    itemId: 'wcf-service', name: 'WCF service', groupBy: 'source_path', scope: 'occurrence',
    project: `src/P${String(i).padStart(2, '0')}/P.csproj`, projectId: `p${i}`, attribute: null, state: 'found', reason: null,
    fileCount: 2, possibleCount: 0, distinctFiles: 2,
    files: { total: 2, matching: 2, offset: 0, items: [{ filePath: `src/P${i}/A.cs`, line: 3, value: null, certainty: 'confirmed' }, { filePath: `src/P${i}/B.cs`, line: 4, value: null, certainty: 'confirmed' }] },
    evidencePaths: [], decision: null, note: null,
  }))
  return {
    calls: [] as string[],
    cause: 'feed_auth',
    page,
    work,
    origins: { hierarchy_scanned: false, origin_counts: { internal: 0, external: 0, unresolved: 0, not_classified: 0 } },
  }
})

vi.mock('../../api/results', () => ({
  getFingerprintOverview: () => Promise.resolve({ status_counts: { SCANNED: 3 }, categories: [{ category: 'ENTRY_POINT', signals: 2, distinct: 1 }] }),
  fingerprintSignals: (_a: string, category: string) => () => {
    server.calls.push(`signals:${category}`)
    return server.page([{ name: 'ASP_NET_CORE', value: '8.0', project: 'src/A/A.csproj', sourcePath: null, occurrences: 1, confidence: 1 }])
  },
  listDependencyFeeds: () => Promise.resolve([{ name: 'nuget.org', url: 'https://api.nuget.org/v3/index.json', role: 'nuget_org' }]),
  getDependencyOrigins: () => Promise.resolve(server.origins),
  dependencyPackages: (_a: string, _showCurrent: boolean, part: string) => () => {
    server.calls.push(`packages:${part}`)
    const one = (packageId: string, origin: string | null) => ({
      packageId, drift: false, projectCount: 1, origin, originBasis: null, producer: null,
      versions: [{ version: '12.0.3', useCount: 1, outcomes: ['upgrade_safe'], projects: ['src/A/A.csproj'],
                   first: { project: 'src/A/A.csproj', declaredAt: { filePath: 'src/A/A.csproj', line: 9 } },
                   worst: { project: 'src/A/A.csproj', pkg: { packageId, outcome: origin === 'unknown' ? 'unknown' : 'upgrade_safe', currentVersion: '12.0.3', recommendedVersion: '13.0.3',
                   ...(origin === 'unknown' ? { unknownCause: server.cause, failedFeeds: [{ name: 'corp', url: 'https://pkgs.client-a.example/v3/index.json', failure: 'auth', httpStatus: 401 }] } : {}) } } }],
    })
    return server.page(part === 'internal' ? [one('Offline.Lib', 'unknown'), one('Gone.Lib', null)] : [one('Newtonsoft.Json', 'external')])
  },
  dependencyUses: () => () => server.page([{ project: 'src/A/A.csproj', pkg: { outcome: 'upgrade_safe', callSites: [] } }]),
  getWorkItemTotals: () => Promise.resolve({ occurrence_rows: 50, possible_rows: 0 }),
  workItems: () => (_q: string, offset: number, limit: number) => {
    server.calls.push(`work:${offset}:${limit}`)
    return Promise.resolve({ total: 25, matching: 25, offset, items: server.work.slice(offset, offset + limit) })
  },
  workItemFiles: () => () => server.page([]),
}))

import { StoredDependenciesView, StoredFingerprintView, StoredWorkListView } from './StoredResultViews'

afterEach(cleanup)

async function show(node: React.ReactNode) {
  await act(async () => {
    render(<ToastProvider>{node}</ToastProvider>)
  })
}

describe('stored result views', () => {
  it('the fingerprint lists categories, and asks for a category\'s signals when it is opened', async () => {
    await show(<StoredFingerprintView artifactId="a" head={{ summary: { totalSignals: 2, totalEvidence: 2 } }} localPath={null} />)
    expect(screen.getByText('3 scanned')).toBeTruthy()
    expect(server.calls.filter((c) => c.startsWith('signals'))).toEqual([])
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /entry point/ }))
    })
    expect(server.calls).toContain('signals:ENTRY_POINT')
    expect(screen.getByText('ASP_NET_CORE')).toBeTruthy()
  })

  it('dependencies show each package with its worst project\'s assessment', async () => {
    server.origins = { hierarchy_scanned: false, origin_counts: { internal: 0, external: 0, unresolved: 0, not_classified: 0 } }
    await show(<StoredDependenciesView artifactId="d" head={{ summary: { packageCount: 1 }, targetFramework: 'net10.0' }} localPath={null} />)
    expect(screen.getAllByText('Newtonsoft.Json').length).toBeGreaterThan(0)
    expect(screen.getByText('13.0.3')).toBeTruthy()
  })

  it('dependencies are one list, with a hint, until dependency-hierarchy has run', async () => {
    server.origins = { hierarchy_scanned: false, origin_counts: { internal: 0, external: 0, unresolved: 0, not_classified: 0 } }
    server.calls.length = 0
    await show(<StoredDependenciesView artifactId="d" head={{ summary: { packageCount: 1 }, targetFramework: 'net10.0' }} localPath={null} />)
    expect(screen.getByText(/Run dependency-hierarchy to split/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Internal/ })).toBeNull()
    expect(server.calls.filter((c) => c.startsWith('packages'))).toEqual(['packages:all'])
  })

  it('dependencies split into Internal and External with counts, and flag what is unresolved', async () => {
    server.origins = { hierarchy_scanned: true, origin_counts: { internal: 2, external: 1, unresolved: 1, not_classified: 1 } }
    server.calls.length = 0
    await show(<StoredDependenciesView artifactId="d" head={{ summary: { packageCount: 3 }, targetFramework: 'net10.0' }} localPath={null} />)
    expect(screen.getByRole('button', { name: 'Internal (2)' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'External (1)' })).toBeTruthy()
    expect(screen.getByText('1 unresolved · 1 not classified')).toBeTruthy()
    expect(screen.getAllByText('Offline.Lib').length).toBeGreaterThan(0)
    expect(screen.getByText('Unresolved')).toBeTruthy()
    expect(screen.getByText('Not classified')).toBeTruthy()
    expect(screen.getByText('Artifactory needs a login')).toBeTruthy()
    expect(screen.getByText(/corp · login needed \(401\)/)).toBeTruthy()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'External (1)' }))
    })
    expect(server.calls.filter((c) => c.startsWith('packages')).pop()).toBe('packages:external')
    expect(screen.getAllByText('Newtonsoft.Json').length).toBeGreaterThan(0)
    expect(screen.queryByText('Unresolved')).toBeNull()
  })

  it('an unresolved package says what to do and links to the Artifactory tab', async () => {
    const opened: string[] = []
    const listener = (event: Event) => opened.push((event as CustomEvent<string>).detail)
    window.addEventListener('platform:open-tab', listener)
    server.origins = { hierarchy_scanned: true, origin_counts: { internal: 2, external: 1, unresolved: 1, not_classified: 1 } }
    try {
      server.cause = 'not_on_feed'
      await show(<StoredDependenciesView artifactId="d" head={{ summary: { packageCount: 3 }, targetFramework: 'net10.0' }} localPath={null} />)
      expect(screen.getByText('On no consulted artifactory')).toBeTruthy()
      expect(screen.getByText(/Add the artifactory URL in the/)).toBeTruthy()
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Artifactory tab' }))
      })
      expect(opened).toEqual(['artifactory'])
      cleanup()

      server.cause = 'feed_auth'
      await show(<StoredDependenciesView artifactId="d" head={{ summary: { packageCount: 3 }, targetFramework: 'net10.0' }} localPath={null} />)
      expect(screen.getByText(/Set the artifactory's login/)).toBeTruthy()
      expect(screen.getByRole('button', { name: 'Artifactory tab' })).toBeTruthy()
    } finally {
      window.removeEventListener('platform:open-tab', listener)
      server.cause = 'feed_auth'
    }
  })

  it('the work list shows 20 rows with their first files, and asks for more when told to', async () => {
    await show(<StoredWorkListView artifactId="w" head={{ summary: { found: 25 } }} localPath={null} />)
    expect(screen.getAllByText('WCF service')).toHaveLength(20)
    expect(screen.getByText('50 occurrences')).toBeTruthy()
    expect(screen.getByText('src/P0/A.cs:3')).toBeTruthy()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '+5 more' }))
    })
    expect(screen.getAllByText('WCF service')).toHaveLength(25)
    expect(server.calls.filter((c) => c.startsWith('work'))).toEqual(['work:0:20', 'work:20:5'])
  })
})
