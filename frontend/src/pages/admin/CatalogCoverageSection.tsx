import { useEffect, useState } from 'react'
import { listEngagements } from '../../api/catalog'
import { getCatalogCoverage, getPendingSignalPromotions } from '../../api/classification'
import { ApiError } from '../../api/client'
import type { Engagement } from '../../types/catalog'
import type { CatalogCoverage, PendingSignalPromotion } from '../../types/classification'

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded border border-neutral-200 bg-neutral-50 px-3 py-2">
      <p className="text-xs font-medium uppercase tracking-wide text-neutral-400">{label}</p>
      <p className="text-lg font-semibold text-neutral-900">{value}</p>
    </div>
  )
}

/** 24-STEP-004-CLASSIFICATION.md Part I 'Catalog coverage — master view':
 * registered vs referenced signals, patterns never matched, patterns
 * awaiting signals grouped by expected extractor, and the most frequent
 * unmatched signal combinations. The catalog itself is shared master IP,
 * but coverage is only observable through what an engagement's
 * repositories have actually been scanned against — hence the selector. */
export function CatalogCoverageSection() {
  const [engagements, setEngagements] = useState<Engagement[]>([])
  const [engagementId, setEngagementId] = useState<string | null>(null)
  const [coverage, setCoverage] = useState<CatalogCoverage | null>(null)
  const [pending, setPending] = useState<PendingSignalPromotion[]>([])
  const [loading, setLoading] = useState(true)
  const [noData, setNoData] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    listEngagements()
      .then((result) => {
        setEngagements(result)
        if (result.length > 0) setEngagementId(result[0].id)
        else setLoading(false)
      })
      .catch(() => {
        setLoadError('Could not load engagements.')
        setLoading(false)
      })
  }, [])

  useEffect(() => {
    if (!engagementId) return
    let cancelled = false
    setLoading(true)
    setNoData(false)
    setLoadError(null)

    Promise.all([getCatalogCoverage(engagementId), getPendingSignalPromotions()])
      .then(([coverageResult, pendingResult]) => {
        if (cancelled) return
        setCoverage(coverageResult)
        setPending(pendingResult)
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 404) setNoData(true)
        else setLoadError('Could not load catalog coverage.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [engagementId])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-neutral-900">Catalog coverage</h3>
        {engagements.length > 0 && (
          <select
            value={engagementId ?? ''}
            onChange={(e) => setEngagementId(e.target.value)}
            className="rounded border border-neutral-300 px-2 py-1 text-sm"
          >
            {engagements.map((e) => (
              <option key={e.id} value={e.id}>
                {e.client_name}
              </option>
            ))}
          </select>
        )}
      </div>

      {engagements.length === 0 && !loading && (
        <p className="text-sm text-neutral-400">No engagements registered yet.</p>
      )}

      {loading && <p className="text-sm text-neutral-400">Loading coverage…</p>}

      {loadError && <p className="text-sm text-red-600">{loadError}</p>}

      {noData && !loading && (
        <div className="rounded border border-dashed border-neutral-200 bg-neutral-50 p-4 text-sm text-neutral-500">
          No repository in this engagement has been classified yet — pattern classification (lifecycle step 4)
          hasn&apos;t produced a coverage report.
        </div>
      )}

      {coverage && !loading && !noData && (
        <>
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6">
            <StatCard label="Registered signals" value={coverage.registered_signal_count} />
            <StatCard label="Referenced" value={coverage.referenced_signal_count} />
            <StatCard label="Unreferenced" value={coverage.unreferenced_signal_count} />
            <StatCard label="Active patterns" value={coverage.active_pattern_count} />
            <StatCard label="Evaluated" value={coverage.evaluated_pattern_count} />
            <StatCard label="Matched" value={coverage.matched_pattern_count} />
          </div>
          <p className="text-xs text-neutral-400">
            Catalog {coverage.catalog_version} · signal registry {coverage.signal_registry_version ?? 'unknown'} ·
            aggregated across {coverage.repositories_included} classified repositor
            {coverage.repositories_included === 1 ? 'y' : 'ies'}.
          </p>

          <div>
            <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-neutral-500">
              Patterns never matched ({coverage.never_matched_pattern_ids.length})
            </h4>
            {coverage.never_matched_pattern_ids.length === 0 ? (
              <p className="text-sm text-neutral-400">Every active pattern has matched at least once.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {coverage.never_matched_pattern_ids.map((id) => (
                  <span key={id} className="rounded border border-neutral-200 bg-white px-2 py-0.5 font-mono text-xs text-neutral-600">
                    {id}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div>
            <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-neutral-500">
              Patterns awaiting signals, by expected extractor — the step 3 extractor backlog
            </h4>
            {Object.keys(coverage.patterns_awaiting_signals_by_extractor).length === 0 ? (
              <p className="text-sm text-neutral-400">No pattern is waiting on an unregistered signal.</p>
            ) : (
              <div className="space-y-2">
                {Object.entries(coverage.patterns_awaiting_signals_by_extractor).map(([extractor, patternIds]) => (
                  <div key={extractor} className="rounded border border-neutral-200 bg-white p-2.5">
                    <p className="text-sm font-medium text-neutral-800">{extractor}</p>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {patternIds.map((id) => {
                        const promo = pending.find((p) => p.pattern_id === id)
                        return (
                          <span
                            key={id}
                            title={promo?.promotable ? 'Promotable to active' : 'Still missing a blocking signal'}
                            className={`rounded px-2 py-0.5 font-mono text-xs ${
                              promo?.promotable
                                ? 'bg-emerald-50 text-emerald-700'
                                : 'bg-amber-50 text-amber-700'
                            }`}
                          >
                            {id}
                          </span>
                        )
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div>
            <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-neutral-500">
              Rules referencing a signal never seen in this engagement ({coverage.rule_references_never_emitted_signal.length})
            </h4>
            {coverage.rule_references_never_emitted_signal.length === 0 ? (
              <p className="text-sm text-neutral-400">
                Every active pattern's referenced signals have appeared at least once somewhere in this engagement.
              </p>
            ) : (
              <div className="space-y-2">
                {coverage.rule_references_never_emitted_signal.map((finding) => (
                  <div key={finding.pattern_id} className="rounded border border-amber-200 bg-amber-50 p-2.5">
                    <p className="text-sm font-medium text-amber-900">
                      {finding.name} <span className="font-mono text-xs text-amber-700">({finding.pattern_id})</span>
                    </p>
                    <p className="mt-0.5 text-xs text-amber-700">
                      Never emitted anywhere in this engagement — a broken rule (wrong signal name) looks identical
                      to a genuinely absent legacy shape until this is checked by hand:
                    </p>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {finding.never_emitted_signals.map((name) => (
                        <span key={name} className="rounded bg-white px-2 py-0.5 font-mono text-xs text-amber-800">
                          {name}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div>
            <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-neutral-500">
              Most frequent unmatched anchor-signal combinations — step 5's direct input
            </h4>
            {coverage.most_frequent_unmatched_signal_combinations.length === 0 ? (
              <p className="text-sm text-neutral-400">No unmatched combinations recorded.</p>
            ) : (
              <ul className="space-y-1">
                {coverage.most_frequent_unmatched_signal_combinations.map((combo, i) => (
                  <li key={i} className="flex items-center justify-between text-sm">
                    <span className="font-mono text-xs text-neutral-600">{combo.anchor_signals.join(' + ')}</span>
                    <span className="text-xs text-neutral-400">{combo.count}×</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  )
}
