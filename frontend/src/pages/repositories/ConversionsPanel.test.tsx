import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Conversions, PrepareAttempt } from '../../types/conversion'
import { ConversionsPanel, preparationProblem } from './ConversionsPanel'

const api = vi.hoisted(() => ({ listConversions: vi.fn() }))
vi.mock('../../api/conversion', () => ({
  listConversions: api.listConversions,
  startNextConversion: vi.fn(),
  verifyConversion: vi.fn(),
  getRepositoryConversion: vi.fn(),
  evidenceHref: (url: string) => url,
}))

function conversions(last: PrepareAttempt): Conversions {
  return {
    conversions: [], other_plans: [], discovery_job: null, verification_job: null, held: null, last_prepare: last,
    next: { number: 1, branch: 'conversion/1', starts_from: null, starts_from_subject: null, last_scanned: null, last_scanned_at: null },
  }
}

async function show(last: PrepareAttempt) {
  api.listConversions.mockResolvedValue(conversions(last))
  render(<ConversionsPanel repositoryId="r" refreshToken={0} />)
  await act(async () => {})
}

afterEach(cleanup)

describe('the last preparation', () => {
  it('shows a refusal as a short summary, with the full list behind a details toggle', async () => {
    const details = Array.from({ length: 12 }, (_, i) => `.github/upgrades/skills/applying-${i}.md: repository value (the value of K${i} in deploy/SetParam.xml)`)
    await show({ at: null, status: 'failed', number: null, jobExecutionId: null, details,
      message: 'Refused, a generated input would still contain a secret value: 12 finding(s) in 12 file(s). Nothing was written.' })
    const note = screen.getByTestId('preparation-failed')
    expect(note.querySelector('p')?.textContent).toContain('12 finding(s) in 12 file(s)')
    const toggle = screen.getByText('details (12)')
    expect(note.querySelector('details')?.open).toBe(false)
    fireEvent.click(toggle)
    expect(note.querySelectorAll('li')).toHaveLength(12)
  })

  it('shows secret values named by reference as a warning, the preparation having completed', async () => {
    await show({ at: null, status: 'prepared', message: 'conversion 1 prepared', number: 1, jobExecutionId: null,
      warnings: { summary: '2 secret value(s) named by file, key and line instead of quoted, in 1 generated file(s)',
        details: ['.github/upgrades/skills/applying-move-to-secret.md: 2 reference(s)'] } })
    expect(screen.getByTestId('preparation-warning').textContent).toContain('2 secret value(s) named by file, key and line')
    expect(screen.queryByTestId('preparation-failed')).toBeNull()
  })
})

describe('preparationProblem', () => {
  it('summarises a long message recorded before the summary and the list were kept apart', () => {
    const old = 'SecretFound: .github/a.md: repository value (the value of X_Binding@value in d/SetParam.xml); '
      + '.github/b.md: repository value (the value of Cors_Domain_W@value in d/SetParam.xml); '
      + '.github/a.md: token (line 3)'
    expect(preparationProblem(old)).toEqual({
      summary: 'SecretFound: 3 finding(s) in 2 file(s)',
      details: [
        '.github/a.md: repository value (the value of X_Binding@value in d/SetParam.xml)',
        '.github/b.md: repository value (the value of Cors_Domain_W@value in d/SetParam.xml)',
        '.github/a.md: token (line 3)',
      ],
    })
    expect(preparationProblem('RuntimeError: one thing')).toEqual({ summary: 'RuntimeError: one thing', details: [] })
  })
})
