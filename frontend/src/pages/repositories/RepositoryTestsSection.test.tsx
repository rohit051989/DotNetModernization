import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RepositoryTests } from '../../types/tests'
import { RepositoryTestsSection } from './RepositoryTestsSection'

const NO_REPORT = 'not measured — no coverage report in the repository or a configured CI output location, and test execution is not enabled'
const INTEGRATION = 'not measured — integration tests are not executed during discovery, and no integration coverage report exists'
const NOT_IN_REPORT = 'not measured — this file is in no coverage report'

/** 25 source files: the last one (not measured for a reason of its own) is past the first 20. */
const data = {
  repository_id: 'r',
  scan: { commit_sha: null, cache_state: 'computed', cache_note: null },
  summary: { testClasses: 0, testMethods: 0 },
  ci_maturity: null,
  test_projects: [],
  test_classes: [],
  projects: [
    { project_path: 'src/A/A.csproj', files: 25, has_tests: 0, missing_tests: 25, no_testable_logic: 0,
      unit_line_pct: null, unit_not_measured_reason: NO_REPORT, integration_line_pct: null, integration_not_measured_reason: INTEGRATION },
  ],
  source_files: Array.from({ length: 25 }, (_, i) => ({
    file_path: `src/A/F${String(i + 1).padStart(2, '0')}.cs`, bucket: 'missing_tests', testable_members: 1, tests: [],
    line_pct: null, not_measured_reason: i === 24 ? NOT_IN_REPORT : NO_REPORT, branch_pct: null, coverage_source: 'none',
  })),
  coverage_reports: [],
  execution: 'Tests are not executed during discovery.',
} as unknown as RepositoryTests

vi.mock('../../api/surface', () => ({ getRepositoryTests: () => Promise.resolve(data) }))

afterEach(cleanup)

describe('RepositoryTestsSection', () => {
  it('lists every not-measured reason as a numbered footnote, numbered as the cells refer to them', async () => {
    render(<RepositoryTestsSection repositoryId="r" localPath={null} refreshToken={0} />)
    const notes = await screen.findByRole('list', { name: 'Not measured: why' })
    expect(within(notes).getAllByRole('listitem').map((li) => li.textContent)).toEqual([`1 ${NO_REPORT}`, `2 ${INTEGRATION}`, `3 ${NOT_IN_REPORT}`])

    // The per-project row refers to notes 1 and 2.
    const project = screen.getByText('src/A/A.csproj').closest('tr')!
    expect([...project.querySelectorAll('sup')].map((s) => s.textContent)).toEqual(['1', '2'])

    // A file past the first 20 keeps its number once shown.
    fireEvent.click(screen.getByRole('button', { name: '+5 more' }))
    const last = screen.getByText('src/A/F25.cs').closest('tr')!
    expect(last.querySelector('sup')?.textContent).toBe('3')
  })
})
