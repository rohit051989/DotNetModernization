import type { ReactNode } from 'react'
import type { RepositoryDetail } from '../../types/repositories'
import type { TabSlug } from './repositoryTabs'
import type { KeyFigure, RepositorySummary } from './useRepositorySummary'

interface OverviewProps {
  repo: RepositoryDetail
  summary: RepositorySummary
  /** The summary cards: size, files, main language, projects, request entry points and the rest. */
  tiles: ReactNode
  onOpenTab: (tab: TabSlug) => void
}

/** The Overview tab: the repository's summary cards, then the key figure from each tab, each a link into its tab. */
export function RepositoryOverview({ repo, summary, tiles, onOpenTab }: OverviewProps) {
  const figures: { label: string; tab: TabSlug; figure: KeyFigure | undefined; awaiting: string }[] = [
    { label: 'Work items', tab: 'work-list', figure: summary.workItems, awaiting: 'item-detection has not run' },
    { label: 'Request entry points', tab: 'surface', figure: summary.requestEntryPoints, awaiting: 'entry-point-inventory has not run' },
    { label: 'Dependencies needing change', tab: 'dependencies', figure: summary.dependenciesNeedingChange, awaiting: 'dependency-assessment has not run' },
    { label: 'SOAP calls needing change', tab: 'surface', figure: summary.soapCallsNeedingChange, awaiting: 'no SOAP calls recorded' },
    { label: 'Conversion', tab: 'conversion', figure: summary.conversion, awaiting: 'no conversion yet' },
    { label: 'Latest execution', tab: 'executions', figure: summary.latestExecution, awaiting: 'discovery has not run' },
  ]

  return (
    <div className="space-y-4">
      <div className="text-xs text-neutral-400">
        {/* The folder it was registered from, on its owner's machine; each person's own is "your clone", above. */}
        <p className="break-all">
          Registered from <span className="font-mono">{repo.local_path}</span>
          {repo.registered_host && <> on {repo.registered_host}</>}
        </p>
        {repo.source_type === 'git_clone' && repo.clone_url && (
          <p className="break-all">
            Cloned from <span className="font-mono">{repo.clone_url}</span>
            {repo.default_branch && <> ({repo.default_branch})</>}; Rescan fetches and fast-forwards it first.
          </p>
        )}
      </div>

      {tiles}

      <section aria-label="Key figures" className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {figures.map(({ label, tab, figure, awaiting }) => {
          const tone =
            figure?.tone === 'red' ? 'border-red-200 bg-red-50' : figure?.tone === 'amber' ? 'border-amber-200 bg-amber-50' : 'border-neutral-200 bg-white'
          return (
            <button
              key={label}
              type="button"
              onClick={() => onOpenTab(tab)}
              className={`min-w-0 rounded border px-3 py-2 text-left hover:border-violet-300 hover:shadow-sm ${tone}`}
            >
              <span className="block text-[11px] font-medium uppercase tracking-wide text-neutral-400">{label}</span>
              <span className="block truncate text-lg font-semibold text-neutral-900">
                {figure ? figure.value : <span className="text-neutral-300">—</span>}
              </span>
              <span className="block truncate text-xs text-neutral-500">{figure ? (figure.detail ?? ' ') : awaiting}</span>
              <span className="mt-0.5 block text-[11px] text-violet-600">Open {tabLabel(tab)} →</span>
            </button>
          )
        })}
      </section>
    </div>
  )
}

function tabLabel(tab: TabSlug): string {
  return { 'work-list': 'Work list', surface: 'Surface', dependencies: 'Dependencies', conversion: 'Conversion', executions: 'Executions' }[tab as string] ?? tab
}
