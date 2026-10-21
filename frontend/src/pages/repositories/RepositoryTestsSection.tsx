import { useEffect, useMemo, useState } from 'react'
import { ApiError } from '../../api/client'
import { getRepositoryTests } from '../../api/surface'
import { LimitedList } from '../../components/LimitedList'
import type { RepositoryTests, SourceFileRow, TestBucket, TestType } from '../../types/tests'
import { SourceLink } from './SourceLink'

const TYPE_STYLE: Record<TestType, string> = {
  unit: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  integration: 'border-sky-200 bg-sky-50 text-sky-800',
  functional: 'border-indigo-200 bg-indigo-50 text-indigo-800',
  smoke: 'border-amber-200 bg-amber-50 text-amber-800',
  unclassified: 'border-neutral-200 bg-neutral-50 text-neutral-600',
}

const BUCKET_LABEL: Record<TestBucket, string> = {
  has_tests: 'has tests',
  missing_tests: 'missing tests',
  no_testable_logic: 'no testable logic',
}

const CACHE_LABEL: Record<string, string> = {
  computed: 'computed at this commit',
  reused: 'reused from an earlier run at this commit',
  no_commit: 'computed — no git history to cache on',
  uncommitted_changes: 'computed — uncommitted changes, cache not used',
}

/** Collects not-measured reasons into numbered notes, so a cell shows
 * "not measured" with its note number and the reasons read in full below —
 * never a percentage for unknown, and never hidden behind a hover. */
function noteCollector() {
  const notes: string[] = []
  const number = (reason: string) => {
    const index = notes.indexOf(reason)
    if (index >= 0) return index + 1
    notes.push(reason)
    return notes.length
  }
  return { notes, number }
}

function Pct({ value, reason, note }: { value: number | null; reason: string | null; note: (reason: string) => number }) {
  if (value !== null) return <span className="font-mono">{value.toFixed(1)}%</span>
  return (
    <span className="text-neutral-400">
      not measured<sup className="ml-0.5 text-[10px]">{reason ? note(reason) : '?'}</sup>
    </span>
  )
}

function TypeChip({ type, count }: { type: TestType; count?: number }) {
  return (
    <span className={`inline-block rounded border px-1 text-[11px] ${TYPE_STYLE[type]}`}>
      {count !== undefined ? `${count} ` : ''}
      {type}
    </span>
  )
}

/** Step 8's Tests section (32-TEST-COVERAGE-ASSESSMENT Part K): CI maturity, test projects
 * and classes by type, the per-project table, and the per-file table. */
export function RepositoryTestsSection({ repositoryId, localPath, refreshToken }: { repositoryId: string; localPath: string | null; refreshToken: number }) {
  const [data, setData] = useState<RepositoryTests | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'not_scanned' | 'error'>('loading')
  const [bucket, setBucket] = useState<TestBucket | 'all'>('all')
  const [showClasses, setShowClasses] = useState(false)
  const [showCiEvidence, setShowCiEvidence] = useState(false)

  useEffect(() => {
    let cancelled = false
    setState('loading')
    getRepositoryTests(repositoryId)
      .then((result) => {
        if (cancelled) return
        setData(result)
        setState('ready')
      })
      .catch((err) => {
        if (!cancelled) setState(err instanceof ApiError && err.status === 409 ? 'not_scanned' : 'error')
      })
    return () => {
      cancelled = true
    }
  }, [repositoryId, refreshToken])

  const files = useMemo(() => (data ? data.source_files.filter((f) => bucket === 'all' || f.bucket === bucket) : []), [data, bucket])

  if (state === 'loading') return <div className="h-16 animate-pulse rounded bg-neutral-100" />
  if (state === 'not_scanned') return <p className="text-sm text-neutral-400">Test coverage (lifecycle step 8) hasn't run for this repository yet.</p>
  if (state === 'error' || !data) return <p className="text-sm text-red-600">Could not load the tests.</p>

  const { notes, number } = noteCollector()
  const ci = data.ci_maturity
  const byType = data.summary.testClassesByType
  const byBucket = data.summary.sourceFilesByBucket

  return (
    <div className="space-y-4 text-sm">
      <p className="text-xs text-neutral-500">
        {data.scan.commit_sha ? <>commit <span className="font-mono">{data.scan.commit_sha.slice(0, 12)}</span> · </> : null}
        {CACHE_LABEL[data.scan.cache_state] ?? data.scan.cache_state}
        {data.scan.cache_note && <span className="block text-neutral-400">{data.scan.cache_note}</span>}
      </p>

      {/* CI maturity, Part H */}
      <div>
        <h4 className="mb-1 text-[11px] font-medium uppercase tracking-wide text-neutral-400">CI maturity</h4>
        {ci ? (
          <>
            <div className="flex flex-wrap gap-1.5">
              {(
                [
                  ['pipeline', ci.has_pipeline],
                  ['runs tests', ci.runs_tests],
                  ['collects coverage', ci.collects_coverage],
                  ['publishes coverage', ci.publishes_coverage],
                  ['coverage gate', ci.enforces_coverage_gate],
                ] as const
              ).map(([label, value]) => (
                <span
                  key={label}
                  className={`rounded border px-1.5 py-0.5 text-xs ${value ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-neutral-200 bg-neutral-50 text-neutral-500'}`}
                >
                  {value ? '✓' : '✗'} {label}
                </span>
              ))}
            </div>
            <LimitedList items={ci.pipelines} name={(p) => p.path} noun="pipelines" className="mt-1 text-xs text-neutral-500">
              {(visible) => (
                <p>
                  {visible.map((p) => `${p.path} (${p.system.replace('_', ' ')})`).join(' · ')}
                  {ci.evidence.length > 0 && (
                    <button type="button" onClick={() => setShowCiEvidence((v) => !v)} className="ml-2 text-violet-600 hover:underline">
                      {showCiEvidence ? 'hide evidence' : 'why'}
                    </button>
                  )}
                </p>
              )}
            </LimitedList>
            {showCiEvidence && (
              <LimitedList items={ci.evidence} name={(e) => [e.fact.replaceAll('_', ' '), e.path]} noun="evidence lines" className="mt-1">
                {(visible) => (
                  <ul className="space-y-0.5 text-[11px] text-neutral-600">
                    {visible.map((e, i) => (
                      <li key={i}>
                        <span className="font-medium">{e.fact.replaceAll('_', ' ')}</span> —{' '}
                        <SourceLink localPath={localPath} filePath={e.path} line={e.line} className="font-mono text-violet-700">
                          {e.path}:{e.line}
                        </SourceLink>{' '}
                        <code className="text-neutral-500">{e.text}</code>
                      </li>
                    ))}
                  </ul>
                )}
              </LimitedList>
            )}
          </>
        ) : (
          <p className="text-xs text-neutral-400">Not assessed.</p>
        )}
      </div>

      {/* Test projects and classes, Part B */}
      <div>
        <h4 className="mb-1 text-[11px] font-medium uppercase tracking-wide text-neutral-400">
          Tests — {data.summary.testClasses ?? 0} classes, {data.summary.testMethods ?? 0} test methods
        </h4>
        <LimitedList
          items={data.test_projects}
          name={(p) => p.project_path}
          noun="test projects"
          empty={<p className="text-xs text-neutral-400">No test project found.</p>}
        >
          {(visible) => (
          <ul className="space-y-0.5 text-xs">
            {visible.map((p) => (
              <li key={p.project_path} className="flex flex-wrap items-center gap-1">
                <span className="font-mono text-neutral-700">{p.project_path}</span>
                {(Object.entries(p.test_classes_by_type) as [TestType, number][])
                  .filter(([, n]) => n > 0)
                  .map(([type, n]) => (
                    <TypeChip key={type} type={type} count={n} />
                  ))}
              </li>
            ))}
          </ul>
          )}
        </LimitedList>
        {byType && (byType.unclassified ?? 0) > 0 && (
          <p className="mt-1 text-xs text-neutral-500">Unclassified means the evidence conflicted or there was none — never guessed.</p>
        )}
        {data.test_classes.length > 0 && (
          <button type="button" onClick={() => setShowClasses((v) => !v)} className="mt-1 text-xs text-violet-600 hover:underline">
            {showClasses ? 'hide test classes' : `show the ${data.test_classes.length} test classes and why each is classified`}
          </button>
        )}
        {showClasses && (
          <LimitedList items={data.test_classes} name={(c) => [c.class_name, c.file_path]} noun="test classes" className="mt-1">
            {(visible) => (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-xs">
              <thead className="text-neutral-400">
                <tr>
                  <th className="py-1 pr-3 font-medium">Test class</th>
                  <th className="py-1 pr-3 font-medium">Type</th>
                  <th className="py-1 pr-3 font-medium">Tests</th>
                  <th className="py-1 font-medium">Why</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((c) => (
                  <tr key={`${c.file_path}|${c.class_name}`} className="border-t border-neutral-100 align-top">
                    <td className="py-1 pr-3">
                      <span className="font-medium text-neutral-800">{c.class_name}</span>
                      <SourceLink localPath={localPath} filePath={c.file_path} line={c.line_start} className="block font-mono text-[11px] text-violet-700">
                        {c.file_path}
                      </SourceLink>
                    </td>
                    <td className="py-1 pr-3"><TypeChip type={c.test_type} /></td>
                    <td className="py-1 pr-3 font-mono">{c.test_count}</td>
                    <td className="py-1 text-neutral-600">{c.classification_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
            )}
          </LimitedList>
        )}
      </div>

      {/* Per project, Part K */}
      <div className="overflow-x-auto">
        <h4 className="mb-1 text-[11px] font-medium uppercase tracking-wide text-neutral-400">Per project</h4>
        <LimitedList items={data.projects} name={(p) => p.project_path} noun="projects">
          {(visible) => (
        <table className="w-full min-w-[640px] text-left text-xs">
          <thead className="text-neutral-400">
            <tr>
              <th className="py-1 pr-3 font-medium">Project</th>
              <th className="py-1 pr-3 font-medium">Files</th>
              <th className="py-1 pr-3 font-medium">Has tests</th>
              <th className="py-1 pr-3 font-medium">Missing</th>
              <th className="py-1 pr-3 font-medium">No testable logic</th>
              <th className="py-1 pr-3 font-medium">Unit %</th>
              <th className="py-1 font-medium">Integration %</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((p) => (
              <tr key={p.project_path} className="border-t border-neutral-100">
                <td className="py-1 pr-3 font-mono text-neutral-700">{p.project_path}</td>
                <td className="py-1 pr-3 font-mono">{p.files}</td>
                <td className="py-1 pr-3 font-mono">{p.has_tests}</td>
                <td className={`py-1 pr-3 font-mono ${p.missing_tests > 0 ? 'text-amber-700' : ''}`}>{p.missing_tests}</td>
                <td className="py-1 pr-3 font-mono text-neutral-500">{p.no_testable_logic}</td>
                <td className="py-1 pr-3"><Pct value={p.unit_line_pct} reason={p.unit_not_measured_reason} note={number} /></td>
                <td className="py-1"><Pct value={p.integration_line_pct} reason={p.integration_not_measured_reason} note={number} /></td>
              </tr>
            ))}
          </tbody>
        </table>
          )}
        </LimitedList>
      </div>

      {/* Per source file, Part K */}
      <div>
        <div className="mb-1 flex flex-wrap items-center gap-1.5">
          <h4 className="text-[11px] font-medium uppercase tracking-wide text-neutral-400">Per source file</h4>
          {(['all', 'has_tests', 'missing_tests', 'no_testable_logic'] as const).map((b) => (
            <button
              key={b}
              type="button"
              onClick={() => setBucket(b)}
              aria-pressed={bucket === b}
              className={`rounded border px-1.5 py-0.5 text-[11px] ${bucket === b ? 'border-violet-300 bg-violet-50 text-violet-800' : 'border-neutral-200 text-neutral-600 hover:bg-neutral-50'}`}
            >
              {b === 'all' ? `all ${data.source_files.length}` : `${byBucket?.[b] ?? 0} ${BUCKET_LABEL[b]}`}
            </button>
          ))}
        </div>
        {/* Keyed by bucket: a new bucket starts again at its first 20 files. */}
        <LimitedList key={bucket} items={files} name={(f) => f.file_path} noun="source files">
          {(visible) => (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead className="text-neutral-400">
              <tr>
                <th className="py-1 pr-3 font-medium">Source file</th>
                <th className="py-1 pr-3 font-medium">Test file(s)</th>
                <th className="py-1 pr-3 font-medium">Test type</th>
                <th className="py-1 pr-3 font-medium">Line %</th>
                <th className="py-1 pr-3 font-medium">Branch %</th>
                <th className="py-1 font-medium">Coverage source</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((f) => (
                <FileRow key={f.file_path} file={f} localPath={localPath} note={number} />
              ))}
            </tbody>
          </table>
        </div>
          )}
        </LimitedList>
      </div>

      {notes.length > 0 && (
        <ol className="space-y-0.5 text-[11px] text-neutral-500">
          {notes.map((reason, i) => (
            <li key={reason}>
              <sup>{i + 1}</sup> {reason}
            </li>
          ))}
        </ol>
      )}

      {/* Execution decisions, Part F — phase 3 */}
      <p className="rounded border border-neutral-200 bg-neutral-50 px-2 py-1.5 text-xs text-neutral-600">{data.execution}</p>
    </div>
  )
}

function FileRow({ file: f, localPath, note }: { file: SourceFileRow; localPath: string | null; note: (reason: string) => number }) {
  return (
    <tr className="border-t border-neutral-100 align-top">
      <td className="py-1 pr-3">
        <SourceLink localPath={localPath} filePath={f.file_path} line={1} className="font-mono text-violet-700">
          {f.file_path}
        </SourceLink>
        <span className={`block text-[11px] ${f.bucket === 'missing_tests' ? 'text-amber-700' : 'text-neutral-400'}`}>
          {BUCKET_LABEL[f.bucket]}
          {f.bucket !== 'no_testable_logic' && ` · ${f.testable_members} member${f.testable_members === 1 ? '' : 's'} with logic`}
        </span>
      </td>
      <td className="py-1 pr-3">
        <LimitedList items={f.tests} name={(t) => [t.test_file, t.test_class]} noun="test files" empty={<span className="text-neutral-300">—</span>}>
          {(visible) =>
            visible.map((t) => (
              <span key={`${t.test_file}|${t.test_class}`} className="block">
                <SourceLink localPath={localPath} filePath={t.test_file} line={1} className="font-mono text-violet-700">
                  {t.test_file.split('/').pop()}
                </SourceLink>{' '}
                <span className="text-[10px] text-neutral-400">
                  {t.method === 'naming_only' ? 'name only, ' : ''}
                  {t.confidence.toFixed(2)}
                </span>
              </span>
            ))
          }
        </LimitedList>
      </td>
      <td className="py-1 pr-3">
        {[...new Set(f.tests.map((t) => t.test_type))].map((type) => (
          <span key={type} className="mr-1">
            <TypeChip type={type} />
          </span>
        ))}
      </td>
      <td className="py-1 pr-3"><Pct value={f.line_pct} reason={f.not_measured_reason} note={note} /></td>
      <td className="py-1 pr-3">
        {f.branch_pct !== null ? <span className="font-mono">{f.branch_pct.toFixed(1)}%</span> : <span className="text-neutral-300">—</span>}
      </td>
      <td className="py-1 text-neutral-600">{f.coverage_source.replace('_', ' ')}</td>
    </tr>
  )
}
