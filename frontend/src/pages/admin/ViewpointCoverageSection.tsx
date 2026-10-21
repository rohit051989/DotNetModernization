import { useEffect, useState } from 'react'
import { listEngagements } from '../../api/catalog'
import { getViewpointCoverage } from '../../api/registration'
import { ApiError } from '../../api/client'
import { LimitedList } from '../../components/LimitedList'
import type { Engagement } from '../../types/catalog'
import type { ViewpointCoverage } from '../../types/registration'

const LABEL_TONE: Record<string, string> = {
  strong: 'bg-emerald-100 text-emerald-700',
  partial: 'bg-amber-100 text-amber-700',
  thin: 'bg-orange-100 text-orange-700',
  none: 'bg-neutral-100 text-neutral-500',
}

function CoverageLabel({ label }: { label: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${LABEL_TONE[label] ?? LABEL_TONE.none}`}>
      {label}
    </span>
  )
}

/** 25-STANDARDS-AND-VIEWPOINTS.md Part A2 — "This assessment covers
 * Development and Deployment fully, addresses Concurrency and Operational
 * partially, and requires stakeholder input for Context" is a stronger
 * position than implying complete coverage. Honest scoping, next to the step
 * registry it's derived from. */
export function ViewpointCoverageSection() {
  const [engagements, setEngagements] = useState<Engagement[]>([])
  const [engagementId, setEngagementId] = useState<string | null>(null)
  const [coverage, setCoverage] = useState<ViewpointCoverage | null>(null)
  const [loading, setLoading] = useState(true)
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
    setLoadError(null)

    getViewpointCoverage(engagementId)
      .then((result) => {
        if (!cancelled) setCoverage(result)
      })
      .catch((err) => {
        if (cancelled) return
        setLoadError(err instanceof ApiError ? err.message : 'Could not load viewpoint coverage.')
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
        <div>
          <h3 className="text-sm font-semibold text-neutral-900">Viewpoint coverage</h3>
          <p className="text-xs text-neutral-500">
            Which Rozanski &amp; Woods architecture viewpoints this platform's implemented steps address, and how
            much of that ran for this engagement.
          </p>
        </div>
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

      {coverage && !loading && !loadError && (
        <LimitedList items={coverage.viewpoints} name={(v) => v.viewpoint} noun="viewpoints">
          {(visible) => (
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-neutral-500">
                <tr>
                  <th className="px-3 py-2 font-medium">Viewpoint</th>
                  <th className="px-3 py-2 font-medium">Coverage</th>
                  <th className="px-3 py-2 font-medium">Implemented</th>
                  <th className="px-3 py-2 font-medium">Ran (this engagement)</th>
                  <th className="px-3 py-2 font-medium">Contributing steps</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((v) => (
                  <tr key={v.viewpoint} className="border-t border-neutral-100">
                    <td className="px-3 py-2 font-medium text-neutral-800">{v.viewpoint}</td>
                    <td className="px-3 py-2">
                      <CoverageLabel label={v.coverage_label} />
                    </td>
                    <td className="px-3 py-2 text-neutral-600">
                      {v.implemented_count} / {v.total_contributing}
                    </td>
                    <td className="px-3 py-2 text-neutral-600">{v.ran_count}</td>
                    <td className="px-3 py-2 text-xs text-neutral-500">
                      <LimitedList items={v.contributing_steps} name={(s) => s} noun="steps" empty="—">
                        {(visible) => visible.join(', ')}
                      </LimitedList>
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
