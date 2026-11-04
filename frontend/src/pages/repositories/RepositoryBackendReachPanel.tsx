import { useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import { backendApplications, backendOperations, getBackendSummary } from '../../api/results'
import { CollapsibleSection } from '../../components/CollapsibleSection'
import { PagedList } from '../../components/PagedList'
import { counted } from './repositoryTabs'
import { surfaceSectionId } from './surfaceSections'
import { SourceLink } from './SourceLink'
import { OperationFlowGraph } from './reach/OperationFlowGraph'
import type { BackendApplication, BackendSummary } from '../../types/results'
import type { BackendStatus, EntryPointBackendRow } from '../../types/surface'

// Inbound operations → backend calls — step 5 1.3.0 (29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES Part C9).
// Per application, every request entry point and the outbound call sites it
// reaches, drawn as a flow: directly in its method, or through the methods it
// calls, in its class or in others.
// The No rows are listed on purpose — an operation that calls nothing is a
// fact a migration plan needs as much as one that does.

const STATUS: Record<BackendStatus, { label: string; style: string; title: string }> = {
  yes: { label: 'Yes', style: 'border-violet-200 bg-violet-50 text-violet-800', title: 'Reaches at least one backend call' },
  no: {
    label: 'No',
    style: 'border-neutral-200 bg-neutral-50 text-neutral-500',
    title:
      'No detected backend call site is reached, and no path was left unfollowed. A call through a library’s own abstraction, or to a ' +
      'client or context named by something other than a literal or constant, is not detected.',
  },
  unresolved: {
    label: 'Unresolved',
    style: 'border-amber-200 bg-amber-50 text-amber-800',
    title: 'No backend call found, but a path deeper than the limit was not followed — never guessed',
  },
  not_assessed: { label: 'Not assessed', style: 'border-neutral-200 bg-white text-neutral-400', title: 'Step 5 ran without step 4’s entry points; rescan' },
}

/** One inbound operation: its identity, its status, and the flow of calls it makes — the handler, the methods it walks,
 * and the backend call each makes — opened under the row like the structure graph. An operation that calls nothing says so. */
function Row({ row, localPath }: { row: EntryPointBackendRow; localPath: string }) {
  const status = STATUS[row.status]
  const hasFlow = row.calls.length > 0 || row.unresolved.length > 0
  const [open, setOpen] = useState(false)
  return (
    <>
    <tr className={`align-top ${open ? '' : 'border-b border-neutral-100'}`}>
      <td className="py-1.5 pr-2 text-right text-neutral-400">{row.number}</td>
      <td className="py-1.5 pr-3 font-mono text-neutral-700">{row.service}</td>
      <td className="py-1.5 pr-3">
        <SourceLink localPath={localPath} filePath={row.handler.filePath} line={row.handler.lineStart} className="font-mono text-neutral-900">
          {row.operation}
        </SourceLink>
      </td>
      <td className="py-1.5 pr-3">
        <span className={`whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-medium ${status.style}`} title={status.title}>
          {status.label}
        </span>
      </td>
      <td className="w-full py-1.5">
        {hasFlow ? (
          <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="text-violet-700 hover:underline">
            {open ? 'Hide flow' : 'Show flow'} · {row.calls.length} backend call{row.calls.length === 1 ? '' : 's'}
          </button>
        ) : (
          <span className="text-neutral-300">—</span>
        )}
      </td>
    </tr>
    {open && (
      <tr className="border-b border-neutral-100">
        <td colSpan={5} className="pb-2">
          <OperationFlowGraph row={row} localPath={localPath} />
        </td>
      </tr>
    )}
    </>
  )
}

/** A list of at most this many panels opens them all at first; a longer one starts with each folded. */
const FEW_OPEN = 3

/** Open at first only when it is one of a few: its header line already gives its counts (release 6). Its operations
 * come a page at a time. */
function Application({ repositoryId, app, localPath, refreshToken, defaultOpen = true }: { repositoryId: string; app: BackendApplication; localPath: string; refreshToken: number; defaultOpen?: boolean }) {
  const [expanded, setExpanded] = useState(defaultOpen)
  const count = (s: BackendStatus) => app.counts[s] ?? 0
  return (
    <div className="rounded border border-neutral-200">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full flex-wrap items-center justify-between gap-x-3 gap-y-1 px-3 py-2 text-left hover:bg-neutral-50"
        aria-expanded={expanded}
      >
        <span className="min-w-0 break-all font-mono text-xs text-neutral-800">{app.project_path}</span>
        <span className="flex flex-wrap gap-2 text-xs text-neutral-400">
          {app.operations} operation{app.operations === 1 ? '' : 's'}
          <span className="text-violet-700">{count('yes')} call backend</span>
          <span>{count('no')} no</span>
          {count('unresolved') > 0 && <span className="text-amber-700">{count('unresolved')} unresolved</span>}
          {count('not_assessed') > 0 && <span>{count('not_assessed')} not assessed</span>}
          <span>{expanded ? '▲' : '▼'}</span>
        </span>
      </button>
      {expanded && (
        <div className="border-t border-neutral-100 px-3 py-2">
        <PagedList<EntryPointBackendRow> load={backendOperations(repositoryId, app.project_id)} resetKey={`${repositoryId}|${refreshToken}|${app.project_id}`} noun="operations">
          {(shown) => (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead className="text-neutral-400">
              <tr className="border-b border-neutral-200">
                {['#', 'Service', 'Operation', 'Calls backend?', 'Flow'].map((h) => (
                  <th key={h} className={`py-1.5 pr-3 font-medium ${h === '#' ? 'text-right' : ''}`}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <Row key={row.entry_point_id} row={row} localPath={localPath} />
              ))}
            </tbody>
          </table>
        </div>
          )}
        </PagedList>
        </div>
      )}
    </div>
  )
}

export function RepositoryBackendReachPanel({ repositoryId, localPath, refreshToken }: { repositoryId: string; localPath: string; refreshToken: number }) {
  const [data, setData] = useState<BackendSummary | null>(null)
  const [notScanned, setNotScanned] = useState(false)
  const [failed, setFailed] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setNotScanned(false)
    setFailed(false)
    getBackendSummary(repositoryId)
      .then((result) => {
        if (!cancelled) setData(result)
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 409) setNotScanned(true)
        else setFailed(true)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [repositoryId, refreshToken])

  const operations = data?.operations ?? 0
  const applications = data?.applications ?? 0
  const count = (status: BackendStatus) => data?.count_by_status[status] ?? 0
  const summary = loading
    ? 'loading…'
    : failed
      ? 'could not be loaded'
      : notScanned || !data
        ? 'not scanned yet'
        : `${operations} operation${operations === 1 ? '' : 's'} in ${applications} application${applications === 1 ? '' : 's'} · ` +
          `${count('yes')} call backend` +
          (count('unresolved') > 0 ? `, ${count('unresolved')} unresolved` : '')

  return (
    <CollapsibleSection
      id={surfaceSectionId(repositoryId, 'reach')}
      title="Inbound operations → backend calls"
      barTitle="Backend calls"
      count={data ? counted(operations, 'operation') : undefined}
      summary={summary}
      rowCount={data ? operations : undefined}
      persist="browser"
      variant="nested"
    >
      {loading ? (
        <p className="text-sm text-neutral-400">Loading…</p>
      ) : failed ? (
        <p className="text-sm text-red-600">Could not load which backend calls each operation reaches.</p>
      ) : notScanned || !data ? (
        <div className="rounded border border-dashed border-neutral-200 bg-neutral-50 p-4 text-sm text-neutral-500">
          The outbound-invocation inventory (outbound-invocation-inventory) hasn't run for this repository yet.
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-[11px] text-neutral-400">
            Every inbound operation, and the backend calls it reaches — in its own method, or through the methods it calls, in this
            class or others (up to eight calls deep, shown as a flow from the handler). Conditional and loop are read from the code
            around the call; hover for it. Calls on a type that is not in the repository are not followed, never guessed. A database is
            reached where a context's sets or SaveChanges are used, an HTTP client where it is called by name. No means no detected call
            site is reached, not that the operation calls nothing. The endpoint is the{' '}
            {data.production_environment ? `${data.production_environment} environment's host` : 'host as found (no production environment is set)'}.
          </p>
          {applications === 0 && <p className="text-sm text-neutral-400">No request entry points in this repository.</p>}
          {applications > 0 && (
            <PagedList<BackendApplication> load={backendApplications(repositoryId)} resetKey={`${repositoryId}|${refreshToken}`} noun="applications">
              {(shown) => (
                <div className="space-y-2">
                  {shown.map((app) => (
                    <Application key={app.project_id} repositoryId={repositoryId} app={app} localPath={localPath} refreshToken={refreshToken} defaultOpen={applications <= FEW_OPEN} />
                  ))}
                </div>
              )}
            </PagedList>
          )}
        </div>
      )}
    </CollapsibleSection>
  )
}
