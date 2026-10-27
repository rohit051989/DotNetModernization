import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PagedList, localPages, type Page, type PageLoader } from './PagedList'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

const projects = (n: number) => Array.from({ length: n }, (_, i) => `src/Client.Project${String(i + 1).padStart(3, '0')}/Client.Project${String(i + 1).padStart(3, '0')}.csproj`)

/** A server that pages and filters, recording what it was asked for: the list asks only for what it shows. */
function server(items: string[]) {
  const asked: { q: string; offset: number; limit: number }[] = []
  const pages = localPages(items, (p) => p)
  const load: PageLoader<string> = (q, offset, limit) => {
    asked.push({ q, offset, limit })
    return pages(q, offset, limit)
  }
  return { load, asked }
}

async function show(load: PageLoader<string>, initial: Page<string> | null = null) {
  await act(async () => {
    render(
      <PagedList load={load} resetKey="r" noun="projects" initial={initial}>
        {(visible) => (
          <ul>
            {visible.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
      </PagedList>,
    )
  })
}

const rows = () => screen.queryAllByRole('listitem').length
const click = async (name: string) => {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name }))
  })
}

describe('PagedList', () => {
  it('asks for the first 20 only, then for what each control shows', async () => {
    const { load, asked } = server(projects(176))
    await show(load)
    expect(rows()).toBe(20)
    expect(asked).toEqual([{ q: '', offset: 0, limit: 20 }])
    await click('Show 20 more · 156 remaining')
    expect(rows()).toBe(40)
    expect(asked[1]).toEqual({ q: '', offset: 20, limit: 20 })
    await click('Show all')
    expect(rows()).toBe(176)
    expect(asked[2]).toEqual({ q: '', offset: 40, limit: 136 })
    await click('Show less')
    expect(rows()).toBe(20)
  })

  it('sends the filter box to the server once typing pauses, and starts again from its first page', async () => {
    vi.useFakeTimers()
    const { load, asked } = server(projects(176))
    await show(load)
    fireEvent.change(screen.getByRole('searchbox', { name: 'Filter projects' }), { target: { value: 'project17' } })
    await act(async () => {
      vi.advanceTimersByTime(300)
    })
    expect(asked.at(-1)).toEqual({ q: 'project17', offset: 0, limit: 20 })
    expect(rows()).toBe(7)
    expect(screen.getByText('7 of 176 match')).toBeTruthy()
  })

  it('starts from a first page it was given, asking nothing until more is wanted', async () => {
    const { load, asked } = server(projects(30))
    await show(load, { total: 30, matching: 30, offset: 0, items: projects(20) })
    expect(rows()).toBe(20)
    expect(asked).toEqual([])
    await click('+10 more')
    expect(rows()).toBe(30)
    expect(asked).toEqual([{ q: '', offset: 20, limit: 10 }])
  })

  it('shows a short list whole, with no controls and no filter', async () => {
    await show(server(projects(20)).load)
    expect(rows()).toBe(20)
    expect(screen.queryAllByRole('button')).toHaveLength(0)
    expect(screen.queryByRole('searchbox')).toBeNull()
  })
})
