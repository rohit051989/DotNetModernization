import { useState } from 'react'

/** A small, dependency-free collapsible JSON tree — approximate syntax
 * highlighting by value type, objects/arrays collapsible. */
export function JsonTreeView({ value }: { value: unknown }) {
  return (
    <div className="font-mono text-xs leading-relaxed">
      <JsonNode value={value} depth={0} />
    </div>
  )
}

function JsonNode({ value, depth }: { value: unknown; depth: number }) {
  if (value === null) return <span className="text-neutral-400">null</span>
  if (typeof value === 'boolean') return <span className="text-purple-600">{String(value)}</span>
  if (typeof value === 'number') return <span className="text-blue-600">{value}</span>
  if (typeof value === 'string') return <span className="text-emerald-700">"{value}"</span>

  if (Array.isArray(value)) {
    return <CollapsibleContainer open="[" close="]" depth={depth} count={value.length} entries={value.map((item, index) => ({ key: String(index), value: item }))} />
  }

  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).map(([key, v]) => ({ key, value: v }))
    return <CollapsibleContainer open="{" close="}" depth={depth} count={entries.length} entries={entries} showKeys />
  }

  return <span>{String(value)}</span>
}

function CollapsibleContainer({
  open,
  close,
  depth,
  count,
  entries,
  showKeys = false,
}: {
  open: string
  close: string
  depth: number
  count: number
  entries: { key: string; value: unknown }[]
  showKeys?: boolean
}) {
  const [expanded, setExpanded] = useState(depth < 2)

  if (count === 0) {
    return (
      <span className="text-neutral-400">
        {open}
        {close}
      </span>
    )
  }

  return (
    <span>
      <button type="button" onClick={() => setExpanded((v) => !v)} className="text-neutral-400 hover:text-neutral-700">
        {expanded ? '▾' : '▸'} {open}
        {!expanded && <span className="italic text-neutral-300"> {count} items </span>}
      </button>
      {expanded && (
        <div className="ml-4 border-l border-neutral-100 pl-3">
          {entries.map(({ key, value }, index) => (
            <div key={key}>
              {showKeys && <span className="text-neutral-700">"{key}"</span>}
              {showKeys && <span className="text-neutral-400">: </span>}
              <JsonNode value={value} depth={depth + 1} />
              {index < entries.length - 1 && <span className="text-neutral-400">,</span>}
            </div>
          ))}
        </div>
      )}
      {expanded && <span className="text-neutral-400">{close}</span>}
      {!expanded && <span className="text-neutral-400">{close}</span>}
    </span>
  )
}
