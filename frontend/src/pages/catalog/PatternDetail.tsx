import { useEffect, useState } from 'react'
import { getPattern, listTargetStates } from '../../api/catalog'
import type { DetectionRules, PatternDetail as PatternDetailModel, TargetStateDetail } from '../../types/catalog'
import { CategoryBadge, StatusBadge } from '../../components/Badge'
import { Markdown } from '../../components/Markdown'
import { TargetStateCard } from './TargetStateCard'

interface PatternDetailProps {
  patternId: string
}

const DETECTION_RULE_LIST_FIELDS: { key: keyof DetectionRules; label: string }[] = [
  { key: 'target_frameworks', label: 'Target frameworks' },
  { key: 'required_namespaces', label: 'Required namespaces' },
  { key: 'forbidden_namespaces', label: 'Forbidden namespaces' },
  { key: 'required_packages', label: 'Required packages' },
  { key: 'file_globs', label: 'File globs' },
  { key: 'forbidden_file_globs', label: 'Forbidden file globs' },
  { key: 'config_markers', label: 'Config markers' },
]

export function PatternDetail({ patternId }: PatternDetailProps) {
  const [pattern, setPattern] = useState<PatternDetailModel | null>(null)
  const [targetStates, setTargetStates] = useState<TargetStateDetail[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showRawJson, setShowRawJson] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setShowRawJson(false)

    Promise.all([getPattern(patternId), listTargetStates(patternId)])
      .then(([patternResult, targetStatesResult]) => {
        if (cancelled) return
        setPattern(patternResult)
        setTargetStates(targetStatesResult)
      })
      .catch(() => {
        if (!cancelled) setError('Could not load this pattern.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [patternId])

  if (loading) {
    return (
      <div className="space-y-4 p-8">
        <div className="h-8 w-1/3 animate-pulse rounded bg-neutral-100" />
        <div className="h-24 animate-pulse rounded bg-neutral-100" />
        <div className="h-40 animate-pulse rounded bg-neutral-100" />
      </div>
    )
  }

  if (error || !pattern) {
    return <div className="p-8 text-sm text-red-600">{error ?? 'Pattern not found.'}</div>
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-8">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-xl font-semibold text-neutral-900">{pattern.name}</h2>
          <p className="mt-0.5 font-mono text-xs text-neutral-400">{pattern.id}</p>
          <div className="mt-2 flex items-center gap-2">
            <CategoryBadge category={pattern.category} />
            <StatusBadge status={pattern.status} />
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            disabled
            title="Coming soon"
            className="cursor-not-allowed rounded border border-neutral-200 px-3 py-1.5 text-sm text-neutral-400"
          >
            Edit
          </button>
          <button
            type="button"
            disabled
            title="Coming soon"
            className="cursor-not-allowed rounded border border-neutral-200 px-3 py-1.5 text-sm text-neutral-400"
          >
            Deprecate
          </button>
        </div>
      </div>

      <section className="rounded border border-neutral-200 bg-white p-5">
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-neutral-500">Definition</h3>
        <p className="text-sm text-neutral-700">{pattern.summary}</p>
        {pattern.description && (
          <div className="mt-3">
            <Markdown text={pattern.description} />
          </div>
        )}
        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
          <div>
            <dt className="text-xs text-neutral-400">Legacy stack</dt>
            <dd className="text-neutral-700">{pattern.legacy_stack}</dd>
          </div>
          <div>
            <dt className="text-xs text-neutral-400">Version</dt>
            <dd className="text-neutral-700">{pattern.version}</dd>
          </div>
          {pattern.typical_indicators && (
            <div className="col-span-2">
              <dt className="text-xs text-neutral-400">Typical indicators</dt>
              <dd className="text-neutral-700">{pattern.typical_indicators}</dd>
            </div>
          )}
          {pattern.known_risks && (
            <div className="col-span-2">
              <dt className="text-xs text-neutral-400">Known risks</dt>
              <dd className="text-neutral-700">{pattern.known_risks}</dd>
            </div>
          )}
        </dl>
      </section>

      <section className="rounded border border-neutral-200 bg-white p-5">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">Detection rules</h3>
          <button
            type="button"
            onClick={() => setShowRawJson((value) => !value)}
            className="text-xs font-medium text-violet-600 hover:text-violet-700"
          >
            {showRawJson ? 'Hide raw JSON' : 'View raw JSON'}
          </button>
        </div>

        {showRawJson ? (
          <pre className="overflow-x-auto rounded bg-neutral-900 p-3 text-xs text-neutral-100">
            {JSON.stringify(pattern.detection_rules, null, 2)}
          </pre>
        ) : (
          <div className="space-y-3">
            {DETECTION_RULE_LIST_FIELDS.map(({ key, label }) => {
              const values = pattern.detection_rules[key]
              if (!Array.isArray(values) || values.length === 0) return null
              return (
                <div key={key}>
                  <p className="text-xs font-medium text-neutral-500">{label}</p>
                  <ul className="mt-1 flex flex-wrap gap-1.5">
                    {values.map((value) => (
                      <li key={value} className="rounded bg-neutral-100 px-2 py-0.5 font-mono text-xs text-neutral-700">
                        {value}
                      </li>
                    ))}
                  </ul>
                </div>
              )
            })}
            {pattern.detection_rules.notes && (
              <p className="text-sm italic text-neutral-500">{pattern.detection_rules.notes}</p>
            )}
          </div>
        )}
      </section>

      <section className="rounded border border-neutral-200 bg-white p-5">
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-neutral-500">
          Target state options
        </h3>
        <div className="space-y-3">
          {targetStates.map((option, index) => (
            <TargetStateCard key={option.id} option={option} isPresumptive={index === 0} />
          ))}
        </div>
        <button
          type="button"
          disabled
          title="Coming soon"
          className="mt-3 w-full cursor-not-allowed rounded border border-dashed border-neutral-300 py-2 text-sm font-medium text-neutral-400"
        >
          + Add target state option
        </button>
      </section>
    </div>
  )
}
