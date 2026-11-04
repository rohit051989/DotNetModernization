import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EntryPointBackendRow } from '../../../types/surface'
import { ToastProvider } from '../../../components/Toast'
import { buildFlow } from './flowModel'
import { OperationFlowGraph, toRfNodes } from './OperationFlowGraph'
import { layoutFlow } from './reachLayout'

// React Flow needs a real layout engine; jsdom has none. The stand-in renders each node through the graph's own node
// components.
vi.mock('@xyflow/react', async () => {
  const React = await import('react')
  return {
    ReactFlowProvider: ({ children }: { children: React.ReactNode }) => children,
    ReactFlow: ({ nodes, edges, nodeTypes }: { nodes: { id: string; type: string; data: unknown }[]; edges: { id: string }[]; nodeTypes: Record<string, React.ComponentType<{ data: unknown }>> }) => (
      <div data-testid="flow" data-edges={edges.length}>
        {nodes.map((n) => React.createElement(nodeTypes[n.type], { key: n.id, data: n.data }))}
      </div>
    ),
    useReactFlow: () => ({ fitView: () => Promise.resolve(true) }),
    Background: () => null,
    Controls: () => null,
    Handle: () => null,
    Position: { Top: 'top', Bottom: 'bottom' },
    MarkerType: { ArrowClosed: 'arrowclosed' },
  }
})

afterEach(cleanup)

const host = { environment: 'prod', host: 'verify.client-a.example', port: null, path: null, source_file: null, deploy_parameter: null, host_project: null, linux_verdict: null }

const row: EntryPointBackendRow = {
  number: 1,
  entry_point_id: 'ep',
  kind: 'http_action',
  service: 'AccountController',
  operation: 'Post',
  handler: { type: 'AccountController', member: 'Post', filePath: 'src/AccountController.cs', lineStart: 5 },
  status: 'yes',
  calls: [
    {
      invocation_id: 'soap-1',
      mechanism: 'soap_client',
      contract: 'IVerify',
      operation: 'Check',
      call_site: { filePath: 'src/VerificationClient.cs', lineStart: 30, lineEnd: 30 },
      depth: 2,
      via: ['Post', 'AccountService.Open', 'VerificationClient.Verify'],
      conditional: true,
      in_loop: false,
      context: ['if (isNew)'],
      endpoint: { shown: host, grouped_by: 'production_environment', others: [] },
      linux_verdict: 'compatible',
    },
  ],
  unresolved: [],
}

describe('toRfNodes', () => {
  it('never marks a node unselectable, or React Flow turns its pointer events off and its + and − stop working', () => {
    const flow = buildFlow(row)
    const nodes = toRfNodes(flow, layoutFlow(flow), (node) => ({ node, localPath: '', folded: false, children: 0, onToggle: () => undefined }))
    expect(nodes).toHaveLength(flow.nodes.length)
    expect(nodes.every((n) => n.selectable !== false)).toBe(true)
  })
})

describe('OperationFlowGraph', () => {
  it('draws the handler, each method it walks and the backend call with its mechanism, endpoint and condition', () => {
    render(
      <ToastProvider>
        <OperationFlowGraph row={row} localPath="C:\repo" />
      </ToastProvider>,
    )
    expect(screen.getByTestId('flow-method-AccountController.Post')).toBeTruthy()
    expect(screen.getByTestId('flow-method-AccountService.Open')).toBeTruthy()
    expect(screen.getByTestId('flow-method-VerificationClient.Verify')).toBeTruthy()
    const backend = screen.getByTestId('flow-call-soap_client')
    expect(backend.textContent).toContain('SOAP')
    expect(backend.textContent).toContain('Check')
    expect(backend.textContent).toContain('verify.client-a.example')
    expect(backend.textContent).toContain('conditional')
    expect(screen.getByTestId('flow').getAttribute('data-edges')).toBe('3')
  })

  it('folds what a method calls with its − and shows it again with its +', () => {
    render(
      <ToastProvider>
        <OperationFlowGraph row={row} localPath="C:\repo" />
      </ToastProvider>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Collapse AccountService.Open' }))
    expect(screen.queryByTestId('flow-method-VerificationClient.Verify')).toBeNull()
    expect(screen.queryByTestId('flow-call-soap_client')).toBeNull()
    expect(screen.getByTestId('flow-method-AccountService.Open')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Expand AccountService.Open' }))
    expect(screen.getByTestId('flow-call-soap_client')).toBeTruthy()
  })
})
