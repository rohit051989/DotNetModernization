import { Fragment, useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import { getRepositorySoapCompatibility } from '../../api/surface'
import type { RepositorySoap, SoapVerdictLive } from '../../types/surface'
import { UNDER_REVIEW, UNDER_REVIEW_LABEL } from '../../types/estate'

// The repository's own view of the SOAP backend compatibility report
// (31-DEPENDENCY-AND-CONTEXT-MAP.md Part J): each used SOAP client, per
// environment, with both verdicts and whether a person has confirmed the matrix
// entry each rests on. Read from this repository's scan, so a rescan updates it
// at once; the estate report is rebuilt only by the estate consolidation, and the
// panel says plainly when that has not run since the last scan.

interface RepositorySoapPanelProps {
  repositoryId: string
  refreshToken: number
  /** Opens the call's row in the Estate tab's SOAP compatibility report. */
  onOpenEstateSoap?: (invocationId: string) => void
}

const STYLE: Record<string, string> = {
  unsupported: 'border-red-200 bg-red-50 text-red-700',
  incompatible: 'border-red-200 bg-red-50 text-red-700',
  requires_change: 'border-amber-200 bg-amber-50 text-amber-800',
  supported_with_caveat: 'border-amber-200 bg-amber-50 text-amber-800',
  unknown: 'border-neutral-300 bg-neutral-100 text-neutral-600',
  not_assessed: 'border-neutral-300 bg-neutral-100 text-neutral-600',
  supported: 'border-teal-200 bg-teal-50 text-teal-700',
  compatible: 'border-teal-200 bg-teal-50 text-teal-700',
  under_review: 'border-violet-300 bg-violet-50 text-violet-800',
}

function Verdict({ live }: { live: SoapVerdictLive }) {
  const verdict = live.verdict ?? 'unknown'
  const label = verdict === UNDER_REVIEW ? UNDER_REVIEW_LABEL : verdict.replaceAll('_', ' ')
  const confirmation = live.evidenceMissing
    ? 'evidence missing'
    : live.matrixConfirmed === null
      ? 'no matrix entry'
      : live.matrixConfirmed
        ? `confirmed by ${live.confirmedBy ?? '?'} (${live.decision ?? 'no decision'}${live.confirmationSource === 'engagement' ? ', this engagement' : ''})`
        : 'unconfirmed'
  return (
    <div title={live.matrixEntry ?? undefined}>
      <span className={`whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] ${STYLE[verdict] ?? STYLE.unknown}`}>{label}</span>
      <span className={`mt-0.5 block text-[10px] ${live.evidenceMissing ? 'font-semibold text-red-700' : live.matrixConfirmed ? 'text-neutral-500' : 'font-medium text-amber-700'}`}>{confirmation}</span>
      {live.unrevisedVerdict && <span className="block text-[10px] text-violet-800">entry says {live.unrevisedVerdict.replaceAll('_', ' ')}</span>}
      {live.evidencePredatesTarget && <span className="block text-[10px] font-medium text-amber-700">evidence older than the targeted WCF client</span>}
    </div>
  )
}

export function RepositorySoapPanel({ repositoryId, refreshToken, onOpenEstateSoap }: RepositorySoapPanelProps) {
  const [data, setData] = useState<RepositorySoap | null>(null)
  const [notScanned, setNotScanned] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    setNotScanned(false)
    setFailed(false)
    getRepositorySoapCompatibility(repositoryId)
      .then((result) => {
        if (!cancelled) setData(result)
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 409) setNotScanned(true)
        else setFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [repositoryId, refreshToken])

  if (notScanned || (data && data.calls.length === 0 && data.unused_count === 0)) return null
  return (
    <section aria-labelledby="soap-compatibility-heading" className="min-w-0">
      <h3 id="soap-compatibility-heading" className="mb-2 text-sm font-semibold text-neutral-800">
        SOAP compatibility
      </h3>
      {failed && <p className="text-xs text-red-700">Could not load this repository's SOAP compatibility.</p>}
      {data && (
        <div className="space-y-2 text-xs">
          {data.estate_note && (
            <p className={`rounded border px-2 py-1.5 ${data.estate_stale ? 'border-amber-300 bg-amber-50 text-amber-900' : 'border-neutral-200 text-neutral-600'}`}>
              {data.estate_note}
            </p>
          )}
          <p className="text-neutral-500">
            {data.calls.length} SOAP call{data.calls.length === 1 ? '' : 's'}, both verdicts per environment, from the last scan
            {data.scanned_at ? ` (${new Date(data.scanned_at).toLocaleString()})` : ''}; matrix confirmations read live. Target WCF client{' '}
            {data.target_wcf_client_version ?? '?'}.
            {data.unused_count > 0 && ` ${data.unused_count} unused client${data.unused_count === 1 ? '' : 's'} not listed.`}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left">
              <thead className="text-neutral-400">
                <tr>
                  {['SOAP call', 'Environment', 'Binding', 'Security', 'Credential', 'Runtime', 'Platform (Linux)', 'Estate report'].map((h) => (
                    <th key={h} className="py-1 pr-3 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.calls.map((call) => (
                  <Fragment key={call.invocationId}>
                    {call.environments.map((env, index) => (
                      <tr key={`${env.environment}|${env.sourceFile}`} className={`align-top ${index === 0 ? 'border-t border-neutral-100' : ''}`}>
                        <td className="py-1 pr-3">
                          {index === 0 && (
                            <>
                              <span className="font-medium text-neutral-800">{call.contract ?? call.clientType ?? 'SOAP client'}</span>
                              <span className="block break-all font-mono text-[10px] text-neutral-500">{call.endpoint}</span>
                              <span className="block font-mono text-[10px] text-neutral-400">{call.projectPath}</span>
                            </>
                          )}
                        </td>
                        <td className="py-1 pr-3">
                          {env.environment}
                          <span className="block break-all font-mono text-[10px] text-neutral-400">{env.address}</span>
                        </td>
                        <td className="py-1 pr-3 font-mono">{env.binding}</td>
                        <td className="py-1 pr-3">
                          {env.securityMode}
                          {env.securitySource === 'binding_default' && <span className="block text-[10px] text-neutral-400">binding default</span>}
                        </td>
                        <td className="py-1 pr-3">{env.credentialType}</td>
                        <td className="py-1 pr-3"><Verdict live={env.runtime} /></td>
                        <td className="py-1 pr-3"><Verdict live={env.platform} /></td>
                        <td className="py-1">
                          {index === 0 &&
                            (call.estateHost && onOpenEstateSoap ? (
                              <button type="button" onClick={() => onOpenEstateSoap(call.invocationId)} className="text-left text-violet-700 hover:underline">
                                {call.estateHost} →
                                {data.estate_stale && <span className="block text-[10px] text-amber-700">as of the last estate run</span>}
                              </button>
                            ) : (
                              <span className="text-neutral-400">{data.estate_run_at ? 'not in the estate report: rerun it' : 'no estate report yet'}</span>
                            ))}
                        </td>
                      </tr>
                    ))}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  )
}
