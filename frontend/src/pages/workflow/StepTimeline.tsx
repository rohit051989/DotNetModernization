import { useState } from 'react'
import { CopyButton } from '../../components/CopyButton'
import { OwnerCodeBadge, StubChip, GateChip, CarriedForwardChip } from '../../components/WorkflowBadges'
import type { StepExecution } from '../../types/workflow'

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

function markerClass(step: StepExecution): string {
  if (step.exit_status === 'NOT_IMPLEMENTED') return 'bg-neutral-300'
  if (step.carried_forward) return 'border-2 border-dashed border-teal-500 bg-white'
  return MARKER_CLASS[step.batch_status] ?? 'bg-neutral-200'
}

interface StepTimelineProps {
  steps: StepExecution[]
  onViewArtifact: (artifactId: string) => void
}

export function StepTimeline({ steps, onViewArtifact }: StepTimelineProps) {
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
          <div className={`flex-1 rounded border px-3 py-2 ${step.batch_status === 'FAILED' ? 'border-red-200 bg-red-50/40' : 'border-neutral-200 bg-white'}`}>
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
              <span className="text-xs text-neutral-400">{formatDuration(step.duration_seconds)}</span>
              <span className="text-xs text-neutral-400">
                read {step.metrics.read_count} · write {step.metrics.write_count} · skip {step.metrics.skip_count}
              </span>
              <span className="ml-auto text-xs text-neutral-300">{isExpanded(step) ? '▲' : '▼'}</span>
            </button>

            {isExpanded(step) && (
              <div className="mt-3 space-y-3 border-t border-neutral-100 pt-3 text-xs">
                {step.attempt > 1 && <p className="text-neutral-500">Attempt {step.attempt}</p>}
                {step.exit_message && <p className="text-neutral-700">{step.exit_message}</p>}

                {step.inputs_resolved.length > 0 && (
                  <div>
                    <p className="mb-1 font-semibold uppercase tracking-wide text-neutral-400">Inputs resolved</p>
                    <ul className="space-y-1">
                      {step.inputs_resolved.map((input) => (
                        <li key={input.artifact_id}>
                          <button type="button" onClick={() => onViewArtifact(input.artifact_id)} className="text-violet-600 hover:underline">
                            {input.logical_name}: {input.artifact_type}@{input.artifact_version}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {step.outputs_produced.length > 0 && (
                  <div>
                    <p className="mb-1 font-semibold uppercase tracking-wide text-neutral-400">Outputs produced</p>
                    <ul className="space-y-1">
                      {step.outputs_produced.map((output) => (
                        <li key={output.artifact_id}>
                          <button type="button" onClick={() => onViewArtifact(output.artifact_id)} className="text-violet-600 hover:underline">
                            {output.artifact_type}@{output.artifact_version}
                          </button>
                        </li>
                      ))}
                    </ul>
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
                    <span className="font-mono">{step.working_dir}</span>
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
