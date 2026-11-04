import { useEffect, useMemo, useState } from 'react'
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, ReactFlowProvider, useReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { BackendHost, EntryPointBackendRow } from '../../../types/surface'
import { SourceLink } from '../SourceLink'
import { buildFlow, childCounts, visibleFlow, type Flow, type FlowNode } from './flowModel'
import { SIZES, layoutFlow } from './reachLayout'

// One inbound operation's call chain, drawn like the structure graph (React Flow, laid out top to bottom by dagre): the
// handler, the methods it walks, and each backend call (REST, SOAP, database, ...) on the method that makes it. Built
// from the stored `via` hops (29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES, "BackendReach"). + and − fold a method's calls.

const HANDLER_LOOK = { box: 'border-violet-500 bg-violet-50', tag: 'bg-violet-600 text-white' }
const METHOD_LOOK = { box: 'border-sky-500 bg-sky-50', tag: 'bg-sky-600 text-white' }
const MECHANISMS: Record<string, { label: string; box: string; tag: string }> = {
  http_client: { label: 'REST', box: 'border-amber-500 bg-amber-50 rounded-xl', tag: 'bg-amber-500 text-white' },
  soap_client: { label: 'SOAP', box: 'border-fuchsia-500 bg-fuchsia-50 rounded-xl', tag: 'bg-fuchsia-600 text-white' },
  grpc_client: { label: 'gRPC', box: 'border-indigo-500 bg-indigo-50 rounded-xl', tag: 'bg-indigo-600 text-white' },
  database: { label: 'Database', box: 'border-emerald-500 bg-emerald-50 rounded-xl', tag: 'bg-emerald-600 text-white' },
  message_producer: { label: 'Message out', box: 'border-orange-500 bg-orange-50 rounded-xl', tag: 'bg-orange-500 text-white' },
  message_consumer: { label: 'Message in', box: 'border-orange-500 bg-orange-50 rounded-xl', tag: 'bg-orange-500 text-white' },
  cache: { label: 'Cache', box: 'border-rose-500 bg-rose-50 rounded-xl', tag: 'bg-rose-500 text-white' },
}
const OTHER_LOOK = { box: 'border-slate-400 bg-white rounded-xl', tag: 'bg-slate-500 text-white' }

function hostLabel(h: BackendHost) {
  if (!h.host) return '(unresolved)'
  return `${h.host}${h.port && h.port !== 80 && h.port !== 443 ? `:${h.port}` : ''}`
}

const badge = 'whitespace-nowrap rounded px-1 text-[10px] font-medium leading-4'
const HANDLE = '!h-1 !min-h-0 !w-1 !min-w-0 !border-0 !bg-transparent'

type Data = { node: FlowNode; localPath: string; folded: boolean; children: number; onToggle: (id: string) => void }
type FlowRfNode = Node<Data, FlowNode['kind']>

function Handles({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Handle type="target" position={Position.Top} className={HANDLE} />
      {children}
      <Handle type="source" position={Position.Bottom} className={HANDLE} />
    </>
  )
}

/** The + / − of a node with nodes below it. */
function Fold({ data, name }: { data: Data; name: string }) {
  if (data.children === 0) return null
  return (
    <button
      type="button"
      aria-label={`${data.folded ? 'Expand' : 'Collapse'} ${name}`}
      title={data.folded ? `Show its ${data.children} calls` : 'Hide what it calls'}
      onClick={(event) => {
        event.stopPropagation()
        data.onToggle(data.node.id)
      }}
      className="nodrag h-5 w-5 shrink-0 rounded border border-neutral-300 bg-white text-xs font-bold leading-4 text-neutral-700 hover:bg-neutral-100"
    >
      {data.folded ? '+' : '−'}
    </button>
  )
}

function Card({ look, tag, name, subtitle, fold, badges, testId, dashed }: {
  look: { box: string; tag: string }
  tag: string
  name: string
  subtitle: string
  fold?: React.ReactNode
  badges?: React.ReactNode
  testId: string
  dashed?: boolean
}) {
  return (
    <div style={SIZES.method} className={`flex flex-col justify-between overflow-hidden rounded border-2 px-2 py-1 shadow-sm ${look.box} ${dashed ? 'border-dashed' : ''}`} data-testid={testId}>
      <Handles>
        <div className="flex items-start gap-1">
          <span className={`mt-0.5 shrink-0 rounded px-1 text-[9px] font-semibold uppercase leading-3 ${look.tag}`}>{tag}</span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-xs font-semibold text-neutral-900" title={name}>
              {name}
            </div>
            <div className="truncate text-[10px] text-neutral-500" title={subtitle}>
              {subtitle}
            </div>
          </div>
          {fold}
        </div>
        <span className="flex flex-nowrap items-center gap-1 overflow-hidden">{badges}</span>
      </Handles>
    </div>
  )
}

function MethodView({ data }: NodeProps<FlowRfNode>) {
  const node = data.node as Extract<FlowNode, { kind: 'method' }>
  const name = node.method || node.owner
  return (
    <Card
      look={node.root ? HANDLER_LOOK : METHOD_LOOK}
      tag={node.root ? 'Handler' : 'Method'}
      name={name}
      subtitle={node.owner}
      fold={<Fold data={data} name={`${node.owner}.${name}`} />}
      badges={data.children > 0 && <span className={`${badge} bg-white text-neutral-600 ring-1 ring-neutral-300`}>{data.children} call{data.children === 1 ? '' : 's'}</span>}
      testId={`flow-method-${node.owner}.${node.method}`}
    />
  )
}

function BackendView({ data }: NodeProps<FlowRfNode>) {
  const { call } = data.node as Extract<FlowNode, { kind: 'backend' }>
  const look = MECHANISMS[call.mechanism] ?? { ...OTHER_LOOK, label: call.mechanism.replace(/_/g, ' ') }
  const { shown, others } = call.endpoint
  const hosts = [shown, ...others].map((h) => `${h.environment}: ${hostLabel(h)}`).join('\n')
  return (
    <div title={hosts} data-testid={`flow-call-${call.mechanism}`}>
      <Card
        look={look}
        tag={look.label}
        name={call.operation ?? look.label}
        subtitle={[call.contract, shown.host ? `${hostLabel(shown)} · ${shown.environment}` : null].filter(Boolean).join(' · ') || look.label}
        badges={
          <>
            {call.conditional && (
              <span className={`${badge} cursor-help bg-sky-100 text-sky-800`} title={call.context.join('\n')}>
                conditional
              </span>
            )}
            {call.in_loop && (
              <span className={`${badge} cursor-help bg-fuchsia-100 text-fuchsia-800`} title={call.context.join('\n')}>
                loop
              </span>
            )}
            {call.linux_verdict === 'requires_change' && <span className={`${badge} bg-amber-200 text-amber-900`}>requires change</span>}
            <SourceLink localPath={data.localPath} filePath={call.call_site.filePath} line={call.call_site.lineStart} className="font-mono text-[10px] text-violet-700">
              {call.call_site.filePath.split('/').pop()}:{call.call_site.lineStart}
            </SourceLink>
          </>
        }
        testId={`flow-card-${call.mechanism}`}
      />
    </div>
  )
}

function UnresolvedView({ data }: NodeProps<FlowRfNode>) {
  const node = data.node as Extract<FlowNode, { kind: 'unresolved' }>
  return (
    <Card
      look={{ box: 'border-amber-400 bg-amber-50', tag: 'bg-amber-500 text-white' }}
      tag="Not followed"
      name={node.reason}
      subtitle="never guessed"
      badges={
        <SourceLink localPath={data.localPath} filePath={node.filePath} line={node.line} className="font-mono text-[10px] text-neutral-500">
          {node.filePath.split('/').pop()}:{node.line}
        </SourceLink>
      }
      testId="flow-unresolved"
      dashed
    />
  )
}

function MoreView({ data }: NodeProps<FlowRfNode>) {
  const node = data.node as Extract<FlowNode, { kind: 'more' }>
  return (
    <div style={SIZES.more} className="flex items-center justify-center rounded-full border border-dashed border-neutral-400 bg-white text-xs text-neutral-600" title="Only the first part of this flow is drawn">
      <Handles>+{node.hidden} more</Handles>
    </div>
  )
}

const NODE_TYPES = { method: MethodView, backend: BackendView, unresolved: UnresolvedView, more: MoreView }

/** The flow's nodes as React Flow takes them. A node is never `selectable: false`: React Flow gives a node that is
 * neither selectable, draggable nor clickable `pointer-events: none`, which would kill its + and − buttons. */
export function toRfNodes(flow: Flow, placed: Map<string, { x: number; y: number }>, data: (node: FlowNode) => Data): FlowRfNode[] {
  return flow.nodes.map((node) => ({
    id: node.id,
    type: node.kind,
    position: placed.get(node.id) ?? { x: 0, y: 0 },
    data: data(node),
    draggable: false,
    connectable: false,
  }))
}

function FlowCanvas({ row, localPath }: { row: EntryPointBackendRow; localPath: string }) {
  const full = useMemo(() => buildFlow(row), [row])
  const counts = useMemo(() => childCounts(full), [full])
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set())
  const flow = useMemo(() => visibleFlow(full, collapsed), [full, collapsed])
  const reactFlow = useReactFlow()

  const toggle = (id: string) =>
    setCollapsed((current) => {
      const next = new Set(current)
      if (!next.delete(id)) next.add(id)
      return next
    })

  const nodes = useMemo<FlowRfNode[]>(
    () => toRfNodes(flow, layoutFlow(flow), (node) => ({ node, localPath, folded: collapsed.has(node.id), children: counts.get(node.id) ?? 0, onToggle: toggle })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [flow, localPath, collapsed, counts],
  )

  const edges = useMemo<Edge[]>(
    () =>
      flow.edges.map((edge) => {
        const stroke = edge.kind === 'unresolved' ? '#b45309' : '#475569'
        return {
          id: edge.id,
          source: edge.from,
          target: edge.to,
          style: { stroke, strokeWidth: 1.1, strokeDasharray: edge.kind === 'unresolved' ? '7 4' : undefined },
          markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 14, height: 14 },
          selectable: false,
        }
      }),
    [flow],
  )

  // After a fold or an unfold, bring the graph back into view.
  useEffect(() => {
    requestAnimationFrame(() => void reactFlow.fitView({ maxZoom: 1, padding: 0.15, duration: 250 }))
  }, [flow, reactFlow])

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      fitView
      fitViewOptions={{ maxZoom: 1, padding: 0.15 }}
      minZoom={0.1}
      nodesDraggable={false}
      nodesConnectable={false}
      zoomOnDoubleClick={false}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={20} size={1} />
      <Controls showInteractive={false} />
    </ReactFlow>
  )
}

/** One operation's call chain as a flow: pan, zoom, and fold a method's calls with its + and −. */
export function OperationFlowGraph({ row, localPath }: { row: EntryPointBackendRow; localPath: string }) {
  return (
    <div className="h-[480px] min-w-0 rounded border border-neutral-200 bg-neutral-50" data-testid="operation-flow">
      <ReactFlowProvider>
        <FlowCanvas row={row} localPath={localPath} />
      </ReactFlowProvider>
    </div>
  )
}
