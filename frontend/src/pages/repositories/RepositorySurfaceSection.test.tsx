import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/Toast'

// The Surface tab against a server that pages: each panel shows its summary, its projects a page at a time, and a
// project's entry points or invocations only when the project is opened.
const asked = vi.hoisted(() => [] as string[])
const page = vi.hoisted(() => (name: string, items: unknown[]) => () => {
  asked.push(name)
  return Promise.resolve({ total: items.length, matching: items.length, offset: 0, items })
})
const project = (id: string, path: string, requests: number) => ({
  project_id: id, project_path: path, status: 'SCANNED', skip_reason: null, request_entry_point_count: requests, lifecycle_hook_count: 0,
  count_by_kind: {}, count_by_origin: {}, count_by_verb: {}, no_declared_authentication_count: 0, authorisation_not_assessed_count: 0,
  global_authorisation: [], conventional_routes: [], kinds: requests ? [{ entry_class: 'request', kind: 'http_controller_action', count: requests }] : [],
})

vi.mock('../../api/results', () => ({
  getEntryPointSummary: () => Promise.resolve({
    repository_id: 'r', scanner_version: '2', skip_source: 'x', scanned_at: null, entry_point_count: 1, request_entry_point_count: 1,
    lifecycle_hook_count: 0, count_by_kind: { http_controller_action: 1 }, count_by_origin: {}, count_by_verb: {}, no_declared_authentication_count: 0,
    authorisation_not_assessed_count: 0, auth_declared_scope: 'scope', capabilities_manifest_version: null, capability_kinds: [],
    project_count: 5, projects_with_requests: 1, lifecycle_hooks_without_requests: 0,
  }),
  entryPointProjects: (_r: string, withRequests: boolean) =>
    withRequests ? page('projects', [project('p1', 'src/Api/Api.csproj', 1)]) : page('no-requests', [project('p2', 'src/Lib/Lib.csproj', 0)]),
  entryPoints: () => page('entries', [{
    id: 'e1', kind: 'http_controller_action', origin: 'application', origin_reconciled_from: null, origin_reconciliation_reason: null,
    entry_class: 'request', handler_type: 'OrdersController', handler_member: 'Get', file_path: 'src/Api/OrdersController.cs', line_start: 10, line_end: 12,
    detail: { verb: 'GET', routeTemplate: 'api/orders/{id}', routing: 'attribute', parameters: [], authorisation: null, mappedTemplate: null },
    confidence: 1, confidence_reasons: [], auth_declared: 'declared',
  }]),
  getOutboundSummary: () => Promise.resolve({
    repository_id: 'r', scanner_version: '1', skip_source: 'x', scanned_at: null, invocation_count: 0, unused_count: 0, count_by_mechanism: {},
    count_by_verdict: {}, auth_declared_scope: 'scope', project_count: 5, projects_with_invocations: 0,
  }),
  outboundProjects: () => page('outbound', []),
  outboundInvocations: () => page('invocations', []),
  getBackendSummary: () => Promise.resolve({ repository_id: 'r', production_environment: null, operations: 0, applications: 0, count_by_status: {} }),
  backendApplications: () => page('applications', []),
  backendOperations: () => page('operations', []),
  getSoapSummary: () => Promise.resolve({ repository_id: 'r', engagement_id: 'e', scanned_at: null, estate_run_at: null, estate_stale: false, estate_note: null,
                                          target_wcf_client_version: null, unused_count: 0, calls: 0, environments: 0, need_change: 0, undecided: 0 }),
  soapCalls: () => page('soap', []),
}))

import { RepositorySurfaceSection } from './RepositorySurfaceSection'

afterEach(cleanup)

describe('RepositorySurfaceSection', () => {
  it('lists projects a page at a time, and a project\'s routes from its own list', async () => {
    await act(async () => {
      render(
        <ToastProvider>
          <RepositorySurfaceSection repositoryId="r" localPath="D:\\repos\\shop" refreshToken={0} />
        </ToastProvider>,
      )
    })
    expect(screen.getByText('src/Api/Api.csproj')).toBeTruthy()
    // One of a few: open at first, its routes asked for and shown.
    expect(screen.getByText('/api/orders/{id}')).toBeTruthy()
    expect(screen.getByText('4 projects with no request entry points')).toBeTruthy()
    expect(asked).not.toContain('no-requests')
    await act(async () => {
      fireEvent.click(screen.getByText('4 projects with no request entry points'))
    })
    expect(asked).toContain('no-requests')
    expect(screen.getByText('src/Lib/Lib.csproj')).toBeTruthy()
  })
})
