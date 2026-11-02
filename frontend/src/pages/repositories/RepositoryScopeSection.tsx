import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '../../api/client'
import { getConversionScope, saveConversionScope } from '../../api/scope'
import { LimitedList } from '../../components/LimitedList'
import { useToast } from '../../components/Toast'
import type { ConversionScope, ScopeProblem, ScopeProject, ScopeSolution } from '../../types/scope'
import { counted } from './repositoryTabs'
import { changes, problems, sameDraft, setSolution, solutionState, type Draft } from './scopeDraft'

interface RepositoryScopeSectionProps {
  repositoryId: string
  refreshToken: number
  /** Why this person cannot save (not the owner or an admin, or not on its machine), or null. */
  refusal: string | null
  /** Whether the draft has unsaved changes: the page asks before leaving the tab. */
  onDirtyChange?: (dirty: boolean) => void
  /** Changed by the page when someone leaves the tab and discards the draft. */
  discardToken?: number
  /** After a save: the page's counts (the tab label, the work list's) change with it. */
  onSaved?: () => void
}

const NOT_IN_A_SOLUTION = '(not in any solution)'

/** Scope — which of the repository's solutions and projects its conversions cover (36-COPILOT-ENHANCED-CONVERSION.md
 * Part O). Editing is a draft: tick and untick freely; problems show as warnings. Save checks the whole selection,
 * shows what changes, and records who, when and why. */
export function RepositoryScopeSection({ repositoryId, refreshToken, refusal, onDirtyChange, discardToken = 0, onSaved }: RepositoryScopeSectionProps) {
  const { showToast } = useToast()
  const [scope, setScope] = useState<ConversionScope | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [draft, setDraft] = useState<Draft>(new Set())
  const [keptBy, setKeptBy] = useState<Map<string, string>>(new Map())
  const [filter, setFilter] = useState('')
  const [reviewing, setReviewing] = useState(false)
  const [refused, setRefused] = useState<ScopeProblem[] | null>(null)
  const [stale, setStale] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [loads, setLoads] = useState(0)

  useEffect(() => {
    let live = true
    getConversionScope(repositoryId).then(
      (result) => {
        if (!live) return
        setScope(result)
        setDraft(new Set(result.projects.filter((p) => p.excluded).map((p) => p.path)))
        setKeptBy(new Map())
        setFailed(null)
      },
      (error) => live && setFailed(error instanceof ApiError ? error.message : 'Could not load the scope.'),
    )
    return () => {
      live = false
    }
  }, [repositoryId, refreshToken, loads])

  const saved = useMemo<Draft>(() => new Set(scope?.projects.filter((p) => p.excluded).map((p) => p.path) ?? []), [scope])
  const dirty = scope !== null && !sameDraft(saved, draft)
  const dirtyRef = useRef(dirty)
  useEffect(() => {
    if (dirtyRef.current !== dirty) onDirtyChange?.(dirty)
    dirtyRef.current = dirty
  }, [dirty, onDirtyChange])

  const discard = useCallback(() => {
    setDraft(new Set(saved))
    setKeptBy(new Map())
    setReviewing(false)
    setRefused(null)
    setReason('')
  }, [saved])

  const discarded = useRef(discardToken)
  useEffect(() => {
    if (discarded.current !== discardToken) {
      discarded.current = discardToken
      discard()
    }
  }, [discardToken, discard])

  const warnings = useMemo(() => (scope ? problems(scope.projects, draft) : []), [scope, draft])

  if (failed) return <p className="text-sm text-red-600">{failed}</p>
  if (!scope) return <p className="text-sm text-neutral-400">Loading scope…</p>
  if (scope.projects.length === 0) {
    return <p className="text-sm text-neutral-400">Solution discovery (solution-discovery) has not found any project in this repository yet.</p>
  }

  const byPath = new Map(scope.projects.map((p) => [p.path, p]))
  const standalone = scope.projects.filter((p) => p.solutions.length === 0).map((p) => p.path)
  const groups: ScopeSolution[] = [...scope.solutions, ...(standalone.length ? [{ path: NOT_IN_A_SOLUTION, name: NOT_IN_A_SOLUTION, projects: standalone }] : [])]
  const term = filter.trim().toLowerCase()
  const matches = (p: ScopeProject) => !term || `${p.name} ${p.path}`.toLowerCase().includes(term)
  const shownGroups = groups
    .map((g) => ({ group: g, projects: g.projects.map((p) => byPath.get(p)!).filter((p) => g.name.toLowerCase().includes(term) || matches(p)) }))
    .filter((g) => g.projects.length > 0)

  const kept = scope.projects.length - draft.size
  const outOfScope = scope.projects.filter((p) => draft.has(p.path)).reduce((n, p) => n + p.workItems, 0)
  const change = changes(scope.projects, saved, draft)

  function replaceDraft(next: Set<string>) {
    setDraft(next)
    setKeptBy(new Map())
    setRefused(null)
  }

  function toggleProject(path: string) {
    setDraft((current) => {
      const next = new Set(current)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
    setKeptBy((current) => {
      if (!current.has(path)) return current
      const next = new Map(current)
      next.delete(path)
      return next
    })
    setRefused(null)
  }

  function toggleSolution(solution: ScopeSolution) {
    const keep = solutionState(solution, draft) !== 'all'
    if (solution.path === NOT_IN_A_SOLUTION) {
      setDraft((current) => {
        const next = new Set(current)
        for (const p of solution.projects) {
          if (keep) next.delete(p)
          else next.add(p)
        }
        return next
      })
    } else {
      const result = setSolution(scope!.solutions, solution, keep, draft)
      setDraft(result.excluded)
      setKeptBy((current) => {
        const next = new Map(current)
        for (const p of solution.projects) next.delete(p)
        for (const [p, by] of result.keptBy) next.set(p, by)
        return next
      })
    }
    setRefused(null)
  }

  function fix(problem: ScopeProblem, how: 'keep' | 'exclude') {
    setDraft((current) => {
      const next = new Set(current)
      if (how === 'keep') for (const p of [problem.dependency!, ...(problem.through ?? [])]) next.delete(p)
      else next.add(problem.project!)
      return next
    })
    setRefused(null)
  }

  function askToSave() {
    if (warnings.length > 0) {
      setRefused(warnings)
      setReviewing(false)
      return
    }
    setRefused(null)
    setReviewing(true)
  }

  async function save() {
    setSaving(true)
    try {
      const result = await saveConversionScope(repositoryId, [...draft].sort(), reason.trim() || null, scope!.version)
      showToast('success', result.note)
      setReviewing(false)
      setReason('')
      setLoads((n) => n + 1)
      onSaved?.()
    } catch (error) {
      if (error instanceof ApiError && error.status === 422 && error.code === 'SCOPE_INVALID') {
        setRefused(error.rawDetail as ScopeProblem[])
        setReviewing(false)
      } else if (error instanceof ApiError && error.status === 409) {
        setStale(error.message)
        setReviewing(false)
      } else {
        showToast('error', error instanceof ApiError ? error.message : 'Could not save the scope.')
      }
    } finally {
      setSaving(false)
    }
  }

  const name = (path?: string) => (path ? (byPath.get(path)?.name ?? path) : '')
  const button = 'rounded border border-neutral-300 px-2.5 py-1 text-xs text-neutral-700 hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-50'

  return (
    <div className="space-y-3">
      <p className="text-xs text-neutral-500">
        Which of this repository's projects its conversions cover. The project is the unit: a solution's checkbox is a shortcut for its
        projects. Every project is in scope until someone saves a scope; a project discovered later is in scope by default.
      </p>

      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm" data-testid="scope-totals">
        <span>
          <strong>{kept}</strong> of {counted(scope.projects.length, 'project')} kept
        </span>
        <span className={draft.size > 0 ? 'text-amber-800' : 'text-neutral-500'}>{draft.size} excluded</span>
        <span className="text-neutral-500">{counted(outOfScope, 'work item')} out of scope</span>
        {scope.totals.new > 0 && <span className="text-sky-700">{scope.totals.new} new since scope was set</span>}
        {dirty && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-900">unsaved changes</span>}
      </div>
      <p className="text-xs text-neutral-500" data-testid="scope-saved">
        {scope.saved
          ? `Saved by ${scope.saved.by}${scope.saved.on ? ` on ${scope.saved.on}` : ''}, ${new Date(scope.saved.at).toLocaleString()}${scope.saved.reason ? `: ${scope.saved.reason}` : ''}.`
          : 'No scope saved yet: every project is in scope, and the repository converts as a whole.'}{' '}
        {scope.on_save.note}
      </p>
      {scope.gone.length > 0 && (
        <p className="text-xs text-neutral-500">
          {counted(scope.gone.length, 'excluded project')} no longer in the repository: dropped out of the scope.
        </p>
      )}

      <fieldset className="rounded border border-neutral-200 px-3 py-2 text-xs">
        <legend className="px-1 font-medium text-neutral-700">What happens to excluded projects</legend>
        <label className="mr-6 inline-flex items-center gap-1.5">
          <input type="radio" name={`treatment-${repositoryId}`} checked readOnly /> Leave untouched
        </label>
        <label className="inline-flex items-center gap-1.5 text-neutral-400" title="Coming later: needs to know what is dead code">
          <input type="radio" name={`treatment-${repositoryId}`} disabled /> Retire — remove as dead code{' '}
          <span className="rounded bg-neutral-100 px-1">coming later</span>
        </label>
      </fieldset>

      {stale && (
        <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800" data-testid="scope-stale">
          {stale}{' '}
          <button
            type="button"
            className="text-violet-700 hover:underline"
            onClick={() => {
              setStale(null)
              setLoads((n) => n + 1)
            }}
          >
            Reload
          </button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-1.5">
        <button type="button" className={button} onClick={() => replaceDraft(new Set())}>
          Select all
        </button>
        <button type="button" className={button} onClick={() => replaceDraft(new Set(scope.projects.map((p) => p.path)))}>
          Deselect all
        </button>
        <button type="button" className={button} onClick={discard} disabled={!dirty}>
          Discard changes
        </button>
        <button
          type="button"
          onClick={askToSave}
          disabled={!dirty || !!refusal || saving}
          title={refusal ?? undefined}
          className="rounded bg-violet-600 px-3 py-1 text-xs font-medium text-white hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Save…
        </button>
        <input
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={`Filter ${scope.solutions.length} solutions and ${scope.projects.length} projects…`}
          aria-label="Filter solutions and projects"
          className="ml-auto w-full max-w-xs rounded border border-neutral-300 px-2 py-1 text-xs focus:border-violet-400 focus:outline-none"
        />
      </div>

      {refused && refused.length > 0 && (
        <ProblemList
          problems={refused}
          title={`Not saved: ${counted(refused.length, 'problem')} to resolve first`}
          tone="red"
          testId="scope-refused"
          name={name}
          onFix={fix}
        />
      )}
      {!refused && warnings.length > 0 && (
        <ProblemList problems={warnings} title={counted(warnings.length, 'warning')} tone="amber" testId="scope-warnings" name={name} onFix={fix} />
      )}

      {reviewing && (
        <div className="space-y-2 rounded border border-violet-200 bg-violet-50 px-3 py-2 text-sm" data-testid="scope-summary">
          <p className="font-medium text-neutral-900">Save this scope?</p>
          <SummaryLine label="Excluding" projects={change.excluding} />
          <SummaryLine label="Re-including" projects={change.reIncluding} />
          <p className="text-xs text-neutral-700">
            {counted(change.workItemsOut, 'work item')} move out of scope; {counted(change.workItemsBack, 'work item')} move back into scope.
          </p>
          <p className="text-xs text-neutral-600">{scope.on_save.note}</p>
          <label className="block text-xs text-neutral-700">
            Reason (optional)
            <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} className="mt-1 w-full rounded border border-neutral-300 px-2 py-1 text-sm" />
          </label>
          <div className="flex gap-2">
            <button type="button" className={button} onClick={() => setReviewing(false)}>
              Cancel
            </button>
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="rounded bg-violet-600 px-3 py-1 text-xs font-medium text-white hover:bg-violet-700 disabled:opacity-50"
            >
              {saving ? 'Saving…' : 'Save scope'}
            </button>
          </div>
        </div>
      )}

      {shownGroups.length === 0 ? (
        <p className="text-sm text-neutral-400">No solution or project matches “{filter}”.</p>
      ) : (
        <LimitedList items={shownGroups} noun="solutions">
          {(visible) => (
            <ul className="space-y-2">
              {visible.map(({ group, projects }) => (
                <SolutionRow
                  key={group.path}
                  solution={group}
                  projects={projects}
                  draft={draft}
                  keptBy={keptBy}
                  standalone={group.path === NOT_IN_A_SOLUTION}
                  solutionNames={new Map(scope.solutions.map((s) => [s.path, s.name]))}
                  onSolution={() => toggleSolution(group)}
                  onProject={toggleProject}
                  open={!!term || groups.length <= 3}
                />
              ))}
            </ul>
          )}
        </LimitedList>
      )}
    </div>
  )
}

function ProblemList({
  problems: list,
  title,
  tone,
  testId,
  name,
  onFix,
}: {
  problems: ScopeProblem[]
  title: string
  tone: 'red' | 'amber'
  testId: string
  name: (path?: string) => string
  onFix: (problem: ScopeProblem, how: 'keep' | 'exclude') => void
}) {
  const colours = tone === 'red' ? 'border-red-200 bg-red-50 text-red-900' : 'border-amber-200 bg-amber-50 text-amber-900'
  return (
    <div className={`rounded border px-3 py-2 text-xs ${colours}`} data-testid={testId}>
      <p className="mb-1 font-medium">{title}</p>
      <LimitedList items={list} name={(p) => p.message} noun="problems">
        {(visible) => (
          <ul className="space-y-1">
            {visible.map((p) => (
              <li key={`${p.code}:${p.project ?? ''}:${p.dependency ?? ''}`} className="flex flex-wrap items-baseline gap-x-2">
                <span>{p.message}</span>
                {p.code === 'DEPENDENCY_EXCLUDED' && (
                  <span className="flex gap-2">
                    <button type="button" className="text-violet-700 hover:underline" onClick={() => onFix(p, 'keep')}>
                      Keep {name(p.dependency)}
                    </button>
                    <button type="button" className="text-violet-700 hover:underline" onClick={() => onFix(p, 'exclude')}>
                      Exclude {name(p.project)} too
                    </button>
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </LimitedList>
    </div>
  )
}

function SummaryLine({ label, projects }: { label: string; projects: ScopeProject[] }) {
  if (projects.length === 0) return <p className="text-xs text-neutral-600">{label}: none.</p>
  return (
    <div className="text-xs text-neutral-700">
      {label} {counted(projects.length, 'project')}:
      <LimitedList items={projects} name={(p) => [p.name, p.path]} noun="projects">
        {(visible) => (
          <ul className="ml-4 list-disc">
            {visible.map((p) => (
              <li key={p.path}>
                {p.name} <span className="text-neutral-500">({counted(p.workItems, 'work item')})</span>
              </li>
            ))}
          </ul>
        )}
      </LimitedList>
    </div>
  )
}

function SolutionRow({
  solution,
  projects,
  draft,
  keptBy,
  standalone,
  solutionNames,
  onSolution,
  onProject,
  open: openAtFirst,
}: {
  solution: ScopeSolution
  projects: ScopeProject[]
  draft: Draft
  keptBy: Map<string, string>
  standalone: boolean
  solutionNames: Map<string, string>
  onSolution: () => void
  onProject: (path: string) => void
  open: boolean
}) {
  const [chosen, setOpen] = useState<boolean | null>(null)
  const open = chosen ?? openAtFirst
  const box = useRef<HTMLInputElement>(null)
  const state = solutionState(solution, draft)
  useEffect(() => {
    if (box.current) box.current.indeterminate = state === 'some'
  }, [state])
  const keptCount = solution.projects.filter((p) => !draft.has(p)).length
  return (
    <li className="rounded border border-neutral-200" data-testid={`scope-solution:${solution.name}`}>
      <div className="flex flex-wrap items-center gap-2 px-3 py-1.5">
        <input
          ref={box}
          type="checkbox"
          checked={state === 'all'}
          onChange={onSolution}
          aria-label={`Solution ${solution.name}`}
          data-state={state}
        />
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="flex min-w-0 flex-1 items-baseline gap-2 text-left">
          <span className="text-xs text-neutral-400" aria-hidden>
            {open ? '▾' : '▸'}
          </span>
          <span className={`text-sm font-medium ${standalone ? 'italic text-neutral-500' : 'text-neutral-900'}`}>{solution.name}</span>
          {!standalone && <span className="truncate font-mono text-xs text-neutral-400">{solution.path}</span>}
          <span className="text-xs text-neutral-500">
            {keptCount} of {counted(solution.projects.length, 'project')} kept
          </span>
        </button>
      </div>
      {open && (
        <div className="border-t border-neutral-100 px-3 py-1.5">
          <LimitedList items={projects} name={(p) => [p.name, p.path]} noun="projects">
            {(visible) => (
              <ul className="space-y-0.5">
                {visible.map((p) => {
                  const others = p.solutions.filter((s) => s !== solution.path).map((s) => solutionNames.get(s) ?? s)
                  const holder = keptBy.get(p.path)
                  return (
                    <li key={p.path} className="flex flex-wrap items-center gap-x-2 text-sm" data-testid={`scope-project:${p.path}`}>
                      <input type="checkbox" checked={!draft.has(p.path)} onChange={() => onProject(p.path)} aria-label={`Project ${p.name}`} />
                      <span className={draft.has(p.path) ? 'text-neutral-400 line-through' : 'text-neutral-900'}>{p.name}</span>
                      <span className="truncate font-mono text-xs text-neutral-400">{p.path}</span>
                      {p.workItems > 0 && <span className="text-xs text-neutral-500">{counted(p.workItems, 'work item')}</span>}
                      {others.length > 0 && (
                        <span className="rounded bg-neutral-100 px-1.5 text-xs text-neutral-600" title="A shared project: deselecting one of its solutions keeps it while another is selected">
                          also in solution {others.join(', ')}
                        </span>
                      )}
                      {holder && !draft.has(p.path) && (
                        <span className="rounded bg-violet-100 px-1.5 text-xs text-violet-800" data-testid="kept-by">
                          kept by {holder}
                        </span>
                      )}
                      {p.new && <span className="rounded bg-sky-100 px-1.5 text-xs text-sky-800">new since scope was set</span>}
                    </li>
                  )
                })}
              </ul>
            )}
          </LimitedList>
        </div>
      )}
    </li>
  )
}
