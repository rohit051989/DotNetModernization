import { Fragment, useEffect, useMemo, useState } from 'react'
import { listSteps } from '../../api/registration'
import { AdapterTypeChip, ImplementationStatusChip, OwnerCodeBadge } from '../../components/WorkflowBadges'
import { JsonTreeView } from '../../components/JsonTreeView'
import type { StepRegistration } from '../../types/registration'
import { PHASES, UNASSIGNED_PHASE_NAME, phaseForStep } from './phases'

const ALL = '__all__'

/** 23-WORKFLOW-ADMINISTRATION.md Part C1 — read-only inspection of every
 * registered step. Registration is a build-time, API-only operation; there
 * is nothing to mutate here. */
export function StepRegistrySection() {
  const [steps, setSteps] = useState<StepRegistration[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState(ALL)
  const [ownerFilter, setOwnerFilter] = useState(ALL)
  const [adapterFilter, setAdapterFilter] = useState(ALL)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  useEffect(() => {
    setLoading(true)
    listSteps()
      .then(setSteps)
      .catch(() => setLoadError('Could not load the step registry.'))
      .finally(() => setLoading(false))
  }, [])

  const { ownerCodes, adapterTypes } = useMemo(() => {
    const owners = new Set<string>()
    const adapters = new Set<string>()
    for (const s of steps) {
      owners.add(s.owner_code)
      adapters.add(s.adapter_type)
    }
    return { ownerCodes: Array.from(owners).sort(), adapterTypes: Array.from(adapters).sort() }
  }, [steps])

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase()
    return steps.filter((s) => {
      if (statusFilter !== ALL && s.implementation_status !== statusFilter) return false
      if (ownerFilter !== ALL && s.owner_code !== ownerFilter) return false
      if (adapterFilter !== ALL && s.adapter_type !== adapterFilter) return false
      if (query && !s.step_name.toLowerCase().includes(query) && !s.display_name.toLowerCase().includes(query)) return false
      return true
    })
  }, [steps, statusFilter, ownerFilter, adapterFilter, search])

  const grouped = useMemo(() => {
    const byPhase = new Map<string, StepRegistration[]>()
    for (const phase of PHASES) byPhase.set(phase.name, [])
    byPhase.set(UNASSIGNED_PHASE_NAME, [])
    for (const step of filtered) {
      const phase = phaseForStep(step.lifecycle_step_no)
      byPhase.get(phase)!.push(step)
    }
    for (const list of byPhase.values()) list.sort((a, b) => (a.lifecycle_step_no ?? 0) - (b.lifecycle_step_no ?? 0))
    return byPhase
  }, [filtered])

  // Per-phase implemented counts are computed from the FULL registry, not
  // the filtered set — "Phase 0 — 3 of 12 implemented" is a fact about the
  // platform, not about the current filter.
  const phaseCounts = useMemo(() => {
    const counts = new Map<string, { total: number; implemented: number }>()
    for (const phase of PHASES) counts.set(phase.name, { total: 0, implemented: 0 })
    counts.set(UNASSIGNED_PHASE_NAME, { total: 0, implemented: 0 })
    for (const step of steps) {
      const phase = phaseForStep(step.lifecycle_step_no)
      const entry = counts.get(phase)!
      entry.total += 1
      if (step.implementation_status === 'implemented') entry.implemented += 1
    }
    return counts
  }, [steps])

  if (loading) return <p className="p-4 text-sm text-neutral-400">Loading step registry…</p>
  if (loadError) return <p className="p-4 text-sm text-red-600">{loadError}</p>

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search step name or display name…"
          className="w-64 rounded border border-neutral-300 px-2 py-1.5 text-sm focus:border-violet-400 focus:outline-none"
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded border border-neutral-300 px-2 py-1.5 text-sm"
        >
          <option value={ALL}>All statuses</option>
          <option value="implemented">implemented</option>
          <option value="stub">stub</option>
          <option value="deprecated">deprecated</option>
        </select>
        <select
          value={ownerFilter}
          onChange={(e) => setOwnerFilter(e.target.value)}
          className="rounded border border-neutral-300 px-2 py-1.5 text-sm"
        >
          <option value={ALL}>All owner codes</option>
          {ownerCodes.map((code) => (
            <option key={code} value={code}>
              {code}
            </option>
          ))}
        </select>
        <select
          value={adapterFilter}
          onChange={(e) => setAdapterFilter(e.target.value)}
          className="rounded border border-neutral-300 px-2 py-1.5 text-sm"
        >
          <option value={ALL}>All adapter types</option>
          {adapterTypes.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
        <span className="text-xs text-neutral-400">
          {filtered.length} of {steps.length} steps
        </span>
      </div>

      {[...PHASES.map((p) => p.name), UNASSIGNED_PHASE_NAME].map((phaseName) => {
        const phaseSteps = grouped.get(phaseName) ?? []
        const counts = phaseCounts.get(phaseName)
        if (phaseSteps.length === 0) return null
        return (
          <section key={phaseName} className="rounded border border-neutral-200 bg-white">
            <div className="flex items-center justify-between border-b border-neutral-100 px-4 py-2">
              <h3 className="text-sm font-semibold text-neutral-900">{phaseName}</h3>
              {counts && (
                <span className="text-xs font-medium text-neutral-500">
                  {counts.implemented} of {counts.total} implemented
                </span>
              )}
            </div>
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-neutral-500">
                <tr>
                  <th className="px-4 py-2 font-medium">#</th>
                  <th className="px-3 py-2 font-medium">Step name</th>
                  <th className="px-3 py-2 font-medium">Display name</th>
                  <th className="px-3 py-2 font-medium">Owner</th>
                  <th className="px-3 py-2 font-medium">Viewpoint</th>
                  <th className="px-3 py-2 font-medium">Adapter</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Version</th>
                  <th className="px-3 py-2 font-medium">Owner team</th>
                  <th className="px-3 py-2 font-medium">Consumes</th>
                  <th className="px-3 py-2 font-medium">Produces</th>
                </tr>
              </thead>
              <tbody>
                {phaseSteps.map((step) => (
                  <Fragment key={step.step_name}>
                    <tr
                      className="cursor-pointer border-b border-neutral-100 hover:bg-neutral-50"
                      onClick={() => setExpanded((cur) => ({ ...cur, [step.step_name]: !cur[step.step_name] }))}
                    >
                      <td className="px-4 py-2 font-mono text-xs text-neutral-400">{step.lifecycle_step_no ?? '—'}</td>
                      <td className="px-3 py-2 font-mono text-xs text-neutral-700">{step.step_name}</td>
                      <td className="px-3 py-2 text-neutral-700">{step.display_name}</td>
                      <td className="px-3 py-2">
                        <OwnerCodeBadge code={step.owner_code} />
                      </td>
                      <td className="px-3 py-2 text-xs text-neutral-500">
                        {step.viewpoint && step.viewpoint !== 'NONE' ? step.viewpoint : '—'}
                      </td>
                      <td className="px-3 py-2">
                        <AdapterTypeChip adapterType={step.adapter_type} />
                      </td>
                      <td className="px-3 py-2">
                        <ImplementationStatusChip status={step.implementation_status} />
                      </td>
                      <td className="px-3 py-2 font-mono text-xs text-neutral-500">{step.version}</td>
                      <td className="px-3 py-2 text-xs text-neutral-500">{step.owner_team ?? '—'}</td>
                      <td className="px-3 py-2 text-xs text-neutral-500">
                        {step.consumes.length === 0 ? '—' : step.consumes.map((c) => c.artifact_type).join(', ')}
                      </td>
                      <td className="px-3 py-2 text-xs text-neutral-500">
                        {step.produces.length === 0 ? '—' : step.produces.map((p) => p.artifact_type).join(', ')}
                      </td>
                    </tr>
                    {expanded[step.step_name] && (
                      <tr className="border-b border-neutral-100 bg-neutral-50">
                        <td colSpan={11} className="px-4 py-3">
                          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral-400">
                            adapter_config — where this step actually runs from
                          </p>
                          <JsonTreeView value={step.adapter_config} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </section>
        )
      })}
    </div>
  )
}
