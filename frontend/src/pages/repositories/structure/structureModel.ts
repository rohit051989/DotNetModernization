import type { HierarchyChild, HierarchyEdge, HierarchyNode } from '../../../types/hierarchy'

/** The 20-item rule: a node shows its first 20 children, then "+N more". */
export const CHILD_PAGE = 20

/** A node's children as loaded so far, page by page, for the current view. */
export interface LoadedChildren {
  total: number
  items: HierarchyChild[]
}

/**
 * What the person has opened. The graph and the tree both draw from this.
 * - expanded: nodes whose + was pressed (and not their −);
 * - shown: how many children each expanded node shows (20, then 40 after "+N more", …);
 * - pinned: children made visible beyond that, because a search revealed them;
 * - children: what has been loaded, by node id.
 */
export interface StructureState {
  roots: HierarchyNode[]
  children: Record<string, LoadedChildren>
  expanded: ReadonlySet<string>
  shown: Record<string, number>
  pinned: Record<string, HierarchyChild[]>
}

export function initialState(roots: HierarchyNode[]): StructureState {
  return { roots, children: {}, expanded: new Set(), shown: {}, pinned: {} }
}

export function expand(state: StructureState, nodeId: string): StructureState {
  if (state.expanded.has(nodeId)) return state
  return { ...state, expanded: new Set([...state.expanded, nodeId]), shown: { ...state.shown, [nodeId]: state.shown[nodeId] ?? CHILD_PAGE } }
}

/** Hides the node's children. What only they led to disappears with them; their own expanded state is kept, so
 * expanding again shows the same picture. */
export function collapse(state: StructureState, nodeId: string): StructureState {
  if (!state.expanded.has(nodeId)) return state
  const expanded = new Set(state.expanded)
  expanded.delete(nodeId)
  return { ...state, expanded }
}

export function showMore(state: StructureState, nodeId: string): StructureState {
  return { ...state, shown: { ...state.shown, [nodeId]: (state.shown[nodeId] ?? CHILD_PAGE) + CHILD_PAGE } }
}

/** Adds a loaded page of children, in order, without repeating any already held. */
export function addChildren(state: StructureState, nodeId: string, total: number, items: HierarchyChild[]): StructureState {
  const current = state.children[nodeId]?.items ?? []
  const seen = new Set(current.map(key))
  return {
    ...state,
    children: { ...state.children, [nodeId]: { total, items: [...current, ...items.filter((i) => !seen.has(key(i)))] } },
  }
}

/** Makes a child visible under its parent whatever page it is on — a search's path. */
export function pin(state: StructureState, parentId: string, child: HierarchyChild): StructureState {
  const pinned = state.pinned[parentId] ?? []
  if (pinned.some((p) => key(p) === key(child))) return state
  return { ...state, pinned: { ...state.pinned, [parentId]: [...pinned, child] } }
}

/** The view changed (transitive packages, filter): what was loaded no longer applies. What is expanded stays. */
export function resetChildren(state: StructureState, roots: HierarchyNode[]): StructureState {
  return { ...state, roots, children: {}, pinned: {} }
}

/** How many children a node needs loaded to show what it should. */
export function wanted(state: StructureState, nodeId: string): number {
  return state.shown[nodeId] ?? CHILD_PAGE
}

/** Whether a node needs its next page loaded: expanded, showing more than is loaded, and the server has more. */
export function needsLoad(state: StructureState, nodeId: string): boolean {
  if (!state.expanded.has(nodeId)) return false
  const loaded = state.children[nodeId]
  return loaded === undefined || (loaded.items.length < wanted(state, nodeId) && loaded.items.length < loaded.total)
}

function key(child: HierarchyChild): string {
  return `${child.edge.from_node}|${child.edge.to_node}|${child.edge.kind}`
}

export interface VisibleEdge {
  id: string
  edge: HierarchyEdge
}

export interface VisibleGraph {
  /** Each node once, however many visible parents it has. */
  nodes: HierarchyNode[]
  edges: VisibleEdge[]
  /** For each expanded node with children not shown: how many. */
  more: Record<string, number>
}

/**
 * What is on screen: from the roots, through every expanded node, its first `shown` children and any pinned ones.
 * A node two expanded parents lead to is drawn once, with an edge from each — it is a graph, not a tree.
 */
export function visibleGraph(state: StructureState): VisibleGraph {
  const nodes = new Map<string, HierarchyNode>()
  const edges = new Map<string, VisibleEdge>()
  const more: Record<string, number> = {}
  const queue: string[] = []
  for (const root of state.roots) {
    if (!nodes.has(root.id)) {
      nodes.set(root.id, root)
      queue.push(root.id)
    }
  }

  while (queue.length > 0) {
    const id = queue.shift()!
    if (!state.expanded.has(id)) continue
    const loaded = state.children[id]
    if (!loaded) continue
    const shown = loaded.items.slice(0, wanted(state, id))
    const shownKeys = new Set(shown.map(key))
    const children = [...shown, ...(state.pinned[id] ?? []).filter((p) => !shownKeys.has(key(p)))]
    const hidden = loaded.total - shown.length
    if (hidden > 0) more[id] = hidden
    for (const child of children) {
      const edgeKey = key(child)
      if (!edges.has(edgeKey)) edges.set(edgeKey, { id: edgeKey, edge: child.edge })
      if (!nodes.has(child.node.id)) {
        nodes.set(child.node.id, child.node)
        queue.push(child.node.id)
      }
    }
  }

  return { nodes: [...nodes.values()], edges: [...edges.values()], more }
}
