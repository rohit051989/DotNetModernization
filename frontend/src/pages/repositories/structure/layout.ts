import dagre from '@dagrejs/dagre'
import type { VisibleGraph } from './structureModel'

export const NODE_WIDTH = 236
export const NODE_HEIGHT = 74
export const MORE_WIDTH = 120
export const MORE_HEIGHT = 30

export interface Placed {
  id: string
  x: number
  y: number
}

/** The id of a parent's "+N more" placeholder. */
export function moreId(parentId: string) {
  return `more:${parentId}`
}

/**
 * Top to bottom from the roots (dagre, the layered layout): each visible node and each "+N more" placeholder gets a
 * position, its top-left corner. Only what is on screen is laid out, so expanding stays quick however large the
 * repository's graph is.
 */
export function layout(graph: VisibleGraph): Map<string, Placed> {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'TB', nodesep: 22, ranksep: 64, marginx: 12, marginy: 12 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const node of graph.nodes) g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT })
  for (const { edge } of graph.edges) {
    if (!edge.closes_cycle) g.setEdge(edge.from_node, edge.to_node)          // a cycle's closing edge must not pull ranks upward
  }
  for (const parent of Object.keys(graph.more)) {
    g.setNode(moreId(parent), { width: MORE_WIDTH, height: MORE_HEIGHT })
    g.setEdge(parent, moreId(parent))
  }

  dagre.layout(g)
  const placed = new Map<string, Placed>()
  for (const id of g.nodes()) {
    const n = g.node(id)
    placed.set(id, { id, x: n.x - n.width / 2, y: n.y - n.height / 2 })
  }
  return placed
}
