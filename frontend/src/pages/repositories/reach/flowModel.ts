import type { BackendCall, EntryPointBackendRow } from '../../../types/surface'

/** An operation's flow is drawn at most this large; the rest is a "+N more" node, as the structure graph does. */
export const MAX_FLOW_NODES = 40

export type FlowNode =
  | { id: string; kind: 'method'; owner: string; method: string; root: boolean }
  | { id: string; kind: 'backend'; call: BackendCall }
  | { id: string; kind: 'unresolved'; reason: string; filePath: string; line: number }
  | { id: string; kind: 'more'; hidden: number }

export interface FlowEdge {
  id: string
  from: string
  to: string
  kind: 'call' | 'unresolved'
}

export interface Flow {
  nodes: FlowNode[]
  edges: FlowEdge[]
}

export const ROOT_ID = 'root'

/** How many nodes hang directly off each node: what its + and − fold. */
export function childCounts(flow: Flow): Map<string, number> {
  const counts = new Map<string, number>()
  for (const edge of flow.edges) counts.set(edge.from, (counts.get(edge.from) ?? 0) + 1)
  return counts
}

/** The flow with everything below a collapsed node left out. */
export function visibleFlow(flow: Flow, collapsed: ReadonlySet<string>): Flow {
  if (collapsed.size === 0) return flow
  const children = new Map<string, string[]>()
  for (const edge of flow.edges) children.set(edge.from, [...(children.get(edge.from) ?? []), edge.to])
  const shown = new Set<string>([ROOT_ID])
  const queue = [ROOT_ID]
  while (queue.length > 0) {
    const id = queue.shift()!
    if (collapsed.has(id)) continue
    for (const child of children.get(id) ?? []) {
      shown.add(child)
      queue.push(child)
    }
  }
  return { nodes: flow.nodes.filter((n) => shown.has(n.id)), edges: flow.edges.filter((e) => shown.has(e.from) && shown.has(e.to)) }
}

/** One hop of `call.via`: `Type.Method` names its class, a bare `Method` stays in the class before it. */
function parseHop(hop: string, owner: string): { owner: string; method: string } {
  const dot = hop.lastIndexOf('.')
  return dot < 0 ? { owner, method: hop } : { owner: hop.slice(0, dot), method: hop.slice(dot + 1) }
}

/**
 * The call chain of one inbound operation as a tree: the handler, the methods it walks to reach each backend call
 * (`via`, merged where two calls share a prefix), and each backend call hung off the method that makes it. Paths that
 * were not followed hang off the handler, since they carry no hops of their own.
 */
export function buildFlow(row: EntryPointBackendRow): Flow {
  const nodes: FlowNode[] = [{ id: ROOT_ID, kind: 'method', owner: row.handler.type, method: row.handler.member ?? '', root: true }]
  const edges: FlowEdge[] = []
  const known = new Set<string>([ROOT_ID])

  const add = (node: FlowNode, from: string, kind: FlowEdge['kind'] = 'call') => {
    if (known.has(node.id)) return
    known.add(node.id)
    nodes.push(node)
    edges.push({ id: `${from}>${node.id}`, from, to: node.id, kind })
  }

  for (const call of row.calls) {
    let parent = ROOT_ID
    let owner = row.handler.type
    for (const hop of call.via.slice(1)) {          // the first hop is the handler, already the root
      const next = parseHop(hop, owner)
      owner = next.owner
      const id = `${parent}/${owner}.${next.method}`
      add({ id, kind: 'method', owner, method: next.method, root: false }, parent)
      parent = id
    }
    add({ id: `call:${call.invocation_id}|${call.call_site.filePath}|${call.call_site.lineStart}`, kind: 'backend', call }, parent)
  }

  for (const path of row.unresolved) {
    add({ id: `unresolved:${path.reason}|${path.callSite.lineStart}`, kind: 'unresolved', reason: path.reason, filePath: path.callSite.filePath, line: path.callSite.lineStart }, ROOT_ID, 'unresolved')
  }

  if (nodes.length <= MAX_FLOW_NODES) return { nodes, edges }
  // A parent is always added before its children, so the first nodes stay connected to the handler.
  const kept = nodes.slice(0, MAX_FLOW_NODES)
  const ids = new Set(kept.map((n) => n.id))
  const more: FlowNode = { id: 'more', kind: 'more', hidden: nodes.length - MAX_FLOW_NODES }
  return {
    nodes: [...kept, more],
    edges: [...edges.filter((e) => ids.has(e.from) && ids.has(e.to)), { id: `${ROOT_ID}>more`, from: ROOT_ID, to: 'more', kind: 'call' }],
  }
}
