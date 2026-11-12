import { useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import { getCompatibilitySummary, getSoapSummary, linuxCompatibility } from '../../api/results'
import { PagedList } from '../../components/PagedList'
import type { PageLoader } from '../../components/PagedList'
import type { CompatibilityFinding, CompatibilitySummary, Treatment } from '../../types/compatibility'
import type { SoapSummary } from '../../types/results'
import { counted } from './repositoryTabs'
import { RepositorySoapPanel } from './RepositorySoapPanel'
import { SourceLink } from './SourceLink'

// The Compatibility tab: what in this repository will not work, or needs a change, on the modern
// stack on Linux/OpenShift. Two inner tabs: SOAP (RepositorySoapPanel) and Linux. Each reads the database a page at a
// time; nothing here reads a file. Breaking package upgrades and packages to replace are on the Dependencies tab and
// the Work list, not repeated here. The Linux tab is for a repository moving from Windows to Linux hosting only
// (hosting.ts); for any other it is not shown, and SOAP stands alone.

interface Props {
  repositoryId: string
  /** The repository's path on this machine: file links open in the person's editor from their own clone. */
  localPath: string
  refreshToken: number
  /** Whether the Linux tab is shown: the repository moves from Windows to Linux hosting (showsLinux in hosting.ts). */
  showLinux?: boolean
  /** Opens a SOAP call's row in the Estate tab's SOAP compatibility report. */
  onOpenEstateSoap?: (invocationId: string) => void
}

const KIND_LABEL: Record<CompatibilityFinding['kind'], string> = {
  item: 'catalog item',
  package: 'Windows-only package',
}

const BADGE: Record<Treatment, { label: string; style: string; help: string }> = {
  blocker: { label: 'Blocker', style: 'border-red-200 bg-red-50 text-red-700', help: 'Fails on Linux, or does not exist on modern .NET: it must change before the application runs.' },
  container: { label: 'Needs container change', style: 'border-amber-200 bg-amber-50 text-amber-800', help: 'Runs on Linux, but needs a change to run well in an OpenShift container.' },
  other: { label: 'Review', style: 'border-neutral-300 bg-neutral-100 text-neutral-600', help: 'Runs, but behaves differently or its host model changes.' },
}

/** The Linux counts: read only when the Linux tab is shown. */
function useSummary(repositoryId: string, refreshToken: number, enabled: boolean) {
  const [data, setData] = useState<CompatibilitySummary | null>(null)
  const [notScanned, setNotScanned] = useState(false)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let cancelled = false
    setData(null)
    setNotScanned(false)
    setFailed(false)
    if (!enabled) return
    getCompatibilitySummary(repositoryId)
      .then((result) => {
        if (!cancelled) setData(result)
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 409) setNotScanned(true)
        else setFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [repositoryId, refreshToken, enabled])
  return { data, notScanned, failed }
}

/** The project, and the file where the finding is: each opens in the editor like a file link on any other tab. A
 * finding with no file of its own (a package) links to its project file. */
function Where({ finding, localPath }: { finding: CompatibilityFinding; localPath: string }) {
  return (
    <>
      <SourceLink localPath={localPath} filePath={finding.project} line={1} className="block font-mono text-[10px] text-neutral-500">
        {finding.project}
      </SourceLink>
      {finding.file && (
        <SourceLink localPath={localPath} filePath={finding.file} line={1} className="block break-all font-mono text-[10px] text-violet-700">
          {finding.file}
        </SourceLink>
      )}
    </>
  )
}

function FindingRow({ finding, localPath }: { finding: CompatibilityFinding; localPath: string }) {
  return (
    <tr className="border-t border-neutral-100 align-top">
      <td className="py-1 pr-3">
        {finding.treatment && (
          <span title={BADGE[finding.treatment].help} className={`whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] ${BADGE[finding.treatment].style}`}>
            {BADGE[finding.treatment].label}
          </span>
        )}
      </td>
      <td className="py-1 pr-3">
        <span className="font-medium text-neutral-800">{finding.itemName}</span>
        <span className="block text-[10px] text-neutral-400">
          {KIND_LABEL[finding.kind]}
          {finding.kind === 'item' ? ` · ${finding.category}` : ''}
          {finding.certainty === 'possible' ? ' · possible' : ''}
        </span>
      </td>
      <td className="py-1 pr-3">
        <Where finding={finding} localPath={localPath} />
      </td>
      <td className="py-1 pr-3 font-mono text-[11px]">
        {finding.value ?? ''}
      </td>
      <td className="max-w-[24rem] py-1 text-[11px] text-neutral-600">
        {finding.whyBlocked && <span className="block text-neutral-500">{finding.whyBlocked}</span>}
        {finding.whatToDo}
      </td>
    </tr>
  )
}

type Inner = 'soap' | 'linux'

function rememberedInner(repositoryId: string): Inner {
  try {
    const value = window.localStorage.getItem(`compat-tab:${repositoryId}`)
    // A remembered 'api' (the Method/API tab, removed) falls back to SOAP.
    return value === 'linux' || value === 'soap' ? value : 'soap'
  } catch {
    return 'soap'
  }
}

interface FindingsListProps {
  repositoryId: string
  localPath: string
  refreshToken: number
  noun: string
  summary?: string
  intro: string
  load: PageLoader<CompatibilityFinding>
  empty: string
}

function FindingsList({ repositoryId, localPath, refreshToken, noun, summary, intro, load, empty }: FindingsListProps) {
  return (
    <div className="space-y-2 text-xs">
      {summary && <p className="font-medium text-neutral-700">{summary}</p>}
      <p className="text-neutral-500">{intro}</p>
      <PagedList<CompatibilityFinding>
        load={load}
        resetKey={`${repositoryId}|${refreshToken}`}
        noun={`${noun}s`}
        empty={<p className="text-neutral-500">{empty}</p>}
      >
        {(shown) => (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[800px] text-left">
              <thead className="text-neutral-400">
                <tr>
                  {['Treatment', 'Finding', 'Where', 'Value / version', 'Why · what to do'].map((h) => (
                    <th key={h} className="py-1 pr-3 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {shown.map((finding) => (
                  <FindingRow key={`${finding.kind}:${finding.id}`} finding={finding} localPath={localPath} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </PagedList>
    </div>
  )
}

export function RepositoryCompatibilityPanel({ repositoryId, localPath, refreshToken, showLinux = true, onOpenEstateSoap }: Props) {
  const { data, notScanned, failed } = useSummary(repositoryId, refreshToken, showLinux)
  const [soap, setSoap] = useState<SoapSummary | null>(null)
  const [remembered, setInner] = useState<Inner>(() => rememberedInner(repositoryId))
  useEffect(() => setInner(rememberedInner(repositoryId)), [repositoryId])
  // A remembered Linux tab on a repository that no longer shows it opens on SOAP.
  const inner: Inner = showLinux ? remembered : 'soap'
  useEffect(() => {
    let cancelled = false
    getSoapSummary(repositoryId)
      .then((result) => !cancelled && setSoap(result))
      .catch(() => !cancelled && setSoap(null))
    return () => {
      cancelled = true
    }
  }, [repositoryId, refreshToken])

  const choose = (next: Inner) => {
    setInner(next)
    try {
      window.localStorage.setItem(`compat-tab:${repositoryId}`, next)
    } catch {
      // Not remembered: the next visit opens on SOAP.
    }
  }
  const label = (n: number | undefined, noun: string) => (n === undefined ? '' : ` · ${counted(n, noun)}`)
  const tabs: { key: Inner; label: string }[] = [{ key: 'soap', label: `SOAP${label(soap?.calls, 'call')}` }]
  if (showLinux) tabs.push({ key: 'linux', label: `Linux${label(data?.linux, 'finding')}` })
  return (
    <div className="min-w-0 space-y-3 p-4">
      <p className="text-xs text-neutral-500">
        {showLinux ? (
          'What will not work, or needs a change, when this repository moves to the modern stack on Linux (OpenShift): from the last scan, read from the database.'
        ) : (
          <>
            What will not work, or needs a change, when this repository moves to the modern stack: from the last scan, read from the database.{' '}
            <strong className="font-semibold text-amber-700">The Linux list is shown only for a move from Windows to Linux hosting.</strong>
          </>
        )}
      </p>
      {tabs.length > 1 && (
        <div role="tablist" aria-label="Compatibility" className="flex flex-wrap gap-1 border-b border-neutral-200">
          {tabs.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={inner === t.key}
              onClick={() => choose(t.key)}
              className={`-mb-px border-b-2 px-3 py-1.5 text-xs ${inner === t.key ? 'border-violet-600 font-semibold text-violet-700' : 'border-transparent text-neutral-600 hover:text-neutral-900'}`}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}
      <div role="tabpanel">
        {inner === 'soap' && <RepositorySoapPanel repositoryId={repositoryId} refreshToken={refreshToken} onOpenEstateSoap={onOpenEstateSoap} bare />}
        {inner !== 'soap' && notScanned && <p className="text-xs text-neutral-500">The application fingerprint has not run yet for this repository.</p>}
        {inner !== 'soap' && failed && <p className="text-xs text-red-700">Could not load this repository's compatibility.</p>}
        {inner === 'linux' && !notScanned && (
          <FindingsList
            repositoryId={repositoryId}
            localPath={localPath}
            refreshToken={refreshToken}
            noun="finding"
            summary={data ? `${counted(data.linux_blockers, 'blocker')} · ${data.linux_container} need container change · ${data.linux_other} to review` : undefined}
            intro="What the move to a Linux container on OpenShift needs, each with a badge: Blocker (fails on Linux or does not exist on modern .NET), Needs container change (runs, but must change for a container) or Review (behaves differently). Direct packages that only work on Windows are blockers. Each says what to do instead."
            load={linuxCompatibility(repositoryId)}
            empty="Nothing found that blocks this repository on Linux."
          />
        )}
      </div>
    </div>
  )
}
