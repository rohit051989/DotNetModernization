import { useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import { getRepositoryEntryPoints } from '../../api/surface'
import { RepositoryOutboundPanel } from './RepositoryOutboundPanel'
import { sourceHref } from './sourceHref'
import type { EntryPoint, EntryPointInventory, EntryPointKind, HttpDetail, HttpParameter, ProjectEntryPoints, WcfEndpoint } from '../../types/surface'

interface RepositorySurfaceSectionProps {
  repositoryId: string
  /** The repository's path on this machine — source links open the
   * handler in VS Code, which only works on the machine that registered it
   * (the single-operator model; CLAUDE.md "Operating model"). */
  localPath: string
  refreshToken: number
}

const KIND_LABEL: Record<EntryPointKind, string> = {
  http_controller_action: 'HTTP — controller actions',
  http_minimal_api: 'HTTP — minimal APIs',
  razor_page: 'HTTP — Razor Pages',
  blazor_component: 'Blazor routable components',
  azure_function: 'Azure Functions',
  http_handler: 'HTTP handlers and modules',
  global_asax: 'Global.asax events',
  owin_startup: 'OWIN startup',
  windows_service: 'Windows services',
  desktop_app: 'Desktop applications',
  wcf_operation: 'WCF operations',
  asmx_web_method: 'ASMX web methods',
  grpc_service_method: 'gRPC service methods',
  signalr_hub_method: 'SignalR hub methods',
  message_consumer: 'Message consumers',
  hosted_service: 'Hosted services',
  scheduled_job: 'Scheduled jobs',
  console_main: 'Console / desktop mains',
  webforms_page: 'WebForms pages',
}

const KIND_ORDER = Object.keys(KIND_LABEL) as EntryPointKind[]

const VERB_STYLE: Record<string, string> = {
  GET: 'bg-sky-50 text-sky-700 border-sky-200',
  POST: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  PUT: 'bg-amber-50 text-amber-700 border-amber-200',
  PATCH: 'bg-amber-50 text-amber-700 border-amber-200',
  DELETE: 'bg-red-50 text-red-700 border-red-200',
}

function isHttp(entry: EntryPoint): boolean {
  return entry.kind === 'http_controller_action' || entry.kind === 'http_minimal_api' || entry.kind === 'razor_page'
}

function HandlerLink({ entry, localPath }: { entry: EntryPoint; localPath: string }) {
  const label = entry.handler_member ? `${entry.handler_type}.${entry.handler_member}` : entry.handler_type
  return (
    <a
      href={sourceHref(localPath, entry.file_path, entry.line_start)}
      title={`${entry.file_path}:${entry.line_start}–${entry.line_end} — opens in VS Code`}
      className="font-mono text-violet-700 hover:underline"
    >
      {label}
    </a>
  )
}

/** A registered framework or package type: kept for the move to
 * middleware, but it migrates through its package, not by rewriting. */
function OriginMark({ entry }: { entry: EntryPoint }) {
  if (entry.origin !== 'framework') return null
  return (
    <span
      title="Framework or package type the application only registers — migrates through its package's own path, not by rewriting"
      className="ml-1 rounded bg-neutral-100 px-1 text-[10px] font-medium text-neutral-500"
    >
      framework
    </span>
  )
}

function ConfidenceMark({ entry }: { entry: EntryPoint }) {
  if (entry.confidence >= 1) return null
  return (
    <span
      title={entry.confidence_reasons.join('\n')}
      className={`ml-1 cursor-help rounded px-1 text-[10px] font-medium ${
        entry.confidence < 0.7 ? 'bg-amber-100 text-amber-800' : 'bg-neutral-100 text-neutral-500'
      }`}
    >
      {entry.confidence.toFixed(1)}
    </span>
  )
}

/** A review prompt, not a finding: authentication in front of the code —
 * an API gateway, an access manager injecting headers — is invisible here. */
function NoDeclaredAuthFlag() {
  return (
    <span
      title="No authentication declared in source or config, or declared waived ([AllowAnonymous], no WCF client credential). Gateway, proxy and header-based authentication are not visible to static analysis — review how this is protected."
      className="whitespace-nowrap rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800"
    >
      no declared auth
    </span>
  )
}

function Parameters({ parameters }: { parameters: HttpParameter[] }) {
  if (parameters.length === 0) return <span className="text-neutral-300">—</span>
  return (
    <span className="flex flex-wrap gap-1">
      {parameters.map((p) => {
        const source = p.source === 'inferred' ? (p.inferredSource ? `${p.inferredSource}?` : '?') : p.source
        return (
          <span
            key={p.name}
            title={`${p.type ?? 'untyped'} ${p.name} — ${
              p.source === 'inferred'
                ? p.inferredSource
                  ? `inferred from convention: ${p.inferredSource}`
                  : 'binding source not decidable syntactically'
                : `[From${p.source[0].toUpperCase()}${p.source.slice(1)}]`
            }`}
            className="rounded bg-neutral-100 px-1.5 py-0.5 font-mono text-[11px] text-neutral-700"
          >
            {p.name}
            <span className="text-neutral-400">:{source}</span>
          </span>
        )
      })}
    </span>
  )
}

function RouteCell({ http }: { http: HttpDetail }) {
  if (http.routeTemplate !== null) {
    return (
      <span className="font-mono text-neutral-800" title={http.pageFile ?? undefined}>
        /{http.routeTemplate}
        {http.pageHandler && <span className="text-neutral-400">?handler={http.pageHandler}</span>}
      </span>
    )
  }
  if (http.routing === 'conventional') {
    return (
      <span className="text-neutral-400" title="No attribute routing: the route comes from the conventional route table, recorded below. Not guessed.">
        conventional
        <span className="font-mono text-neutral-500"> · {http.controller}/{http.action}</span>
      </span>
    )
  }
  return (
    <span className="text-amber-700" title={http.groupPrefix?.expression ? `MapGroup prefix: ${http.groupPrefix.expression}` : undefined}>
      unresolved
      {http.mappedTemplate !== null && <span className="font-mono"> · …/{http.mappedTemplate.replace(/^\//, '')}</span>}
    </span>
  )
}

function HttpRouteTable({ entries, localPath }: { entries: EntryPoint[]; localPath: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead className="text-neutral-400">
          <tr className="border-b border-neutral-200">
            <th className="py-1.5 pr-3 font-medium">Verb</th>
            <th className="py-1.5 pr-3 font-medium">Route</th>
            <th className="py-1.5 pr-3 font-medium">Handler</th>
            <th className="py-1.5 pr-3 font-medium">Parameters</th>
            <th className="py-1.5 font-medium">Authorisation</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => {
            const http = entry.detail as HttpDetail
            return (
              <tr key={entry.id} className={`border-b border-neutral-100 align-top ${entry.auth_declared === 'none_declared' ? 'bg-amber-50/40' : ''}`}>
                <td className="py-1.5 pr-3">
                  <span className={`rounded border px-1.5 py-0.5 font-mono text-[11px] font-semibold ${VERB_STYLE[http.verb] ?? 'border-neutral-200 bg-neutral-50 text-neutral-600'}`}>
                    {http.verb}
                  </span>
                </td>
                <td className="py-1.5 pr-3">
                  <RouteCell http={http} />
                  <ConfidenceMark entry={entry} />
                </td>
                <td className="py-1.5 pr-3">
                  {entry.handler_member === null && entry.kind === 'razor_page' ? (
                    <span className="font-mono text-neutral-600" title="The page renders on GET with no handler method">
                      <HandlerLink entry={entry} localPath={localPath} />
                      <span className="ml-1 text-[10px] text-neutral-400">(no handler)</span>
                    </span>
                  ) : (
                    <HandlerLink entry={entry} localPath={localPath} />
                  )}
                  {http.handlerForm === 'lambda' && <span className="ml-1 text-[10px] text-neutral-400">(lambda)</span>}
                </td>
                <td className="py-1.5 pr-3">
                  <Parameters parameters={http.parameters} />
                </td>
                <td className="py-1.5">
                  <span className="flex flex-wrap items-center gap-1">
                    {entry.auth_declared === 'none_declared' && <NoDeclaredAuthFlag />}
                    {http.authorisation ? (
                      <span className="font-mono text-[11px] text-neutral-600">{http.authorisation}</span>
                    ) : (
                      entry.auth_declared !== 'none_declared' && <span className="text-neutral-300">—</span>
                    )}
                  </span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** One line describing a non-HTTP entry point's kind-specific block. */
function describe(entry: EntryPoint): string {
  const d = entry.detail as Record<string, unknown>
  const text = (value: unknown) => (value === null || value === undefined ? '' : String(value))
  switch (entry.kind) {
    case 'wcf_operation':
      return `${text(d.contract)}.${text(d.operation)}${d.isOneWay ? ' (one-way)' : ''}${d.hostedBy ? '' : ' · no .svc, ServiceHost or CoreWCF host found'}`
    case 'asmx_web_method':
      return `${text(d.servicePath)} → ${text(d.method)}`
    case 'webforms_page':
      return text(d.pagePath)
    case 'grpc_service_method':
      return text(d.fullMethod) || `${text(d.service)}/${text(d.method)} (no .proto found)`
    case 'signalr_hub_method':
      return `${d.hubRoute ? `/${text(d.hubRoute)}` : text(d.hub)} → ${text(d.method)}`
    case 'message_consumer': {
      const sources = (d.sources as string[] | undefined) ?? []
      return `${text(d.transport)} · ${sources.length > 0 ? sources.join(', ') : 'source unresolved'}${d.hostedService ? ' · in a hosted service' : ''}`
    }
    case 'scheduled_job':
      return [text(d.scheduler), d.jobId ? `"${text(d.jobId)}"` : '', text(d.expression)].filter(Boolean).join(' · ')
    case 'hosted_service':
      return `${text(d.serviceBase)}${d.registered ? ' · registered with AddHostedService' : ''}`
    case 'windows_service':
      return `${d.serviceName ? `"${text(d.serviceName)}" · ` : ''}${((d.hooks as string[]) ?? []).join(', ') || 'no lifecycle overrides'}${d.runAt ? ` · run at ${text(d.runAt)}` : ''}`
    case 'http_handler':
      return `${text(d.role)} ${text(d.typeName)}${d.path ? ` · ${text(d.path)}` : ''}${d.verb ? ` (${text(d.verb)})` : ''}${d.inRepository ? '' : ' · framework/package type'}${d.registeredAt ? ` · registered at ${text(d.registeredAt)}` : ''}`
    case 'global_asax':
      return `${text(d.event)} · ${text(d.scope)} scope`
    case 'owin_startup':
      return `declared by ${text(d.declaredBy).replace('_', ' ')}${((d.middleware as string[]) ?? []).length ? ` · middleware: ${((d.middleware as string[]) ?? []).join(' → ')}` : ''}`
    case 'blazor_component':
      return `${text(d.route)}${d.authorisation ? ` · ${text(d.authorisation)}` : ''}`
    case 'azure_function':
      return `"${text(d.functionName)}" · ${text(d.trigger) || 'trigger unknown'}${d.authorizationLevel ? ` (${text(d.authorizationLevel)})` : ''}${d.route ? ` · /${text(d.route)}` : ''} · ${text(d.model).replace('_', '-')}`
    case 'desktop_app':
      return `${text(d.framework) === 'wpf' ? 'WPF' : 'WinForms'}${d.mainWindow ? ` · ${text(d.mainWindow)}` : ''}`
    case 'console_main':
      return `${d.form === 'top_level_statements' ? 'top-level statements' : 'static Main'}${d.staThread ? ' · [STAThread] (desktop)' : ''}`
    default:
      return ''
  }
}

const HOST_LABEL: Record<WcfEndpoint['hostKind'], string> = { svc: '.svc', service_host: 'ServiceHost', corewcf: 'CoreWCF' }

/** Binding and security per endpoint — the answer that turns a WCF
 * operation from "not assessed" into assessed. */
function WcfEndpoints({ endpoints }: { endpoints: WcfEndpoint[] }) {
  if (endpoints.length === 0) {
    return <p className="mt-0.5 text-[11px] text-neutral-400">No endpoint declared in config or code — security not assessed.</p>
  }
  return (
    <ul className="mt-1 space-y-0.5">
      {endpoints.map((e) => (
        <li key={`${e.hostedAt}|${e.declaredAt}`} className="flex flex-wrap items-center gap-1 text-[11px]">
          <span className="rounded bg-neutral-100 px-1 text-neutral-500">{HOST_LABEL[e.hostKind]}</span>
          <span className="font-mono text-neutral-700">{e.binding}</span>
          <span className="text-neutral-500">
            {e.securityMode ?? '?'} / {e.clientCredentialType ?? '?'}
          </span>
          {e.securitySource === 'binding_default' && (
            <span className="text-neutral-400" title="Left out of the config or code; WCF's documented default for this binding">
              (binding default)
            </span>
          )}
          {e.securitySource === 'unresolved' && <span className="text-amber-700">(not determinable)</span>}
          {e.anonymous && <span className="font-semibold text-red-600">anonymous</span>}
          {e.condition && <span className="text-neutral-400" title="Added only when this holds">if {e.condition}</span>}
          <span className="font-mono text-neutral-300" title={`hosted at ${e.hostedAt}`}>{e.declaredAt}</span>
        </li>
      ))}
    </ul>
  )
}

function OtherKindTable({ entries, localPath }: { entries: EntryPoint[]; localPath: string }) {
  return (
    <table className="w-full text-left text-xs">
      <tbody>
        {entries.map((entry) => {
          const authorisation = (entry.detail as Record<string, unknown>).authorisation as string | null | undefined
          return (
            <tr key={entry.id} className={`border-b border-neutral-100 align-top ${entry.auth_declared === 'none_declared' ? 'bg-amber-50/40' : ''}`}>
              <td className="w-2/5 py-1.5 pr-3">
                <HandlerLink entry={entry} localPath={localPath} />
                <OriginMark entry={entry} />
                <ConfidenceMark entry={entry} />
              </td>
              <td className="py-1.5 pr-3 text-neutral-600">
                {describe(entry)}
                {entry.kind === 'wcf_operation' && <WcfEndpoints endpoints={((entry.detail as Record<string, unknown>).endpoints as WcfEndpoint[]) ?? []} />}
              </td>
              <td className="py-1.5 text-right">
                <span className="flex flex-wrap justify-end gap-1">
                  {entry.auth_declared === 'none_declared' && <NoDeclaredAuthFlag />}
                  {authorisation && <span className="font-mono text-[11px] text-neutral-600">{authorisation}</span>}
                </span>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function KindGroups({ entries, localPath }: { entries: EntryPoint[]; localPath: string }) {
  const byKind = KIND_ORDER.map((kind) => ({ kind, entries: entries.filter((e) => e.kind === kind) })).filter((g) => g.entries.length > 0)
  return (
    <>
      {byKind.map(({ kind, entries: group }) => (
        <div key={kind}>
          <h5 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-neutral-400">
            {KIND_LABEL[kind]} · {group.length}
          </h5>
          {isHttp(group[0]) ? <HttpRouteTable entries={group} localPath={localPath} /> : <OtherKindTable entries={group} localPath={localPath} />}
        </div>
      ))}
    </>
  )
}

function ProjectPanel({ project, localPath }: { project: ProjectEntryPoints; localPath: string }) {
  const [expanded, setExpanded] = useState(true)
  const [showLifecycle, setShowLifecycle] = useState(false)
  const requests = project.entry_points.filter((e) => e.entry_class === 'request')
  const lifecycle = project.entry_points.filter((e) => e.entry_class === 'lifecycle')

  return (
    <div className="rounded border border-neutral-200">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-neutral-50"
      >
        <span className="font-mono text-xs text-neutral-800">{project.project_path}</span>
        <span className="flex flex-none items-center gap-2 text-xs text-neutral-400">
          {project.request_entry_point_count} request{project.request_entry_point_count === 1 ? '' : 's'}
          {project.lifecycle_hook_count > 0 && <span> · {project.lifecycle_hook_count} lifecycle</span>}
          {(project.count_by_origin.framework ?? 0) > 0 && <span> · {project.count_by_origin.framework} framework</span>}
          {project.no_declared_authentication_count > 0 && (
            <span className="font-semibold text-amber-700">{project.no_declared_authentication_count} no declared authentication</span>
          )}
          <span>{expanded ? '▲' : '▼'}</span>
        </span>
      </button>
      {expanded && (
        <div className="space-y-3 border-t border-neutral-100 px-3 py-3">
          {requests.length > 0 ? (
            <KindGroups entries={requests} localPath={localPath} />
          ) : (
            <p className="text-xs text-neutral-400">No request entry points.</p>
          )}
          {lifecycle.length > 0 && (
            <div className="rounded border border-dashed border-neutral-200 px-2 py-1.5">
              <button type="button" onClick={() => setShowLifecycle((v) => !v)} className="text-xs text-violet-600 hover:underline">
                {showLifecycle ? 'Hide' : 'Show'} {lifecycle.length} lifecycle hook{lifecycle.length === 1 ? '' : 's'}
              </button>
              <span className="ml-2 text-[11px] text-neutral-400">
                Bootstrap and wiring (Global.asax, OWIN startup, HTTP modules, services, mains) — not where external work enters, so not
                counted as surface or made test targets.
              </span>
              {showLifecycle && (
                <div className="mt-2 space-y-3">
                  <KindGroups entries={lifecycle} localPath={localPath} />
                </div>
              )}
            </div>
          )}
          {(project.conventional_routes.length > 0 || project.global_authorisation.length > 0) && (
            <div className="space-y-1 rounded bg-neutral-50 px-2 py-1.5 text-[11px] text-neutral-500">
              {project.conventional_routes.map((route) => (
                <p key={route}>
                  <span className="font-medium text-neutral-600">Conventional route table:</span> <span className="font-mono">{route}</span>
                </p>
              ))}
              {project.global_authorisation.map((text) => (
                <p key={text}>
                  <span className="font-medium text-neutral-600">Project-wide authorisation:</span> <span className="font-mono">{text}</span>
                </p>
              ))}
            </div>
          )}
          {project.authorisation_not_assessed_count > 0 && (
            <p className="text-[11px] text-neutral-400">
              {project.authorisation_not_assessed_count} entry point(s) have no authorisation declared in source or config (no &lt;authorization&gt;
              rules, no WCF endpoint) — not assessed, and not counted as having no declared authentication.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: 'amber' }) {
  return (
    <div className={`rounded border px-3 py-2 ${tone === 'amber' && value > 0 ? 'border-amber-200 bg-amber-50' : 'border-neutral-200 bg-neutral-50'}`}>
      <p className="text-xs font-medium uppercase tracking-wide text-neutral-400">{label}</p>
      <p className={`text-lg font-semibold ${tone === 'amber' && value > 0 ? 'text-amber-800' : 'text-neutral-900'}`}>{value}</p>
    </div>
  )
}

/** Surface — 29-STEPS-004-005-INVENTORIES.md Part D. Inbound is step 4's
 * entry points; Outbound is step 5's invocations. */
export function RepositorySurfaceSection({ repositoryId, localPath, refreshToken }: RepositorySurfaceSectionProps) {
  const [inventory, setInventory] = useState<EntryPointInventory | null>(null)
  const [notScanned, setNotScanned] = useState(false)
  const [failed, setFailed] = useState(false)
  const [loading, setLoading] = useState(true)
  const [showEmpty, setShowEmpty] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setNotScanned(false)
    setFailed(false)
    getRepositoryEntryPoints(repositoryId)
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

  const withEntries = inventory?.projects.filter((p) => p.entry_points.length > 0) ?? []
  const without = inventory?.projects.filter((p) => p.entry_points.length === 0) ?? []

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-neutral-900">Surface</h3>

      <div>
        <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-neutral-400">Inbound — what can call this repository</h4>
        {loading ? (
          <p className="text-sm text-neutral-400">Loading entry points…</p>
        ) : failed ? (
          <p className="text-sm text-red-600">Could not load the entry-point inventory.</p>
        ) : notScanned || !inventory ? (
          <div className="rounded border border-dashed border-neutral-200 bg-neutral-50 p-4 text-sm text-neutral-500">
            The entry-point inventory (lifecycle step 4) hasn't run for this repository yet.
          </div>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
              <Stat label="Request entry points" value={inventory.request_entry_point_count} />
              <Stat label="No declared auth" value={inventory.no_declared_authentication_count} tone="amber" />
              <Stat
                label="HTTP routes"
                value={(inventory.count_by_kind.http_controller_action ?? 0) + (inventory.count_by_kind.http_minimal_api ?? 0) + (inventory.count_by_kind.razor_page ?? 0)}
              />
              <Stat label="Auth not assessed" value={inventory.authorisation_not_assessed_count} />
              <Stat label="Lifecycle hooks" value={inventory.lifecycle_hook_count} />
              <Stat label="Framework-origin" value={inventory.count_by_origin.framework ?? 0} />
            </div>
            <p className="rounded border border-amber-100 bg-amber-50/60 px-2 py-1.5 text-[11px] text-amber-900">
              <span className="font-semibold">About “no declared auth”:</span> {inventory.auth_declared_scope}
            </p>
            <p className="text-[11px] text-neutral-400">
              {inventory.capabilities_manifest_version
                ? `Scanned for ${inventory.capability_kinds.length} entry-point kinds (capability manifest ${inventory.capabilities_manifest_version}); patterns outside it are listed in Workflow Administration → Detection capabilities. `
                : 'Scanned before capability manifests existed — rescan to see which kinds were looked for. '}
              Syntax-only: routes, types and authorisation as written in source and config. A number beside a route or handler is its confidence below 1.0 —
              hover for why. Handler links open the source in VS Code.
            </p>
            {withEntries.length === 0 ? (
              <p className="text-sm text-neutral-400">No entry points found in any project.</p>
            ) : (
              <div className="space-y-2">
                {withEntries.map((project) => (
                  <ProjectPanel key={project.project_id} project={project} localPath={localPath} />
                ))}
              </div>
            )}
            {without.length > 0 && (
              <div>
                <button type="button" onClick={() => setShowEmpty((v) => !v)} className="text-xs text-violet-600 hover:underline">
                  {showEmpty ? 'Hide' : 'Show'} {without.length} project(s) with no entry points
                </button>
                {showEmpty && (
                  <ul className="mt-1 space-y-0.5 text-xs text-neutral-500">
                    {without.map((project) => (
                      <li key={project.project_id}>
                        <span className="font-mono">{project.project_path}</span>
                        {project.status !== 'SCANNED' && <span className="text-neutral-400"> — {project.skip_reason ?? project.status.toLowerCase()}</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <RepositoryOutboundPanel repositoryId={repositoryId} localPath={localPath} refreshToken={refreshToken} />
    </div>
  )
}
