import { Fragment, useEffect, useState } from 'react'
import { soapCompatibilityCsvUrl } from '../api/estate'
import type { MatrixProbe, RuntimeVerdict, SoapBackendHost, SoapCompatibilityArtifact, SoapEnvironment } from '../types/estate'
import { UNDER_REVIEW, UNDER_REVIEW_LABEL } from '../types/estate'

// The Estate tab's SOAP backend compatibility report — 31-DEPENDENCY-AND-CONTEXT-MAP.md
// Part J. Per backend host, each calling application per environment: binding,
// security, both verdicts (runtime: the target .NET's WCF client; platform:
// Linux), what must change and who changes it, and the probes recorded on the
// matrix entries behind each verdict, with the WCF client version their evidence
// covers. A verdict resting on an entry a probe contradicts is shown as under
// review, never as that verdict, and counted apart. A draft until a person has
// confirmed every entry, none is contradicted, and no evidence is older than the
// WCF client the engagement targets.

const RUNTIME_STYLE: Record<RuntimeVerdict, string> = {
  unsupported: 'border-red-200 bg-red-50 text-red-700',
  unknown: 'border-neutral-300 bg-neutral-100 text-neutral-600',
  not_assessed: 'border-neutral-300 bg-neutral-100 text-neutral-600',
  supported_with_caveat: 'border-amber-200 bg-amber-50 text-amber-800',
  supported: 'border-teal-200 bg-teal-50 text-teal-700',
  under_review: 'border-violet-300 bg-violet-50 text-violet-800',
}

const PLATFORM_STYLE: Record<string, string> = {
  incompatible: 'border-red-200 bg-red-50 text-red-700',
  requires_change: 'border-amber-200 bg-amber-50 text-amber-800',
  unknown: 'border-neutral-300 bg-neutral-100 text-neutral-600',
  compatible: 'border-teal-200 bg-teal-50 text-teal-700',
  under_review: 'border-violet-300 bg-violet-50 text-violet-800',
}

function verdictLabel(verdict: string): string {
  return verdict === UNDER_REVIEW ? UNDER_REVIEW_LABEL : verdict.replaceAll('_', ' ')
}

/** Under each verdict: unconfirmed, contradicted, or evidence older than the targeted WCF client. */
function EntryFlags({ live, target }: { live: SoapEnvironment['runtime'] | SoapEnvironment['platform']; target: string | null }) {
  return (
    <>
      {live.matrixConfirmed === false && live.verdict !== UNDER_REVIEW && (
        <span className="mt-0.5 block text-[10px] font-medium text-amber-700">matrix entry unconfirmed</span>
      )}
      {live.evidenceMissing && <span className="mt-0.5 block text-[10px] font-semibold text-red-700">evidence missing</span>}
      {live.evidencePredatesTarget && (
        <span className="mt-0.5 block text-[10px] font-medium text-amber-700">
          evidence covers WCF {live.evidenceCovers?.wcfClient}, older than {target}: re-probe
        </span>
      )}
    </>
  )
}

const WHO_LABEL = { we: 'we change it', backend_owner: "backend's owner", we_or_backend_owner: "we or the backend's owner" } as const

const PROBE_STYLE: Record<string, string> = {
  passed: 'text-teal-700',
  failed: 'text-red-700',
  error: 'text-red-700',
  not_probed: 'text-neutral-500',
}

function MatrixEntry({ label, live }: { label: string; live: SoapEnvironment['runtime'] | SoapEnvironment['platform'] }) {
  if (!live.matrixEntry) return null
  return (
    <p>
      <span className="text-neutral-400">{label} matrix entry: </span><span className="font-mono">{live.matrixEntry}</span>
      {live.matrixConfirmed
        ? ` — confirmed by ${live.confirmedBy ?? '?'} on ${live.confirmedOn ?? '?'}${live.confirmationSource === 'engagement' ? ', in this engagement on its own evidence' : ''}`
        : ' — not yet confirmed by a person'}
      {live.evidenceMissing && <span className="block font-semibold text-red-700">evidence missing: this engagement's evidence is gone or no longer matches its hash</span>}
      {live.sources.length > 0 && <> · sources: {live.sources.join(', ')}</>}
      {live.evidenceCovers
        ? ` · evidence covers WCF client ${live.evidenceCovers.wcfClient} on .NET ${live.evidenceCovers.runtimes.join(', ')}`
        : ' · no probe evidence'}
      {live.unrevisedVerdict && (
        <span className="block font-medium text-violet-800">
          {UNDER_REVIEW_LABEL}: the entry says {live.unrevisedVerdict.replaceAll('_', ' ')}, and a probe disagrees. A reviewer revises it.
        </span>
      )}
    </p>
  )
}

/** A probe's identity: its evidence path, its reference to a client engagement's evidence, or its reason. */
function probeKey(probe: MatrixProbe): string {
  return probe.evidence ?? (probe.evidenceRef ? `${probe.evidenceRef.engagement}/${probe.evidenceRef.id}` : probe.reason ?? '')
}

/** The probes behind an environment's two entries, once each: one probe is recorded on both. */
function Probes({ env }: { env: SoapEnvironment }) {
  const seen = new Set<string>()
  const probes: MatrixProbe[] = []
  for (const probe of [...env.runtime.probes, ...env.platform.probes]) {
    const key = probeKey(probe)
    if (seen.has(key)) continue
    seen.add(key)
    probes.push(probe)
  }
  const contradictions = [...env.runtime.probeContradictions, ...env.platform.probeContradictions]
  if (probes.length === 0) return <p><span className="text-neutral-400">Probes: </span>none recorded yet</p>
  return (
    <div>
      <span className="text-neutral-400">Probes (.NET 10 client in a Linux container, against a real service):</span>
      <ul className="ml-3 list-disc">
        {probes.map((probe) => (
          <li key={probeKey(probe)}>
            {probe.outcome === 'not_probed' ? (
              <span className={PROBE_STYLE.not_probed}>
                not probed: {probe.reason}
                {probe.openItem && <span className="block text-amber-800">Open item: {probe.openItem}</span>}
              </span>
            ) : (
              <>
                <span className="font-mono">{probe.scenario}</span> on {probe.probedOn}:{' '}
                <span className={`font-medium ${PROBE_STYLE[probe.outcome] ?? ''}`}>{probe.outcome}</span>
                {probe.attribution === 'platform' && ' (passed on Windows with the same client: a Linux failure)'} — {probe.summary}
                <span className="block font-mono text-[10px] text-neutral-400">
                  {probe.evidenceRef
                    ? `${probe.errorType ?? ''} · WCF ${probe.covers?.wcfClient ?? '?'} on .NET ${probe.covers?.runtime ?? '?'} · evidence ${probe.evidenceRef.id}, kept with engagement ${probe.evidenceRef.engagement}`
                    : `${probe.service} · ${probe.client?.os} · ${probe.client?.framework} · WCF ${probe.client?.wcfClient?.split('+')[0]} · ${probe.evidence}`}
                </span>
              </>
            )}
          </li>
        ))}
      </ul>
      {contradictions.map((c) => (
        <p key={c} className="font-medium text-red-700">Contradicts its matrix entry: {c}</p>
      ))}
    </div>
  )
}

function Chip({ children, className, title }: { children: React.ReactNode; className: string; title?: string }) {
  return (
    <span className={`whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] ${className}`} title={title}>
      {children}
    </span>
  )
}

function Owner({ host }: { host: SoapBackendHost }) {
  return host.backendOwner === 'this_migration' ? (
    <span className="text-xs text-neutral-700">this migration — served by {host.servedBy.join(', ')}</span>
  ) : (
    <span className="text-xs text-neutral-700">another team{host.owningTeam ? `: ${host.owningTeam}` : ''}</span>
  )
}

function HostTable({ host, target, highlight }: { host: SoapBackendHost; target: string | null; highlight: string | null }) {
  const [open, setOpen] = useState<string | null>(null)
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1000px] text-left text-xs">
        <thead className="text-neutral-400">
          <tr>
            {['Calling application', 'Environment', 'Binding', 'Security mode', 'Credential', 'Runtime', 'Platform', 'What must change', 'Who'].map((h) => (
              <th key={h} className="py-1 pr-3 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {host.callers.map((caller) =>
            caller.environments.map((env, index) => {
              const key = `${caller.invocationId}|${env.environment}|${env.sourceFile}`
              return (
                <Fragment key={key}>
                  <tr
                    id={index === 0 ? `soap-call-${caller.invocationId}` : undefined}
                    className={`border-t border-neutral-100 align-top ${highlight === caller.invocationId ? 'bg-violet-50' : ''}`}
                  >
                    <td className="py-1 pr-3">
                      {index === 0 ? (
                        <>
                          <span className="font-medium text-neutral-800">{caller.application}</span>
                          <span className="block font-mono text-[11px] text-neutral-500">{caller.contract}</span>
                          <span className="block font-mono text-[10px] text-neutral-400">{caller.projectPath}</span>
                        </>
                      ) : null}
                    </td>
                    <td className="py-1 pr-3">
                      <button type="button" onClick={() => setOpen(open === key ? null : key)} aria-expanded={open === key}
                        className="text-left text-neutral-800 hover:text-violet-700">
                        {env.environment}
                      </button>
                      <span className="block break-all font-mono text-[10px] text-neutral-400">{env.address}</span>
                    </td>
                    <td className="py-1 pr-3 font-mono">{env.binding}</td>
                    <td className="py-1 pr-3">
                      {env.securityMode}
                      {env.securitySource === 'binding_default' && <span className="block text-[10px] text-neutral-400">binding default</span>}
                    </td>
                    <td className="py-1 pr-3">{env.credentialType}</td>
                    <td className="py-1 pr-3">
                      <Chip className={RUNTIME_STYLE[env.runtime.verdict]}>{verdictLabel(env.runtime.verdict)}</Chip>
                      <EntryFlags live={env.runtime} target={target} />
                    </td>
                    <td className="py-1 pr-3">
                      {env.platform.verdict && <Chip className={PLATFORM_STYLE[env.platform.verdict] ?? PLATFORM_STYLE.unknown}>{verdictLabel(env.platform.verdict)}</Chip>}
                      <EntryFlags live={env.platform} target={target} />
                    </td>
                    <td className="py-1 pr-3 text-neutral-700">
                      {env.changes.length === 0 ? (
                        env.underReview && env.underReview.length > 0
                          ? <span className="text-violet-800">under review: what must change waits for the revised entry</span>
                          : <span className="text-neutral-400">no change</span>
                      ) : (
                        <ul className="space-y-0.5">{env.changes.map((c, i) => <li key={i}>{c.change}</li>)}</ul>
                      )}
                    </td>
                    <td className="py-1 text-neutral-700">
                      <ul className="space-y-0.5">{env.changes.map((c, i) => <li key={i} className="whitespace-nowrap">{WHO_LABEL[c.who]}</li>)}</ul>
                    </td>
                  </tr>
                  {open === key && (
                    <tr className="bg-neutral-50/60 text-[11px]">
                      <td />
                      <td colSpan={8} className="space-y-1 py-2 pr-2">
                        <p><span className="text-neutral-400">Runtime: </span>{env.runtime.reasons.join(' · ')}</p>
                        <MatrixEntry label="Runtime" live={env.runtime} />
                        <p><span className="text-neutral-400">Platform: </span>{env.platform.reasons.join(' · ')}</p>
                        <MatrixEntry label="Platform" live={env.platform} />
                        <Probes env={env} />
                        {env.changes.filter((c) => c.note).map((c, i) => (
                          <p key={i}><span className="text-neutral-400">Note: </span>{c.note}</p>
                        ))}
                        <p className="text-neutral-400">
                          {env.sourceFile}
                          {env.deployParameter ? ` · SetParameters ${env.deployParameter}` : ''}
                        </p>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            }),
          )}
        </tbody>
      </table>
    </div>
  )
}

export function SoapCompatibilityView({
  data,
  engagementId,
  focusInvocationId = null,
  onFocusShown,
}: {
  data: SoapCompatibilityArtifact | undefined
  engagementId: string
  /** A call opened from its repository page: scrolled to and highlighted. */
  focusInvocationId?: string | null
  onFocusShown?: () => void
}) {
  const [highlight] = useState(focusInvocationId)
  useEffect(() => {
    if (!data || !highlight) return
    // After the page has laid out: the tab's other content settles a moment later, so once more then.
    const scroll = () => document.getElementById(`soap-call-${highlight}`)?.scrollIntoView({ block: 'center' })
    const frame = requestAnimationFrame(scroll)
    const settle = window.setTimeout(scroll, 400)
    onFocusShown?.()
    return () => {
      cancelAnimationFrame(frame)
      window.clearTimeout(settle)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, highlight])
  if (!data) {
    return <p className="text-sm text-neutral-400">No SOAP compatibility report yet: run the estate consolidation.</p>
  }
  const chart = data.matrix.sources.find((s) => s.id.startsWith('chart-'))
  return (
    <div className="space-y-4 text-sm">
      {!data.matrix.readyForClient && (
        <div className="rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
          <span className="font-semibold">Draft — not for the client yet.</span> The verdicts rest on{' '}
          {data.matrix.entriesUsed.length} WCF client matrix entr{data.matrix.entriesUsed.length === 1 ? 'y' : 'ies'};{' '}
          {data.matrix.unconfirmedEntries.length} {data.matrix.unconfirmedEntries.length === 1 ? 'has' : 'have'} not been confirmed by a person
          {data.matrix.contradictedEntries.length > 0 && <>, a probe contradicts {data.matrix.contradictedEntries.length}</>}
          {data.matrix.evidencePredatesTarget.length > 0 && (
            <>, {data.matrix.evidencePredatesTarget.length} rest on evidence older than WCF client {data.matrix.targetWcfClientVersion}</>
          )}
          {data.matrix.evidenceMissingEntries.length > 0 && <>, {data.matrix.evidenceMissingEntries.length} rest on evidence that is missing</>}
          {Object.keys(data.matrix.newerMatrices).length > 0 && <>, and this run used an older matrix than the newest: rescan</>}.
          Review each with its probe results, then confirm or revise it in{' '}
          <span className="font-mono">steps/step-003-fingerprinting/schemas/wcf-client-support-{data.matrix.version}.json</span> or{' '}
          <span className="font-mono">wcf-client-platform-{data.matrix.platformVersion}.json</span> (confirmation.status, by, on) by pull request.
          <span className="mt-1 block font-mono text-[10px] text-amber-800">{data.matrix.unconfirmedEntries.join(' · ')}</span>
          {data.matrix.contradictedEntries.length > 0 && (
            <span className="mt-1 block font-mono text-[10px] text-violet-800">{UNDER_REVIEW_LABEL}: {data.matrix.contradictedEntries.join(' · ')}</span>
          )}
          {data.matrix.evidenceMissingEntries.length > 0 && (
            <span className="mt-1 block font-mono text-[10px] text-red-700">evidence missing: {data.matrix.evidenceMissingEntries.join(' · ')}</span>
          )}
          {data.matrix.evidencePredatesTarget.length > 0 && (
            <span className="mt-1 block font-mono text-[10px] text-amber-800">re-probe: {data.matrix.evidencePredatesTarget.join(' · ')}</span>
          )}
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-neutral-500">
          {data.summary.hosts} SOAP backend(s) · {data.summary.runtimeUnsupported} with a call the target's WCF client does not support ·{' '}
          {data.summary.platformIncompatible} incompatible with Linux · {data.summary.backendOwnerMustChange} need their owner to change
          {' · '}{data.summary.underReview ?? 0} {UNDER_REVIEW_LABEL}, counted apart
          <span className="block text-neutral-400">
            Target WCF client {data.matrix.targetWcfClientVersion ?? '?'}
            {data.matrix.targetWcfClientVersionSource === 'matrix' ? " (the matrices' version for the target framework)" : ' (set for this engagement)'}
            {' · '}{data.matrix.unprobedEntries.length} of {data.matrix.entriesUsed.length} entries have no probe evidence
          </span>
          {chart && (
            <span className="block text-neutral-400">
              Runtime rules: WCF client support matrix {data.matrix.version}, from{' '}
              <a href={chart.url} target="_blank" rel="noreferrer" className="text-violet-700 hover:underline">{chart.title} {chart.version}</a>
              {chart.committedOn ? ` (last changed ${chart.committedOn})` : ''} and the dotnet/wcf release notes. Platform rules: WCF client
              platform matrix {data.matrix.platformVersion}, keyed by binding, security mode and credential.
            </span>
          )}
        </p>
        <a href={soapCompatibilityCsvUrl(engagementId)} className="rounded border border-neutral-300 bg-white px-2 py-1 text-xs text-neutral-700 hover:bg-neutral-50">
          Export CSV{data.matrix.readyForClient ? '' : ' (draft)'}
        </a>
      </div>
      {data.hosts.map((host) => (
        <section key={host.host} className="rounded border border-neutral-200 p-3">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <h4 className="font-mono text-sm text-neutral-800">{host.host}</h4>
            <Chip className={RUNTIME_STYLE[host.worstRuntime]}>runtime: {verdictLabel(host.worstRuntime)}</Chip>
            <Chip className={PLATFORM_STYLE[host.worstPlatform] ?? PLATFORM_STYLE.unknown}>platform: {verdictLabel(host.worstPlatform)}</Chip>
            {(host.underReview ?? 0) > 0 && (
              <Chip className={PLATFORM_STYLE.under_review}>{host.underReview} {UNDER_REVIEW_LABEL}</Chip>
            )}
            <span className="text-xs text-neutral-400">backend owner:</span>
            <Owner host={host} />
          </div>
          <HostTable host={host} target={data.matrix.targetWcfClientVersion} highlight={highlight} />
        </section>
      ))}
    </div>
  )
}
