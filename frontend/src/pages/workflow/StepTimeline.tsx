import { useEffect, useState } from 'react'
import { getArtifact } from '../../api/workflow'
import { CopyButton } from '../../components/CopyButton'
import { OwnerCodeBadge, StubChip, GateChip, CarriedForwardChip, SkipReasonChip } from '../../components/WorkflowBadges'
import type { ArtifactSummary, StepExecution } from '../../types/workflow'
import { ArtifactContentView } from './artifacts/ArtifactContentView'

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  if (seconds < 60) return `${seconds.toFixed(3)}s`
  return `${Math.round(seconds / 60)}m`
}

const MARKER_CLASS: Record<string, string> = {
  COMPLETED: 'bg-teal-500',
  FAILED: 'bg-red-500',
  STARTED: 'bg-amber-400 animate-pulse',
  STARTING: 'bg-amber-400 animate-pulse',
  NOT_REACHED: 'border-2 border-neutral-200 bg-white',
}

/** 22-STEP-SEQUENCING-AND-POLICY.md Part D's timeline treatment table: a
 * skipped step is always a hollow marker — never visually identical to a
 * step that never ran (that's the empty NOT_REACHED marker, no border-2) —
 * dashed specifically for a policy disable (global or engagement — split by
 * 23-WORKFLOW-ADMINISTRATION.md Part A), solid for the other reasons. */
function markerClass(step: StepExecution): string {
  if (step.exit_status === 'SKIPPED') {
    return step.skip_reason === 'POLICY_DISABLED_GLOBAL' || step.skip_reason === 'POLICY_DISABLED_ENGAGEMENT'
      ? 'border-2 border-dashed border-violet-400 bg-white'
      : 'border-2 border-violet-300 bg-white'
  }
  if (step.exit_status === 'NOT_IMPLEMENTED') return 'bg-neutral-300'
  if (step.carried_forward) return 'border-2 border-dashed border-teal-500 bg-white'
  return MARKER_CLASS[step.batch_status] ?? 'bg-neutral-200'
}

/** hh:mm:ss, or mm:ss under an hour. */
function formatElapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  const two = (n: number) => String(n).padStart(2, '0')
  const h = Math.floor(s / 3600)
  return h > 0 ? `${h}:${two(Math.floor((s % 3600) / 60))}:${two(s % 60)}` : `${two(Math.floor(s / 60))}:${two(s % 60)}`
}

/** A running step's progress (rbc-release-5): the phase, items done out of the total, the current item, and the
 * time since the step started, ticking every second between polls. Once the step has ended without completing — a
 * time limit, a stall, a stop — where it was when it ended. */
function StepProgressLine({ step }: { step: StepExecution }) {
  const running = step.batch_status === 'STARTED' || step.batch_status === 'STARTING'
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [running])

  const progress = step.progress
  if (!running && (!progress || step.exit_status === 'COMPLETED' || step.exit_status === 'SKIPPED')) return null
  const count = progress && (progress.total ? `${progress.done} of ${progress.total}` : progress.done > 0 ? `${progress.done} done` : null)
  const lastHeard = step.progress_at ? Math.round((now - new Date(step.progress_at).getTime()) / 1000) : null
  return (
    <div className={`mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs ${running ? 'text-amber-800' : 'text-red-700'}`}>
      {running && step.started_at && <span className="font-mono">{formatElapsed((now - new Date(step.started_at).getTime()) / 1000)}</span>}
      {!running && <span className="font-medium">stopped at</span>}
      {progress ? (
        <>
          <span className="font-medium">{progress.phase}</span>
          {count && <span>{count}</span>}
          {progress.item && (
            <span className="max-w-md truncate font-mono text-neutral-500" title={progress.item}>
              {progress.item}
            </span>
          )}
          {running && lastHeard !== null && lastHeard > 30 && <span className="text-neutral-500">last progress {formatElapsed(lastHeard)} ago</span>}
        </>
      ) : (
        running && <span className="text-neutral-500">no progress reported yet</span>
      )}
    </div>
  )
}

/** Which step produced an input: from this execution's artifacts, or — for
 * an input carried from an earlier execution — looked up on demand. */
function ProducedBy({ artifactId, known, displayNames }: { artifactId: string; known: ArtifactSummary | undefined; displayNames: Record<string, string> }) {
  const [fetched, setFetched] = useState<{ step: string; other: boolean } | null>(null)
  useEffect(() => {
    if (known) return
    let cancelled = false
    getArtifact(artifactId)
      .then((a) => {
        if (!cancelled) setFetched({ step: a.step_name, other: true })
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [artifactId, known])
  const step = known?.step_name ?? fetched?.step
  if (!step) return <span className="text-neutral-300">—</span>
  return (
    <span className="text-neutral-600">
      {displayNames[step] ?? step}
      {fetched?.other && <span className="text-neutral-400"> (earlier execution)</span>}
    </span>
  )
}

interface StepTimelineProps {
  steps: StepExecution[]
  /** This execution's artifacts, by id — what an input's producing step is read from. */
  artifactsById: Record<string, ArtifactSummary>
  /** The repository's path on this machine, for source links in readable views. */
  localPath: string | null
  onViewArtifact: (artifactId: string) => void
}

export function StepTimeline({ steps, artifactsById, localPath, onViewArtifact }: StepTimelineProps) {
  const displayNames = Object.fromEntries(steps.map((s) => [s.step_name, s.display_name]))
  const [manualExpanded, setManualExpanded] = useState<Record<string, boolean>>({})

  function isExpanded(step: StepExecution): boolean {
    const manual = manualExpanded[step.step_execution_id]
    if (manual !== undefined) return manual
    return step.batch_status === 'FAILED'
  }

  function toggle(step: StepExecution) {
    setManualExpanded((current) => ({ ...current, [step.step_execution_id]: !isExpanded(step) }))
  }

  return (
    <div className="space-y-0">
      {steps.map((step, index) => (
        <div key={step.step_execution_id} className="relative flex gap-3 pb-4">
          <div className="flex flex-col items-center">
            <span className={`mt-1 h-3 w-3 flex-none rounded-full ${markerClass(step)}`} />
            {index < steps.length - 1 && <span className="mt-1 w-px flex-1 bg-neutral-200" />}
          </div>
          <div className={`min-w-0 flex-1 rounded border px-3 py-2 ${step.batch_status === 'FAILED' ? 'border-red-200 bg-red-50/40' : 'border-neutral-200 bg-white'}`}>
            <button type="button" onClick={() => toggle(step)} className="flex w-full flex-wrap items-center gap-2 text-left">
              <span className="font-mono text-xs text-neutral-400">
                #{step.sequence}
                {step.lifecycle_step_no !== null ? ` · L${step.lifecycle_step_no}` : ''}
              </span>
              <span className={`text-sm font-medium ${step.exit_status === 'NOT_IMPLEMENTED' ? 'text-neutral-400' : 'text-neutral-900'}`}>
                {step.display_name}
              </span>
              <OwnerCodeBadge code={step.owner_code} />
              {step.exit_status === 'NOT_IMPLEMENTED' && <StubChip />}
              {step.exit_status === 'AWAITING_APPROVAL' && <GateChip />}
              {step.exit_status === 'SKIPPED' && <SkipReasonChip reason={step.skip_reason} />}
              {step.carried_forward && <CarriedForwardChip />}
              <span
                className={`rounded-full border px-2 py-0.5 text-xs font-medium ${
                  step.batch_status === 'COMPLETED'
                    ? 'border-teal-200 bg-teal-50 text-teal-700'
                    : step.batch_status === 'FAILED'
                      ? 'border-red-200 bg-red-50 text-red-700'
                      : 'border-neutral-200 bg-neutral-50 text-neutral-600'
                }`}
              >
                {step.batch_status}
              </span>
              {/* Skip reasons appear in the collapsed row, not only on expand
                  (Part D) — someone scanning the timeline sees why immediately. */}
              {step.exit_status === 'SKIPPED' && step.exit_message && (
                <span className="max-w-xs truncate text-xs text-neutral-500" title={step.exit_message}>
                  {step.exit_message}
                </span>
              )}
              <span className="text-xs text-neutral-400">{formatDuration(step.duration_seconds)}</span>
              <span className="text-xs text-neutral-400">
                read {step.metrics.read_count} · write {step.metrics.write_count} · skip {step.metrics.skip_count}
              </span>
              <span className="ml-auto text-xs text-neutral-300">{isExpanded(step) ? '▲' : '▼'}</span>
            </button>
            <StepProgressLine step={step} />

            {isExpanded(step) && (
              <div className="mt-3 space-y-3 border-t border-neutral-100 pt-3 text-xs">
                {step.attempt > 1 && <p className="text-neutral-500">Attempt {step.attempt}</p>}
                {step.exit_message && <p className="text-neutral-700">{step.exit_message}</p>}

                {step.inputs_resolved.length > 0 && (
                  <div>
                    <p className="mb-1 font-semibold uppercase tracking-wide text-neutral-400">Inputs resolved</p>
                    <ul className="space-y-0.5">
                      {step.inputs_resolved.map((input) => (
                        <li key={input.artifact_id} className="flex flex-wrap items-baseline gap-x-2">
                          <button type="button" onClick={() => onViewArtifact(input.artifact_id)} className="font-medium text-violet-600 hover:underline">
                            {input.artifact_type}
                          </button>
                          <span className="text-neutral-500">v{input.artifact_version}</span>
                          <span className="text-neutral-400">from</span>
                          <ProducedBy artifactId={input.artifact_id} known={artifactsById[input.artifact_id]} displayNames={displayNames} />
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {step.outputs_produced.length > 0 && (
                  <div className="space-y-2">
                    <p className="font-semibold uppercase tracking-wide text-neutral-400">Outputs produced</p>
                    {step.outputs_produced.map((output) => (
                      <div key={output.artifact_id} className="rounded border border-neutral-200 p-2">
                        <div className="mb-2 flex flex-wrap items-baseline gap-x-2">
                          <span className="font-medium text-neutral-800">{output.artifact_type}</span>
                          <span className="text-neutral-500">v{output.artifact_version}</span>
                          <button type="button" onClick={() => onViewArtifact(output.artifact_id)} className="ml-auto text-violet-600 hover:underline">
                            Open in viewer
                          </button>
                        </div>
                        <ArtifactContentView artifactId={output.artifact_id} artifactType={output.artifact_type} localPath={localPath} />
                      </div>
                    ))}
                  </div>
                )}

                {step.diagnostics.length > 0 && (
                  <div>
                    <p className="mb-1 font-semibold uppercase tracking-wide text-neutral-400">Diagnostics</p>
                    <table className="w-full border-collapse text-left">
                      <thead className="text-neutral-400">
                        <tr>
                          <th className="pr-2 font-medium">Level</th>
                          <th className="pr-2 font-medium">Code</th>
                          <th className="pr-2 font-medium">Message</th>
                          <th className="font-medium">Ref</th>
                        </tr>
                      </thead>
                      <tbody>
                        {step.diagnostics.map((diagnostic, i) => (
                          <tr key={i} className="align-top">
                            <td className="pr-2 text-neutral-500">{diagnostic.level}</td>
                            <td className="pr-2 font-mono text-neutral-500">{diagnostic.code}</td>
                            <td className="pr-2 text-neutral-700">{diagnostic.message}</td>
                            <td className="text-neutral-400">{diagnostic.ref ?? '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                <div>
                  <p className="mb-1 font-semibold uppercase tracking-wide text-neutral-400">stdout</p>
                  {step.stdout_tail ? (
                    <pre className="max-h-32 overflow-auto rounded bg-neutral-900 p-2 font-mono text-[11px] text-neutral-100">{step.stdout_tail}</pre>
                  ) : (
                    <p className="text-neutral-400">No output captured.</p>
                  )}
                </div>
                <div>
                  <p className="mb-1 font-semibold uppercase tracking-wide text-neutral-400">stderr</p>
                  {step.stderr_tail ? (
                    <pre className="max-h-32 overflow-auto rounded bg-neutral-900 p-2 font-mono text-[11px] text-red-300">{step.stderr_tail}</pre>
                  ) : (
                    <p className="text-neutral-400">No output captured.</p>
                  )}
                </div>

                {step.working_dir && (
                  <p className="flex items-center gap-1.5 text-neutral-500">
                    <span className="break-all font-mono">{step.working_dir}</span>
                    <CopyButton value={step.working_dir} />
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
