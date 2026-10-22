import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { HierarchyChild, HierarchyNode, HierarchyView } from '../../../types/hierarchy'
import { ToastProvider } from '../../../components/Toast'

// React Flow needs a real layout engine; jsdom has none. The stand-in renders each node through the section's own node
// component, so its + and − are the real ones.
vi.mock('@xyflow/react', async () => {
  const React = await import('react')
  return {
    ReactFlowProvider: ({ children }: { children: React.ReactNode }) => children,
    ReactFlow: ({ nodes, edges, nodeTypes }: { nodes: { id: string; type: string; data: unknown }[]; edges: { id: string }[]; nodeTypes: Record<string, React.ComponentType<{ data: unknown }>> }) => (
      <div data-testid="flow" data-edges={edges.length}>
        {nodes.map((n) => React.createElement(nodeTypes[n.type], { key: n.id, data: n.data }))}
      </div>
    ),
    useReactFlow: () => ({ setCenter: () => undefined, fitView: () => Promise.resolve(true) }),
    Background: () => null,
    Controls: () => null,
    Handle: () => null,
    Position: { Top: 'top', Bottom: 'bottom' },
    MarkerType: { ArrowClosed: 'arrowclosed' },
  }
})

const api = vi.hoisted(() => ({ children: vi.fn(), overview: vi.fn() }))
vi.mock('../../../api/hierarchy', () => ({
  getHierarchy: api.overview,
  getHierarchyChildren: api.children,
  searchHierarchy: () => Promise.resolve({ query: '', total: 0, matches: [] }),
  getHierarchyNode: () => new Promise(() => undefined),
}))

import { StructureSection } from './StructureSection'

function node(id: string, extra: Partial<HierarchyNode> = {}): HierarchyNode {
  return {
    id, type: id.startsWith('package:') ? 'package' : 'project', name: id.split(':')[1], status: 'checked', not_checked_reason: null,
    kind: 'application', origin: 'external', location: null, version: null, target_frameworks: ['net8.0'], legacy: false, transitive: false,
    findings: { vulnerable: false, vulnerability_max_severity: null, outdated: false, deprecated: false, outcome: null },
    work_items: 0, referenced_by: 1, child_count: 0, ...extra,
  }
}

function child(from: string, target: HierarchyNode): HierarchyChild {
  return {
    edge: { from_node: from, to_node: target.id, kind: target.type === 'package' ? 'package_reference' : 'project_reference', resolution: 'declared',
      version_requested: null, frameworks: [], closes_cycle: false, declared_file: null, declared_line: null },
    node: target,
  }
}

const SHARED = node('project:Shared', { kind: 'library', referenced_by: 2 })
const PACKAGES = Array.from({ length: 23 }, (_, i) => node(`package:Pkg${String(i).padStart(2, '0')}`))
const CHILDREN: Record<string, HierarchyChild[]> = {
  'project:Web': [child('project:Web', SHARED), ...PACKAGES.map((p) => child('project:Web', p))],
  'project:Worker': [child('project:Worker', SHARED)],
}

beforeEach(() => {
  window.localStorage.clear()
  api.overview.mockReset().mockResolvedValue({
    repository_id: 'r', step_execution_id: null,
    summary: { project_count: 3, count_by_project_kind: { application: 2, library: 1 }, package_count: 23, internal_package_count: 0, external_package_count: 23,
      transitive_package_count: 0, assembly_count: 0, edge_count: 25, count_by_edge_kind: {}, cycle_count: 0, not_checked_count: 0 },
    roots: [node('project:Web', { child_count: 24 }), node('project:Worker', { child_count: 1 })],
  })
  api.children.mockReset().mockImplementation((_r: string, id: string, _v: HierarchyView, offset: number, limit: number) =>
    Promise.resolve({ node_id: id, total: CHILDREN[id].length, offset, items: CHILDREN[id].slice(offset, offset + limit) }))
})
afterEach(cleanup)

async function renderSection(mode: 'graph' | 'tree') {
  window.localStorage.setItem('structure:view', mode)
  render(
    <ToastProvider>
      <StructureSection repositoryId="r" localPath="D:\repo" refreshToken={0} assessment={undefined} />
    </ToastProvider>,
  )
  await screen.findByRole('button', { name: 'Expand Web' })
}

async function click(name: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name }))
  })
}

describe('Structure, as a graph', () => {
  it('opens showing only the roots, and expands a node only with its +', async () => {
    await renderSection('graph')
    expect(screen.getAllByTestId(/^graph-node-/).map((n) => n.dataset.testid)).toEqual(['graph-node-project:Web', 'graph-node-project:Worker'])
    expect(api.children).not.toHaveBeenCalled()

    fireEvent.doubleClick(screen.getByTestId('graph-node-project:Web'))
    expect(api.children).not.toHaveBeenCalled()                                  // nothing expands on a double click

    await click('Expand Web')
    expect(api.children).toHaveBeenCalledWith('r', 'project:Web', { transitive: false, show: 'all' }, 0, 20)
    expect(screen.getByTestId('graph-node-project:Shared')).toBeTruthy()
    expect(screen.getByRole('button', { name: '+4 more' })).toBeTruthy()       // 24 children: 20, then +4 more
  })

  it('a shared node is drawn once when a second parent is expanded, and says how many reference it', async () => {
    await renderSection('graph')
    await click('Expand Web')
    await click('Expand Worker')
    expect(screen.getAllByTestId('graph-node-project:Shared')).toHaveLength(1)
    expect(within(screen.getByTestId('graph-node-project:Shared')).getByText('referenced by 2')).toBeTruthy()
  })

  it('− collapses: the children disappear, and + brings them back without asking again', async () => {
    await renderSection('graph')
    await click('Expand Web')
    await click('Collapse Web')
    expect(screen.queryByTestId('graph-node-project:Shared')).toBeNull()
    await click('Expand Web')
    expect(screen.getByTestId('graph-node-project:Shared')).toBeTruthy()
    expect(api.children).toHaveBeenCalledTimes(1)
  })

  it('"+N more" shows the rest', async () => {
    await renderSection('graph')
    await click('Expand Web')
    await click('+4 more')
    expect(screen.getByTestId('graph-node-package:Pkg22')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /more$/ })).toBeNull()
  })
})

describe('Structure, as a tree', () => {
  it('has the same + and −, and the 20-item rule', async () => {
    await renderSection('tree')
    expect(screen.getAllByRole('treeitem').map((t) => t.getAttribute('aria-label'))).toEqual(['Web', 'Worker'])
    await click('Expand Web')
    const web = screen.getAllByRole('treeitem')[0]
    expect(within(web).getAllByRole('treeitem')).toHaveLength(20)
    expect(within(web).getByRole('button', { name: '+4 more' })).toBeTruthy()
    await click('Collapse Web')
    expect(screen.getAllByRole('treeitem')).toHaveLength(2)
  })

  it('turning on transitive packages asks again with the new view', async () => {
    await renderSection('tree')
    await act(async () => {
      fireEvent.click(screen.getByRole('checkbox', { name: 'Transitive packages' }))
    })
    expect(api.overview).toHaveBeenLastCalledWith('r', { transitive: true, show: 'all' })
  })
})
