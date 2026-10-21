import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { CollapsibleSection, GroupedItems, SectionGroup } from './CollapsibleSection'

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
  // jsdom has no layout: scrolling is a no-op here.
  Element.prototype.scrollIntoView = () => {}
})
afterEach(cleanup)

/** A section's header: the button that folds it (it carries aria-expanded), by the title in it. */
const header = (title: string) => {
  const found = screen.getAllByRole('button').find((b) => b.hasAttribute('aria-expanded') && b.querySelector('h3')?.textContent === title)
  if (!found) throw new Error(`no header ${title}`)
  return found
}
const isOpen = (title: string) => header(title).getAttribute('aria-expanded') === 'true'

function Surface({ rows }: { rows: number }) {
  return (
    <SectionGroup label="Surface sections" order={['s:inbound', 's:soap']}>
      <CollapsibleSection id="s:soap" title="SOAP compatibility" summary="9 calls, 2 need change" rowCount={9} persist="browser" variant="nested">
        <p>soap body</p>
      </CollapsibleSection>
      <CollapsibleSection id="s:inbound" title="Inbound" summary={`${rows} projects`} rowCount={rows} persist="browser" variant="nested">
        <p>inbound body</p>
      </CollapsibleSection>
    </SectionGroup>
  )
}

describe('CollapsibleSection', () => {
  it('folds and opens from its header, and says what is inside while folded', () => {
    render(<Surface rows={10} />)
    expect(isOpen('Inbound')).toBe(true)
    expect(screen.getByText('inbound body')).toBeTruthy()
    fireEvent.click(header('Inbound'))
    expect(isOpen('Inbound')).toBe(false)
    expect(screen.queryByText('inbound body')).toBeNull()
    expect(screen.getByText('10 projects')).toBeTruthy()
  })

  it('starts collapsed the first time when it lists more than 50 rows', () => {
    render(<Surface rows={176} />)
    expect(isOpen('Inbound')).toBe(false)
    expect(isOpen('SOAP compatibility')).toBe(true)
  })

  it('remembers its state in the browser across a reload', () => {
    const first = render(<Surface rows={176} />)
    fireEvent.click(header('Inbound'))
    fireEvent.click(header('SOAP compatibility'))
    first.unmount()
    render(<Surface rows={176} />)
    expect(isOpen('Inbound')).toBe(true)
    expect(isOpen('SOAP compatibility')).toBe(false)
    expect(window.localStorage.getItem('section:s:inbound')).toBe('open')
  })

  it('expands and collapses every section of its group, and jump links follow the group order', () => {
    render(<Surface rows={176} />)
    const nav = screen.getByRole('navigation', { name: 'Surface sections' })
    const links = Array.from(nav.querySelectorAll('button')).map((b) => b.textContent)
    expect(links).toEqual(['Inbound', 'SOAP compatibility', 'Expand all', 'Collapse all'])
    fireEvent.click(screen.getByRole('button', { name: 'Expand all' }))
    expect([isOpen('Inbound'), isOpen('SOAP compatibility')]).toEqual([true, true])
    fireEvent.click(screen.getByRole('button', { name: 'Collapse all' }))
    expect([isOpen('Inbound'), isOpen('SOAP compatibility')]).toEqual([false, false])
  })

  it('opens a section from its jump link', () => {
    render(<Surface rows={176} />)
    fireEvent.click(screen.getByRole('button', { name: 'Inbound' }))
    expect(isOpen('Inbound')).toBe(true)
  })
})

describe('GroupedItems', () => {
  it('is one line until opened', () => {
    render(
      <GroupedItems label="164 projects with no request entry points">
        <p>the projects</p>
      </GroupedItems>,
    )
    expect(screen.queryByText('the projects')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /164 projects with no request entry points/ }))
    expect(screen.getByText('the projects')).toBeTruthy()
  })
})
