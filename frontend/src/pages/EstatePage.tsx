import { Fragment, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ApiError } from '../api/client'
import { getEstate, putEndpointAnnotation, putEstateSettings } from '../api/estate'
import { launchJob } from '../api/workflow'
import { LimitedList } from '../components/LimitedList'
import { useToast } from '../components/Toast'
import { SoapCompatibilityView } from './SoapCompatibilityView'
import { EstateRuleConflictsView } from './RuleConflictsViews'
import type {
  ContextMapArtifact,
  ConversationStatus,
  Coverage,
  DependencyGraphArtifact,
  EndpointAnnotation,
  EndpointRegisterArtifact,
  EstateSettings,
  EstateView,
  IntegrationApplication,
  IntegrationMapArtifact,
  PackageEstateArtifact,
  RegisterHost,
} from '../types/estate'
import { UNDER_REVIEW, UNDER_REVIEW_LABEL } from '../types/estate'

/** The backend's own words for a refusal it explains (someone else changed it first; only an admin may), else ours. */
function staleOr(err: unknown, fallback: string): string {
  return err instanceof ApiError && (err.code === 'STALE_COPY' || err.code === 'NOT_ALLOWED') ? err.message : fallback
}

// The Estate tab — lifecycle step 11, 31-DEPENDENCY-AND-CONTEXT-MAP.md
// Part H. Five views over the newest run's artifacts; coverage on each, since
// a register built from part of the estate is provisional.

type View = 'register' | 'soap' | 'integration' | 'packages' | 'dependencies' | 'context' | 'rule-conflicts'

const VIEWS: { key: View; label: string }[] = [
  { key: 'register', label: 'Endpoint register' },
  { key: 'soap', label: 'SOAP compatibility' },
  { key: 'integration', label: 'Integration' },
  { key: 'packages', label: 'Packages' },
  { key: 'dependencies', label: 'Dependencies' },
  { key: 'context', label: 'Context' },
  { key: 'rule-conflicts', label: 'Catalog rule conflicts' },
]

const STATUS_LABEL: Record<ConversationStatus, string> = {
  not_started: 'not started',
  in_progress: 'in progress',
  agreed: 'agreed',
  resolved: 'resolved',
  not_required: 'not required',
}

const VERDICT_STYLE: Record<string, string> = {
  incompatible: 'border-red-200 bg-red-50 text-red-700',
  requires_change: 'border-amber-200 bg-amber-50 text-amber-800',
  unknown: 'border-neutral-300 bg-neutral-100 text-neutral-600',
  compatible: 'border-teal-200 bg-teal-50 text-teal-700',
  under_review: 'border-violet-300 bg-violet-50 text-violet-800',
}

/** A verdict as shown: one resting on a matrix entry a probe contradicts is never shown as that verdict. */
function verdictLabel(verdict: string): string {
  return verdict === UNDER_REVIEW ? UNDER_REVIEW_LABEL : verdict.replace('_', ' ')
}

function Pill({ children, className = '', title }: { children: React.ReactNode; className?: string; title?: string }) {
  return (
    <span className={`whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] ${className || 'border-neutral-200 bg-neutral-50 text-neutral-600'}`} title={title}>
      {children}
    </span>
  )
}

function CoverageBanner({ coverage }: { coverage: Coverage | undefined }) {
  if (!coverage) return null
  return (
    <p
      className={`rounded border px-3 py-2 text-sm ${coverage.partialEstate ? 'border-amber-200 bg-amber-50 text-amber-900' : 'border-neutral-200 bg-white text-neutral-600'}`}
    >
      <span className="font-medium">
        {coverage.repositoriesIncluded} of {coverage.repositoriesInEngagement} repositories included
      </span>
      {coverage.partialEstate
        ? ` — partial estate: ${coverage.repositoriesPending} not yet scanned, so everything below is provisional.`
        : ' — the whole estate.'}
    </p>
  )
}

export function EstatePage({
  engagementId,
  onOpenRepository,
  focusSoapInvocation = null,
  onFocusShown,
}: {
  engagementId: string
  onOpenRepository: (repositoryId: string) => void
  /** Open the SOAP report at this call's row (from a repository page's Surface section). */
  focusSoapInvocation?: string | null
  onFocusShown?: () => void
}) {
  const { showToast } = useToast()
  const [estate, setEstate] = useState<EstateView | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [view, setView] = useState<View>(focusSoapInvocation ? 'soap' : 'register')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setEstate(await getEstate(engagementId))
    } catch {
      setEstate(null)
      showToast('error', 'Could not load the estate view.')
    } finally {
      setLoading(false)
    }
  }, [engagementId, showToast])

  useEffect(() => {
    load()
  }, [load])

  async function runEstate() {
    setRunning(true)
    try {
      const execution = await launchJob('phase0-estate-consolidation', { engagement_id: engagementId, run_token: crypto.randomUUID() })
      showToast(execution.batch_status === 'COMPLETED' ? 'success' : 'error', `Estate consolidation ${execution.batch_status.toLowerCase()}.`)
      await load()
    } catch {
      showToast('error', 'Could not run estate consolidation.')
    } finally {
      setRunning(false)
    }
  }

  const register = estate?.artifacts['endpoint-register']
  const coverage = register?.coverage ?? estate?.artifacts['package-estate']?.coverage

  return (
    <div className="mx-auto max-w-[1440px] space-y-4 px-4 py-4 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-xl font-semibold text-neutral-900">Estate</h2>
          <p className="text-sm text-neutral-500">
            Across every repository in the engagement: who the estate calls, which upgrades recur, and what depends on what (dependency-and-context-map).
          </p>
          {estate?.run && (
            <p className="text-xs text-neutral-400">
              From the estate run of {estate.run.completed_at ? new Date(estate.run.completed_at).toLocaleString() : '—'}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={runEstate}
          disabled={running}
          className="rounded border border-violet-300 bg-violet-50 px-3 py-1.5 text-sm font-medium text-violet-800 hover:bg-violet-100 disabled:opacity-50"
        >
          {running ? 'Running…' : estate?.run ? 'Rerun estate consolidation' : 'Run estate consolidation'}
        </button>
      </div>

      <nav aria-label="Estate views" className="flex gap-1 overflow-x-auto border-b border-neutral-200">
        {VIEWS.map((v) => (
          <button
            key={v.key}
            type="button"
            onClick={() => setView(v.key)}
            className={`shrink-0 whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium ${view === v.key ? 'border-violet-600 text-neutral-900' : 'border-transparent text-neutral-500 hover:text-neutral-800'}`}
          >
            {v.label}
          </button>
        ))}
      </nav>

      {loading && !estate ? (
        <p className="text-sm text-neutral-400">Loading…</p>
      ) : !estate?.run ? (
        <p className="rounded border border-neutral-200 bg-white px-4 py-6 text-sm text-neutral-500">
          Estate consolidation has not run for this engagement yet. Run it once the repositories are scanned; it works on whatever has been scanned so far.
        </p>
      ) : (
        <>
          <CoverageBanner coverage={coverage} />
          {view === 'register' && register && (
            <RegisterView
              engagementId={engagementId}
              register={register}
              annotations={estate.annotations}
              settings={estate.settings}
              onOpenRepository={onOpenRepository}
              onSaved={load}
            />
          )}
          {view === 'integration' &&
            (estate.artifacts['integration-map'] ? (
              <IntegrationView data={estate.artifacts['integration-map']} onOpenRepository={onOpenRepository} />
            ) : (
              <p className="rounded border border-neutral-200 bg-white px-4 py-6 text-sm text-neutral-500">
                This estate run predates the integration map. Rerun estate consolidation to build it.
              </p>
            ))}
          {view === 'packages' && estate.artifacts['package-estate'] && <PackagesView data={estate.artifacts['package-estate']} />}
          {view === 'dependencies' && estate.artifacts['dependency-graph'] && <DependenciesView data={estate.artifacts['dependency-graph']} />}
          {view === 'context' && estate.artifacts['context-map'] && <ContextView data={estate.artifacts['context-map']} />}
          {view === 'rule-conflicts' && <EstateRuleConflictsView engagementId={engagementId} onOpenRepository={onOpenRepository} />}
          {view === 'soap' && (
            <SoapCompatibilityView
              data={estate?.artifacts['soap-backend-compatibility']}
              engagementId={engagementId}
              focusInvocationId={focusSoapInvocation}
              onFocusShown={onFocusShown}
            />
          )}
        </>
      )}
    </div>
  )
}

// ---------- endpoint register ----------

/** A row of the register: a host the estate calls, or one no longer called whose annotation is kept. */
type RegisterRow = { host: RegisterHost; noLongerCalled?: undefined } | { host?: undefined; noLongerCalled: string }

/** The names a person sees on a register row, for its filter box. */
function registerRowNames(row: RegisterRow): string[] {
  if (!row.host) return [row.noLongerCalled]
  return [
    row.host.host,
    ...row.host.otherHosts.map((o) => o.host),
    ...row.host.services.flatMap((s) => [s.path, s.contract ?? '']),
    ...row.host.callingRepositories,
  ]
}

function RegisterView({
  engagementId,
  register,
  annotations,
  settings,
  onOpenRepository,
  onSaved,
}: {
  engagementId: string
  register: EndpointRegisterArtifact
  annotations: EndpointAnnotation[]
  settings: EstateSettings
  onOpenRepository: (repositoryId: string) => void
  onSaved: () => void
}) {
  const { showToast } = useToast()
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [showUnresolved, setShowUnresolved] = useState(false)
  const byHost = useMemo(() => Object.fromEntries(annotations.map((a) => [a.host, a])), [annotations])
  const status = (host: string): ConversationStatus => byHost[host]?.conversation_status ?? 'not_started'

  const backend = register.hosts.filter((h) => h.requiresBackendChange)
  const underWay = backend.filter((h) => ['in_progress', 'agreed'].includes(status(h.host))).length
  const notStarted = backend.filter((h) => status(h.host) === 'not_started').length
  const done = backend.length - underWay - notStarted
  const rows: RegisterRow[] = [...register.hosts.map((host) => ({ host })), ...register.noLongerCalled.map((noLongerCalled) => ({ noLongerCalled }))]

  // Settings and served-by annotations take effect on the next run: say so
  // when what is stored differs from what this register was built with.
  const productionPending = (settings.production_environment ?? null) !== (register.productionEnvironment ?? null)
  const servedByPending = annotations.some((a) => (a.served_by_repository ?? undefined) !== register.servedByAnnotations?.[a.host])

  async function setProduction(value: string) {
    try {
      await putEstateSettings(engagementId, { production_environment: value || null }, settings.version)
      onSaved()
    } catch (err) {
      showToast('error', staleOr(err, 'Could not save the production environment.'))
    }
  }

  async function setTargetWcfClient(text: string) {
    const value = text.trim()
    if (value === (settings.target_wcf_client_version ?? '')) return
    try {
      await putEstateSettings(engagementId, { target_wcf_client_version: value || null }, settings.version)
      onSaved()
    } catch (err) {
      showToast('error', staleOr(err, 'Could not save the target WCF client version: use a version such as 8.1.2.'))
    }
  }

  async function setGlobs(text: string) {
    const globs = text.split(',').map((g) => g.trim()).filter(Boolean)
    if (globs.join(',') === settings.deploy_parameter_globs.join(',')) return
    try {
      await putEstateSettings(engagementId, { deploy_parameter_globs: globs.length > 0 ? globs : null }, settings.version)
      onSaved()
    } catch (err) {
      showToast('error', staleOr(err, 'Could not save the SetParameters globs.'))
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 rounded border border-neutral-200 bg-white px-3 py-2 text-xs">
        <label htmlFor="production-environment" className="font-medium text-neutral-700">
          Production environment
        </label>
        <select
          id="production-environment"
          className="rounded border border-neutral-200 px-1.5 py-1 text-xs focus:border-violet-400 focus:outline-none"
          value={settings.production_environment ?? ''}
          onChange={(e) => setProduction(e.target.value)}
        >
          <option value="">— not set: group by host as found —</option>
          {[...new Set([...settings.environments, ...(settings.production_environment ? [settings.production_environment] : [])])].map((env) => (
            <option key={env} value={env}>
              {env}
            </option>
          ))}
        </select>
        <span className="text-neutral-500">
          Each service is filed under the host its {settings.production_environment ? `'${settings.production_environment}'` : 'production'} configuration names, with
          other environments' hosts beneath.
        </span>
        <label htmlFor="deploy-globs" className="font-medium text-neutral-700 sm:ml-4">
          SetParameters files
        </label>
        <input
          id="deploy-globs"
          key={settings.deploy_parameter_globs.join(',')}
          defaultValue={settings.deploy_parameter_globs.join(', ')}
          onBlur={(e) => setGlobs(e.currentTarget.value)}
          title="Repository-relative globs, comma-separated. Web Deploy SetParameters files found by them are read by steps 3 and 5 on the next scan; empty restores the defaults."
          className="w-full min-w-0 rounded border border-neutral-200 px-1.5 py-1 font-mono text-[11px] focus:border-violet-400 focus:outline-none sm:w-72"
        />
        {settings.deploy_parameter_globs_default && <span className="text-neutral-400">(defaults)</span>}
        <label htmlFor="target-wcf-client" className="font-medium text-neutral-700 sm:ml-4">
          Target WCF client
        </label>
        <input
          id="target-wcf-client"
          key={settings.target_wcf_client_version ?? ''}
          defaultValue={settings.target_wcf_client_version ?? ''}
          placeholder={settings.target_wcf_client_version_effective ?? ''}
          onBlur={(e) => setTargetWcfClient(e.currentTarget.value)}
          title="The System.ServiceModel.* package version this engagement targets. The SOAP report flags matrix entries whose probe evidence covers an older one. Empty: the version the WCF client matrices record for the target framework. Takes effect at once."
          className="w-20 rounded border border-neutral-200 px-1.5 py-1 font-mono text-[11px] focus:border-violet-400 focus:outline-none"
        />
        {!settings.target_wcf_client_version && <span className="text-neutral-400">(the matrices')</span>}
        {(productionPending || servedByPending) && (
          <span className="rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-amber-800">
            {productionPending ? 'Production environment' : 'A served-by annotation'} changed since this register was built — rerun estate consolidation to apply.
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded border border-neutral-200 bg-white px-3 py-2 text-sm">
        <span className={backend.length > 0 ? 'font-semibold text-red-700' : 'text-neutral-600'}>
          {backend.length} host{backend.length === 1 ? ' requires' : 's require'} backend change
        </span>
        {backend.length > 0 && (
          <span className="text-neutral-600">
            ({backend.filter((h) => h.backendChangeOwner !== 'this_migration').length} another team's service,{' '}
            {backend.filter((h) => h.backendChangeOwner === 'this_migration').length} a service inside this migration)
          </span>
        )}
        <span className="text-neutral-500">
          — {underWay} conversation{underWay === 1 ? '' : 's'} under way, {notStarted} not started{done > 0 ? `, ${done} resolved or not required` : ''}.
        </span>
        <span className="ml-auto flex flex-wrap gap-1.5">
          <Pill>{register.summary.hosts} hosts</Pill>
          <Pill>{register.summary.internal} internal</Pill>
          <Pill>{register.summary.external} external</Pill>
          {register.summary.unresolved > 0 && <Pill className="border-amber-200 bg-amber-50 text-amber-800">{register.summary.unresolved} unresolved</Pill>}
          {register.summary.unusedExcluded > 0 && <Pill title="Clients with no construction site or configuration: dead code, not dependencies">{register.summary.unusedExcluded} unused excluded</Pill>}
        </span>
      </div>

      <LimitedList items={rows} name={registerRowNames} noun="hosts">
        {(visible) => (
      <div className="overflow-x-auto rounded border border-neutral-200 bg-white">
        <table className="w-full min-w-[1100px] text-left text-xs">
          <thead className="border-b border-neutral-200 text-neutral-400">
            <tr>
              {['Host', 'Kind', 'Services', 'Calling repositories', 'Bindings', 'Worst verdict', 'Owning team', 'Conversation', 'Target date', 'Notes', 'Served by'].map((h) => (
                <th key={h} className="px-2 py-2 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map(({ host, noLongerCalled }) =>
              host ? (
              <HostRow
                key={host.host}
                engagementId={engagementId}
                host={host}
                repositories={settings.repositories}
                annotation={byHost[host.host] ?? (host.annotationCarriedFrom ?? []).map((h) => byHost[h]).find(Boolean)}
                expanded={!!open[host.host]}
                onToggle={() => setOpen((o) => ({ ...o, [host.host]: !o[host.host] }))}
                onOpenRepository={onOpenRepository}
                onSaved={onSaved}
              />
              ) : (
              <HostRow
                key={noLongerCalled}
                engagementId={engagementId}
                host={null}
                hostName={noLongerCalled}
                repositories={settings.repositories}
                annotation={byHost[noLongerCalled]}
                expanded={false}
                onToggle={() => undefined}
                onOpenRepository={onOpenRepository}
                onSaved={onSaved}
              />
              ),
            )}
          </tbody>
        </table>
      </div>
        )}
      </LimitedList>

      {register.unresolved.length > 0 && (
        <div className="rounded border border-neutral-200 bg-white">
          <button
            type="button"
            onClick={() => setShowUnresolved((v) => !v)}
            aria-expanded={showUnresolved}
            className="flex w-full items-center justify-between px-3 py-2 text-left text-sm"
          >
            <span>
              <span className="font-medium text-neutral-800">Unresolved endpoints ({register.unresolved.length})</span>
              <span className="text-neutral-500"> — the address is decided at runtime or in configuration the scan could not read; never guessed into a host.</span>
            </span>
            <span className="text-neutral-400">{showUnresolved ? '▲' : '▼'}</span>
          </button>
          {showUnresolved && (
            <LimitedList
              items={register.unresolved}
              name={(u) => [`${u.repositorySlug}:${u.projectPath}`, u.contract, u.placeholder ?? u.resolution]}
              noun="unresolved endpoints"
              className="border-t border-neutral-100 px-3 py-2"
            >
              {(visible) => (
            <ul className="space-y-1 text-xs">
              {visible.map((u) => (
                <li key={u.invocationId} className="break-all">
                  <span className="font-mono text-neutral-700">
                    {u.repositorySlug}:{u.projectPath}
                  </span>{' '}
                  <Pill>{u.mechanism.replace(/_/g, ' ')}</Pill> {u.contract && <span className="font-mono text-neutral-500">{u.contract} </span>}
                  <span className="text-neutral-500">{u.placeholder ?? u.resolution}</span>
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

function HostRow({
  engagementId,
  host,
  hostName,
  repositories,
  annotation,
  expanded,
  onToggle,
  onOpenRepository,
  onSaved,
}: {
  engagementId: string
  host: RegisterHost | null
  hostName?: string
  repositories: string[]
  annotation: EndpointAnnotation | undefined
  expanded: boolean
  onToggle: () => void
  onOpenRepository: (repositoryId: string) => void
  onSaved: () => void
}) {
  const name = host?.host ?? hostName ?? ''
  const targets = host ? host.services.flatMap((s) => s.internalTargets) : []
  const servingRepos = [...new Map(targets.map((t) => [t.repositoryId, t])).values()]
  return (
    <Fragment>
      <tr className={`border-b border-neutral-100 align-top ${host?.requiresBackendChange ? 'bg-red-50/30' : ''} ${host ? '' : 'text-neutral-400'}`}>
        <td className="px-2 py-1.5">
          {host ? (
            <button type="button" onClick={onToggle} className="mr-1 text-neutral-400 hover:text-violet-700" aria-expanded={expanded} title="Show services and environments">
              {expanded ? '▾' : '▸'}
            </button>
          ) : (
            <span className="mr-1 inline-block w-[0.7em]" />
          )}
          <span className="font-mono font-medium text-neutral-800">{name}</span>
          {host?.loopback && (
            <span className="block pl-4 text-[11px] text-neutral-400" title="A development address in the scanned configuration; the deployed host comes from each environment's own settings">
              development address
            </span>
          )}
          {host?.groupedBy === 'production_environment' && (
            <span className="block pl-4 text-[11px] text-neutral-500">{host.productionEnvironment} host</span>
          )}
          {host && (
            <LimitedList items={host.otherHosts} name={(o) => [o.host, ...o.environments]} noun="hosts">
              {(visible) => visible.map((o) => (
            <span key={o.host} className="block break-all pl-4 font-mono text-[11px] text-neutral-500" title="The same service as other environments' configuration names it">
              ↳ {o.host} <span className="font-sans text-neutral-400">({o.environments.join(', ')})</span>
            </span>
              ))}
            </LimitedList>
          )}
          {(host?.annotationCarriedFrom ?? []).length > 0 && (
            <span
              className="block pl-4 text-[11px] text-violet-700"
              title="Setting the production environment moved this host's calls here, so its conversation record is shown on this row. The original annotation is kept unchanged; an edit here saves to this row."
            >
              annotation carried from {host!.annotationCarriedFrom!.join(', ')}
              {annotation?.host === host!.host ? ' (this row has its own; showing it)' : ''}
            </span>
          )}
          {host?.groupingNote &&
            (host.productionEnvironment ? (
              <span className="block pl-4 text-[11px] text-amber-700">{host.groupingNote}</span>
            ) : (
              // No setting: the bar above says so once; each row says how it was grouped.
              <span className="block pl-4 text-[11px] text-neutral-400" title={host.groupingNote}>
                grouped by host as found
              </span>
            ))}
          {!host && <span className="block pl-4 text-[11px] text-neutral-500">no longer called — annotation kept</span>}
          {host?.requiresBackendChange && (
            <span className="block pl-4">
              {host.backendChangeOwner === 'this_migration' ? (
                <Pill
                  className="border-amber-200 bg-amber-50 text-amber-800"
                  title="A service inside this migration must change first: plan it with its callers, in the same wave or before"
                >
                  change a service in this migration
                </Pill>
              ) : (
                <Pill
                  className="border-red-200 bg-red-50 text-red-700"
                  title="Another team owns the service and must change it before callers can move: start the conversation now"
                >
                  another team must change their service
                </Pill>
              )}
            </span>
          )}
        </td>
        <td className="px-2 py-1.5">
          {host ? (
            host.classification === 'internal' ? (
              <>
                <Pill className="border-violet-200 bg-violet-50 text-violet-700">internal</Pill>
                <LimitedList items={servingRepos} name={(t) => t.repositorySlug} noun="repositories">
                  {(visible) => visible.map((t) => (
                  <button
                    key={t.repositoryId}
                    type="button"
                    onClick={() => onOpenRepository(t.repositoryId)}
                    className="block text-left text-[11px] text-violet-700 hover:underline"
                    title="Open the serving repository"
                  >
                    served by {t.repositorySlug}
                    {t.sameRepository ? ' (same repository)' : ''}
                  </button>
                  ))}
                </LimitedList>
              </>
            ) : (
              <Pill>external</Pill>
            )
          ) : (
            '—'
          )}
        </td>
        <td className="px-2 py-1.5">
          {host && (
            <LimitedList items={host.services} name={(s) => [s.path, s.contract]} noun="services">
              {(visible) => visible.map((s) => (
            <span key={`${s.path}|${s.contract}`} className="block font-mono text-[11px] text-neutral-700">
              {s.path || '(no path)'} {s.contract && <span className="text-neutral-400">{s.contract}</span>}
            </span>
              ))}
            </LimitedList>
          )}
        </td>
        <td className="px-2 py-1.5">
          {host && (
            <>
              <span className="font-medium text-neutral-800">{host.callingRepositoryCount}</span>
              <span className="block text-[11px] text-neutral-500">{host.callingRepositories.join(', ')}</span>
            </>
          )}
        </td>
        <td className="px-2 py-1.5">
          <div className="flex flex-wrap gap-1">
            {host?.bindings.map((b) => (
              <Pill key={b} className={b.toLowerCase().startsWith('nettcp') ? 'border-red-200 bg-red-50 text-red-700 font-medium' : ''}>
                {b}
              </Pill>
            ))}
            {host && host.bindings.length === 0 && <span className="text-[11px] text-neutral-400">{host.mechanisms.join(', ').replace(/_/g, ' ')}</span>}
          </div>
        </td>
        <td className="px-2 py-1.5">
          {host?.worstVerdict && <Pill className={VERDICT_STYLE[host.worstVerdict]}>{verdictLabel(host.worstVerdict)}</Pill>}
          {host?.underReview && host.underReview.length > 0 && (
            <Pill className={VERDICT_STYLE.under_review} title={`Matrix entries a probe contradicts, until a reviewer revises them: ${host.underReview.join(', ')}`}>
              {UNDER_REVIEW_LABEL}
            </Pill>
          )}
        </td>
        <AnnotationCells
          engagementId={engagementId}
          host={name}
          loopback={!!host?.loopback}
          repositories={repositories}
          annotation={annotation}
          onSaved={onSaved}
        />
      </tr>
      {expanded && host && (
        <tr className="border-b border-neutral-100 bg-neutral-50/60">
          <td colSpan={11} className="space-y-2 px-6 py-2 text-xs">
            <LimitedList items={host.backendChangeReasons} name={(r) => r} noun="reasons">
              {(visible) => visible.map((r) => (
              <p key={r} className="text-red-700">
                {r}
              </p>
              ))}
            </LimitedList>
            <LimitedList items={host.services} name={(s) => [s.path, s.contract, ...s.callingProjects]} noun="services">
              {(visibleServices) => (
            <table className="w-full text-left">
              <thead className="text-neutral-400">
                <tr>
                  {['Service', 'Contract', 'Ports', 'Bindings', 'Calling projects', 'Verdict', 'Served by'].map((h) => (
                    <th key={h} className="py-1 pr-3 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visibleServices.map((s) => (
                  <tr key={`${s.path}|${s.contract}`} className="align-top">
                    <td className="py-1 pr-3 font-mono">{s.path || '(no path)'}</td>
                    <td className="py-1 pr-3 font-mono">{s.contract ?? '—'}</td>
                    <td className="py-1 pr-3">{s.ports.join(', ') || '—'}</td>
                    <td className="py-1 pr-3">{s.bindings.join(', ') || s.mechanisms.join(', ').replace(/_/g, ' ')}</td>
                    <td className="py-1 pr-3 font-mono text-[11px]">
                      <LimitedList items={s.callingProjects} name={(p) => p} noun="projects">
                        {(visible) => visible.map((p) => (
                        <span key={p} className="block break-all">
                          {p}
                        </span>
                        ))}
                      </LimitedList>
                    </td>
                    <td className="py-1 pr-3">{s.worstVerdict && <Pill className={VERDICT_STYLE[s.worstVerdict]}>{verdictLabel(s.worstVerdict)}</Pill>}</td>
                    <td className="py-1 pr-3 text-[11px]">
                      <LimitedList items={s.internalTargets} name={(t) => [`${t.repositorySlug}:${t.projectPath}`, t.served]} noun="entry points" empty="—">
                        {(visible) => visible.map((t) => (
                            <span key={`${t.projectId}|${t.served}`} className="block">
                              <button type="button" onClick={() => onOpenRepository(t.repositoryId)} className="text-violet-700 hover:underline">
                                {t.repositorySlug}:{t.projectPath}
                              </button>{' '}
                              <span className="text-neutral-400">
                                {t.served} · entry point {t.entryPointId.slice(0, 10)}
                              </span>
                            </span>
                        ))}
                      </LimitedList>
                      {s.matchedBy.length > 0 && <span className="block text-neutral-400">matched by {s.matchedBy.join('; ')}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
              )}
            </LimitedList>
            <p>
              <span className="font-medium text-neutral-600">Verdict by environment: </span>
              {Object.entries(host.verdictByEnvironment).map(([env, v]) => (
                <span key={env} className="mr-2">
                  {env} <Pill className={VERDICT_STYLE[v]}>{verdictLabel(v)}</Pill>
                </span>
              ))}
            </p>
          </td>
        </tr>
      )}
    </Fragment>
  )
}

/** The tracker: owning team, conversation status, target date and notes,
 * edited in place and saved on change or blur. Keyed by host, so it survives
 * rescans (Part C4). */
function AnnotationCells({
  engagementId,
  host,
  loopback,
  repositories,
  annotation,
  onSaved,
}: {
  engagementId: string
  host: string
  loopback: boolean
  repositories: string[]
  annotation: EndpointAnnotation | undefined
  onSaved: () => void
}) {
  const { showToast } = useToast()
  const fromAnnotation = useCallback(
    () => ({
      owning_team: annotation?.owning_team ?? '',
      conversation_status: annotation?.conversation_status ?? ('not_started' as ConversationStatus),
      target_date: annotation?.target_date ?? '',
      notes: annotation?.notes ?? '',
      served_by_repository: annotation?.served_by_repository ?? '',
    }),
    [annotation],
  )
  const [draft, setDraft] = useState(fromAnnotation)
  useEffect(() => {
    setDraft(fromAnnotation())
  }, [fromAnnotation])

  async function save(next: typeof draft) {
    const current = fromAnnotation()
    const unchanged = (Object.keys(next) as (keyof typeof next)[]).every((k) => next[k] === current[k])
    if (unchanged) return
    try {
      // The PUT replaces the whole annotation: every field is sent.
      await putEndpointAnnotation(engagementId, host, {
        owning_team: next.owning_team || null,
        contact: annotation?.contact ?? null,
        conversation_status: next.conversation_status,
        target_date: next.target_date || null,
        notes: next.notes || null,
        served_by_repository: next.served_by_repository || null,
        updated_by: annotation?.updated_by ?? null,
      })
      onSaved()
    } catch {
      showToast('error', `Could not save the annotation for ${host}.`)
    }
  }

  const input = 'w-full min-w-0 rounded border border-neutral-200 px-1.5 py-1 text-xs focus:border-violet-400 focus:outline-none'
  return (
    <>
      <td className="px-2 py-1.5">
        <input
          aria-label={`Owning team for ${host}`}
          className={input}
          value={draft.owning_team}
          placeholder="team"
          onChange={(e) => setDraft({ ...draft, owning_team: e.target.value })}
          onBlur={(e) => save({ ...draft, owning_team: e.currentTarget.value })}
        />
      </td>
      <td className="px-2 py-1.5">
        <select
          aria-label={`Conversation status for ${host}`}
          className={input}
          value={draft.conversation_status}
          onChange={(e) => {
            const next = { ...draft, conversation_status: e.target.value as ConversationStatus }
            setDraft(next)
            save(next)
          }}
        >
          {Object.entries(STATUS_LABEL).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </td>
      <td className="px-2 py-1.5">
        <input
          type="date"
          aria-label={`Target date for ${host}`}
          className={input}
          value={draft.target_date}
          onChange={(e) => {
            const next = { ...draft, target_date: e.target.value }
            setDraft(next)
            save(next)
          }}
        />
      </td>
      <td className="px-2 py-1.5">
        <input
          aria-label={`Notes for ${host}`}
          className={input}
          value={draft.notes}
          placeholder="notes"
          title={annotation?.updated_at ? `Last updated ${new Date(annotation.updated_at).toLocaleString()}${annotation.updated_by ? ` by ${annotation.updated_by}` : ''}` : undefined}
          onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
          onBlur={(e) => save({ ...draft, notes: e.currentTarget.value })}
        />
      </td>
      <td className="px-2 py-1.5">
        {loopback ? (
          <span className="text-[11px] text-neutral-400" title="Local addresses are matched to the estate's routes without an annotation">
            matched locally
          </span>
        ) : (
          <select
            aria-label={`Repository serving ${host}`}
            title="The estate repository that serves this host: HTTP calls to it are matched against that repository's routes on the next run"
            className={input}
            value={draft.served_by_repository}
            onChange={(e) => {
              const next = { ...draft, served_by_repository: e.target.value }
              setDraft(next)
              save(next)
            }}
          >
            <option value="">not known</option>
            {repositories.map((slug) => (
              <option key={slug} value={slug}>
                {slug}
              </option>
            ))}
          </select>
        )}
      </td>
    </>
  )
}

// ---------- integration ----------

const MECHANISM_LABEL: Record<string, string> = { soap_client: 'SOAP', http_client: 'HTTP', grpc_client: 'gRPC' }

function site(s: { filePath: string | null; lineStart: number | null }) {
  return s.filePath ? `${s.filePath}${s.lineStart ? `:${s.lineStart}` : ''}` : '—'
}

/** Per application (project): the operations it calls, each with the entry
 * point it reaches or why none was found, and the operations of its that the
 * estate calls. An operation nothing in the estate calls is "no internal
 * caller found" — never unused: it may be called from outside the estate. */
function IntegrationView({ data, onOpenRepository }: { data: IntegrationMapArtifact; onOpenRepository: (repositoryId: string) => void }) {
  const [query, setQuery] = useState('')
  const [exposed, setExposed] = useState<'called' | 'all'>('called')
  const q = query.trim().toLowerCase()
  const apps = data.applications.filter((a) => {
    if (a.calls.length === 0 && (exposed === 'called' ? !a.exposes.some((e) => e.callers.length > 0) : a.exposes.length === 0)) return false
    if (!q) return true
    return (
      `${a.repositorySlug}:${a.projectPath}`.toLowerCase().includes(q) ||
      a.calls.some((c) => c.operation.toLowerCase().includes(q)) ||
      a.exposes.some((e) => e.operation.toLowerCase().includes(q))
    )
  })
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Pill className="border-violet-200 bg-violet-50 text-violet-700">{data.summary.edges} integration edges</Pill>
        <Pill>{data.summary.crossRepositoryEdges} cross-repository</Pill>
        <Pill>{data.summary.sameRepositoryEdges} same repository</Pill>
        <Pill className={data.summary.operationsUnmatched > 0 ? 'border-amber-200 bg-amber-50 text-amber-800' : ''}>
          {data.summary.operationsUnmatched} calls unmatched ({data.summary.operationsUnresolved} unresolved)
        </Pill>
        <Pill title="Entry points a call can reach: WCF and ASMX operations, HTTP actions, gRPC methods">
          {data.summary.entryPointsInternalCallerFound} of {data.summary.entryPoints} entry points have an internal caller
        </Pill>
        <label className="ml-auto flex items-center gap-1.5 text-[11px] text-neutral-500">
          Applications
          <select className="rounded border border-neutral-200 px-1 py-0.5 text-[11px]" value={exposed} onChange={(e) => setExposed(e.target.value as 'called' | 'all')}>
            <option value="called">that call, or are called</option>
            <option value="all">with any entry point</option>
          </select>
        </label>
        <input
          aria-label="Filter applications and operations"
          className="w-full rounded border border-neutral-200 px-2 py-1 text-xs sm:w-56"
          placeholder="filter application or operation"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <p className="text-xs text-neutral-500">
        Matched from what step 5 recorded each call site invoking to what step 4 found each entry point serving: SOAP by contract and operation, HTTP by verb and
        route template (on a local address, or a host annotated with its serving repository), gRPC by service and method. "No internal caller found" is not
        "unused" — callers outside the estate are not visible here.
      </p>
      {/* The filter above is this list's own, so the list is limited without a second filter box. */}
      <LimitedList
        items={apps}
        noun="applications"
        className="space-y-3"
        empty={<p className="rounded border border-neutral-200 bg-white px-4 py-6 text-sm text-neutral-500">No application matches.</p>}
      >
        {(visible) => visible.map((a) => (
          <ApplicationCard key={`${a.repositorySlug}:${a.projectPath}`} app={a} showUncalled={exposed === 'all'} onOpenRepository={onOpenRepository} />
        ))}
      </LimitedList>
    </div>
  )
}

function ApplicationCard({ app, showUncalled, onOpenRepository }: { app: IntegrationApplication; showUncalled: boolean; onOpenRepository: (repositoryId: string) => void }) {
  const called = app.exposes.filter((e) => e.callers.length > 0)
  const uncalled = app.exposes.filter((e) => e.callers.length === 0)
  const [showAll, setShowAll] = useState(false)
  return (
    <div className="rounded border border-neutral-200 bg-white">
      <div className="flex flex-wrap items-baseline gap-2 border-b border-neutral-100 px-3 py-2">
        <button type="button" onClick={() => onOpenRepository(app.repositoryId)} className="font-mono text-sm font-medium text-neutral-900 hover:text-violet-700 hover:underline break-all">
          {app.repositorySlug}:{app.projectPath}
        </button>
        <span className="text-[11px] text-neutral-500">
          calls {app.calls.length} operation{app.calls.length === 1 ? '' : 's'} · {called.length} of {app.exposes.length} of its entry points called from the estate
        </span>
      </div>
      <div className="grid gap-3 px-3 py-2 lg:grid-cols-2">
        <div className="min-w-0">
          <h4 className="text-[11px] font-medium uppercase tracking-wide text-neutral-400">Operations it calls</h4>
          <LimitedList
            items={app.calls}
            name={(c) => [c.operation, site(c.callSite), ...c.targets.map((t) => `${t.calleeRepositorySlug}:${t.calleeProjectPath}`)]}
            noun="calls"
            className="mt-1"
            empty={<p className="mt-1 text-xs text-neutral-500">No SOAP, HTTP or gRPC call recorded.</p>}
          >
            {(visibleCalls) => (
            <ul className="space-y-1.5 text-xs">
              {visibleCalls.map((c) => (
                <li key={`${site(c.callSite)}|${c.operation}|${c.invocationId}`} className="break-all">
                  <Pill>{MECHANISM_LABEL[c.mechanism] ?? c.mechanism}</Pill> <span className="font-mono text-neutral-800">{c.operation}</span>
                  <span className="block pl-1 font-mono text-[11px] text-neutral-400">{site(c.callSite)}</span>
                  <LimitedList items={c.targets} name={(t) => [`${t.calleeRepositorySlug}:${t.calleeProjectPath}`, t.served]} noun="targets">
                    {(visible) => visible.map((t) => (
                    <span key={t.entryPointId} className="block pl-1 text-[11px]">
                      → <span className="font-mono text-violet-700">{t.calleeRepositorySlug}:{t.calleeProjectPath}</span>{' '}
                      <span className="text-neutral-500">
                        {t.served} · {t.matchMethod.replace(/_/g, ' ')} · {Math.round(t.confidence * 100)}%
                      </span>
                      {t.sameRepository && <Pill className="ml-1">same repository</Pill>}
                    </span>
                    ))}
                  </LimitedList>
                  {c.unmatchedReason && <span className="block pl-1 text-[11px] text-amber-700">not matched: {c.unmatchedReason}</span>}
                </li>
              ))}
            </ul>
            )}
          </LimitedList>
        </div>
        <div className="min-w-0">
          <h4 className="text-[11px] font-medium uppercase tracking-wide text-neutral-400">Its operations others call</h4>
          {called.length === 0 && <p className="mt-1 text-xs text-neutral-500">{app.exposes.length === 0 ? 'No entry point a call can reach.' : 'No internal caller found for any of its entry points.'}</p>}
          <LimitedList
            items={called}
            name={(e) => [e.operation, ...e.callers.map((c) => `${c.callerRepositorySlug}:${c.callerProjectPath}`)]}
            noun="operations"
            className="mt-1"
          >
            {(visibleCalled) => (
          <ul className="space-y-1.5 text-xs">
            {visibleCalled.map((e) => (
              <li key={e.entryPointId} className="break-all">
                <span className="font-mono text-neutral-800">{e.operation}</span>{' '}
                <Pill className="border-violet-200 bg-violet-50 text-violet-700">
                  internal caller found{e.crossRepositoryCallerCount > 0 ? ` · ${e.crossRepositoryCallerCount} from other repositories` : ''}
                </Pill>
                <LimitedList items={e.callers} name={(c) => [`${c.callerRepositorySlug}:${c.callerProjectPath}`, site(c.callSite)]} noun="callers">
                  {(visible) => visible.map((c, i) => (
                  <span key={i} className="block pl-1 text-[11px] text-neutral-500">
                    ← <span className="font-mono">{c.callerRepositorySlug}:{c.callerProjectPath}</span> <span className="font-mono text-neutral-400">{site(c.callSite)}</span>
                    {c.sameRepository && <Pill className="ml-1">same repository</Pill>}
                  </span>
                  ))}
                </LimitedList>
              </li>
            ))}
          </ul>
            )}
          </LimitedList>
          {uncalled.length > 0 && (showUncalled || showAll) && (
            <LimitedList items={uncalled} name={(e) => e.operation} noun="operations" className="mt-1.5">
              {(visible) => (
            <ul className="space-y-0.5 text-xs">
              {visible.map((e) => (
                <li key={e.entryPointId} className="break-all text-neutral-500">
                  <span className="font-mono">{e.operation}</span>{' '}
                  <Pill title="Nothing in the estate calls it; callers outside the estate are not visible">
                    {e.matchable ? 'no internal caller found' : 'no internal caller found · not matchable'}
                  </Pill>
                </li>
              ))}
            </ul>
              )}
            </LimitedList>
          )}
          {uncalled.length > 0 && !showUncalled && (
            <button type="button" onClick={() => setShowAll((v) => !v)} className="mt-1 text-[11px] text-violet-700 hover:underline">
              {showAll ? 'Hide' : 'Show'} {uncalled.length} with no internal caller found
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ---------- packages ----------

function PackagesView({ data }: { data: PackageEstateArtifact }) {
  const [driftOnly, setDriftOnly] = useState(false)
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const rows = data.packages.filter(
    (p) => (!driftOnly || p.estateDrift) && (!query || p.packageId.toLowerCase().includes(query.toLowerCase())),
  )
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Pill>{data.summary.packages} packages</Pill>
        <Pill className="border-amber-200 bg-amber-50 text-amber-800" title="Used at more than one version across the estate">
          {data.summary.estateDrift} with estate drift
        </Pill>
        <Pill className="border-amber-200 bg-amber-50 text-amber-800" title="Repositories use different versions from each other">
          {data.summary.crossRepositoryDrift} differ between repositories
        </Pill>
        <label className="ml-auto flex items-center gap-1.5 text-[11px] text-neutral-500">
          <input type="checkbox" checked={driftOnly} onChange={(e) => setDriftOnly(e.target.checked)} />
          Estate drift only
        </label>
        <input
          aria-label="Filter packages"
          className="w-48 rounded border border-neutral-200 px-2 py-1 text-xs"
          placeholder="filter packages"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      {/* The filter above is this table's own, so the rows are limited without a second filter box. */}
      <LimitedList items={rows} noun="packages">
        {(visible) => (
      <div className="overflow-x-auto rounded border border-neutral-200 bg-white">
        <table className="w-full min-w-[900px] text-left text-xs">
          <thead className="border-b border-neutral-200 text-neutral-400">
            <tr>
              {['Package', 'Repositories', 'Projects', 'Versions in use', 'Recommended', 'Outcomes', 'Flags'].map((h) => (
                <th key={h} className="px-2 py-2 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((p) => (
              <Fragment key={p.packageId}>
                <tr className="border-b border-neutral-100 align-top">
                  <td className="px-2 py-1.5">
                    {p.breakingMembers.length > 0 ? (
                      <button type="button" onClick={() => setOpen((o) => ({ ...o, [p.packageId]: !o[p.packageId] }))} className="mr-1 text-neutral-400 hover:text-violet-700" aria-expanded={!!open[p.packageId]}>
                        {open[p.packageId] ? '▾' : '▸'}
                      </button>
                    ) : (
                      <span className="mr-1 inline-block w-[0.7em]" />
                    )}
                    <span className="font-medium text-neutral-800">{p.packageId}</span>
                  </td>
                  <td className="px-2 py-1.5">
                    <span className="font-medium">{p.repositoryCount}</span>
                    <span className="block text-[11px] text-neutral-500">{p.repositories.join(', ')}</span>
                  </td>
                  <td className="px-2 py-1.5">{p.projectCount}</td>
                  <td className="px-2 py-1.5">
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(p.versionsInUse).map(([v, n]) => (
                        <Pill key={v}>
                          {v} ×{n}
                        </Pill>
                      ))}
                    </div>
                    {p.estateDrift && (
                      <span className="mt-0.5 block text-[11px] text-amber-700">
                        estate drift{p.crossRepositoryDrift ? ' — repositories disagree' : ' — within one repository'}
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-1.5 font-mono">{p.recommendedVersion ?? '—'}</td>
                  <td className="px-2 py-1.5">
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(p.outcomes).map(([o, n]) => (
                        <Pill key={o} className={o === 'upgrade_breaking' ? 'border-amber-200 bg-amber-50 text-amber-800' : o === 'no_compatible_version' ? 'border-red-200 bg-red-50 text-red-700' : ''}>
                          {o.replace(/_/g, ' ')} ×{n}
                        </Pill>
                      ))}
                    </div>
                  </td>
                  <td className="px-2 py-1.5">
                    <div className="flex flex-wrap gap-1">
                      {p.flags.vulnerable && <Pill className="border-red-200 bg-red-50 text-red-700">vulnerable</Pill>}
                      {p.flags.deprecated && <Pill className="border-amber-200 bg-amber-50 text-amber-800">deprecated</Pill>}
                      {p.flags.notInClientFeed && <Pill className="border-amber-200 bg-amber-50 text-amber-800">not in client feed</Pill>}
                    </div>
                  </td>
                </tr>
                {open[p.packageId] && (
                  <tr className="border-b border-neutral-100 bg-neutral-50/60">
                    <td colSpan={7} className="px-6 py-2">
                      <p className="text-[11px] font-medium uppercase tracking-wide text-neutral-400">Changed members hit anywhere in the estate</p>
                      <LimitedList
                        items={p.breakingMembers}
                        name={(m) => [`${m.type ?? ''}${m.member ? `.${m.member}` : ''}`, m.change?.replace(/_/g, ' ')]}
                        noun="members"
                        className="mt-0.5"
                      >
                        {(visibleMembers) => (
                      <ul className="space-y-0.5">
                        {visibleMembers.map((m, i) => (
                          <li key={i} className="font-mono text-[11px] text-neutral-700">
                            <span className="text-neutral-400">{m.change?.replace(/_/g, ' ')}</span> {m.type}
                            {m.member ? `.${m.member}` : ''}
                          </li>
                        ))}
                      </ul>
                        )}
                      </LimitedList>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
        )}
      </LimitedList>
    </div>
  )
}

// ---------- dependencies ----------

function DependenciesView({ data }: { data: DependencyGraphArtifact }) {
  const cross = data.edges.filter((e) => e.crossRepository)
  const ref = (p: { repositorySlug: string; projectPath: string }) => `${p.repositorySlug}:${p.projectPath}`
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Pill>{data.summary.projects} projects</Pill>
        <Pill>{data.summary.edges} dependencies</Pill>
        <Pill>{data.summary.crossRepositoryEdges} cross-repository</Pill>
        <Pill>{data.summary.sharedLibraries} shared libraries</Pill>
        <Pill className={data.summary.cycles > 0 ? 'border-red-200 bg-red-50 text-red-700' : ''}>{data.summary.cycles} cycles</Pill>
        <Pill>{data.summary.originReconciliations} origin reconciliations</Pill>
      </div>
      <Section
        title="Shared libraries"
        empty="No project is depended on from two or more repositories."
        items={data.sharedLibraries}
        name={(s) => ref(s.project)}
        noun="shared libraries"
      >
        {(visible) => visible.map((s) => (
          <li key={s.project.projectId}>
            <span className="font-mono text-neutral-800">{ref(s.project)}</span>{' '}
            <span className="text-neutral-500">
              used from {s.consumerRepositoryCount} repositories, {s.consumerProjectCount} projects — migrates first; a breaking change reaches every consumer
            </span>
          </li>
        ))}
      </Section>
      <Section
        title="Cycles"
        empty="No cycles: every dependency chain has a project that can migrate first."
        items={data.cycles}
        name={(c) => c.members.map(ref)}
        noun="cycles"
      >
        {(visible) => visible.map((c) => (
          <li key={c.cycleId}>
            {c.crossRepository && <Pill className="border-red-200 bg-red-50 text-red-700">across repositories</Pill>}{' '}
            <span className="font-mono text-neutral-800">{c.members.map(ref).join(' → ')}</span>
          </li>
        ))}
      </Section>
      <Section
        title="Cross-repository dependencies"
        empty="No package reference names a project in another repository of the engagement."
        items={cross}
        name={(e) => [ref(e.from), ref(e.to), e.via]}
        noun="dependencies"
      >
        {(visible) => visible.map((e) => (
          <li key={`${e.from.projectId}|${e.to.projectId}|${e.kind}`}>
            <span className="font-mono">{ref(e.from)}</span> → <span className="font-mono">{ref(e.to)}</span>{' '}
            <span className="text-neutral-500">
              via package {e.via}
              {e.clientFeed ? ' (client feed)' : ''}
            </span>
          </li>
        ))}
      </Section>
      <Section
        title="Origin reconciliations"
        empty="No framework-origin entry point turned out to be declared in another repository."
        items={data.originReconciliations}
        name={(r) => [r.entryPointId.slice(0, 12), r.originalOrigin, r.reconciledOrigin, r.reason]}
        noun="origin reconciliations"
      >
        {(visible) => visible.map((r) => (
          <li key={r.entryPointId}>
            <span className="font-mono">{r.entryPointId.slice(0, 12)}</span> {r.originalOrigin} → {r.reconciledOrigin}: <span className="text-neutral-500">{r.reason}</span>
          </li>
        ))}
      </Section>
    </div>
  )
}

/** A titled list of the dependency graph: limited, with a filter on the names its rows show. */
function Section<T>({
  title,
  empty,
  items,
  name,
  noun,
  children,
}: {
  title: string
  empty: string
  items: T[]
  name: (item: T) => string | (string | null)[]
  noun: string
  children: (visible: T[]) => ReactNode
}) {
  return (
    <div className="rounded border border-neutral-200 bg-white px-3 py-2">
      <h3 className="text-sm font-semibold text-neutral-900">
        {title} <span className="font-normal text-neutral-400">({items.length})</span>
      </h3>
      <LimitedList items={items} name={name} noun={noun} className="mt-1" empty={<p className="mt-1 text-xs text-neutral-500">{empty}</p>}>
        {(visible) => <ul className="space-y-1 break-all text-xs">{children(visible)}</ul>}
      </LimitedList>
    </div>
  )
}

// ---------- context ----------

/** The C4 system landscape drawn from the same model the DSL was written
 * from: the estate's repositories on the left, external hosts on the right,
 * relationships as labelled arrows. The DSL itself is downloadable. */
function ContextView({ data }: { data: ContextMapArtifact }) {
  const [showDsl, setShowDsl] = useState(false)
  const repos = data.systems.filter((s) => s.kind === 'repository')
  const externals = data.systems.filter((s) => s.kind === 'external')
  const rowH = 64
  const height = Math.max(repos.length, externals.length) * rowH + 60
  const width = 900
  const boxW = 220
  const leftX = 40
  const rightX = width - boxW - 40
  const yOf = (list: typeof repos, id: string) => 40 + list.findIndex((s) => s.id === id) * rowH
  const internalRels = data.relationships.filter((r) => repos.some((s) => s.id === r.to))

  function download() {
    const blob = new Blob([data.dsl], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `context-map-${data.engagementId}.dsl`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Pill>{repos.length} repositories</Pill>
        <Pill>{externals.length} external systems</Pill>
        <Pill>{internalRels.length} repository-to-repository relationships</Pill>
        <button type="button" onClick={download} className="ml-auto rounded border border-neutral-300 px-2.5 py-1 text-xs text-neutral-700 hover:bg-neutral-50">
          Download Structurizr DSL
        </button>
        <button type="button" onClick={() => setShowDsl((v) => !v)} className="rounded border border-neutral-300 px-2.5 py-1 text-xs text-neutral-700 hover:bg-neutral-50">
          {showDsl ? 'Hide DSL' : 'Show DSL'}
        </button>
      </div>
      <div className="overflow-x-auto rounded border border-neutral-200 bg-white">
        <svg viewBox={`0 0 ${width} ${height}`} className="min-w-[700px]" role="img" aria-label="System landscape of the estate and the external systems it calls">
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#737373" />
            </marker>
          </defs>
          <text x={leftX} y={22} className="fill-neutral-500 text-[11px]">
            Engagement estate
          </text>
          <text x={rightX} y={22} className="fill-neutral-500 text-[11px]">
            External systems
          </text>
          {data.relationships.map((r, i) => {
            const fromY = yOf(repos, r.from) + 22
            const toIsRepo = repos.some((s) => s.id === r.to)
            const toY = (toIsRepo ? yOf(repos, r.to) : yOf(externals, r.to)) + 22
            const x1 = leftX + boxW
            const x2 = toIsRepo ? leftX + boxW : rightX
            const path = toIsRepo
              ? `M ${x1} ${fromY} C ${x1 + 80} ${fromY}, ${x2 + 80} ${toY}, ${x2} ${toY}`
              : `M ${x1} ${fromY} L ${x2} ${toY}`
            return (
              <g key={i}>
                <path d={path} fill="none" stroke="#a3a3a3" strokeWidth={1.2} markerEnd="url(#arrow)" />
                <text x={(x1 + x2) / 2 + (toIsRepo ? 60 : 0)} y={(fromY + toY) / 2 - 4} textAnchor="middle" className="fill-neutral-500 text-[10px]">
                  {r.label}
                </text>
              </g>
            )
          })}
          {repos.map((s, i) => (
            <g key={s.id}>
              <rect x={leftX} y={40 + i * rowH} width={boxW} height={44} rx={4} fill="#6d28d9" />
              <text x={leftX + boxW / 2} y={40 + i * rowH + 27} textAnchor="middle" className="fill-white text-[12px] font-medium">
                {s.name}
              </text>
            </g>
          ))}
          {externals.map((s, i) => (
            <g key={s.id}>
              <rect
                x={rightX}
                y={40 + i * rowH}
                width={boxW}
                height={44}
                rx={4}
                fill="#737373"
                stroke={s.requiresBackendChange ? '#b91c1c' : 'none'}
                strokeWidth={2}
                strokeDasharray={s.requiresBackendChange ? '4 3' : undefined}
              />
              <text x={rightX + boxW / 2} y={40 + i * rowH + 22} textAnchor="middle" className="fill-white text-[12px] font-medium">
                {s.name}
              </text>
              {s.loopback && (
                <text x={rightX + boxW / 2} y={40 + i * rowH + 36} textAnchor="middle" className="fill-neutral-200 text-[10px]">
                  development address
                </text>
              )}
            </g>
          ))}
        </svg>
      </div>
      {internalRels.length === 0 && (
        <p className="text-xs text-neutral-500">
          No repository calls another repository of the estate. Calls a repository makes to its own services are in the endpoint register as internal hosts, not
          drawn here.
        </p>
      )}
      {showDsl && <pre className="max-h-96 overflow-auto rounded border border-neutral-200 bg-neutral-50 p-3 font-mono text-[11px] text-neutral-700">{data.dsl}</pre>}
    </div>
  )
}
