import type { FailedScan } from '../../types/results'
import type { TabSlug } from './repositoryTabs'

/** The discovery steps whose results each tab shows. A tab whose step did not complete in a failed run shows an
 * earlier run's results, and says so. */
export const TAB_STEPS: Partial<Record<TabSlug, string[]>> = {
  surface: ['entry-point-inventory', 'outbound-invocation-inventory'],
  compatibility: ['entry-point-inventory', 'outbound-invocation-inventory'],
  projects: ['solution-discovery', 'application-fingerprinting'],
  dependencies: ['dependency-assessment'],
  'dependency-graph': ['dependency-hierarchy'],
  impact: ['impact-analysis'],
  tests: ['test-coverage-assessment'],
  scope: ['solution-discovery', 'item-detection'],
  'work-list': ['item-detection'],
  conversion: ['conversion-preparation'],
}

function when(at: string): string {
  return new Date(at).toLocaleString()
}

/** The page header's notice: the latest discovery run failed, at which step and when, with a link to the Activity tab. */
export function FailedScanBanner({ failed, onOpenActivity }: { failed: FailedScan; onOpenActivity: () => void }) {
  return (
    <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800" data-testid="failed-scan">
      <p>
        The latest scan, on {when(failed.at)},{' '}
        {failed.failed_step ? (
          <>
            failed at <span className="font-mono text-xs">{failed.failed_step}</span>
          </>
        ) : (
          <>ended {failed.status.toLowerCase()}</>
        )}
        {failed.message ? `: ${failed.message}` : '.'}{' '}
        <button type="button" onClick={onOpenActivity} className="font-medium text-red-900 underline hover:no-underline">
          Open Activity
        </button>
      </p>
      <p className="mt-0.5 text-xs text-red-700">
        Tabs fed by the steps it did not complete show an earlier scan's results, and say so. No conversion is prepared
        until a scan completes.
      </p>
    </div>
  )
}

/** On a tab whose results are older because the latest run failed: which, and from when. Nothing otherwise. */
export function OlderResultsNotice({ failed, tab }: { failed: FailedScan | null | undefined; tab: TabSlug }) {
  if (!failed) return null
  const older = (TAB_STEPS[tab] ?? []).filter((step) => step in failed.results_from)
  if (older.length === 0) return null
  const dates = older.map((step) => failed.results_from[step]).filter((d): d is string => !!d).sort()
  return (
    <p className="mb-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800" data-testid="older-results">
      {dates.length > 0 ? (
        <>Older results, from the scan of {when(dates[0])}</>
      ) : (
        <>No results yet</>
      )}
      : the latest scan ({when(failed.at)}) did not complete {older.map((s, i) => (
        <span key={s}>
          {i > 0 && ', '}
          <span className="font-mono text-xs">{s}</span>
        </span>
      ))}
      .
    </p>
  )
}
