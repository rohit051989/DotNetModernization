import { Fragment, useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import { evidenceHref, getRepositoryConversion } from '../../api/conversion'
import type { ConversionUnit, EvidenceLink, PlanStatus, RepositoryConversion, TestRun, UnitStatus } from '../../types/conversion'

const STATUS_STYLE: Record<UnitStatus, string> = {
  committed: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  not_applicable: 'border-neutral-200 bg-neutral-50 text-neutral-500',
  failed: 'border-red-200 bg-red-50 text-red-800',
  blocked: 'border-amber-200 bg-amber-50 text-amber-800',
  stale: 'border-amber-200 bg-amber-50 text-amber-800',
  planned: 'border-sky-200 bg-sky-50 text-sky-800',
  applied: 'border-sky-200 bg-sky-50 text-sky-800',
  verified: 'border-sky-200 bg-sky-50 text-sky-800',
  awaiting_review: 'border-violet-200 bg-violet-50 text-violet-800',
  awaiting_human: 'border-violet-200 bg-violet-50 text-violet-800',
  excluded: 'border-neutral-300 bg-neutral-100 text-neutral-600',
}

const PLAN_LABEL: Record<PlanStatus, string> = {
  planned: 'planned, not run',
  running: 'running',
  completed: 'completed — every unit committed or not applicable',
  partial: 'run to the end — some units failed, are blocked, or wait for assisted work',
  stopped: 'stopped',
}

const STATUS_ORDER: UnitStatus[] = ['committed', 'not_applicable', 'failed', 'blocked', 'planned', 'stale', 'awaiting_review', 'awaiting_human', 'excluded', 'applied', 'verified']

function StatusChip({ status, count }: { status: UnitStatus; count?: number }) {
  return (
    <span className={`inline-block whitespace-nowrap rounded border px-1 text-[11px] ${STATUS_STYLE[status]}`}>
      {count !== undefined ? `${count} ` : ''}
      {status.replace('_', ' ')}
    </span>
  )
}

function EvidenceLinks({ evidence }: { evidence: EvidenceLink[] }) {
  if (evidence.length === 0) return <span className="text-neutral-400">none recorded</span>
  return (
    <ul className="space-y-0.5">
      {evidence.map((e) => (
        <li key={e.path}>
          <a href={evidenceHref(e.url)} target="_blank" rel="noreferrer" className="font-mono text-violet-700 hover:underline">
            {e.kind.replace('_', ' ')}
            {e.project ? ` · ${e.project.split('/').pop()}` : ''}
          </a>{' '}
          <span className="font-mono text-[10px] text-neutral-400" title={e.sha256}>
            sha256 {e.sha256.slice(0, 12)}
          </span>
        </li>
      ))}
    </ul>
  )
}

function TestTable({ label, run, extra }: { label: string; run: TestRun | null; extra?: string }) {
  return (
    <div className="min-w-[240px] flex-1 rounded border border-neutral-200 p-2">
      <h4 className="mb-1 text-[11px] font-medium uppercase tracking-wide text-neutral-400">{label}</h4>
      {!run ? (
        <p className="text-xs text-neutral-400">{extra ?? 'Not run yet.'}</p>
      ) : (
        <>
          <p className="text-xs text-neutral-500">
            {run.commit && <>commit <span className="font-mono">{run.commit.slice(0, 10)}</span> · </>}
            {run.framework && <>{run.framework} · </>}
            {run.sequence !== null && <>after unit {run.sequence} · </>}
            <span className={run.passed === run.total ? 'text-emerald-700' : 'text-red-700'}>
              {run.passed}/{run.total} passed
            </span>
          </p>
          <ul className="mt-1 space-y-0.5 text-xs">
            {Object.entries(run.tests).map(([project, t]) => (
              <li key={project}>
                <span className="font-mono text-neutral-700">{project}</span>{' '}
                <span className="font-mono">
                  {t.passed}/{t.total}
                </span>
                {t.failed > 0 && <span className="text-red-700"> · {t.failed} failed: {t.failed_tests.join(', ')}</span>}
                {t.skipped > 0 && <span className="text-neutral-500"> · {t.skipped} skipped</span>}
              </li>
            ))}
          </ul>
          <div className="mt-1 text-[11px]">
            <EvidenceLinks evidence={run.evidence} />
          </div>
        </>
      )}
    </div>
  )
}

function UnitRow({ unit, open, onToggle }: { unit: ConversionUnit; open: boolean; onToggle: () => void }) {
  return (
    <Fragment>
      <tr className="border-t border-neutral-100 align-top">
        <td className="py-1 pr-2 font-mono text-neutral-500">{unit.sequence}</td>
        <td className="py-1 pr-2">
          <button type="button" onClick={onToggle} aria-expanded={open} className="text-left text-neutral-800 hover:text-violet-700">
            {unit.title}
          </button>
          <span className="block text-[11px] text-neutral-400">
            {unit.approach_id} {unit.approach_version} · {unit.automation_class}
          </span>
        </td>
        <td className="py-1 pr-2"><StatusChip status={unit.status} /></td>
        <td className="py-1 pr-2 font-mono text-neutral-600">{unit.commit_sha ? unit.commit_sha.slice(0, 10) : ''}</td>
        <td className="py-1 pr-2 font-mono text-neutral-600">
          {unit.tests ? Object.values(unit.tests).join(', ') : ''}
        </td>
        <td className="py-1 text-neutral-600">
          {unit.status_reason && <span className={unit.status === 'failed' ? 'text-red-700' : ''}>{unit.status_reason}</span>}
        </td>
      </tr>
      {open && (
        <tr className="bg-neutral-50/60 text-[11px]">
          <td />
          <td colSpan={5} className="space-y-1 py-2 pr-2">
            <p><span className="text-neutral-400">Why here: </span>{unit.order_reason}</p>
            {unit.together_because && (
              <p><span className="text-neutral-400">Why together: </span>{unit.together_because}</p>
            )}
            {unit.depends_on.length > 0 && (
              <div>
                <span className="text-neutral-400">Depends on: </span>
                <ul className="ml-3 list-disc">
                  {unit.depends_on.map((d) => (
                    <li key={d.sequence}>unit {d.sequence} — {d.reason}</li>
                  ))}
                </ul>
              </div>
            )}
            <div>
              <span className="text-neutral-400">Evidence: </span>
              <EvidenceLinks evidence={unit.evidence} />
            </div>
            <p className="font-mono text-neutral-400">{unit.unit_id}</p>
          </td>
        </tr>
      )}
    </Fragment>
  )
}

/** One package-step plan (34-CONVERSION-ARCHITECTURE C4, Part E): its units in
 * order with status, commit, failure reason and evidence, and the unit tests
 * before and after. Shown inside its conversion's entry (ConversionsPanel). */
export function RepositoryConversionSection({ repositoryId, planId, refreshToken }: { repositoryId: string; planId?: string; refreshToken: number }) {
  const [data, setData] = useState<RepositoryConversion | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'no_plan' | 'error'>('loading')
  const [open, setOpen] = useState<Set<number>>(new Set())

  useEffect(() => {
    let cancelled = false
    setState('loading')
    getRepositoryConversion(repositoryId, planId)
      .then((result) => {
        if (cancelled) return
        setData(result)
        setState('ready')
      })
      .catch((err) => {
        if (!cancelled) setState(err instanceof ApiError && err.status === 409 ? 'no_plan' : 'error')
      })
    return () => {
      cancelled = true
    }
  }, [repositoryId, planId, refreshToken])

  if (state === 'loading') return <div className="h-16 animate-pulse rounded bg-neutral-100" />
  if (state === 'no_plan') return <p className="text-sm text-neutral-400">No package-step plan yet.</p>
  if (state === 'error' || !data) return <p className="text-sm text-red-600">Could not load the conversion.</p>

  const { plan } = data
  const toggle = (sequence: number) =>
    setOpen((current) => {
      const next = new Set(current)
      if (next.has(sequence)) next.delete(sequence)
      else next.add(sequence)
      return next
    })

  return (
    <div className="space-y-4 text-sm">
      <div className="space-y-1">
        <p className="text-xs text-neutral-500">
          <span className="font-medium text-neutral-700">{PLAN_LABEL[plan.status]}</span>
          {plan.status_reason && <span className="text-neutral-500"> — {plan.status_reason}</span>}
        </p>
        <p className="text-xs text-neutral-500">
          {plan.from_framework ?? '?'} → {plan.target_framework} · branch <span className="font-mono">{plan.branch}</span> from{' '}
          <span className="font-mono">{plan.legacy_commit.slice(0, 10)}</span>
          {plan.tip_commit && (
            <>
              {' '}· tip <span className="font-mono">{plan.tip_commit.slice(0, 10)}</span> builds for{' '}
              <span className={plan.tip_framework === plan.target_framework ? 'font-medium text-emerald-700' : 'font-medium text-amber-700'}>
                {plan.tip_framework}
              </span>
            </>
          )}
        </p>
        <p className="break-all font-mono text-[11px] text-neutral-400">{plan.worktree_path}</p>
        <div className="flex flex-wrap gap-1">
          {STATUS_ORDER.filter((s) => (data.counts[s] ?? 0) > 0).map((s) => (
            <StatusChip key={s} status={s} count={data.counts[s]} />
          ))}
          <span className="ml-1 text-[11px] text-neutral-500">
            {Object.entries(data.automation).map(([cls, n]) => `${n} ${cls}`).join(', ')}
          </span>
        </div>
        {plan.exclusions.length > 0 && (
          <p className="text-[11px] text-neutral-500">
            Left out of the plan: {plan.exclusions.map((e) => `${e.package_id} (${e.reason})`).join('; ')}
          </p>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <TestTable
          label="Before — the baseline"
          run={data.baseline}
          extra={data.baseline?.failure ?? undefined}
        />
        <TestTable label="After — the branch tip" run={data.latest} extra="No unit has been committed yet." />
      </div>

      <div className="overflow-x-auto">
        <h4 className="mb-1 text-[11px] font-medium uppercase tracking-wide text-neutral-400">
          Units, in order — select one for why it is there, what it waits on, and its evidence
        </h4>
        <table className="w-full min-w-[720px] text-left text-xs">
          <thead className="text-neutral-400">
            <tr>
              <th className="py-1 pr-2 font-medium">#</th>
              <th className="py-1 pr-2 font-medium">Unit</th>
              <th className="py-1 pr-2 font-medium">Status</th>
              <th className="py-1 pr-2 font-medium">Commit</th>
              <th className="py-1 pr-2 font-medium">Tests</th>
              <th className="py-1 font-medium">Reason</th>
            </tr>
          </thead>
          <tbody>
            {data.units.map((unit) => (
              <UnitRow key={unit.unit_id} unit={unit} open={open.has(unit.sequence)} onToggle={() => toggle(unit.sequence)} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
