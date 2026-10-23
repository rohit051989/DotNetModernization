import { useEffect, useState } from 'react'
import { listConversions } from '../../api/conversion'
import { listRepositoryExecutions } from '../../api/repositories'
import { getRepositorySoapCompatibility } from '../../api/surface'
import type { Conversions } from '../../types/conversion'
import type { RepositorySoap } from '../../types/surface'
import type { JobExecution } from '../../types/workflow'
import { num, obj } from '../workflow/artifacts/adapters'
import { needsChange } from './soapNeedsChange'
import type { LatestArtifact, PageArtifactType } from './useLatestArtifacts'

/** One key figure: a number or word, what it is, and whether it calls for attention. Undefined while unknown. */
export interface KeyFigure {
  value: string | number
  detail?: string
  tone?: 'red' | 'amber'
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
  soapCallsNeedingChange?: KeyFigure
  conversion?: KeyFigure
  latestExecution?: KeyFigure & { executionId: string }
  executions?: number
  projects?: number
}

const CONVERSION_STATE: Record<string, string> = { prepared: 'ready', run: 'run', verified: 'verified' }

export function useRepositorySummary(
  repositoryId: string,
  artifacts: Partial<Record<PageArtifactType, LatestArtifact>>,
  refreshToken: number,
): RepositorySummary {
  const [soap, setSoap] = useState<RepositorySoap | null | undefined>(undefined)
  const [conversions, setConversions] = useState<Conversions | null | undefined>(undefined)
  const [executions, setExecutions] = useState<JobExecution[] | undefined>(undefined)

  useEffect(() => {
    let live = true
    getRepositorySoapCompatibility(repositoryId).then((r) => live && setSoap(r), () => live && setSoap(null))
    listConversions(repositoryId).then((r) => live && setConversions(r), () => live && setConversions(null))
    listRepositoryExecutions(repositoryId).then((r) => live && setExecutions(r), () => live && setExecutions([]))
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
  if (soap) {
    const change = soap.calls.filter((c) => c.environments.some(needsChange)).length
    summary.soapCallsNeedingChange = { value: change, detail: `of ${soap.calls.length} SOAP call${soap.calls.length === 1 ? '' : 's'}`, tone: change > 0 ? 'amber' : undefined }
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
  const inventory = artifacts['solution-project-inventory']
  if (inventory) summary.projects = num(obj(inventory.data.summary).project_file_count)
  return summary
}
