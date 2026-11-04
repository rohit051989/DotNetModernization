import { describe, expect, it } from 'vitest'
import type { BackendCall, EntryPointBackendRow } from '../../../types/surface'
import { MAX_FLOW_NODES, ROOT_ID, buildFlow, childCounts, visibleFlow } from './flowModel'

function call(mechanism: string, via: string[], line: number, operation = 'Op'): BackendCall {
  return {
    invocation_id: `inv-${mechanism}`,
    mechanism,
    contract: null,
    operation,
    call_site: { filePath: 'src/A.cs', lineStart: line, lineEnd: line },
    depth: via.length - 1,
    via,
    conditional: false,
    in_loop: false,
    context: [],
    endpoint: { shown: { environment: 'prod', host: 'h', port: null, path: null, source_file: null, deploy_parameter: null, host_project: null, linux_verdict: null }, grouped_by: 'host', others: [] },
    linux_verdict: 'compatible',
  }
}

function row(calls: BackendCall[], unresolved: EntryPointBackendRow['unresolved'] = []): EntryPointBackendRow {
  return {
    number: 1,
    entry_point_id: 'ep',
    kind: 'http_action',
    service: 'AccountController',
    operation: 'Post',
    handler: { type: 'AccountController', member: 'Post', filePath: 'src/AccountController.cs', lineStart: 5 },
    status: 'yes',
    calls,
    unresolved,
  }
}

const methods = (flow: ReturnType<typeof buildFlow>) =>
  flow.nodes.flatMap((n) => (n.kind === 'method' ? [`${n.owner}.${n.method}`] : []))

describe('buildFlow', () => {
  it('draws the handler alone for an operation that calls nothing', () => {
    const flow = buildFlow(row([]))
    expect(methods(flow)).toEqual(['AccountController.Post'])
    expect(flow.edges).toEqual([])
  })

  it('follows a chain across classes and hangs the backend call on the last method', () => {
    const flow = buildFlow(row([call('database', ['Post', 'AccountService.Open', 'AccountRepo.Save'], 40)]))
    expect(methods(flow)).toEqual(['AccountController.Post', 'AccountService.Open', 'AccountRepo.Save'])
    const leaf = flow.nodes.find((n) => n.kind === 'backend')!
    expect(flow.edges.map((e) => e.to)).toContain(leaf.id)
    expect(flow.edges.find((e) => e.to === leaf.id)!.from).toBe(`${ROOT_ID}/AccountService.Open/AccountRepo.Save`)
  })

  it('shows a call made by an intermediate method on that method, beside the chain that goes on', () => {
    const flow = buildFlow(
      row([
        call('http_client', ['Post', 'AccountService.Open'], 20, 'GET /verify'),
        call('soap_client', ['Post', 'AccountService.Open', 'VerificationClient.Verify'], 30, 'Check'),
        call('database', ['Post', 'AccountService.Open', 'VerificationClient.Verify', 'AccountRepo.Save'], 40),
      ]),
    )
    // The shared prefix is one node, not three.
    expect(methods(flow)).toEqual(['AccountController.Post', 'AccountService.Open', 'VerificationClient.Verify', 'AccountRepo.Save'])
    const from = (mechanism: string) => flow.edges.find((e) => e.to === flow.nodes.find((n) => n.kind === 'backend' && n.call.mechanism === mechanism)!.id)!.from
    expect(from('http_client')).toBe(`${ROOT_ID}/AccountService.Open`)
    expect(from('soap_client')).toBe(`${ROOT_ID}/AccountService.Open/VerificationClient.Verify`)
    expect(from('database')).toBe(`${ROOT_ID}/AccountService.Open/VerificationClient.Verify/AccountRepo.Save`)
  })

  it('keeps a bare hop in the class before it', () => {
    const flow = buildFlow(row([call('http_client', ['Post', 'Send'], 12)]))
    expect(methods(flow)).toEqual(['AccountController.Post', 'AccountController.Send'])
  })

  it('hangs a path that was not followed off the handler, dashed', () => {
    const flow = buildFlow(row([], [{ reason: 'Deep: more than 8 calls deep; not followed', callSite: { filePath: 'src/A.cs', lineStart: 9, lineEnd: 9 } }]))
    const node = flow.nodes.find((n) => n.kind === 'unresolved')!
    expect(flow.edges).toEqual([{ id: expect.any(String), from: ROOT_ID, to: node.id, kind: 'unresolved' }])
  })

  it('draws two calls at the same site once', () => {
    const flow = buildFlow(row([call('database', ['Post'], 7), call('database', ['Post'], 7)]))
    expect(flow.nodes.filter((n) => n.kind === 'backend')).toHaveLength(1)
  })

  it('leaves out everything below a collapsed method, and counts what hangs off each node', () => {
    const flow = buildFlow(
      row([
        call('http_client', ['Post', 'AccountService.Open'], 20),
        call('soap_client', ['Post', 'AccountService.Open', 'VerificationClient.Verify'], 30),
      ]),
    )
    const open = `${ROOT_ID}/AccountService.Open`
    expect(childCounts(flow).get(open)).toBe(2)
    const folded = visibleFlow(flow, new Set([open]))
    expect(folded.nodes.map((n) => n.id)).toEqual([ROOT_ID, open])
    expect(folded.edges).toHaveLength(1)
  })

  it('draws a large operation to a limit, with the rest as a count, and no edge to a node it left out', () => {
    const calls = Array.from({ length: 60 }, (_, i) => call(`m${i}`, ['Post', `S${i}.Run`], i + 1))
    const flow = buildFlow(row(calls))
    expect(flow.nodes).toHaveLength(MAX_FLOW_NODES + 1)
    const more = flow.nodes.find((n) => n.kind === 'more')!
    expect(more).toMatchObject({ hidden: 121 - MAX_FLOW_NODES })
    const ids = new Set(flow.nodes.map((n) => n.id))
    expect(flow.edges.every((e) => ids.has(e.from) && ids.has(e.to))).toBe(true)
  })
})
