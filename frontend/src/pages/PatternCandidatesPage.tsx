import { useCallback, useEffect, useState } from 'react'
import { listPatternCandidates, retryNarration } from '../api/patternCandidates'
import { listValidationQueue } from '../api/validationQueue'
import { useToast } from '../components/Toast'
import type { NarrationStatusInfo, PatternCandidate, PatternCandidatesResponse } from '../types/patternCandidates'
import type { PatternCandidatePayload, QueueItem } from '../types/validationQueue'
import { DecisionPanel } from './patternCandidates/DecisionPanel'

/** Step 5's output and step 6's decision surface —
 * docs/26-STEP-005-PATTERN-DISCOVERY.md and 27 Part F. */

/** Below this, the members of a cluster are only loosely related: connected
 * components chained them together rather than finding one shape. 27 Part F
 * asks for a warning here because the shared signature may describe none of
 * the members well, which changes what a decision on it is worth. */
const LOW_COHESION = 0.6

const STATUS_STYLE: Record<NarrationStatusInfo['status'], { tone: string; label: string }> = {
  succeeded: { tone: 'border-emerald-200 bg-emerald-50 text-emerald-900', label: 'Narration succeeded' },
  partial: { tone: 'border-amber-200 bg-amber-50 text-amber-900', label: 'Narration partly unavailable' },
  failed: { tone: 'border-red-200 bg-red-50 text-red-900', label: 'Narration unavailable' },
  disabled: { tone: 'border-neutral-200 bg-neutral-50 text-neutral-700', label: 'Narration disabled' },
}

const CLUSTER_STATUS_STYLE: Record<string, string> = {
  validated_new: 'bg-emerald-100 text-emerald-800',
  merged: 'bg-sky-100 text-sky-800',
  rejected: 'bg-neutral-200 text-neutral-700',
}

function NarrationBanner({
  narration,
  onRetry,
  retrying,
}: {
  narration: NarrationStatusInfo
  onRetry: () => void
  retrying: boolean
}) {
  // Succeeded is the quiet case — saying so adds noise to every visit.
  if (narration.status === 'succeeded') return null

  const style = STATUS_STYLE[narration.status]
  return (
    <div className={`mb-4 rounded border px-4 py-3 text-sm ${style.tone}`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="font-medium">
            {style.label}
            {narration.status === 'partial' && (
              <span className="font-normal">
                {' '}
                — {narration.narrated_cluster_count} of {narration.cluster_count} clusters named
              </span>
            )}
          </p>
          {narration.reason && <p className="mt-1">{narration.reason}</p>}
          <p className="mt-1 text-xs opacity-80">
            Clusters below are unaffected — naming is advisory and never changes the shapes or their evidence.
            Review them by signature.
          </p>
        </div>
        {narration.retryable && (
          <button
            type="button"
            onClick={onRetry}
            disabled={retrying}
            className="shrink-0 rounded border border-current px-3 py-1.5 text-xs font-medium hover:bg-white/60 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {retrying ? 'Retrying…' : 'Retry narration'}
          </button>
        )}
      </div>
    </div>
  )
}

/** 27 Part F: "Coverage context is mandatory on every card, not tucked in a
 * detail panel." Rendered from the coverage recorded when the question was
 * raised, not from today's coverage — the reviewer needs to know what the
 * evidence looked like for *this* question. */
function CoverageLine({ payload, fallback }: { payload: PatternCandidatePayload | null; fallback: { ratio: number | null; partial: boolean } }) {
  const coverage = payload?.coverage_at_raise
  const ratio = coverage?.coverage_ratio ?? fallback.ratio
  if (ratio === null || ratio === undefined) return null

  const included = coverage?.repositories_included
  const total = coverage ? coverage.repositories_included + coverage.repositories_pending : null
  const percent = Math.round(ratio * 100)
  const partial = ratio < 1

  return (
    <p className={`mt-2 rounded px-2 py-1 text-xs ${partial ? 'bg-amber-50 text-amber-900' : 'bg-neutral-50 text-neutral-600'}`}>
      {partial ? 'Decided on partial evidence — ' : 'Full estate — '}
      {total !== null ? `${included} of ${total} repositories scanned` : `${percent}% of the estate scanned`} ({percent}%)
    </p>
  )
}

/** Past tense, because the banner narrates something that already happened.
 * "Previously reject" reads as a fragment; "Previously rejected" reads as a
 * sentence about a decision someone made. */
const PAST_TENSE_OUTCOME: Record<string, string> = {
  reject: 'rejected',
  create_pattern: 'accepted as a new pattern',
  merge_into_pattern: 'merged into an existing pattern',
}

/** The "then" half comes from the decision record; the "now" half comes from
 * the LIVE cluster, never from the item's payload.
 *
 * The payload is a snapshot frozen when the question was raised — that is what
 * `coverage_at_raise` means, and it is the right source for the evidence a
 * decision was made on. It is the wrong source for "now": a gate waits days by
 * design, membership changes underneath it, and the card's own stats line reads
 * live cluster values. Sourcing the two halves differently let the banner claim
 * "30 members across 15 repositories" on a card that said members 1,
 * repositories 1 directly below it.
 *
 * A banner that misstates evidence is worse than no banner, because it asks a
 * human to overturn a sound decision on grounds that are not true. */
function ReReviewBanner({ cluster, payload }: { cluster: PatternCandidate; payload: PatternCandidatePayload }) {
  const previous = payload.previous_decision
  if (!payload.is_rereview || !previous) return null

  const outcomeThen = previous.outcome ? (PAST_TENSE_OUTCOME[previous.outcome] ?? previous.outcome) : 'decided'
  const coverageThen =
    previous.coverage_then !== null ? `${Math.round(previous.coverage_then * 100)}% coverage` : 'unknown coverage'
  const membersThen = previous.member_count_then
  // The trigger's own basis, re-checked against live evidence rather than
  // assumed from the fact that an item exists.
  const basisLapsed = !cluster.needs_rereview
  const grew = membersThen !== null && cluster.member_count > membersThen

  return (
    <div
      className={`mt-2 rounded border px-3 py-2 text-xs ${
        basisLapsed ? 'border-neutral-200 bg-neutral-50 text-neutral-700' : 'border-amber-200 bg-amber-50 text-amber-900'
      }`}
    >
      <p className="font-medium">
        {basisLapsed ? 'Asked again — but the evidence has since changed back' : 'Asked again — the evidence has grown'}
      </p>
      <p className="mt-1">
        Previously <strong>{outcomeThen}</strong> at {coverageThen} with {membersThen} member
        {membersThen === 1 ? '' : 's'}. Now {cluster.member_count} member
        {cluster.member_count === 1 ? '' : 's'} across {cluster.repository_count} repositor
        {cluster.repository_count === 1 ? 'y' : 'ies'}.
      </p>
      {previous.decision_note && (
        <p className="mt-1 italic">
          “{previous.decision_note}” — {previous.decided_by}
        </p>
      )}
      <p className="mt-1 opacity-80">
        {basisLapsed
          ? 'This cluster no longer meets the re-review threshold, so there may be nothing new to weigh. The earlier decision still stands unless you change it.'
          : grew
            ? 'The earlier decision was not wrong; the information changed. Re-deciding resets the baseline.'
            : 'Re-deciding resets the baseline.'}
      </p>
    </div>
  )
}

interface ClusterCardProps {
  cluster: PatternCandidate
  item: QueueItem | undefined
  engagementId: string
  fallbackCoverage: { ratio: number | null; partial: boolean }
  onDecided: () => void
}

function ClusterCard({ cluster, item, engagementId, fallbackCoverage, onDecided }: ClusterCardProps) {
  const [expanded, setExpanded] = useState(false)
  const payload = (item?.payload as PatternCandidatePayload | undefined) ?? null
  const facets = Object.entries(cluster.canonical_signature.facets).filter(([, v]) => v !== null)
  const unnamed = cluster.naming_source === 'none'
  const lowCohesion = cluster.cohesion !== null && cluster.cohesion < LOW_COHESION
  const decidable = item !== undefined && item.status === 'open'

  return (
    <li className="rounded border border-neutral-200 bg-white">
      <div className="px-4 py-3">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              {unnamed ? (
                <span className="text-sm font-medium italic text-neutral-500">Unnamed shape</span>
              ) : (
                <span className="text-sm font-medium text-neutral-900">{cluster.suggested_name}</span>
              )}
              <code className="rounded bg-neutral-100 px-1.5 py-0.5 font-mono text-xs text-neutral-600">
                {cluster.cluster_id}
              </code>
              {!unnamed && (
                <span className="rounded bg-sky-50 px-1.5 py-0.5 text-xs text-sky-700">
                  suggested · {cluster.narration_confidence} confidence
                </span>
              )}
              {cluster.status !== 'candidate' && (
                <span className={`rounded px-1.5 py-0.5 text-xs ${CLUSTER_STATUS_STYLE[cluster.status] ?? 'bg-neutral-100 text-neutral-700'}`}>
                  {cluster.status.replace('_', ' ')}
                </span>
              )}
              {item?.is_deferred && (
                <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs text-neutral-600">
                  deferred
                  {item.deferred_until_member_count ? ` until ${item.deferred_until_member_count} members` : ''}
                </span>
              )}
              {cluster.needs_rereview && (
                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800">needs re-review</span>
              )}
            </div>
            {cluster.suggested_description && (
              <p className="mt-1 text-sm text-neutral-600">{cluster.suggested_description}</p>
            )}
            {unnamed && cluster.canonical_signature.signals.length > 0 && (
              <p className="mt-1 font-mono text-xs text-neutral-500">
                {cluster.canonical_signature.signals.join(' · ')}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="shrink-0 text-xs text-sky-700 hover:underline"
          >
            {expanded ? 'Hide evidence' : 'Show evidence'}
          </button>
        </div>

        {payload && <ReReviewBanner cluster={cluster} payload={payload} />}
        <CoverageLine payload={payload} fallback={fallbackCoverage} />
      </div>

      <div className="flex flex-wrap gap-x-5 gap-y-1 border-t border-neutral-100 px-4 py-2 text-xs text-neutral-600">
        <span>
          <span className="text-neutral-400">members</span> {cluster.member_count}
        </span>
        <span>
          <span className="text-neutral-400">repositories</span> {cluster.repository_count}
        </span>
        <span>
          <span className="text-neutral-400">method</span> {cluster.cluster_method}
        </span>
        <span className={lowCohesion ? 'font-medium text-amber-700' : ''}>
          <span className={lowCohesion ? 'text-amber-600' : 'text-neutral-400'}>cohesion</span>{' '}
          {cluster.cohesion ?? '—'}
          {lowCohesion && ' ⚠'}
        </span>
        <span>
          <span className="text-neutral-400">signals</span> {cluster.signal_count}
        </span>
        <span className="text-neutral-400">
          {Object.entries(cluster.repository_distribution)
            .map(([repo, n]) => `${repo} ×${n}`)
            .join(' · ')}
        </span>
      </div>

      {lowCohesion && (
        <p className="border-t border-amber-100 bg-amber-50 px-4 py-2 text-xs text-amber-900">
          Low cohesion ({cluster.cohesion}) — these members were chained together through intermediates rather
          than sharing one tight shape. The signature may describe none of them well.
        </p>
      )}

      {expanded && (
        <div className="space-y-3 border-t border-neutral-100 bg-neutral-50 px-4 py-3 text-xs">
          <div>
            <p className="mb-1 font-medium text-neutral-700">Shared signals</p>
            {cluster.canonical_signature.signals.length === 0 ? (
              <p className="text-neutral-500">
                None — these projects share a shape defined entirely by their metadata facets.
              </p>
            ) : (
              <div className="flex flex-wrap gap-1">
                {cluster.canonical_signature.signals.map((signal) => (
                  <code key={signal} className="rounded bg-white px-1.5 py-0.5 font-mono text-neutral-700">
                    {signal}
                  </code>
                ))}
              </div>
            )}
          </div>

          {facets.length > 0 && (
            <div>
              <p className="mb-1 font-medium text-neutral-700">Facets</p>
              <div className="flex flex-wrap gap-3 text-neutral-600">
                {facets.map(([key, value]) => (
                  <span key={key}>
                    <span className="text-neutral-400">{key}</span> {value}
                  </span>
                ))}
              </div>
            </div>
          )}

          {cluster.similar_patterns && cluster.similar_patterns.length > 0 && (
            <div>
              <p className="mb-1 font-medium text-neutral-700">Resembles existing patterns</p>
              <div className="flex flex-wrap gap-3 text-neutral-600">
                {cluster.similar_patterns.map((p) => (
                  <span key={p.pattern_id}>
                    <code className="font-mono">{p.pattern_id}</code> {Math.round(p.similarity * 100)}%
                  </span>
                ))}
              </div>
            </div>
          )}

          <div>
            <p className="mb-1 font-medium text-neutral-700">Members</p>
            <ul className="space-y-0.5 text-neutral-600">
              {cluster.members.map((m) => (
                <li key={m.project_id} className="flex flex-wrap gap-2">
                  <span className="text-neutral-400">{m.repository_name}</span>
                  <span className="font-mono">{m.project_path}</span>
                  <span className="text-neutral-400">{m.classification_status}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {decidable && payload && (
        <DecisionPanel
          engagementId={engagementId}
          clusterId={cluster.cluster_id}
          item={item}
          payload={payload}
          onDecided={onDecided}
        />
      )}
      {!decidable && item?.status === 'decided' && (
        <p className="border-t border-neutral-100 px-4 py-2 text-xs text-neutral-500">
          Decided <strong>{item.outcome}</strong> by {item.decided_by}
          {item.decision_note ? ` — “${item.decision_note}”` : ''}. Applies when the job is resumed.
        </p>
      )}
    </li>
  )
}

export function PatternCandidatesPage({ engagementId }: { engagementId: string }) {
  const [data, setData] = useState<PatternCandidatesResponse | null>(null)
  const [items, setItems] = useState<QueueItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [retrying, setRetrying] = useState(false)
  const [showSingletons, setShowSingletons] = useState(false)
  const { showToast } = useToast()

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      listPatternCandidates(engagementId),
      // Every status, so a decided or deferred cluster still shows what
      // happened to it rather than silently losing its actions.
      listValidationQueue(engagementId, { stepName: 'pattern-validation', includeDeferred: true }),
    ])
      .then(([candidates, queue]) => {
        setData(candidates)
        setItems(queue)
        setError(null)
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [engagementId])

  useEffect(load, [load])

  async function handleRetry() {
    setRetrying(true)
    try {
      const result = await retryNarration(engagementId)
      showToast(
        result.narration_status === 'succeeded' ? 'success' : 'error',
        result.narration_status === 'succeeded'
          ? `Narration succeeded — ${result.narrated_count} of ${result.cluster_count} clusters named.`
          : `Narration ${result.narration_status}: ${result.narration_reason ?? 'no reason reported'}`,
      )
      load()
    } catch (err) {
      showToast('error', (err as Error).message)
    } finally {
      setRetrying(false)
    }
  }

  if (loading && !data) return <p className="p-6 text-sm text-neutral-500">Loading candidate patterns…</p>
  if (error) return <p className="p-6 text-sm text-red-700">{error}</p>
  if (!data) return null

  if (!data.narration) {
    return (
      <div className="p-6">
        <h2 className="text-lg font-medium text-neutral-900">Pattern candidates</h2>
        <p className="mt-2 text-sm text-neutral-500">
          Step 5 has not run for this engagement yet. Launch{' '}
          <code className="font-mono text-neutral-700">phase0-estate-consolidation</code> from the Workflow tab
          to cluster the projects the catalog could not classify.
        </p>
      </div>
    )
  }

  // The newest open item per cluster wins: a superseded item and its
  // replacement share an item_key, and the replacement is the live question.
  const itemByCluster = new Map<string, QueueItem>()
  for (const item of [...items].sort((a, b) => a.created_at.localeCompare(b.created_at))) {
    const existing = itemByCluster.get(item.item_key)
    if (!existing || item.status === 'open' || existing.status !== 'open') itemByCluster.set(item.item_key, item)
  }

  const fallbackCoverage = { ratio: data.coverage_ratio, partial: data.partial_estate }
  const recurring = data.clusters.filter((c) => !c.is_singleton)
  const singletons = data.clusters.filter((c) => c.is_singleton)
  const openCount = items.filter((i) => i.status === 'open' && !i.is_deferred).length

  const renderCard = (cluster: PatternCandidate) => (
    <ClusterCard
      key={cluster.cluster_id}
      cluster={cluster}
      item={itemByCluster.get(cluster.cluster_id)}
      engagementId={engagementId}
      fallbackCoverage={fallbackCoverage}
      onDecided={load}
    />
  )

  return (
    <div className="mx-auto max-w-5xl p-6">
      <div className="mb-4">
        <div className="flex flex-wrap items-baseline gap-2">
          <h2 className="text-lg font-medium text-neutral-900">Pattern candidates</h2>
          {openCount > 0 && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
              {openCount} awaiting your decision
            </span>
          )}
        </div>
        <p className="mt-1 text-sm text-neutral-500">
          Shapes the catalog could not classify, grouped so a recurring one is visible as recurring.
          {data.coverage_ratio !== null && (
            <>
              {' '}
              Measured against {Math.round(data.coverage_ratio * 100)}% of the estate
              {data.partial_estate && ' — the rest has not been scanned yet'}.
            </>
          )}
        </p>
      </div>

      <NarrationBanner narration={data.narration} onRetry={handleRetry} retrying={retrying} />

      {data.clusters.length === 0 ? (
        <p className="text-sm text-neutral-500">
          No candidate shapes. Every project the estate has scanned so far was classified.
        </p>
      ) : (
        <>
          {recurring.length > 0 ? (
            <ul className="space-y-2">{recurring.map(renderCard)}</ul>
          ) : (
            <p className="rounded border border-neutral-200 bg-white px-4 py-3 text-sm text-neutral-500">
              No shape recurs yet. Every candidate below occurs once, which is not yet evidence of a pattern.
            </p>
          )}

          {/* Singletons get their own section, collapsed. A one-off is not a
              pattern and should not dominate the view — but it is still worth
              seeing, and it keeps its cluster_id if it gains members later. */}
          {singletons.length > 0 && (
            <section className="mt-6">
              <button
                type="button"
                onClick={() => setShowSingletons((v) => !v)}
                className="flex w-full items-center justify-between rounded border border-neutral-200 bg-white px-4 py-2 text-left text-sm hover:bg-neutral-50"
              >
                <span className="font-medium text-neutral-700">
                  Single-occurrence shapes ({singletons.length})
                </span>
                <span className="text-xs text-neutral-500">
                  {showSingletons ? 'Hide' : 'Show'} — one occurrence is not yet a pattern
                </span>
              </button>
              {showSingletons && <ul className="mt-2 space-y-2">{singletons.map(renderCard)}</ul>}
            </section>
          )}
        </>
      )}
    </div>
  )
}
