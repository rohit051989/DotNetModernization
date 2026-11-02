import type { ScopeProblem, ScopeProject, ScopeSolution } from '../../types/scope'

/**
 * The Scope tab's draft (36-COPILOT-ENHANCED-CONVERSION.md Part O): the set of excluded projects, by path. Nothing here
 * refuses: problems are warnings while editing, and Save is refused until there are none. The server checks the same
 * rules again (app.scope.service.problems), in the same words.
 */

export type Draft = ReadonlySet<string>

/** Every reason the draft cannot be saved: at least one project kept; every kept project's dependencies kept, directly
 * or through other projects (one problem per excluded dependency, with the excluded projects it is reached through). */
export function problems(projects: readonly ScopeProject[], excluded: Draft): ScopeProblem[] {
  const byPath = new Map(projects.map((p) => [p.path, p]))
  const name = (path: string) => byPath.get(path)?.name ?? path
  const kept = projects.filter((p) => !excluded.has(p.path))
  const out: ScopeProblem[] = []
  if (kept.length === 0) {
    out.push({ code: 'NOTHING_KEPT', message: 'At least one project must be kept: a conversion with no project converts nothing.' })
  }
  for (const project of kept) {
    const seen = new Set<string>()
    const stack: [string, string[]][] = project.dependsOn.filter((d) => excluded.has(d)).reverse().map((d) => [d, []])
    while (stack.length > 0) {
      const [dependency, through] = stack.pop()!
      if (seen.has(dependency)) continue
      seen.add(dependency)
      const how = through.length > 0 ? `, through ${through.map(name).join(', ')}` : ''
      out.push({
        code: 'DEPENDENCY_EXCLUDED',
        project: project.path,
        dependency,
        through,
        message: `${project.name} is kept, but it depends on ${name(dependency)}${how}, which is excluded: keep ${name(dependency)}, or exclude ${project.name} too.`,
      })
      const next = (byPath.get(dependency)?.dependsOn ?? []).filter((d) => excluded.has(d)).reverse()
      for (const d of next) stack.push([d, [...through, dependency]])
    }
  }
  return out
}

export type SolutionState = 'all' | 'some' | 'none'

/** A solution's own checkbox: whether all, some or none of its projects are kept. */
export function solutionState(solution: ScopeSolution, excluded: Draft): SolutionState {
  const kept = solution.projects.filter((p) => !excluded.has(p)).length
  return kept === solution.projects.length ? 'all' : kept === 0 ? 'none' : 'some'
}

/** The other solutions still selected, as far as `solution`'s projects are concerned: one keeps a project that
 * `solution` does not contain. */
function stillSelected(solutions: readonly ScopeSolution[], solution: ScopeSolution, excluded: Draft): ScopeSolution[] {
  const own = new Set(solution.projects)
  return solutions.filter((s) => s.path !== solution.path && s.projects.some((p) => !own.has(p) && !excluded.has(p)))
}

/** Selects or deselects a solution: a shortcut for its projects. Deselecting it deselects each of its projects except
 * one another still-selected solution contains, which stays kept; `keptBy` names that solution for each. */
export function setSolution(
  solutions: readonly ScopeSolution[],
  solution: ScopeSolution,
  keep: boolean,
  excluded: Draft,
): { excluded: Set<string>; keptBy: Map<string, string> } {
  const next = new Set(excluded)
  const keptBy = new Map<string, string>()
  if (keep) {
    for (const p of solution.projects) next.delete(p)
    return { excluded: next, keptBy }
  }
  const others = stillSelected(solutions, solution, excluded)
  for (const p of solution.projects) {
    const holder = others.find((s) => s.projects.includes(p))
    if (holder) keptBy.set(p, holder.name)
    else next.add(p)
  }
  return { excluded: next, keptBy }
}

/** What saving the draft changes, against the saved scope: the projects newly excluded and re-included, and the work
 * items moving out of and back into scope. */
export function changes(projects: readonly ScopeProject[], saved: Draft, draft: Draft) {
  const out = projects.filter((p) => draft.has(p.path) && !saved.has(p.path))
  const back = projects.filter((p) => saved.has(p.path) && !draft.has(p.path))
  const sum = (list: ScopeProject[]) => list.reduce((n, p) => n + p.workItems, 0)
  return { excluding: out, reIncluding: back, workItemsOut: sum(out), workItemsBack: sum(back) }
}

export function sameDraft(a: Draft, b: Draft): boolean {
  return a.size === b.size && [...a].every((p) => b.has(p))
}
