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
    page,
    work,
  }
})

vi.mock('../../api/results', () => ({
  getFingerprintOverview: () => Promise.resolve({ status_counts: { SCANNED: 3 }, categories: [{ category: 'ENTRY_POINT', signals: 2, distinct: 1 }] }),
  fingerprintSignals: (_a: string, category: string) => () => {
    server.calls.push(`signals:${category}`)
    return server.page([{ name: 'ASP_NET_CORE', value: '8.0', project: 'src/A/A.csproj', sourcePath: null, occurrences: 1, confidence: 1 }])
  },
  listDependencyFeeds: () => Promise.resolve([{ name: 'nuget.org', url: 'https://api.nuget.org/v3/index.json', role: 'nuget_org' }]),
  dependencyPackages: () => () =>
    server.page([{
      packageId: 'Newtonsoft.Json', drift: false, projectCount: 1,
      versions: [{ version: '12.0.3', useCount: 1, outcomes: ['upgrade_safe'], projects: ['src/A/A.csproj'],
                   first: { project: 'src/A/A.csproj', declaredAt: { filePath: 'src/A/A.csproj', line: 9 } },
                   worst: { project: 'src/A/A.csproj', pkg: { packageId: 'Newtonsoft.Json', outcome: 'upgrade_safe', currentVersion: '12.0.3', recommendedVersion: '13.0.3' } } }],
    }]),
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
    await show(<StoredDependenciesView artifactId="d" head={{ summary: { packageCount: 1 }, targetFramework: 'net10.0' }} localPath={null} />)
    expect(screen.getAllByText('Newtonsoft.Json').length).toBeGreaterThan(0)
    expect(screen.getByText('13.0.3')).toBeTruthy()
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
