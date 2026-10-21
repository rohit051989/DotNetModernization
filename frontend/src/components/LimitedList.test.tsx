import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { LimitedList } from './LimitedList'

afterEach(cleanup)

const projects = (n: number) => Array.from({ length: n }, (_, i) => `src/Client.Project${String(i + 1).padStart(3, '0')}/Client.Project${String(i + 1).padStart(3, '0')}.csproj`)

function List({ items, named = true }: { items: string[]; named?: boolean }) {
  return (
    <LimitedList items={items} name={named ? (p) => p : undefined} noun="projects">
      {(visible) => (
        <ul>
          {visible.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
    </LimitedList>
  )
}

const rows = () => screen.queryAllByRole('listitem').length
const button = (name: RegExp | string) => screen.getByRole('button', { name })

describe('LimitedList', () => {
  it('shows a short list whole, with no controls and no filter', () => {
    render(<List items={projects(20)} />)
    expect(rows()).toBe(20)
    expect(screen.queryAllByRole('button')).toHaveLength(0)
    expect(screen.queryByRole('searchbox')).toBeNull()
  })

  it('shows 20, then "+N more" reveals the rest when 20 or fewer remain, and "Show less" returns to 20', () => {
    render(<List items={projects(35)} />)
    expect(rows()).toBe(20)
    fireEvent.click(button('+15 more'))
    expect(rows()).toBe(35)
    expect(screen.queryByRole('button', { name: /more/ })).toBeNull()
    fireEvent.click(button('Show less'))
    expect(rows()).toBe(20)
    expect(button('+15 more')).toBeTruthy()
  })

  it('offers "Show 20 more · N remaining" and "Show all" when more than 20 remain', () => {
    render(<List items={projects(176)} />)
    expect(rows()).toBe(20)
    fireEvent.click(button('Show 20 more · 156 remaining'))
    expect(rows()).toBe(40)
    expect(button('Show less')).toBeTruthy()
    fireEvent.click(button('Show all'))
    expect(rows()).toBe(176)
    expect(screen.queryByRole('button', { name: /Show all|more/ })).toBeNull()
    fireEvent.click(button('Show less'))
    expect(rows()).toBe(20)
  })

  it('counts down to "+N more" for the last 20 or fewer', () => {
    render(<List items={projects(50)} />)
    fireEvent.click(button('Show 20 more · 30 remaining'))
    expect(rows()).toBe(40)
    fireEvent.click(button('+10 more'))
    expect(rows()).toBe(50)
  })

  it('filters a long list on the names shown, from part of a name, before limiting', () => {
    render(<List items={projects(176)} />)
    const box = screen.getByRole('searchbox', { name: 'Filter projects' })
    fireEvent.change(box, { target: { value: 'project17' } })
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual(
      ['170', '171', '172', '173', '174', '175', '176'].map((n) => `src/Client.Project${n}/Client.Project${n}.csproj`),
    )
    expect(screen.getByText('7 of 176 match')).toBeTruthy()
    fireEvent.change(box, { target: { value: 'project1' } })
    const matches = projects(176).filter((p) => p.toLowerCase().includes('project1')).length   // Project100 to Project176
    expect(rows()).toBe(20)                                 // limited again, from the start
    expect(button(`Show 20 more · ${matches - 20} remaining`)).toBeTruthy()
    fireEvent.change(box, { target: { value: 'nothing like it' } })
    expect(screen.getByText('No projects match “nothing like it”.')).toBeTruthy()
  })

  it('has no filter without names, and limits all the same', () => {
    render(<List items={projects(60)} named={false} />)
    expect(screen.queryByRole('searchbox')).toBeNull()
    expect(rows()).toBe(20)
  })

  it('limits a nested list independently', () => {
    const groups = Array.from({ length: 3 }, (_, g) => ({ name: `group ${g}`, members: projects(30) }))
    render(
      <LimitedList items={groups}>
        {(visible) => (
          <div>
            {visible.map((group) => (
              <section key={group.name} aria-label={group.name}>
                <LimitedList items={group.members}>{(members) => <ul>{members.map((m) => <li key={m}>{m}</li>)}</ul>}</LimitedList>
              </section>
            ))}
          </div>
        )}
      </LimitedList>,
    )
    const first = within(screen.getByRole('region', { name: 'group 0' }))
    fireEvent.click(first.getByRole('button', { name: '+10 more' }))
    expect(first.getAllByRole('listitem')).toHaveLength(30)
    expect(within(screen.getByRole('region', { name: 'group 1' })).getAllByRole('listitem')).toHaveLength(20)
  })
})
