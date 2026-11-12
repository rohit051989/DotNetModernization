import { useEffect, useState } from 'react'
import { listConversions } from '../../api/conversion'
import { listRepositoryExecutions } from '../../api/repositories'
import { getCompatibilitySummary, getSoapSummary } from '../../api/results'
import type { CompatibilitySummary } from '../../types/compatibility'
import { getConversionScope } from '../../api/scope'
import type { Conversions } from '../../types/conversion'
import type { SoapSummary } from '../../types/results'
import type { JobExecution } from '../../types/workflow'
import { num, obj } from '../workflow/artifacts/adapters'
import type { LatestArtifact, PageArtifactType } from './useLatestArtifacts'

/** One key figure: a number or word, what it is, and whether it calls for attention. Undefined while unknown. */
export interface KeyFigure {
  value: string | number
  detail?: string
  tone?: 'red' | 'amber'
  /** Still being read: the card shows a loader in place of the figure, never a partial one. */
  loading?: boolean
}

/**
 * The key figure from each tab — the Overview's summary and the tab labels' counts. From the artifacts the page already
 * holds, and three small reads of its own: the SOAP calls, the conversions and the executions. None of these is a
 * tab's content: a tab still loads its own the first time it is opened.
 */
export interface RepositorySummary {
  workItems?: KeyFigure
  requestEntryPoints?: KeyFigure
  dependenciesNeedingChange?: KeyFigure
  /** SOAP calls needing change, plus the Linux findings: the Compatibility tab's total. */
  compatibilityIssues?: KeyFigure
  conversion?: KeyFigure
  latestExecution?: KeyFigure & { executionId: string }
  executions?: number
  projects?: number
  /** The conversion scope's totals: projects kept and excluded. */
  scope?: { kept: number; excluded: number; projects: number; workItemsOutOfScope: number }
}

const CONVERSION_STATE: Record<string, string> = { prepared: 'ready', run: 'run', verified: 'verified' }

export function useRepositorySummary(
  repositoryId: string,
  artifacts: Partial<Record<PageArtifactType, LatestArtifact>>,
  refreshToken: number,
  /** Whether the repository moves from Windows to Linux (hosting.ts): when it does not, Linux findings are not counted. */
  showLinux = true,
): RepositorySummary {
  const [soap, setSoap] = useState<SoapSummary | null | undefined>(undefined)
  const [compatibility, setCompatibility] = useState<CompatibilitySummary | null | undefined>(undefined)
  const [conversions, setConversions] = useState<Conversions | null | undefined>(undefined)
  const [executions, setExecutions] = useState<JobExecution[] | undefined>(undefined)
  const [scope, setScope] = useState<RepositorySummary['scope'] | null>(undefined)

  useEffect(() => {
    let live = true
    getSoapSummary(repositoryId).then((r) => live && setSoap(r), () => live && setSoap(null))
    getCompatibilitySummary(repositoryId).then((r) => live && setCompatibility(r), () => live && setCompatibility(null))
    listConversions(repositoryId).then((r) => live && setConversions(r), () => live && setConversions(null))
    listRepositoryExecutions(repositoryId).then((r) => live && setExecutions(r), () => live && setExecutions([]))
    getConversionScope(repositoryId).then((r) => live && setScope(r.totals), () => live && setScope(null))
    return () => {
      live = false
    }
  }, [repositoryId, refreshToken])

  const summary: RepositorySummary = {}
  const work = artifacts['item-occurrences']
  if (work) {
    const s = obj(work.data.summary)
    const found = num(s.found) - num(s.possible_only_found)
    summary.workItems = { value: found, detail: num(s.not_checked) > 0 ? `${num(s.not_checked)} not checked` : undefined }
  }
  const inbound = artifacts['entry-point-inventory']
  if (inbound) summary.requestEntryPoints = { value: num(obj(inbound.data.summary).requestEntryPointCount) }
  const dependencies = artifacts['dependency-assessment']
  if (dependencies) {
    const s = obj(dependencies.data.summary)
    const outcomes = obj(s.countByOutcome)
    const breaking = num(outcomes.upgrade_breaking) + num(outcomes.no_compatible_version)
    const change = breaking + num(outcomes.upgrade_safe) + num(outcomes.framework_provided)
    summary.dependenciesNeedingChange = {
      value: change,
      detail: `of ${num(s.packageCount)}${breaking > 0 ? ` · ${breaking} breaking or with no compatible version` : ''}${num(s.vulnerableCount) > 0 ? ` · ${num(s.vulnerableCount)} vulnerable` : ''}`,
      tone: breaking > 0 || num(s.vulnerableCount) > 0 ? 'amber' : undefined,
    }
  }
  // A repository that is not moving from Windows to Linux has no Linux tab, so its Linux findings are not counted.
  const linuxCounted = showLinux ? compatibility : null
  if (soap === undefined || (showLinux && compatibility === undefined)) {
    // The total is the sum of two reads: nothing is shown until both have come back (or failed).
    summary.compatibilityIssues = { value: '', loading: true }
  } else if (soap || linuxCounted) {
    // Counted by the server, and the same numbers as the Compatibility tab's inner tabs (SOAP calls, and Linux
    // findings when that tab is shown), so the total is what the tab shows. The tone says when a SOAP call needs change.
    const soapChange = soap?.need_change ?? 0
    const soapCalls = soap?.calls ?? 0
    const linux = linuxCounted?.linux ?? 0
    summary.compatibilityIssues = {
      value: soapCalls + linux,
      detail: showLinux ? `SOAP ${soapCalls} · Linux ${linux}` : `SOAP ${soapCalls}`,
      tone: soapChange > 0 || (linuxCounted?.linux_blockers ?? 0) > 0 ? 'amber' : undefined,
    }
  }
  if (conversions) {
    const newest = conversions.conversions[0]
    summary.conversion = newest
      ? { value: CONVERSION_STATE[newest.state] ?? newest.state, detail: `conversion ${newest.number} · ${newest.branch}` }
      : { value: 'none yet', detail: `the next would be conversion ${conversions.next.number}` }
  }
  if (executions) {
    summary.executions = executions.length
    const latest = executions[0]
    if (latest) {
      const failed = latest.batch_status === 'FAILED' || latest.exit_status === 'FAILED'
      summary.latestExecution = {
        executionId: latest.id,
        value: (latest.exit_status ?? latest.batch_status).toLowerCase().replaceAll('_', ' '),
        detail: latest.started_at ? new Date(latest.started_at).toLocaleString() : undefined,
        tone: failed ? 'red' : undefined,
      }
    }
  }
  if (scope) summary.scope = scope
  const inventory = artifacts['solution-project-inventory']
  if (inventory) summary.projects = num(obj(inventory.data.summary).project_file_count)
  return summary
}
