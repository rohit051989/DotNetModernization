// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RepositoryDetail } from '../../types/repositories'
import { RepositoryOverview } from './RepositoryOverview'

afterEach(cleanup)

const repo = { local_path: 'D:\repos\shop', default_branch: null } as unknown as RepositoryDetail

describe('RepositoryOverview: the Compatibility issues card', () => {
  it('shows the overall count and what it is made of, and opens the Compatibility tab', () => {
    const open = vi.fn()
    render(
      <RepositoryOverview
        repo={repo}
        summary={{ compatibilityIssues: { value: 8, detail: 'SOAP 3 · Linux 5', tone: 'amber' } }}
        tiles={null}
        onOpenTab={open}
      />,
    )
    expect(screen.queryByText('SOAP calls needing change')).toBeNull()
    expect(screen.getByText('Compatibility issues')).toBeTruthy()
    expect(screen.getByText('8')).toBeTruthy()
    expect(screen.getByText('SOAP 3 · Linux 5')).toBeTruthy()
    fireEvent.click(screen.getByText('Compatibility issues'))
    expect(open).toHaveBeenCalledWith('compatibility')
  })

  it('shows a loader in the card, and no figure, while the counts are still being read', () => {
    render(<RepositoryOverview repo={repo} summary={{ compatibilityIssues: { value: '', loading: true } }} tiles={null} onOpenTab={() => {}} />)
    expect(screen.getByRole('status', { name: 'Compatibility issues loading' })).toBeTruthy()
    expect(screen.queryByText('0')).toBeNull()
  })

  it('says it is waiting for a scan when there is no figure yet', () => {
    render(<RepositoryOverview repo={repo} summary={{}} tiles={null} onOpenTab={() => {}} />)
    expect(screen.getByText('the repository has not been scanned yet')).toBeTruthy()
  })
})
