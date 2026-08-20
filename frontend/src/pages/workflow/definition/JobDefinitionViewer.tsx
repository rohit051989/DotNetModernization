import { useCallback, useEffect, useState } from 'react'
import { getJobDefinitionView } from '../../../api/workflow'
import { CopyButton } from '../../../components/CopyButton'
import { AdapterTypeChip, ImplementationStatusChip, OwnerCodeBadge } from '../../../components/WorkflowBadges'
import type { ArtifactRefView, FlowStepView, JobDefinitionView } from '../../../types/workflow'
import { StepPolicyDialog } from './StepPolicyDialog'
import { policyOwnRow, policyStatusText, policyToggleLabel } from './policyPresentation'

interface JobDefinitionViewerProps {
  jobName: string
  /** Null (or omitted) selects master scope — policy state resolves only
   * the global and default layers, per 23-WORKFLOW-ADMINISTRATION.md Part
   * C2: "in master scope with no engagement selected — so policy state
   * shows global and default only." */
  engagementId?: string | null
}

interface ArtifactChipProps {
  artifact: ArtifactRefView
  kind: 'consumes' | 'produces'
  hoveredType: string | null
  onHoverType: (type: string | null) => void
}

/** Producer-to-consumer highlighting — 22-STEP-SEQUENCING-AND-POLICY.md Part
 * E: "hovering a produces chip highlights the matching consumes chip
 * downstream." Hover state is lifted to the viewer so a produces chip on one
 * card and a consumes chip on another light up together by shared
 * artifact_type. */
function ArtifactChip({ artifact, kind, hoveredType, onHoverType }: ArtifactChipProps) {
  const label =
    kind === 'produces'
      ? `${artifact.artifact_type}@${artifact.artifact_version}`
      : `${artifact.artifact_type} ${artifact.version_range ?? ''}${artifact.optional ? ' (optional)' : ''}`.trim()
  const highlighted = hoveredType === artifact.artifact_type

  return (
    <span
      onMouseEnter={() => onHoverType(artifact.artifact_type)}
      onMouseLeave={() => onHoverType(null)}
      className={`cursor-default rounded-full border px-2 py-0.5 font-mono text-[10px] transition-colors ${
        highlighted
          ? 'border-violet-500 bg-violet-100 text-violet-800 ring-1 ring-violet-400'
          : kind === 'produces'
            ? 'border-teal-200 bg-teal-50 text-teal-700'
            : 'border-sky-200 bg-sky-50 text-sky-700'
      }`}
    >
      {label}
    </span>
  )
}

interface FlowStepCardProps {
  step: FlowStepView
  isMasterScope: boolean
  hoveredType: string | null
  onHoverType: (type: string | null) => void
  onTogglePolicy: () => void
}

function FlowStepCard({ step, isMasterScope, hoveredType, onHoverType, onTogglePolicy }: FlowStepCardProps) {
  const inputEntries = Object.entries(step.inputs)
  const toggleLabel = policyToggleLabel(step.policy, isMasterScope)

  return (
    <div
      className={`rounded border px-3 py-2 ${
        step.policy.enabled ? 'border-neutral-200 bg-white' : 'border-dashed border-neutral-300 bg-neutral-50'
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-neutral-400">
          #{step.sequence}
          {step.lifecycle_step_no !== null ? ` · L${step.lifecycle_step_no}` : ''}
        </span>
        <span className="text-sm font-medium text-neutral-900">{step.display_name}</span>
        <OwnerCodeBadge code={step.owner_code} />
        <AdapterTypeChip adapterType={step.adapter_type} />
        <ImplementationStatusChip status={step.implementation_status} />
        <span className="ml-auto font-mono text-xs text-neutral-400">v{step.step_version}</span>
      </div>

      {(step.consumes.length > 0 || step.produces.length > 0) && (
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          {step.consumes.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-neutral-400">consumes</span>
              {step.consumes.map((c, i) => (
                <ArtifactChip key={i} artifact={c} kind="consumes" hoveredType={hoveredType} onHoverType={onHoverType} />
              ))}
            </div>
          )}
          {step.produces.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-neutral-400">produces</span>
              {step.produces.map((p, i) => (
                <ArtifactChip key={i} artifact={p} kind="produces" hoveredType={hoveredType} onHoverType={onHoverType} />
              ))}
            </div>
          )}
        </div>
      )}

      {inputEntries.length > 0 && (
        <div className="mt-2 text-xs text-neutral-500">
          <span className="text-neutral-400">inputs</span>{' '}
          {inputEntries.map(([name, expr], i) => (
            <span key={name} className="font-mono">
              {i > 0 && <span className="text-neutral-300">, </span>}
              {name} ← {expr}
            </span>
          ))}
        </div>
      )}

      {step.when_description && <p className="mt-2 text-xs italic text-neutral-500">{step.when_description}</p>}

      <div className="mt-2 flex items-center justify-between border-t border-neutral-100 pt-2 text-xs">
        <span className={step.policy.enabled ? 'text-neutral-500' : 'font-medium text-red-600'}>
          {policyStatusText(step.policy)}
        </span>
        <button type="button" onClick={onTogglePolicy} className="text-violet-600 hover:underline">
          {toggleLabel}
        </button>
      </div>
    </div>
  )
}

/** The job definition viewer — 22-STEP-SEQUENCING-AND-POLICY.md Part E.
 * Read-only over the YAML; only policy state (engagement-scoped) is
 * editable, via StepPolicyDialog. */
export function JobDefinitionViewer({ jobName, engagementId }: JobDefinitionViewerProps) {
  const isMasterScope = !engagementId
  const [view, setView] = useState<JobDefinitionView | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [hoveredType, setHoveredType] = useState<string | null>(null)
  const [rawYamlOpen, setRawYamlOpen] = useState(false)
  const [policyTarget, setPolicyTarget] = useState<FlowStepView | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setLoadError(null)
    getJobDefinitionView(jobName, engagementId ?? undefined)
      .then(setView)
      .catch(() => setLoadError('Could not load this job definition.'))
      .finally(() => setLoading(false))
  }, [jobName, engagementId])

  useEffect(() => {
    load()
  }, [load])

  if (loading) return <p className="p-4 text-sm text-neutral-400">Loading definition…</p>
  if (loadError || !view) return <p className="p-4 text-sm text-red-600">{loadError ?? 'Definition not found.'}</p>

  // 23-WORKFLOW-ADMINISTRATION.md Part D: "The policy summary strip lists
  // every step whose effective state differs from default, with the layer
  // responsible." Not just engagement-sourced any more — a global disable
  // is a deviation too.
  const disabledSteps = view.flow.filter((s) => s.policy.source !== 'default' && !s.policy.enabled)

  return (
    <section className="space-y-4 rounded border border-neutral-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-neutral-100 pb-3">
        <div>
          <h2 className="text-base font-semibold text-neutral-900">{view.job_name}</h2>
          {view.description && <p className="text-sm text-neutral-500">{view.description}</p>}
        </div>
        <div className="flex flex-col items-end gap-1 text-xs text-neutral-500">
          <span>
            v{view.version} · {view.validation_status}
            {view.is_active ? ' · active' : ''}
          </span>
          <span className="font-medium text-neutral-700">
            {view.implemented_step_count} of {view.step_count} steps implemented
          </span>
        </div>
      </div>

      <div>
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral-400">Parameters</h3>
        <table className="w-full text-left text-xs">
          <thead className="text-neutral-400">
            <tr>
              <th className="py-1 pr-3 font-medium">Name</th>
              <th className="py-1 pr-3 font-medium">Type</th>
              <th className="py-1 pr-3 font-medium">Required</th>
              <th className="py-1 pr-3 font-medium">Default</th>
              <th className="py-1 font-medium">Description</th>
            </tr>
          </thead>
          <tbody>
            {view.parameters.map((p) => (
              <tr key={p.name} className="border-t border-neutral-100">
                <td className="py-1 pr-3 font-mono text-neutral-700">{p.name}</td>
                <td className="py-1 pr-3 text-neutral-500">{p.type}</td>
                <td className="py-1 pr-3 text-neutral-500">{p.required ? 'yes' : 'no'}</td>
                <td className="py-1 pr-3 text-neutral-500">{p.default != null ? String(p.default) : '—'}</td>
                <td className="py-1 text-neutral-500">{p.description ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {disabledSteps.length > 0 && (
        <div className="rounded border border-amber-200 bg-amber-50 p-3 text-xs">
          <p className="mb-1 font-semibold uppercase tracking-wide text-amber-700">Policy — deviations from default</p>
          <ul className="space-y-1">
            {disabledSteps.map((s) => (
              <li key={s.step_name} className="text-amber-800">
                <span className="font-medium">{s.display_name}</span> disabled{' '}
                <span className="rounded bg-amber-100 px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700">
                  {s.policy.source}
                </span>
                {s.policy.reason ? ` — ${s.policy.reason}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-400">Flow</h3>
        <div className="space-y-2">
          {view.flow.map((step) => (
            <FlowStepCard
              key={step.step_name}
              step={step}
              isMasterScope={isMasterScope}
              hoveredType={hoveredType}
              onHoverType={setHoveredType}
              onTogglePolicy={() => setPolicyTarget(step)}
            />
          ))}
        </div>
      </div>

      <div>
        <button
          type="button"
          onClick={() => setRawYamlOpen((open) => !open)}
          className="text-xs font-semibold uppercase tracking-wide text-neutral-400 hover:text-neutral-600"
        >
          {rawYamlOpen ? '▲' : '▼'} Raw YAML
        </button>
        {rawYamlOpen &&
          (view.raw_yaml ? (
            <div className="relative mt-2">
              <pre className="max-h-96 overflow-auto rounded bg-neutral-900 p-3 font-mono text-[11px] text-neutral-100">
                {view.raw_yaml}
              </pre>
              <div className="absolute right-2 top-2">
                <CopyButton value={view.raw_yaml} />
              </div>
            </div>
          ) : (
            <p className="mt-2 text-xs text-neutral-400">Not recorded for this stored version.</p>
          ))}
      </div>

      {policyTarget && (
        <StepPolicyDialog
          scope={isMasterScope ? 'global' : { engagementId: engagementId as string }}
          stepName={policyTarget.step_name}
          displayName={policyTarget.display_name}
          effectiveEnabled={policyTarget.policy.enabled}
          ownRow={policyOwnRow(policyTarget.policy, isMasterScope)}
          onClose={() => setPolicyTarget(null)}
          onChanged={load}
        />
      )}
    </section>
  )
}
