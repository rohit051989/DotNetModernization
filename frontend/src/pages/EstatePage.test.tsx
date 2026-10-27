import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../components/Toast'

// The Estate tab against a server that pages: each view renders its summary from the estate's heads and its lists
// from their own endpoints, a page at a time.
const asked = vi.hoisted(() => [] as string[])
const page = vi.hoisted(() => (name: string, items: unknown[]) => () => {
  asked.push(name)
  return Promise.resolve({ total: items.length, matching: items.length, offset: 0, items })
})
const coverage = { repositoriesIncluded: 2, repositoriesInEngagement: 2, partialEstate: false, repositoriesPending: 0, coverageRatio: 1 }

vi.mock('../api/estate', () => ({
  getEstate: () =>
    Promise.resolve({
      engagement_id: 'e',
      run: { step_execution_id: 's', job_execution_id: 'j', completed_at: '2026-10-27T10:00:00Z', exit_message: null },
      artifacts: {
        'endpoint-register': { coverage, productionEnvironment: null, servedByAnnotations: {},
                               summary: { hosts: 1, internal: 0, external: 1, unresolved: 1, unusedExcluded: 0, noLongerCalled: 0, groupedByProductionHost: 0, requiresBackendChange: 1 } },
        'package-estate': { coverage, summary: { packages: 1, estateDrift: 0, crossRepositoryDrift: 0 } },
        'dependency-graph': { coverage, summary: { projects: 2, edges: 1, crossRepositoryEdges: 1, sharedLibraries: 0, cycles: 0, originReconciliations: 0 } },
        'integration-map': { coverage, summary: { edges: 0, crossRepositoryEdges: 0, sameRepositoryEdges: 0, operationsUnmatched: 0, operationsUnresolved: 0, entryPoints: 1, entryPointsInternalCallerFound: 0, entryPointsNoInternalCallerFound: 1 } },
        'context-map': { coverage },
      },
      artifact_ids: {},
      register_counts: { backend: 1, another_team: 1, this_migration: 0, under_way: 0, not_started: 1, done: 0 },
      served_by_pending: false,
      settings: { production_environment: null, target_wcf_client_version: null, target_wcf_client_version_effective: '8.1.2', deploy_parameter_globs: [], deploy_parameter_globs_default: true, environments: [], repositories: ['shop', 'orders'], version: 1 },
    }),
  putEndpointAnnotation: vi.fn(),
  putEstateSettings: vi.fn(),
  soapCompatibilityCsvUrl: () => '#',
}))
vi.mock('../api/results', () => ({
  registerHosts: () =>
    page('hosts', [{
      host: { host: 'inventory.client-a.example', classification: 'external', services: [], otherHosts: [], callingRepositories: ['orders'],
              callingRepositoryCount: 1, bindings: [], mechanisms: ['http_client'], worstVerdict: 'compatible', requiresBackendChange: true,
              backendChangeOwner: 'another_team', backendChangeReasons: [], underReview: [], verdictByEnvironment: {}, loopback: false },
      annotation: null,
    }]),
  registerUnresolved: () => page('unresolved', [{ repositorySlug: 'shop', projectPath: 'a.csproj', mechanism: 'database', contract: null, placeholder: 'Db', resolution: 'unresolved', invocationId: 'i' }]),
  integrationApplications: () =>
    page('applications', [{ repositorySlug: 'orders', projectPath: 'src/Orders.Api/Orders.Api.csproj', repositoryId: 'r', projectId: 'p',
                            counts: { calls: 0, exposes: 1, called: 0, uncalled: 1 },
                            calls: { total: 0, matching: 0, offset: 0, items: [] }, called: { total: 0, matching: 0, offset: 0, items: [] },
                            uncalled: { total: 1, matching: 1, offset: 0, items: [{ entryPointId: 'x', operation: 'GET /api/orders/{id}', matchable: true, callers: [] }] } }]),
  integrationList: () => page('list', []),
  estatePackages: () => page('packages', [{ packageId: 'Newtonsoft.Json', repositoryCount: 1, repositories: ['shop'], projectCount: 2, projects: [], versionsInUse: { '12.0.3': 2 }, estateDrift: false, crossRepositoryDrift: false, recommendedVersion: '13.0.3', outcomes: { upgrade_safe: 2 }, breakingMembers: [], flags: { deprecated: false, vulnerable: false, notInClientFeed: false }, feedSources: [] }]),
  estateDependencies: (_e: string, which: string) => page(`dependencies:${which}`, which === 'cross-repository'
    ? [{ from: { repositorySlug: 'orders', projectPath: 'a', projectId: '1' }, to: { repositorySlug: 'shop', projectPath: 'b', projectId: '2' }, kind: 'package', crossRepository: true, via: 'Shop.Client', clientFeed: true }]
    : []),
  getContextMap: () => Promise.resolve({ coverage, format: 'structurizr-dsl', dsl: 'workspace {}', systems: [], relationships: [] }),
  soapHosts: () => page('soap', []),
  soapCallers: () => page('callers', []),
  locateSoapCall: () => Promise.resolve({ host: null, position: null }),
}))
vi.mock('./RuleConflictsViews', () => ({ EstateRuleConflictsView: () => null }))

import { EstatePage } from './EstatePage'

afterEach(cleanup)

async function view(name: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name }))
  })
}

describe('EstatePage', () => {
  it('shows each view from its own paged list', async () => {
    await act(async () => {
      render(
        <ToastProvider>
          <EstatePage engagementId="e" onOpenRepository={() => {}} />
        </ToastProvider>,
      )
    })
    expect(screen.getByText('inventory.client-a.example')).toBeTruthy()
    expect(screen.getByText('1 host requires backend change')).toBeTruthy()
    expect(screen.getByText(/1 not started/)).toBeTruthy()
    await view('Integration')
    expect(screen.getByText('orders:src/Orders.Api/Orders.Api.csproj')).toBeTruthy()
    await view('Packages')
    expect(screen.getByText('Newtonsoft.Json')).toBeTruthy()
    await view('Dependencies')
    expect(screen.getByText('orders:a')).toBeTruthy()
    await view('Context')
    expect(asked).toEqual(expect.arrayContaining(['hosts', 'applications', 'packages', 'dependencies:cross-repository']))
  })
})
