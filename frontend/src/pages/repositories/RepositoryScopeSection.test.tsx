import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/Toast'
import type { ConversionScope } from '../../types/scope'

// The Scope tab against a server holding two solutions that share Core and Lib: Web.sln {Core, Lib, Web} and
// Legacy.sln {Core, Lib, Old}; Web -> Lib -> Core, Old -> Core.
const P = (name: string) => `src/${name}/${name}.csproj`
const project = (name: string, solutions: string[], dependsOn: string[], workItems: number, excluded = false) => ({
  path: P(name), name, solutions, dependsOn: dependsOn.map(P), workItems, excluded, new: false,
})
function scopeWith(excluded: string[], version: number): ConversionScope {
  const projects = [
    project('Core', ['Web.sln', 'Legacy.sln'], [], 1),
    project('Lib', ['Web.sln', 'Legacy.sln'], ['Core'], 2),
    project('Old', ['Legacy.sln'], ['Core'], 4),
    project('Web', ['Web.sln'], ['Lib'], 3),
  ].map((p) => ({ ...p, excluded: excluded.includes(p.path) }))
  return {
    version,
    saved: version ? { by: 'Ann (ann)', on: 'HOST-A', at: '2026-11-01T10:00:00Z', reason: null } : null,
    treatment: 'leave_untouched',
    solutions: [
      { path: 'Legacy.sln', name: 'Legacy', projects: [P('Core'), P('Lib'), P('Old')] },
      { path: 'Web.sln', name: 'Web', projects: [P('Core'), P('Lib'), P('Web')] },
    ],
    projects,
    gone: [],
    totals: { projects: 4, kept: 4 - excluded.length, excluded: excluded.length, workItemsOutOfScope: 0, new: 0 },
    on_save: { reprepares: null, keeps: null, note: 'No conversion yet: the first one is prepared with this scope.' },
  }
}

const server = vi.hoisted(() => ({ scope: null as unknown, save: vi.fn() }))
vi.mock('../../api/scope', () => ({
  getConversionScope: () => Promise.resolve(server.scope),
  saveConversionScope: (...args: unknown[]) => server.save(...args),
}))

import { ApiError } from '../../api/client'
import { RepositoryScopeSection } from './RepositoryScopeSection'

const dirty = vi.fn()

async function open() {
  await act(async () => {
    render(
      <ToastProvider>
        <RepositoryScopeSection repositoryId="r" refreshToken={0} refusal={null} onDirtyChange={dirty} />
      </ToastProvider>,
    )
  })
}

async function click(element: HTMLElement) {
  await act(async () => {
    fireEvent.click(element)
  })
}

const box = (name: string) => screen.getByRole('checkbox', { name }) as HTMLInputElement
const button = (name: string) => screen.getByRole('button', { name }) as HTMLButtonElement

beforeEach(() => {
  server.scope = scopeWith([], 0)
  server.save.mockReset()
  dirty.mockReset()
})
afterEach(cleanup)

describe('RepositoryScopeSection', () => {
  it('starts with every project in scope, and offers only Leave untouched for the rest', async () => {
    await open()
    expect(screen.getByTestId('scope-totals').textContent).toContain('4 of 4 projects kept')
    expect(screen.getByTestId('scope-saved').textContent).toContain('No scope saved yet: every project is in scope')
    expect((screen.getByLabelText(/Leave untouched/) as HTMLInputElement).checked).toBe(true)
    expect((screen.getByLabelText(/Retire — remove as dead code/) as HTMLInputElement).disabled).toBe(true)
    expect(screen.getByText('coming later')).toBeTruthy()
    expect(button('Save…').disabled).toBe(true)
  })

  it('Deselect all, then a few projects: warnings while editing; Save refused with every problem; accepted once fixed', async () => {
    await open()
    await click(button('Deselect all'))
    expect(dirty).toHaveBeenLastCalledWith(true)
    expect(screen.getByTestId('scope-warnings').textContent).toContain('At least one project must be kept')
    await click(button('Save…'))
    expect(screen.getByTestId('scope-refused').textContent).toContain('Not saved: 1 problem to resolve first')

    await click(box('Project Web'))
    await click(box('Project Old'))
    expect(screen.getByTestId('scope-warnings').textContent).toContain('3 warnings')
    await click(button('Save…'))
    const refused = screen.getByTestId('scope-refused')
    expect(refused.textContent).toContain('Not saved: 3 problems to resolve first')
    expect(refused.textContent).toContain('Web is kept, but it depends on Lib, which is excluded')
    expect(refused.textContent).toContain('Web is kept, but it depends on Core, through Lib, which is excluded')
    expect(refused.textContent).toContain('Old is kept, but it depends on Core, which is excluded')
    expect(screen.queryByTestId('scope-summary')).toBeNull()
    expect(server.save).not.toHaveBeenCalled()

    // Old's offer keeps Core; Web still needs Lib, a warning now, until its offer keeps it too.
    await click(within(refused).getAllByRole('button', { name: 'Keep Core' })[0])
    expect(screen.queryByTestId('scope-refused')).toBeNull()
    const left = screen.getByTestId('scope-warnings')
    expect(left.textContent).toContain('1 warning')
    await click(within(left).getByRole('button', { name: 'Keep Lib' }))
    expect(screen.queryByTestId('scope-warnings')).toBeNull()
    // Back to the saved scope (everything kept): nothing to save.
    expect(button('Save…').disabled).toBe(true)

    await click(box('Project Old'))
    await click(button('Save…'))
    expect(screen.getByTestId('scope-summary').textContent).toContain('Excluding 1 project:Old (4 work items)')
    expect(screen.getByTestId('scope-summary').textContent).toContain('4 work items move out of scope; 0 work items move back into scope.')
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: 'Retired next year' } })
    server.save.mockResolvedValue({ version: 1, newlyExcluded: [P('Old')], reIncluded: [], reprepare_job_execution_id: null, note: 'Saved.' })
    server.scope = scopeWith([P('Old')], 1)
    await click(button('Save scope'))
    expect(server.save).toHaveBeenCalledWith('r', [P('Old')], 'Retired next year', 0)
    expect(screen.getByTestId('scope-saved').textContent).toContain('Saved by Ann (ann) on HOST-A')
    expect(dirty).toHaveBeenLastCalledWith(false)
  })

  it('Discard changes returns to the saved scope', async () => {
    server.scope = scopeWith([P('Old')], 1)
    await open()
    expect(box('Project Old').checked).toBe(false)
    await click(button('Select all'))
    await click(box('Project Web'))
    expect(box('Project Old').checked).toBe(true)
    expect(box('Project Web').checked).toBe(false)
    await click(button('Discard changes'))
    expect(box('Project Old').checked).toBe(false)
    expect(box('Project Web').checked).toBe(true)
    expect(button('Discard changes').disabled).toBe(true)
  })

  it('deselecting a solution keeps its shared projects, kept by the other solution', async () => {
    await open()
    await click(box('Solution Legacy'))
    const legacy = screen.getByTestId('scope-solution:Legacy')
    expect(within(legacy).getByRole('checkbox', { name: 'Project Old' })).toHaveProperty('checked', false)
    expect(within(legacy).getByRole('checkbox', { name: 'Project Core' })).toHaveProperty('checked', true)
    expect(within(legacy).getAllByTestId('kept-by').map((e) => e.textContent)).toEqual(['kept by Web', 'kept by Web'])
    expect(within(legacy).getAllByText('also in solution Web')).toHaveLength(2)
    expect(box('Solution Legacy').dataset.state).toBe('some')
    expect(box('Solution Web').dataset.state).toBe('all')
  })

  it('a save after someone else saved first is refused, with a reload', async () => {
    server.save.mockRejectedValue(new ApiError(409, 'Not saved: someone else changed this scope first.', [], [{ code: 'STALE_COPY' }]))
    await open()
    await click(box('Project Old'))
    await click(button('Save…'))
    await click(button('Save scope'))
    expect(screen.getByTestId('scope-stale').textContent).toContain('someone else changed this scope first')
    server.scope = scopeWith([P('Web')], 2)
    await click(within(screen.getByTestId('scope-stale')).getByRole('button', { name: 'Reload' }))
    expect(box('Project Web').checked).toBe(false)
    expect(box('Project Old').checked).toBe(true)
  })
})
