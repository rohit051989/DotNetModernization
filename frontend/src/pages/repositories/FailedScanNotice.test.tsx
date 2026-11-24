import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { FailedScan } from '../../types/results'
import { FailedScanBanner, OlderResultsNotice } from './FailedScanNotice'
import { TAB_STEPS, TABS } from './repositoryTabs'

const FAILED: FailedScan = {
  job_execution_id: 'e1',
  status: 'FAILED',
  failed_step: 'dependency-assessment',
  message: 'ArtifactSchemaValidationException: Artifact failed JSON Schema validation:',
  at: '2026-11-19T20:06:00Z',
  results_from: {
    'dependency-assessment': '2026-11-19T13:36:00Z',
    'dependency-hierarchy': '2026-11-19T13:37:00Z',
    'item-detection': '2026-11-19T13:38:00Z',
    'test-coverage-assessment': null,
    'impact-analysis': '2026-11-19T13:40:00Z',
    'conversion-preparation': '2026-11-19T13:41:00Z',
  },
}

afterEach(cleanup)

describe('a failed scan', () => {
  it('the header says when, at which step and why, and opens the Activity tab', () => {
    const open = vi.fn()
    render(<FailedScanBanner failed={FAILED} onOpenActivity={open} />)
    const banner = screen.getByTestId('failed-scan')
    expect(banner.textContent).toContain('failed at dependency-assessment')
    expect(banner.textContent).toContain(new Date(FAILED.at).toLocaleString())
    expect(banner.textContent).toContain('ArtifactSchemaValidationException')
    fireEvent.click(screen.getByRole('button', { name: 'Open Activity' }))
    expect(open).toHaveBeenCalled()
  })

  it('a completed run whose conversion-preparation failed says so in the header, and no tab is labelled older for it', () => {
    const prep: FailedScan = { job_execution_id: 'e2', status: 'COMPLETED', failed_step: 'conversion-preparation', kind: 'preparation',
      message: 'ValueError: target v4.7 is not a .NET (5+) framework', at: '2026-11-23T22:00:00Z', results_from: {} }
    render(<FailedScanBanner failed={prep} onOpenActivity={vi.fn()} />)
    const banner = screen.getByTestId('failed-scan').textContent ?? ''
    expect(banner).toContain('completed, but its conversion-preparation failed: ValueError: target v4.7')
    expect(banner).toContain('The Conversion tab shows the conversion an earlier preparation left')
    cleanup()
    render(<OlderResultsNotice failed={prep} tab="conversion" />)
    expect(screen.queryByTestId('older-results')).toBeNull()
  })

  it('a tab whose step did not complete labels its results as older, with their date', () => {
    render(<OlderResultsNotice failed={FAILED} tab="dependencies" />)
    const notice = screen.getByTestId('older-results')
    expect(notice.textContent).toContain(`Older results, from the scan of ${new Date('2026-11-19T13:36:00Z').toLocaleString()}`)
    expect(notice.textContent).toContain('dependency-assessment')
  })

  it('a tab whose steps completed in the failed run says nothing, nor does any tab without a failure', () => {
    render(<OlderResultsNotice failed={FAILED} tab="surface" />)
    render(<OlderResultsNotice failed={FAILED} tab="projects" />)
    render(<OlderResultsNotice failed={null} tab="dependencies" />)
    expect(screen.queryByTestId('older-results')).toBeNull()
  })

  it('a step that never completed says there are no results yet', () => {
    render(<OlderResultsNotice failed={FAILED} tab="tests" />)
    expect(screen.getByTestId('older-results').textContent).toContain('No results yet')
  })

  it('every tab that names steps names real tabs', () => {
    for (const tab of Object.keys(TAB_STEPS)) expect(TABS.some((t) => t.slug === tab)).toBe(true)
  })
})
