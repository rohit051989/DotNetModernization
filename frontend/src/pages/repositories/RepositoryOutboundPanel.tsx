import { Fragment, useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import { CollapsibleSection, GroupedItems } from '../../components/CollapsibleSection'
import { getRepositoryOutboundInvocations } from '../../api/surface'
import type { LinuxVerdict, OutboundInventory, OutboundInvocation, OutboundMechanism, ProjectOutbound } from '../../types/surface'
import { SourceLink } from './SourceLink'
import { surfaceSectionId } from './surfaceSections'
import { LimitedList } from '../../components/LimitedList'

interface RepositoryOutboundPanelProps {
  repositoryId: string
  localPath: string
  refreshToken: number
}

const MECHANISM_LABEL: Record<OutboundMechanism, string> = {
  soap_client: 'SOAP / WCF clients',
  http_client: 'HTTP clients',
  grpc_client: 'gRPC clients',
  database: 'Databases',
  message_producer: 'Message producers',
  message_consumer: 'Message consumers',
  cache: 'Caches',
  secret_store: 'Secret stores',
  file_share: 'File shares',
  smtp: 'SMTP',
  ldap: 'LDAP / directory',
}

const VERDICT_RANK: Record<LinuxVerdict, number> = { incompatible: 0, requires_change: 1, unknown: 2, compatible: 3 }

/** Unused clients sort after every used invocation and never set a group's or project's rank. */
function rank(i: OutboundInvocation): number {
  return i.usage === 'unused' ? 9 : VERDICT_RANK[i.linux_verdict]
}

const VERDICT_LABEL: Record<LinuxVerdict, string> = {
  incompatible: 'incompatible',
  requires_change: 'requires change',
  unknown: 'unknown',
  compatible: 'compatible',
}

// Part D: incompatible red, requires_change amber, unknown grey, compatible teal.
const VERDICT_STYLE: Record<LinuxVerdict, string> = {
  incompatible: 'border-red-200 bg-red-50 text-red-700',
  requires_change: 'border-amber-200 bg-amber-50 text-amber-800',
  unknown: 'border-neutral-200 bg-neutral-100 text-neutral-600',
  compatible: 'border-teal-200 bg-teal-50 text-teal-700',
}

function VerdictBadge({ verdict, reasons }: { verdict: LinuxVerdict; reasons: string[] }) {
  return (
    <span
      className={`whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] font-semibold ${VERDICT_STYLE[verdict]}`}
      title={reasons.join('\n')}
    >
      {VERDICT_LABEL[verdict]}
    </span>
  )
}

function endpointText(i: OutboundInvocation): string {
  const e = i.detail.endpoint
  if (e.resolution === 'unresolved') return e.placeholder ?? 'dynamic'
  if (e.scheme === null && e.host === null) return e.fragments.join(' … ')
  const port = e.port !== null ? `:${e.port}` : ''
  return `${e.scheme ?? '?'}://${e.host ?? '?'}${port}${e.path ?? ''}`
}

function EndpointCell({ invocation }: { invocation: OutboundInvocation }) {
  const e = invocation.detail.endpoint
  return (
    <span className="flex flex-wrap items-center gap-1">
      <span className={`break-all font-mono ${e.resolution === 'unresolved' ? 'text-neutral-500' : 'text-neutral-800'}`}>{endpointText(invocation)}</span>
      {e.resolution !== 'resolved' && (
        <span
          className="rounded bg-neutral-100 px-1 text-[10px] font-medium text-neutral-500"
          title={
            e.resolution === 'unresolved'
              ? 'Waits on a placeholder, environment variable or configuration key that no file supplies. Not guessed.'
              : 'Built from literal fragments and values this step could not resolve.'
          }
        >
          {e.resolution}
        </span>
      )}
      {e.source && (
        <span className="font-mono text-[10px] text-neutral-400" title={e.source.sourceFile}>
          {e.source.keyPath}
        </span>
      )}
    </span>
  )
}

/** What kind of client, in the mechanism's own terms. */
function describe(i: OutboundInvocation): string {
  const b = i.detail.block
  switch (i.mechanism) {
    case 'soap_client':
      return [b.contract, b.binding, b.securityMode && `security ${b.securityMode}`, b.clientCredentialType && `client credential ${b.clientCredentialType}`]
        .filter(Boolean)
        .join(' · ')
    case 'http_client':
      return [b.library, b.clientName && `named "${b.clientName}"`, b.typedClient && `typed ${b.typedClient}`].filter(Boolean).join(' · ')
    case 'grpc_client':
      return b.contract ? `contract ${b.contract}` : 'contract not identified'
    case 'database':
      return [b.name ?? '(unnamed)', b.provider, `auth ${b.authentication}`, b.localDb && 'LocalDB'].filter(Boolean).join(' · ')
    case 'message_producer':
    case 'message_consumer':
      return [
        b.transport,
        b.topics && b.topics.length > 0 && `topics ${b.topics.join(', ')}`,
        b.transport === 'kafka' ? `SASL ${b.authentication}` : `auth ${b.authentication}`,
      ]
        .filter(Boolean)
        .join(' · ')
    case 'cache':
    case 'secret_store':
      return b.provider ?? ''
    case 'file_share':
      return b.share ?? ''
    case 'smtp':
      return b.usesDefaultCredentials ? 'default (Windows) credentials' : ''
    case 'ldap':
      return b.api ?? ''
  }
}

function SubLine({ invocation }: { invocation: OutboundInvocation }) {
  const b = invocation.detail.block
  const notes: string[] = []
  if (b.bindingSource) notes.push(`binding from ${b.bindingSource.replace('_', ' ')}`)
  if (b.clientSource === 'generated') notes.push('generated proxy')
  if (b.clientSource === 'config_only') notes.push('declared in config only')
  if (b.via) notes.push(`built in ${b.via}`)
  if (b.authenticationSource) notes.push(`SASL from ${b.authenticationSource}`)
  return (
    <>
      {notes.length > 0 && <p className="text-[11px] text-neutral-400">{notes.join(' · ')}</p>}
      {b.condition && <p className="text-[11px] text-neutral-400">only if {b.condition}</p>}
    </>
  )
}

function Credentials({ invocation }: { invocation: OutboundInvocation }) {
  if (invocation.credentials.length === 0) {
    return invocation.auth_declared === 'none_declared' ? (
      <span className="text-[11px] text-amber-700" title="Declared as presenting no client credential">none declared</span>
    ) : (
      <span className="text-neutral-300" title="No credential visible in source or config: not assessed">—</span>
    )
  }
  return (
    <LimitedList items={invocation.credentials} name={(c) => [c.kind, c.keyPath]} noun="credentials">
      {(shown) => (
    <span className="flex flex-wrap gap-1">
      {shown.map((c) => (
        <span
          key={`${c.kind}|${c.keyPath ?? ''}|${c.declaredAt ?? ''}`}
          className="rounded bg-neutral-100 px-1.5 py-0.5 text-[11px] text-neutral-700"
          title={[c.keyPath && `key ${c.keyPath}`, c.sourceFile, c.declaredAt && `set at ${c.declaredAt}`].filter(Boolean).join('\n') || undefined}
        >
          {c.kind.replace('_', ' ')}
          {c.keyPath && <span className="font-mono text-neutral-400"> {c.keyPath}</span>}
        </span>
      ))}
    </span>
      )}
    </LimitedList>
  )
}

function CallSites({ invocation, localPath }: { invocation: OutboundInvocation; localPath: string | null }) {
  const sites = invocation.call_sites
  if (sites.length === 0) return null
  const fileName = (path: string) => path.split('/').pop()
  const constructions = invocation.construction_sites ?? []
  return (
    <span className="text-[11px]">
      <LimitedList items={sites} name={(c) => c.filePath} noun="call sites" className="font-sans">
        {(shown) =>
          shown.map((c) => (
            <SourceLink
              key={`${c.filePath}:${c.lineStart}`}
              localPath={localPath}
              filePath={c.filePath}
              line={c.lineStart}
              className="block font-mono text-violet-700"
              title={c.filePath}
            >
              {fileName(c.filePath)}:{c.lineStart}
            </SourceLink>
          ))
        }
      </LimitedList>
      {constructions.length > 0 && (
        <span className="block text-[10px] text-neutral-400">
          created at{' '}
          {constructions.map((c, i) => (
            <Fragment key={`${c.filePath}:${c.lineStart}`}>
              {i > 0 && ', '}
              <SourceLink localPath={localPath} filePath={c.filePath} line={c.lineStart} className="font-mono" title={c.filePath}>
                {fileName(c.filePath) === fileName(sites[0].filePath) ? '' : fileName(c.filePath)}:{c.lineStart}
              </SourceLink>
            </Fragment>
          ))}
        </span>
      )}
    </span>
  )
}

function Bindings({ invocation }: { invocation: OutboundInvocation }) {
  const [open, setOpen] = useState(false)
  const bindings = invocation.environment_bindings
  if (bindings.length === 0) return null
  const hosts = new Set(bindings.map((b) => `${b.host ?? b.placeholder}:${b.port ?? ''}${b.authentication ?? ''}`))
  const verdicts = new Set(bindings.map((b) => b.linuxVerdict))
  return (
    <div className="mt-1">
      <button type="button" onClick={() => setOpen((v) => !v)} className="text-[11px] text-violet-600 hover:underline">
        {open ? '▾' : '▸'} {bindings.length} environment binding{bindings.length === 1 ? '' : 's'}
        {verdicts.size > 1 ? (
          <span className="font-medium text-neutral-600"> — verdicts differ by environment</span>
        ) : (
          hosts.size > 1 && <span className="text-neutral-400"> — values differ</span>
        )}
      </button>
      {open && (
        <LimitedList items={bindings} name={(b) => [b.environment, b.host, b.placeholder, b.sourceFile, b.keyPath]} noun="environment bindings">
          {(shown) => (
        <table className="mt-1 w-full text-left text-[11px]">
          <tbody>
            {shown.map((b) => (
              <tr key={`${b.environment}|${b.sourceFile}|${b.keyPath}`} className="border-t border-neutral-100">
                <td className="py-0.5 pr-2">{b.linuxVerdict && <VerdictBadge verdict={b.linuxVerdict} reasons={b.linuxReasons} />}</td>
                <td className="py-0.5 pr-2 font-medium text-neutral-600">{b.environment}</td>
                <td className="break-all py-0.5 pr-2 font-mono text-neutral-800">
                  {b.resolution === 'unresolved'
                    ? <span className="text-neutral-500">{b.placeholder ?? 'unresolved'}</span>
                    : `${b.scheme ?? '?'}://${b.host ?? '?'}${b.port !== null ? `:${b.port}` : ''}${b.path ?? ''}`}
                </td>
                <td className="py-0.5 pr-2 text-neutral-500" title={b.linuxReasons.join('\n') || undefined}>
                  {b.authentication ?? ''}
                </td>
                <td className="break-all py-0.5 font-mono text-neutral-400" title={b.sourceFile}>
                  {b.sourceFile.split('/').pop()} · {b.keyPath}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
          )}
        </LimitedList>
      )}
    </div>
  )
}

function UnusedBadge() {
  return (
    <span
      className="whitespace-nowrap rounded border border-dashed border-neutral-300 px-1.5 py-0.5 text-[10px] font-semibold text-neutral-500"
      title="Constructed nowhere and configured nowhere: dead code making no outbound call. Kept in the inventory, left out of every count, and not a dependency for the endpoint register."
    >
      unused
    </span>
  )
}

function InvocationRow({ invocation, localPath }: { invocation: OutboundInvocation; localPath: string | null }) {
  const unused = invocation.usage === 'unused'
  return (
    <tr className={`border-b border-neutral-100 align-top last:border-0 ${unused ? 'opacity-60' : ''}`}>
      <td className="py-1.5 pr-3">
        {unused ? <UnusedBadge /> : <VerdictBadge verdict={invocation.linux_verdict} reasons={invocation.linux_reasons} />}
      </td>
      <td className="py-1.5 pr-3">
        <EndpointCell invocation={invocation} />
        <p className="text-[11px] text-neutral-600">
          {describe(invocation)}
          {invocation.confidence < 1 && (
            <span className="ml-1 text-neutral-400" title={invocation.confidence_reasons.join('\n')}>
              ({invocation.confidence.toFixed(2)})
            </span>
          )}
        </p>
        <SubLine invocation={invocation} />
        <p className="text-[11px] text-neutral-500">{invocation.linux_reasons.join(' · ')}</p>
        <Bindings invocation={invocation} />
      </td>
      <td className="py-1.5 pr-3">
        <Credentials invocation={invocation} />
      </td>
      <td className="whitespace-nowrap py-1.5 text-right">
        <CallSites invocation={invocation} localPath={localPath} />
      </td>
    </tr>
  )
}

/** Mechanism groups, worst verdict first; within a group the API's order
 * (incompatible first). */
function MechanismGroups({ invocations, localPath }: { invocations: OutboundInvocation[]; localPath: string | null }) {
  const groups = new Map<OutboundMechanism, OutboundInvocation[]>()
  for (const i of invocations) groups.set(i.mechanism, [...(groups.get(i.mechanism) ?? []), i])
  const ordered = [...groups.entries()].sort(([a, x], [b, y]) => {
    const worst = (list: OutboundInvocation[]) => Math.min(...list.map(rank))
    return worst(x) - worst(y) || MECHANISM_LABEL[a].localeCompare(MECHANISM_LABEL[b])
  })
  return (
    <div className="space-y-3">
      {ordered.map(([mechanism, list]) => (
        <div key={mechanism}>
          <h5 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-neutral-400">
            {MECHANISM_LABEL[mechanism]} <span className="font-normal normal-case">({list.length})</span>
          </h5>
          <LimitedList items={list} name={(i) => [endpointText(i), describe(i)]} noun="invocations">
            {(shown) => (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="text-neutral-400">
                    <tr className="border-b border-neutral-200">
                      <th className="w-28 py-1 pr-3 font-medium">Linux</th>
                      <th className="py-1 pr-3 font-medium">Endpoint</th>
                      <th className="py-1 pr-3 font-medium">Credentials</th>
                      <th className="py-1 text-right font-medium">Called from</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((i) => (
                      <InvocationRow key={i.id} invocation={i} localPath={localPath} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </LimitedList>
        </div>
      ))}
    </div>
  )
}

/** One project's invocations grouped by mechanism, incompatible first.
 * Shared by the repository Surface panel and the
 * outbound-invocation-inventory artifact renderer. */
export function OutboundProjectPanel({ project, localPath }: { project: ProjectOutbound; localPath: string | null }) {
  const incompatible = project.count_by_verdict.incompatible ?? 0
  const requiresChange = project.count_by_verdict.requires_change ?? 0
  const used = project.invocations.length - project.unused_count
  const [open, setOpen] = useState(incompatible > 0)
  return (
    <div className="rounded border border-neutral-200">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full flex-wrap items-center justify-between gap-x-3 gap-y-1 px-3 py-2 text-left hover:bg-neutral-50"
      >
        <span className="break-all font-mono text-xs text-neutral-800">{project.project_path}</span>
        <span className="flex flex-wrap items-center gap-2 text-xs text-neutral-400">
          {used} invocation{used === 1 ? '' : 's'}
          {project.unused_count > 0 && <span>{project.unused_count} unused</span>}
          {incompatible > 0 && <span className="font-semibold text-red-700">{incompatible} incompatible</span>}
          {requiresChange > 0 && <span className="font-semibold text-amber-700">{requiresChange} requires change</span>}
          <span>{open ? '▾' : '▸'}</span>
        </span>
      </button>
      {open && (
        <div className="border-t border-neutral-100 px-3 py-3">
          <MechanismGroups invocations={project.invocations} localPath={localPath} />
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, verdict }: { label: string; value: number; verdict?: LinuxVerdict }) {
  const tone = verdict && value > 0 ? VERDICT_STYLE[verdict] : 'border-neutral-200 bg-neutral-50 text-neutral-900'
  return (
    <div className={`rounded border px-3 py-2 ${tone}`}>
      <p className="text-xs font-medium uppercase tracking-wide opacity-70">{label}</p>
      <p className="text-lg font-semibold">{value}</p>
    </div>
  )
}

/** Outbound — 29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md Part D: step 5's
 * invocations grouped by mechanism, a verdict badge on each, environment
 * bindings expandable, incompatible first. */
export function RepositoryOutboundPanel({ repositoryId, localPath, refreshToken }: RepositoryOutboundPanelProps) {
  const [inventory, setInventory] = useState<OutboundInventory | null>(null)
  const [notScanned, setNotScanned] = useState(false)
  const [failed, setFailed] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setNotScanned(false)
    setFailed(false)
    getRepositoryOutboundInvocations(repositoryId)
      .then((result) => {
        if (!cancelled) setInventory(result)
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

  // Projects with an incompatible invocation first — the list someone will act on.
  const withInvocations = (inventory?.projects.filter((p) => p.invocations.length > 0) ?? []).sort(
    (a, b) =>
      Math.min(...a.invocations.map(rank)) - Math.min(...b.invocations.map(rank)) ||
      a.project_path.localeCompare(b.project_path),
  )
  const without = inventory?.projects.filter((p) => p.invocations.length === 0) ?? []

  const projects = inventory?.projects ?? []
  const used = inventory ? inventory.invocation_count - inventory.unused_count : 0
  const incompatible = inventory?.count_by_verdict.incompatible ?? 0
  const requiresChange = inventory?.count_by_verdict.requires_change ?? 0
  const summary = loading
    ? 'loading…'
    : failed
      ? 'could not be loaded'
      : notScanned || !inventory
        ? 'not scanned yet'
        : `${projects.length} project${projects.length === 1 ? '' : 's'}, ${withInvocations.length} with outbound calls · ` +
          `${used} invocation${used === 1 ? '' : 's'}` +
          (incompatible > 0 ? `, ${incompatible} incompatible` : '') +
          (requiresChange > 0 ? `, ${requiresChange} requires change` : '')

  return (
    <CollapsibleSection
      id={surfaceSectionId(repositoryId, 'outbound')}
      title="Outbound"
      summary={summary}
      rowCount={inventory ? projects.length : undefined}
      persist="browser"
      variant="nested"
    >
      <p className="mb-2 text-xs text-neutral-500">What this repository calls.</p>
      {loading ? (
        <p className="text-sm text-neutral-400">Loading outbound invocations…</p>
      ) : failed ? (
        <p className="text-sm text-red-600">Could not load the outbound-invocation inventory.</p>
      ) : notScanned || !inventory ? (
        <div className="rounded border border-dashed border-neutral-200 bg-neutral-50 p-4 text-sm text-neutral-500">
          The outbound-invocation inventory (outbound-invocation-inventory) hasn't run for this repository yet.
        </div>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <Stat label="Invocations" value={inventory.invocation_count - inventory.unused_count} />
            <Stat label="Incompatible" value={inventory.count_by_verdict.incompatible ?? 0} verdict="incompatible" />
            <Stat label="Requires change" value={inventory.count_by_verdict.requires_change ?? 0} verdict="requires_change" />
            <Stat label="Unknown" value={inventory.count_by_verdict.unknown ?? 0} verdict="unknown" />
            <Stat label="Compatible" value={inventory.count_by_verdict.compatible ?? 0} verdict="compatible" />
            <Stat label="Unused (not counted)" value={inventory.unused_count} />
          </div>
          <p className="text-[11px] text-neutral-400">
            Linux verdict per invocation, the worst of its environments; expand the bindings for each environment's own verdict — the answer for a
            migration target. Hover a badge for its reasons. Unused clients (constructed and configured nowhere) are listed last and counted nowhere. Endpoints are normalised — scheme, host, port, path; credentials in a URL,
            its query and fragment are never stored — and a value from configuration shows its key, with one binding per environment file.
            Credentials are shown by kind and key path only. {inventory.auth_declared_scope}
          </p>
          {withInvocations.length === 0 && <p className="text-sm text-neutral-400">No outbound invocations found in any project.</p>}
          {/* One list: a panel per project with invocations, and the grouped line for the rest, which counts as one. */}
          <LimitedList<ProjectOutbound | 'without'>
            items={[...withInvocations, ...(without.length > 0 ? (['without'] as const) : [])]}
            name={(p) => (p === 'without' ? without.map((w) => w.project_path) : p.project_path)}
            noun="projects"
          >
            {(shown) => (
              <div className="space-y-2">
                {shown.map((project) =>
                  project === 'without' ? (
                    <GroupedItems key="without" label={`${without.length} project${without.length === 1 ? '' : 's'} with no outbound invocations`}>
                      <LimitedList items={without} name={(w) => w.project_path} noun="projects">
                        {(rows) => (
                          <ul className="space-y-0.5 text-xs text-neutral-500">
                            {rows.map((w) => (
                              <li key={w.project_id}>
                                <span className="break-all font-mono">{w.project_path}</span>
                                {w.status !== 'SCANNED' && <span className="text-neutral-400"> — {w.skip_reason ?? w.status.toLowerCase()}</span>}
                              </li>
                            ))}
                          </ul>
                        )}
                      </LimitedList>
                    </GroupedItems>
                  ) : (
                    <OutboundProjectPanel key={project.project_id} project={project} localPath={localPath} />
                  ),
                )}
              </div>
            )}
          </LimitedList>
        </div>
      )}
    </CollapsibleSection>
  )
}
