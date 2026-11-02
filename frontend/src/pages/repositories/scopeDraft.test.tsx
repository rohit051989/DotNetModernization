import { describe, expect, it } from 'vitest'
import type { ScopeProject, ScopeSolution } from '../../types/scope'
import { changes, problems, setSolution, solutionState } from './scopeDraft'

// Two solutions sharing Core and Lib: Web.sln {Core, Lib, Web}, Legacy.sln {Core, Lib, Old}. Web -> Lib -> Core,
// Old -> Core.
const project = (name: string, solutions: string[], dependsOn: string[], workItems = 1): ScopeProject => ({
  path: `src/${name}/${name}.csproj`, name, solutions, dependsOn: dependsOn.map((d) => `src/${d}/${d}.csproj`), workItems, excluded: false, new: false,
})
const P = (name: string) => `src/${name}/${name}.csproj`
const projects = [
  project('Core', ['Web.sln', 'Legacy.sln'], []),
  project('Lib', ['Web.sln', 'Legacy.sln'], ['Core'], 2),
  project('Web', ['Web.sln'], ['Lib'], 3),
  project('Old', ['Legacy.sln'], ['Core'], 4),
]
const web: ScopeSolution = { path: 'Web.sln', name: 'Web', projects: [P('Core'), P('Lib'), P('Web')] }
const legacy: ScopeSolution = { path: 'Legacy.sln', name: 'Legacy', projects: [P('Core'), P('Lib'), P('Old')] }
const solutions = [legacy, web]

describe('the scope draft', () => {
  it('lists every problem together: each kept project and each excluded dependency, directly or through others', () => {
    const found = problems(projects, new Set([P('Lib'), P('Core')]))
    expect(found.map((p) => [p.project, p.dependency, p.through])).toEqual([
      [P('Web'), P('Lib'), []],
      [P('Web'), P('Core'), [P('Lib')]],
      [P('Old'), P('Core'), []],
    ])
    expect(found[1].message).toBe('Web is kept, but it depends on Core, through Lib, which is excluded: keep Core, or exclude Web too.')
  })

  it('needs one project kept', () => {
    expect(problems(projects, new Set(projects.map((p) => p.path))).map((p) => p.code)).toEqual(['NOTHING_KEPT'])
    expect(problems(projects, new Set([P('Old')]))).toEqual([])
  })

  it("a solution's checkbox shows all, some or none of its projects", () => {
    expect(solutionState(web, new Set())).toBe('all')
    expect(solutionState(web, new Set([P('Web')]))).toBe('some')
    expect(solutionState(web, new Set([P('Web'), P('Lib'), P('Core')]))).toBe('none')
  })

  it('deselecting a solution keeps the projects another selected solution contains, and says which', () => {
    const { excluded, keptBy } = setSolution(solutions, legacy, false, new Set())
    expect([...excluded]).toEqual([P('Old')])
    expect(Object.fromEntries(keptBy)).toEqual({ [P('Core')]: 'Web', [P('Lib')]: 'Web' })
    // Then Web too: nothing selected holds them any more.
    const both = setSolution(solutions, web, false, excluded)
    expect([...both.excluded].sort()).toEqual([P('Core'), P('Lib'), P('Old'), P('Web')].sort())
    expect(both.keptBy.size).toBe(0)
    // Selecting a solution keeps all its projects.
    expect([...setSolution(solutions, web, true, both.excluded).excluded]).toEqual([P('Old')])
  })

  it('summarises the change against the saved scope', () => {
    const change = changes(projects, new Set([P('Old')]), new Set([P('Web')]))
    expect(change.excluding.map((p) => p.name)).toEqual(['Web'])
    expect(change.reIncluding.map((p) => p.name)).toEqual(['Old'])
    expect([change.workItemsOut, change.workItemsBack]).toEqual([3, 4])
  })
})
