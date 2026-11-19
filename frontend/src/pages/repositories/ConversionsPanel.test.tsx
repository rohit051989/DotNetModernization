import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Conversions, PrepareAttempt } from '../../types/conversion'
import type { Toolchain } from '../../types/toolchain'
import { ConversionsPanel, preparationProblem } from './ConversionsPanel'

const api = vi.hoisted(() => ({ listConversions: vi.fn(), setConversionEngine: vi.fn() }))
vi.mock('../../api/conversion', () => ({
  listConversions: api.listConversions,
  setConversionEngine: api.setConversionEngine,
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

describe('beside Start the next conversion', () => {
  const notReady: Toolchain = {
    checked: true, ready: false, summary: 'Baseline tests cannot run here: needs the .NET 8 runtime (x64)', present: [],
    host: 'DEVBOX-A', checked_at: '2026-11-03T05:00:00+00:00', held_on: null,
    missing: [{ kind: 'runtime', label: 'the .NET 8 runtime (x64)', for: 'test', projects: ['tests/Shop.Tests/Shop.Tests.csproj'],
      detail: '`dotnet test` starts the test host from C:\\Tools\\dotnet (x64) only, which has .NET 10.0.7' }],
  }

  async function withToolchain(toolchain: Toolchain | null) {
    api.listConversions.mockResolvedValue(conversions({ at: null, status: 'prepared', message: 'conversion 1 prepared', number: 1, jobExecutionId: null }))
    render(<ConversionsPanel repositoryId="r" refreshToken={0} toolchain={toolchain} />)
    await act(async () => {})
  }

  it('a repository whose machine cannot run the baseline is told so plainly, with what is missing', async () => {
    await withToolchain(notReady)
    const notice = screen.getByTestId('toolchain-notice')
    expect(notice.querySelector('p')?.textContent).toBe('Baseline tests cannot run here: needs the .NET 8 runtime (x64).')
    expect(notice.textContent).toContain('A conversion prepared now gets no package step')
    expect(notice.textContent).toContain('the .NET 8 runtime (x64), for the tests of tests/Shop.Tests/Shop.Tests.csproj')
    expect(notice.textContent).toContain('which has .NET 10.0.7')
    // The button stays: a conversion still gets the agent's instructions.
    expect(screen.getByRole('button', { name: 'Start the next conversion' }).hasAttribute('disabled')).toBe(false)
  })

  it('a ready machine says so, and one on another machine says whose finding it is', async () => {
    await withToolchain({ ...notReady, ready: true, missing: [], summary: 'Ready: this machine has what the baseline needs to build and run its tests' })
    expect(screen.getByTestId('toolchain-notice').textContent).toBe('Ready: this machine has what the baseline needs to build and run its tests.')
    cleanup()
    await withToolchain({ ...notReady, held_on: "on Alice's machine (DEVBOX-A)" })
    expect(screen.getByTestId('toolchain-notice').querySelector('p')?.textContent).toContain('(as DEVBOX-A last found)')
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

describe('the engine', () => {
  const engine = {
    engine: 'claude-code' as const, source: 'repository' as const, engagement_id: 'e', engagement_default: 'github-copilot' as const,
    engagement_version: 3, on_change: 'Changing it prepares conversion 1 again (it has not been run yet) for the new engine.',
  }

  it('says which engine the next conversion uses and where that comes from, and each conversion names its own', async () => {
    api.listConversions.mockResolvedValue({
      ...conversions({ at: null, status: 'prepared', message: 'conversion 1 prepared', number: 1, jobExecutionId: null }),
      engine,
      conversions: [{ number: 1, branch: 'conversion/1', state: 'prepared', baseline: 'e89bc6a1', baseline_from: null, scanned_at: null,
        head: null, commits_beyond_inputs: 0, uncommitted: [], worktree: 'D:/runs/wt', prepared_at: null, runbook_path: 'RUNBOOK.md',
        runbook: null, opening_message: null, package_step: {}, left_for_agent: {}, verify_refusal: null, verification: null,
        verifying: false, plan: null, superseded_plans: [] }],
    })
    render(<ConversionsPanel repositoryId="r" refreshToken={0} />)
    await act(async () => {})
    const picker = screen.getByTestId('engine-picker')
    expect(picker.textContent).toContain('Engine: Claude Code (this repository’s choice).')
    expect(picker.textContent).toContain('prepares conversion 1 again')
    expect((screen.getByLabelText("This repository's engine") as HTMLSelectElement).value).toBe('claude-code')
    // A conversion prepared before engines were recorded is GitHub Copilot's.
    expect(screen.getByTestId('conversion-engine').textContent).toBe('GitHub Copilot')
  })

  it('the owner chooses the engine, or goes back to the engagement default', async () => {
    api.listConversions.mockResolvedValue({ ...conversions({ at: null, status: 'prepared', message: 'x', number: 1, jobExecutionId: null }), engine })
    api.setConversionEngine.mockResolvedValue({ engine: 'github-copilot', source: 'engagement', note: 'Saved. Conversion 1 is being prepared again for GitHub Copilot.', reprepare_job_execution_id: 'j' })
    render(<ConversionsPanel repositoryId="r" refreshToken={0} />)
    await act(async () => {})
    await act(async () => {
      fireEvent.change(screen.getByLabelText("This repository's engine"), { target: { value: '' } })
    })
    expect(api.setConversionEngine).toHaveBeenCalledWith('r', null)
    expect(screen.getByText('Saved. Conversion 1 is being prepared again for GitHub Copilot.')).toBeTruthy()
  })

  it('cannot be changed by someone who may not act on the repository', async () => {
    api.listConversions.mockResolvedValue({ ...conversions({ at: null, status: 'prepared', message: 'x', number: 1, jobExecutionId: null }), engine })
    render(<ConversionsPanel repositoryId="r" refreshToken={0} refusal="Only its owner or an admin may do this." />)
    await act(async () => {})
    expect((screen.getByLabelText("This repository's engine") as HTMLSelectElement).disabled).toBe(true)
  })
})
