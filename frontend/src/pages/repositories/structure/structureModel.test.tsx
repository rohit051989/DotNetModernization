import { describe, expect, it } from 'vitest'
import type { HierarchyChild, HierarchyEdgeKind, HierarchyNode } from '../../../types/hierarchy'
import { addChildren, collapse, expand, initialState, needsLoad, pin, showMore, visibleGraph } from './structureModel'

function node(id: string, extra: Partial<HierarchyNode> = {}): HierarchyNode {
  return {
    id,
    type: id.startsWith('package:') ? 'package' : 'project',
    name: id.split(':')[1],
    status: 'checked',
    not_checked_reason: null,
    kind: 'library',
    origin: null,
    location: null,
    version: null,
    target_frameworks: [],
    legacy: false,
    transitive: false,
    findings: { vulnerable: false, vulnerability_max_severity: null, outdated: false, deprecated: false, outcome: null },
    work_items: 0,
    referenced_by: 1,
    child_count: 0,
    ...extra,
  }
}

function child(from: string, to: string, kind: HierarchyEdgeKind = 'project_reference'): HierarchyChild {
  return {
    edge: { from_node: from, to_node: to, kind, resolution: 'declared', version_requested: null, frameworks: [], closes_cycle: false, declared_file: null, declared_line: null },
    node: node(to),
  }
}

const WEB = 'project:Web'
const WORKER = 'project:Worker'
const SHARED = 'project:Shared'
const roots = [node(WEB, { child_count: 1 }), node(WORKER, { child_count: 1 })]

describe('structureModel', () => {
  it('opens showing only the roots', () => {
    const graph = visibleGraph(initialState(roots))
    expect(graph.nodes.map((n) => n.id)).toEqual([WEB, WORKER])
    expect(graph.edges).toEqual([])
  })

  it('expanding a node shows its children once they are loaded, and asks for them until then', () => {
    let state = expand(initialState(roots), WEB)
    expect(needsLoad(state, WEB)).toBe(true)
    state = addChildren(state, WEB, 1, [child(WEB, SHARED)])
    expect(needsLoad(state, WEB)).toBe(false)
    expect(visibleGraph(state).nodes.map((n) => n.id)).toEqual([WEB, WORKER, SHARED])
  })

  it('a shared node two expanded parents lead to is drawn once, with an edge from each', () => {
    let state = initialState(roots)
    state = addChildren(expand(state, WEB), WEB, 1, [child(WEB, SHARED)])
    state = addChildren(expand(state, WORKER), WORKER, 1, [child(WORKER, SHARED)])
    const graph = visibleGraph(state)
    expect(graph.nodes.filter((n) => n.id === SHARED)).toHaveLength(1)
    expect(graph.edges.map((e) => e.edge.from_node).sort()).toEqual([WEB, WORKER])
  })

  it('collapsing hides what only that node led to, and keeps what another expanded parent still shows', () => {
    let state = initialState(roots)
    state = addChildren(expand(state, WEB), WEB, 2, [child(WEB, SHARED), child(WEB, 'project:WebOnly')])
    state = addChildren(expand(state, WORKER), WORKER, 1, [child(WORKER, SHARED)])
    state = collapse(state, WEB)
    const ids = visibleGraph(state).nodes.map((n) => n.id)
    expect(ids).toContain(SHARED)
    expect(ids).not.toContain('project:WebOnly')
    state = collapse(state, WORKER)
    expect(visibleGraph(state).nodes.map((n) => n.id)).toEqual([WEB, WORKER])
  })

  it('collapsing and expanding again restores the same picture without reloading', () => {
    let state = addChildren(expand(initialState(roots), WEB), WEB, 1, [child(WEB, SHARED)])
    state = expand(collapse(state, WEB), WEB)
    expect(needsLoad(state, WEB)).toBe(false)
    expect(visibleGraph(state).nodes.map((n) => n.id)).toContain(SHARED)
  })

  it('shows the first 20 children, then "+N more", 20 more at a time', () => {
    const many = Array.from({ length: 45 }, (_, i) => child(WEB, `package:p${String(i).padStart(2, '0')}@1.0.0`, 'package_reference'))
    let state = addChildren(expand(initialState(roots), WEB), WEB, 45, many.slice(0, 20))
    expect(visibleGraph(state).nodes).toHaveLength(22)
    expect(visibleGraph(state).more).toEqual({ [WEB]: 25 })
    state = showMore(state, WEB)
    expect(needsLoad(state, WEB)).toBe(true)
    state = addChildren(state, WEB, 45, many.slice(20, 40))
    expect(visibleGraph(state).more).toEqual({ [WEB]: 5 })
    expect(visibleGraph(state).nodes).toHaveLength(42)
  })

  it('a pinned child shows beyond the first page, as a search reveals it', () => {
    const many = Array.from({ length: 30 }, (_, i) => child(WEB, `package:p${i}@1.0.0`, 'package_reference'))
    let state = addChildren(expand(initialState(roots), WEB), WEB, 30, many.slice(0, 20))
    state = pin(state, WEB, many[27])
    expect(visibleGraph(state).nodes.map((n) => n.id)).toContain('package:p27@1.0.0')
  })
})
