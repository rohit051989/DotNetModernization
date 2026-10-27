import { Fragment, useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import { backendApplications, backendOperations, getBackendSummary } from '../../api/results'
import { CollapsibleSection } from '../../components/CollapsibleSection'
import { LimitedList, useLimitedList } from '../../components/LimitedList'
import { PagedList } from '../../components/PagedList'
import { surfaceSectionId } from './surfaceSections'
import { SourceLink } from './SourceLink'
import type { BackendApplication, BackendSummary } from '../../types/results'
import type { BackendCall, BackendHost, BackendStatus, EntryPointBackendRow } from '../../types/surface'

// Inbound operations → backend calls — step 5 1.3.0 (29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES Part C9).
// Per application, every request entry point and the outbound call sites it
// reaches: directly in its method, or through methods of the same class.
// The No rows are listed on purpose — an operation that calls nothing is a
// fact a migration plan needs as much as one that does.

const STATUS: Record<BackendStatus, { label: string; style: string; title: string }> = {
  yes: { label: 'Yes', style: 'border-violet-200 bg-violet-50 text-violet-800', title: 'Reaches at least one backend call' },
  no: { label: 'No', style: 'border-neutral-200 bg-neutral-50 text-neutral-500', title: 'No backend call, and no path left unfollowed' },
  unresolved: {
    label: 'Unresolved',
    style: 'border-amber-200 bg-amber-50 text-amber-800',
    title: 'No backend call found, but a path through another class, an injected dependency or deeper calls was not followed — never guessed',
  },
  not_assessed: { label: 'Not assessed', style: 'border-neutral-200 bg-white text-neutral-400', title: 'Step 5 ran without step 4’s entry points; rescan' },
}

function hostLabel(h: BackendHost) {
  if (!h.host) return '(unresolved)'
  return `${h.host}${h.port && h.port !== 80 && h.port !== 443 ? `:${h.port}` : ''}`
}

function Endpoint({ call }: { call: BackendCall }) {
  const [open, setOpen] = useState(false)
  const { shown, others, grouped_by } = call.endpoint
  return (
    <div>
      <span className="font-mono text-neutral-800">{hostLabel(shown)}</span>{' '}
      <span className="text-[10px] text-neutral-400" title={grouped_by === 'host' ? 'No binding for the production environment: the host as found' : undefined}>
        {shown.environment}
      </span>
      {shown.deploy_parameter && <span className="ml-1 text-[10px] text-neutral-400" title="Set by this SetParameters parameter">· {shown.deploy_parameter}</span>}
      {shown.linux_verdict === 'requires_change' && (
        <span className="ml-1 rounded border border-amber-200 bg-amber-50 px-1 text-[10px] text-amber-800">requires change</span>
      )}
      {others.length > 0 && (
        <div>
          <button type="button" onClick={() => setOpen((v) => !v)} className="text-[11px] text-violet-700 hover:underline" aria-expanded={open}>
            {open ? 'Hide' : 'Show'} {others.length} other environment{others.length === 1 ? '' : 's'}
          </button>
          {open && (
            <LimitedList items={others} name={(o) => [o.environment, o.host]} noun="environments">
              {(shown) => (
            <ul className="mt-0.5 space-y-0.5">
              {shown.map((o) => (
                <li key={`${o.environment}|${o.source_file}`} className="text-[11px]" title={o.source_file ?? undefined}>
                  <span className="text-neutral-400">{o.environment}</span> <span className="break-all font-mono text-neutral-700">{hostLabel(o)}</span>
                  {o.linux_verdict === 'requires_change' && <span className="ml-1 text-amber-700">requires change</span>}
                </li>
              ))}
            </ul>
              )}
            </LimitedList>
          )}
        </div>
      )}
    </div>
  )
}

function Flags({ call }: { call: BackendCall }) {
  if (!call.conditional && !call.in_loop) return <span className="text-neutral-300">—</span>
  return (
    <span className="flex flex-wrap gap-1" title={call.context.join('\n')}>
      {call.conditional && <span className="cursor-help rounded border border-sky-200 bg-sky-50 px-1 text-[10px] text-sky-800">conditional</span>}
      {call.in_loop && <span className="cursor-help rounded border border-fuchsia-200 bg-fuchsia-50 px-1 text-[10px] text-fuchsia-800">loop</span>}
      <span className="block w-full text-[10px] text-neutral-400">{call.context.join(' · ')}</span>
    </span>
  )
}

/** One inbound operation: its backend calls are rows of the operations table (the operation's cells span them), so
 * they are limited with the list hook, its controls in a row of their own. */
function Row({ row, localPath }: { row: EntryPointBackendRow; localPath: string }) {
  const status = STATUS[row.status]
  const list = useLimitedList(row.calls, { name: (c) => [c.operation, c.contract, c.call_site.filePath], noun: 'backend calls' })
  const calls: (BackendCall | null)[] = list.visible.length > 0 ? list.visible : [null]
  const span = calls.length + (list.hasControls ? 1 : 0)
  return (
    <>
      {calls.map((call, index) => (
        <tr
          key={call ? `${call.invocation_id}|${call.call_site.lineStart}` : 'none'}
          className={`align-top ${index === calls.length - 1 && !list.hasControls ? 'border-b border-neutral-100' : ''}`}
        >
          {index === 0 && (
            <>
              <td rowSpan={span} className="py-1.5 pr-2 text-right text-neutral-400">
                {row.number}
              </td>
              <td rowSpan={span} className="py-1.5 pr-3 font-mono text-neutral-700">
                {row.service}
              </td>
              <td rowSpan={span} className="py-1.5 pr-3">
                <SourceLink localPath={localPath} filePath={row.handler.filePath} line={row.handler.lineStart} className="font-mono text-neutral-900">
                  {row.operation}
                </SourceLink>
              </td>
              <td rowSpan={span} className="py-1.5 pr-3">
                {list.filterBox}
                <span className={`whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-medium ${status.style}`} title={status.title}>
                  {status.label}
                </span>
                <LimitedList items={row.unresolved} name={(u) => [u.reason, u.callSite.filePath]} noun="paths not followed">
                  {(shown) => (
                    <ul className="mt-1 space-y-0.5 text-[11px] text-amber-800">
                      {shown.map((u) => (
                        <li key={`${u.reason}|${u.callSite.lineStart}`}>
                          not followed: {u.reason}{' '}
                          <SourceLink localPath={localPath} filePath={u.callSite.filePath} line={u.callSite.lineStart} className="font-mono text-neutral-500">
                            :{u.callSite.lineStart}
                          </SourceLink>
                        </li>
                      ))}
                    </ul>
                  )}
                </LimitedList>
              </td>
            </>
          )}
          {call ? (
            <>
              <td className="py-1.5 pr-3">
                <span className="font-mono text-neutral-800">{call.operation ?? call.mechanism.replace(/_/g, ' ')}</span>
                {call.contract && <span className="block text-[10px] text-neutral-400">{call.contract}</span>}
              </td>
              <td className="py-1.5 pr-3">
                <Endpoint call={call} />
              </td>
              <td className="py-1.5 pr-3">
                <SourceLink localPath={localPath} filePath={call.call_site.filePath} line={call.call_site.lineStart} className="break-all font-mono text-violet-700">
                  {call.call_site.filePath.split('/').pop()}:{call.call_site.lineStart}
                </SourceLink>
                {call.depth > 0 && (
                  <span className="block text-[10px] text-neutral-400" title={call.via.join(' → ')}>
                    via {call.via.slice(1).join(' → ')} (depth {call.depth})
                  </span>
                )}
              </td>
              <td className="py-1.5">
                <Flags call={call} />
              </td>
            </>
          ) : (
            <td colSpan={4} className="py-1.5 text-neutral-300">
              {list.noMatch ?? '—'}
            </td>
          )}
        </tr>
      ))}
      {list.hasControls && (
        <tr className="border-b border-neutral-100">
          <td colSpan={4} className="pb-1.5">
            {list.controls}
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
          <table className="w-full min-w-[1000px] text-left text-xs">
            <thead className="text-neutral-400">
              <tr className="border-b border-neutral-200">
                {['#', 'Service', 'Operation', 'Calls backend?', 'Backend operation', 'Backend endpoint', 'Called from (file:line)', 'Conditional / loop'].map((h) => (
                  <th key={h} className={`py-1.5 pr-3 font-medium ${h === '#' ? 'text-right' : ''}`}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <Fragment key={row.entry_point_id}>
                  <Row row={row} localPath={localPath} />
                </Fragment>
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
            Every inbound operation, and the backend calls it reaches — in its own method, or through methods of the same class (up to three calls
            deep). Conditional and loop are read from the code around the call; hover for it. Paths into other classes or injected dependencies that
            make backend calls are shown as not followed, never guessed. The endpoint is the{' '}
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
