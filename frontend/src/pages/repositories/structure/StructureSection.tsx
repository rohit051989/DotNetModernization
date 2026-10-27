import { useCallback, useEffect, useState } from 'react'
import { searchHierarchy } from '../../../api/hierarchy'
import type { HierarchySearch, HierarchySearchMatch, HierarchyShow } from '../../../types/hierarchy'
import { StructureDetails } from './StructureDetails'
import { StructureGraph } from './StructureGraph'
import { StructureTree } from './StructureTree'
import { CYCLE_STROKE, EDGE_STYLES, LEGEND_LOOKS, LOOKS } from './nodeStyle'
import { useStructure } from './useStructure'

interface StructureSectionProps {
  repositoryId: string
  localPath: string | null
  refreshToken: number
  /** The stored dependency-assessment, for the details panel's status and reason; null when it has not run. */
  assessmentId: string | null
}

const SHOW_LABELS: Record<HierarchyShow, string> = {
  all: 'Everything',
  internal: 'Internal only',
  external: 'External only',
  projects: 'Projects only',
}

const VIEW_KEY = 'structure:view'

function readViewMode(): 'graph' | 'tree' {
  try {
    return window.localStorage.getItem(VIEW_KEY) === 'tree' ? 'tree' : 'graph'
  } catch {
    return 'graph'
  }
}

/**
 * The repository's dependency hierarchy (37-DEPENDENCY-HIERARCHY.md Part E): a node-link graph laid out top to bottom
 * from the roots, or the same as an indented tree. It opens showing only the roots; + and − expand and collapse a
 * node, whose children load when it is expanded, 20 at a time.
 */
export function StructureSection({ repositoryId, localPath, refreshToken, assessmentId }: StructureSectionProps) {
  const { view, setView, overview, load, state, graph, toggle, more, reveal } = useStructure(repositoryId, refreshToken)
  const [mode, setMode] = useState<'graph' | 'tree'>(readViewMode)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [focusId, setFocusId] = useState<string | null>(null)

  const chooseMode = (next: 'graph' | 'tree') => {
    setMode(next)
    try {
      window.localStorage.setItem(VIEW_KEY, next)
    } catch {
      // Not remembered: the choice lasts until the page is reloaded.
    }
  }

  const onReveal = useCallback(
    (match: HierarchySearchMatch) => {
      reveal(match)
      setSelectedId(match.node.id)
      setFocusId(match.node.id)
    },
    [reveal],
  )

  if (load.kind === 'loading') return <p className="text-sm text-neutral-400">Loading the dependency graph…</p>
  if (load.kind === 'not_scanned') {
    return <p className="text-sm text-neutral-400">The dependency hierarchy (dependency-hierarchy) hasn't been built for this repository yet. Rescan it.</p>
  }
  if (load.kind === 'error') return <p className="text-sm text-red-600">{load.message}</p>
  const s = overview!.summary

  return (
    <div className="space-y-3">
      <p className="text-xs text-neutral-500">
        {s.project_count} projects ({Object.entries(s.count_by_project_kind).map(([k, v]) => `${v} ${k}`).join(', ')}) from {overview!.roots.length} root
        {overview!.roots.length === 1 ? '' : 's'} · {s.package_count} packages ({s.internal_package_count} internal, {s.external_package_count} external,{' '}
        {s.transitive_package_count} transitive) · {s.assembly_count} assembly references · {s.edge_count} edges
        {s.cycle_count > 0 ? ` · ${s.cycle_count} cycle${s.cycle_count === 1 ? '' : 's'}` : ''}
        {s.not_checked_count > 0 ? ` · ${s.not_checked_count} not checked` : ''}
      </p>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Search repositoryId={repositoryId} transitive={view.transitive} show={view.show} onReveal={onReveal} />
        <label className="flex items-center gap-1.5 text-xs text-neutral-700">
          <input type="checkbox" checked={view.transitive} onChange={(e) => setView({ ...view, transitive: e.target.checked })} />
          Transitive packages
        </label>
        <label className="flex items-center gap-1.5 text-xs text-neutral-700">
          Show
          <select
            value={view.show}
            onChange={(e) => setView({ ...view, show: e.target.value as HierarchyShow })}
            className="rounded border border-neutral-300 bg-white px-1.5 py-0.5 text-xs"
            aria-label="Filter"
          >
            {(Object.keys(SHOW_LABELS) as HierarchyShow[]).map((k) => (
              <option key={k} value={k}>
                {SHOW_LABELS[k]}
              </option>
            ))}
          </select>
        </label>
        <div className="ml-auto inline-flex overflow-hidden rounded border border-neutral-300 text-xs" role="group" aria-label="View">
          {(['graph', 'tree'] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => chooseMode(m)}
              className={`px-2.5 py-1 ${mode === m ? 'bg-violet-600 text-white' : 'bg-white text-neutral-700 hover:bg-neutral-50'}`}
            >
              {m === 'graph' ? 'Graph' : 'Tree'}
            </button>
          ))}
        </div>
      </div>

      <Legend />

      <div className={`grid gap-3 ${selectedId ? 'lg:grid-cols-[minmax(0,1fr)_320px]' : ''}`}>
        {mode === 'graph' ? (
          <StructureGraph
            graph={graph}
            expanded={state.expanded}
            selectedId={selectedId}
            focusId={focusId}
            onToggle={toggle}
            onMore={more}
            onSelect={setSelectedId}
          />
        ) : (
          <StructureTree state={state} selectedId={selectedId} focusId={focusId} onToggle={toggle} onMore={more} onSelect={setSelectedId} />
        )}
        {selectedId && (
          <StructureDetails
            repositoryId={repositoryId}
            localPath={localPath}
            nodeId={selectedId}
            view={view}
            assessmentId={assessmentId}
            onSelect={setSelectedId}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>
    </div>
  )
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-neutral-600" aria-label="Legend">
      {LEGEND_LOOKS.map((look) => (
        <span key={look} className="inline-flex items-center gap-1">
          <span className={`inline-block h-3 w-4 rounded-sm border-2 ${LOOKS[look].box}`} />
          {LOOKS[look].label}
        </span>
      ))}
      <span className="text-neutral-300">|</span>
      {Object.entries(EDGE_STYLES).map(([kind, style]) => (
        <span key={kind} className="inline-flex items-center gap-1">
          <svg width="26" height="8" aria-hidden="true">
            <line x1="0" y1="4" x2="26" y2="4" stroke={style.stroke} strokeWidth="1.6" strokeDasharray={style.dash} />
          </svg>
          {style.label}
        </span>
      ))}
      <span className="inline-flex items-center gap-1">
        <svg width="26" height="8" aria-hidden="true">
          <line x1="0" y1="4" x2="26" y2="4" stroke={CYCLE_STROKE} strokeWidth="1.6" />
        </svg>
        closes a cycle
      </span>
    </div>
  )
}

/** Find a node by name; choosing a match reveals it with its path from a root. */
function Search({ repositoryId, transitive, show, onReveal }: { repositoryId: string; transitive: boolean; show: HierarchyShow; onReveal: (m: HierarchySearchMatch) => void }) {
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<HierarchySearch | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const q = query.trim()
    if (q.length < 2) {
      setResult(null)
      return
    }
    let live = true
    const timer = setTimeout(() => {
      searchHierarchy(repositoryId, q, { transitive, show })
        .then((r) => live && setResult(r))
        .catch(() => live && setResult(null))
    }, 250)
    return () => {
      live = false
      clearTimeout(timer)
    }
  }, [query, repositoryId, transitive, show])

  return (
    <div className="relative">
      <input
        type="search"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="Find a project, package or assembly…"
        aria-label="Find a node"
        className="w-72 rounded border border-neutral-300 px-2 py-1 text-xs"
      />
      {open && result && (
        <div className="absolute left-0 top-full z-30 mt-1 max-h-80 w-[28rem] overflow-auto rounded border border-neutral-200 bg-white py-1 text-xs shadow-lg" role="listbox">
          {result.matches.length === 0 && <div className="px-3 py-1.5 text-neutral-400">No node's name contains "{result.query}".</div>}
          {result.matches.map((m) => (
            <button
              key={m.node.id}
              type="button"
              role="option"
              aria-selected={false}
              disabled={!m.path}
              onClick={() => {
                onReveal(m)
                setOpen(false)
              }}
              className="block w-full px-3 py-1.5 text-left hover:bg-neutral-50 disabled:cursor-default disabled:hover:bg-white"
            >
              <span className="font-medium text-neutral-900">{m.node.name}</span>
              {m.node.version && <span className="text-neutral-500"> {m.node.version}</span>}
              <div className="truncate text-[10px] text-neutral-500">
                {m.path ? m.path.map((p) => p.node.name).join(' › ') : m.unreachable_reason}
              </div>
            </button>
          ))}
          {result.total > result.matches.length && (
            <div className="px-3 py-1 text-[10px] text-neutral-400">
              {result.total - result.matches.length} more match: type more of the name.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
