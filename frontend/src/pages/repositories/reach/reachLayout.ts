import dagre from '@dagrejs/dagre'
import type { Flow, FlowNode } from './flowModel'

// The same card size as the structure graph's nodes.
export const SIZES: Record<FlowNode['kind'], { width: number; height: number }> = {
  method: { width: 236, height: 74 },
  backend: { width: 236, height: 74 },
  unresolved: { width: 236, height: 74 },
  more: { width: 120, height: 30 },
}

/** Top to bottom from the handler (dagre, the layered layout), as the structure graph does: each node's top-left corner. */
export function layoutFlow(flow: Flow): Map<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'TB', nodesep: 22, ranksep: 64, marginx: 12, marginy: 12 })
  g.setDefaultEdgeLabel(() => ({}))
  // dagre writes each node's position onto the object it is given: one copy per node, never the shared size.
  for (const node of flow.nodes) g.setNode(node.id, { ...SIZES[node.kind] })
  for (const edge of flow.edges) g.setEdge(edge.from, edge.to)
  dagre.layout(g)

  const positions = new Map<string, { x: number; y: number }>()
  for (const id of g.nodes()) {
    const n = g.node(id)
    positions.set(id, { x: n.x - n.width / 2, y: n.y - n.height / 2 })
  }
  return positions
}
