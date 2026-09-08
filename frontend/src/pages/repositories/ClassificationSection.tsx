import { Fragment, useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import { getProjectClassification, getRepositoryClassificationSummary, listRepositoryClassifications } from '../../api/classification'
import { ClassificationStatusBadge, ConfidenceLevelBadge, ProjectRoleBadge } from '../../components/ClassificationBadges'
import type {
  ClassificationListItem,
  ClassificationSummary,
  MatchedRule,
  ProjectClassificationDetail,
} from '../../types/classification'

interface ClassificationSectionProps {
  repositoryId: string
  refreshToken: number
}

function SummaryStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-neutral-200 bg-neutral-50 px-3 py-2">
      <p className="text-xs font-medium uppercase tracking-wide text-neutral-400">{label}</p>
      <p className="text-lg font-semibold text-neutral-900">{value}</p>
    </div>
  )
}

const RULE_TONE: Record<'ok' | 'fail' | 'muted', string> = {
  ok: 'text-emerald-700',
  fail: 'text-red-600',
  muted: 'text-neutral-400',
}

function RuleList({ title, rules, tone }: { title: string; rules: MatchedRule[]; tone: 'ok' | 'fail' | 'muted' }) {
  if (rules.length === 0) return null
  return (
    <div className="mt-1.5">
      <p className="text-xs font-semibold uppercase tracking-wide text-neutral-400">{title}</p>
      <ul className="mt-0.5 space-y-0.5">
        {rules.map((r) => (
          <li key={r.rule_id} className={`font-mono text-xs ${RULE_TONE[tone]}`}>
            {r.rule_id}: {r.signal_name ?? r.field}
            {r.required_occurrences != null ? ` (${r.actual_occurrences ?? 0}/${r.required_occurrences})` : ''}
            {r.weight != null ? ` +${r.weight}` : ''}
          </li>
        ))}
      </ul>
    </div>
  )
}

function ProjectDetailPanel({ projectId }: { projectId: string }) {
  const [detail, setDetail] = useState<ProjectClassificationDetail | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    getProjectClassification(projectId)
      .then((result) => {
        if (!cancelled) setDetail(result)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [projectId])

  if (loading) return <p className="p-3 text-xs text-neutral-400">Loading detail…</p>
  if (!detail) return <p className="p-3 text-xs text-red-500">Could not load classification detail.</p>

  return (
    <div className="space-y-3 border-t border-neutral-100 bg-neutral-50 p-3">
      {detail.matches.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-neutral-500">
            Matched patterns ({detail.matches.length})
          </p>
          <div className="space-y-2">
            {detail.matches.map((m) => (
              <div key={m.pattern_id} className="rounded border border-emerald-200 bg-white p-2.5">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-neutral-800">
                    {m.pattern_name}
                    {m.is_primary_selected && <span className="ml-1.5 text-xs font-normal text-emerald-600">primary</span>}
                    {m.classification_role === 'SECONDARY' && (
                      <span className="ml-1.5 text-xs font-normal text-teal-600">secondary</span>
                    )}
                  </span>
                  <span className="flex items-center gap-2">
                    <ConfidenceLevelBadge level={m.confidence_level} />
                    <span className="text-xs text-neutral-400">score {m.match_score}</span>
                  </span>
                </div>
                {m.explanation && <p className="mt-1 text-xs text-neutral-500">{m.explanation}</p>}
                {m.rejection_reason && <p className="mt-1 text-xs font-medium text-amber-600">{m.rejection_reason}</p>}
                <RuleList title="Matched rules" rules={m.matched_rules} tone="ok" />
              </div>
            ))}
          </div>
        </div>
      )}

      {detail.near_misses.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-neutral-500">
            Near-miss patterns ({detail.near_misses.length}) — what makes tuning possible
          </p>
          <div className="space-y-2">
            {detail.near_misses.map((m) => (
              <div key={m.pattern_id} className="rounded border border-neutral-200 bg-white p-2.5">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-neutral-600">{m.pattern_name}</span>
                  <span className="text-xs text-neutral-400">score {m.match_score}</span>
                </div>
                <RuleList
                  title="Why it did not match"
                  rules={m.failed_rules.filter((r) => r.is_disqualifying !== false)}
                  tone="fail"
                />
                <RuleList
                  title="Unsatisfied alternatives (their group passed)"
                  rules={m.failed_rules.filter((r) => r.is_disqualifying === false)}
                  tone="muted"
                />
                <RuleList title="Negative rules triggered" rules={m.negative_triggered} tone="fail" />
              </div>
            ))}
          </div>
        </div>
      )}

      {detail.warnings.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-amber-600">Warnings</p>
          <ul className="mt-1 space-y-0.5 text-xs text-neutral-600">
            {detail.warnings.map((w, i) => (
              <li key={i}>{w.message}</li>
            ))}
          </ul>
        </div>
      )}

      {detail.matches.length === 0 && detail.near_misses.length === 0 && (
        <p className="text-xs text-neutral-400">No patterns were evaluated for this project.</p>
      )}
    </div>
  )
}

export function ClassificationSection({ repositoryId, refreshToken }: ClassificationSectionProps) {
  const [summary, setSummary] = useState<ClassificationSummary | null>(null)
  const [projects, setProjects] = useState<ClassificationListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [notClassified, setNotClassified] = useState(false)
  const [expandedProjectId, setExpandedProjectId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setNotClassified(false)
    setExpandedProjectId(null)

    Promise.all([getRepositoryClassificationSummary(repositoryId), listRepositoryClassifications(repositoryId)])
      .then(([summaryResult, projectsResult]) => {
        if (cancelled) return
        setSummary(summaryResult)
        setProjects(projectsResult)
        if (summaryResult.evaluated === 0) setNotClassified(true)
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 404) setNotClassified(true)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [repositoryId, refreshToken])

  if (loading) return <p className="text-sm text-neutral-400">Loading classification…</p>

  if (notClassified || !summary) {
    return (
      <div className="rounded border border-dashed border-neutral-200 bg-neutral-50 p-4 text-sm text-neutral-500">
        Pattern classification (lifecycle step 4) hasn&apos;t run for this repository yet.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-neutral-900">Classification</h3>

      <div className="grid grid-cols-4 gap-2 lg:grid-cols-8">
        <SummaryStat label="Evaluated" value={summary.evaluated} />
        <SummaryStat label="Matched" value={summary.matched} />
        <SummaryStat label="Multiple" value={summary.multiple_matches} />
        <SummaryStat label="Ambiguous" value={summary.ambiguous} />
        <SummaryStat label="No pattern" value={summary.no_pattern_matched} />
        <SummaryStat label="Insufficient" value={summary.insufficient_fingerprint} />
        <SummaryStat label="Not eligible" value={summary.not_eligible} />
        <SummaryStat label="Skipped" value={summary.skipped} />
      </div>

      <div className="overflow-hidden rounded border border-neutral-200">
        <table className="w-full text-left text-sm">
          <thead className="bg-neutral-50 text-xs uppercase tracking-wide text-neutral-500">
            <tr>
              <th className="px-3 py-2 font-medium">Project</th>
              <th className="px-3 py-2 font-medium">Role</th>
              <th className="px-3 py-2 font-medium">Primary pattern</th>
              <th className="px-3 py-2 font-medium">Confidence</th>
              <th className="px-3 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => (
              <Fragment key={p.project_id}>
                <tr
                  className="cursor-pointer border-t border-neutral-100 hover:bg-neutral-50"
                  onClick={() => setExpandedProjectId((id) => (id === p.project_id ? null : p.project_id))}
                >
                  <td className="px-3 py-2 font-mono text-xs text-neutral-700">{p.project_path}</td>
                  <td className="px-3 py-2">{p.project_role ? <ProjectRoleBadge role={p.project_role} /> : '—'}</td>
                  <td className="px-3 py-2 text-neutral-700">{p.primary_pattern_name ?? '—'}</td>
                  <td className="px-3 py-2">
                    {p.confidence_level ? <ConfidenceLevelBadge level={p.confidence_level} /> : '—'}
                  </td>
                  <td className="px-3 py-2">
                    <ClassificationStatusBadge status={p.classification_status} />
                  </td>
                </tr>
                {expandedProjectId === p.project_id && (
                  <tr>
                    <td colSpan={5} className="p-0">
                      <ProjectDetailPanel projectId={p.project_id} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
