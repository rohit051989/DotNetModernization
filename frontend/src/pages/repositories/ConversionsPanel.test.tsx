import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Conversions, PrepareAttempt } from '../../types/conversion'
import type { Toolchain } from '../../types/toolchain'
import { ConversionsPanel, preparationProblem } from './ConversionsPanel'
import { resetEngineViewForTests } from './engineView'

const api = vi.hoisted(() => ({ listConversions: vi.fn(), verifyConversion: vi.fn() }))
vi.mock('../../api/conversion', () => ({
  listConversions: api.listConversions,
  startNextConversion: vi.fn(),
  verifyConversion: api.verifyConversion,
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

afterEach(() => {
  cleanup()
  resetEngineViewForTests()
  window.localStorage.clear()
})

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

describe('both engines', () => {
  const entry = {
    number: 1, branch: 'conversion/1', state: 'run' as const, baseline: 'e89bc6a1', baseline_from: null, scanned_at: null,
    head: null, commits_beyond_inputs: 2, uncommitted: [], worktree: 'D:/runs/wt', prepared_at: null, runbook_path: 'D:/runs/RUNBOOK.md',
    runbook: 'both', opening_message: 'copilot first message', package_step: {}, left_for_agent: {}, verify_refusal: null,
    verification: null, verifying: false, plan: null, superseded_plans: [],
    engines: {
      'github-copilot': { prepared: true, usable: true, opening: 'copilot first message', runbook: 'COPILOT RUNBOOK: open D:/runs/wt/in-scope.sln' },
      'claude-code': { prepared: true, usable: false, unsafe: 'not safe to use here: Claude Code would also read instruction files above the worktree, which are not the conversion’s: D:/runs/CLAUDE.md',
                       opening: 'claude first message', runbook: 'CLAUDE RUNBOOK: cd "D:/runs/wt"' },
    },
  }

  async function shown() {
    api.listConversions.mockResolvedValue({ ...conversions({ at: null, status: 'prepared', message: 'x', number: 1, jobExecutionId: null }), conversions: [entry] })
    render(<ConversionsPanel repositoryId="r" refreshToken={0} />)
    await act(async () => {})
  }

  it('every conversion has both; the dropdown switches the first message and the runbook, remembered in this browser', async () => {
    await shown()
    expect(screen.getByTestId('conversion-engines').textContent).toContain('GitHub Copilot: prepared')
    expect(screen.getByTestId('conversion-engines').textContent).toContain('Claude Code: not safe to use here')
    expect(screen.getByText('copilot first message')).toBeTruthy()
    expect(screen.getByText('COPILOT RUNBOOK: open D:/runs/wt/in-scope.sln')).toBeTruthy()
    expect(screen.queryByTestId('engine-unsafe')).toBeNull()
    await act(async () => {
      fireEvent.change(screen.getByLabelText("Which assistant's inputs and runbook to show"), { target: { value: 'claude-code' } })
    })
    expect(screen.getByText('claude first message')).toBeTruthy()
    expect(screen.getByText('CLAUDE RUNBOOK: cd "D:/runs/wt"')).toBeTruthy()
    expect(screen.getByTestId('engine-unsafe').textContent).toContain('D:/runs/CLAUDE.md')
    expect(window.localStorage.getItem('conversion:engine-view')).toBe('claude-code')
    expect(screen.queryByTestId('engine-picker')).toBeNull()
  })

  it('Verify asks which assistant did the conversion, defaulting to the one shown, and sends it', async () => {
    window.localStorage.setItem('conversion:engine-view', 'claude-code')
    api.verifyConversion.mockResolvedValue({ job_execution_id: 'j' })
    await shown()
    await act(async () => {
      fireEvent.click(screen.getByText('Verify conversion 1'))
    })
    const asked = screen.getByLabelText('Which assistant did the conversion') as HTMLSelectElement
    expect(asked.value).toBe('claude-code')
    await act(async () => {
      fireEvent.change(asked, { target: { value: 'github-copilot' } })
    })
    await act(async () => {
      fireEvent.click(screen.getByText('Verify'))
    })
    expect(api.verifyConversion).toHaveBeenCalledWith('r', 1, 'github-copilot')
  })
})

describe('not run, kept, and one engine only', () => {
  const legacy = {
    number: 1, branch: 'conversion/1', state: 'prepared' as const, baseline: 'e89bc6a1', baseline_from: null, scanned_at: null,
    head: null, commits_beyond_inputs: 0, uncommitted: ['.goal-workflow.md'], untracked: ['.goal-workflow.md'], run_because: null,
    worktree: 'D:/runs/wt', prepared_at: null, runbook_path: 'D:/runs/RUNBOOK.md', runbook: 'copilot runbook',
    opening_message: 'copilot first message', package_step: {}, left_for_agent: {}, verify_refusal: null, verification: null,
    verifying: false, plan: null, superseded_plans: [],
    engines: {
      'github-copilot': { prepared: true, usable: true, opening: 'copilot first message', runbook: 'copilot runbook' },
      'claude-code': { prepared: false, usable: false, notPrepared: 'prepared for one engine only (GitHub Copilot), before every conversion got both engines’ inputs' },
    },
    one_engine: { engine: 'github-copilot' as const, missing: 'claude-code' as const,
      how: 'It has not been run, so its next preparation adds Claude Code’s inputs: rescan the repository.' },
  }

  it('a conversion prepared for one engine says so and how to add the other; an untracked file is listed, not counted', async () => {
    const last: PrepareAttempt = {
      at: null, status: 'kept', number: 1, jobExecutionId: null, keptBecause: 'collision', details: ['.claude/CLAUDE.md'],
      message: 'conversion 1 kept as it is: 1 untracked file(s) in its worktree sit where the new inputs would be written (.claude/CLAUDE.md). Move or delete them, or commit them on the branch, then rescan.',
    }
    api.listConversions.mockResolvedValue({ ...conversions(last), conversions: [legacy] })
    render(<ConversionsPanel repositoryId="r" refreshToken={0} />)
    await act(async () => {})
    expect(screen.getByTestId('one-engine').textContent).toBe(
      'Prepared for one engine only (GitHub Copilot). It has not been run, so its next preparation adds Claude Code’s inputs: rescan the repository.')
    expect(screen.getByTestId('conversion-untracked').textContent).toContain('1 untracked file(s) a person left (.goal-workflow.md)')
    expect(screen.queryByTestId('run-because')).toBeNull()
    const kept = screen.getByTestId('preparation-kept')
    expect(kept.querySelector('p')?.textContent).toContain('kept the conversion: conversion 1 kept as it is: 1 untracked file(s)')
    expect(kept.querySelectorAll('li')).toHaveLength(1)
    expect(kept.querySelector('li')?.textContent).toBe('.claude/CLAUDE.md')
  })

  it('a conversion prepared for both shows no one-engine note, and one that counts as run says why', async () => {
    api.listConversions.mockResolvedValue({
      ...conversions({ at: null, status: 'refreshed', message: 'x', number: 1, jobExecutionId: null }),
      conversions: [{ ...legacy, one_engine: null, state: 'run' as const, untracked: [],
        run_because: 'its worktree has uncommitted changes to 1 tracked file(s) (a.cs): commit them on the branch, or discard them' }],
    })
    render(<ConversionsPanel repositoryId="r" refreshToken={0} />)
    await act(async () => {})
    expect(screen.queryByTestId('one-engine')).toBeNull()
    expect(screen.getByTestId('run-because').textContent).toContain('uncommitted changes to 1 tracked file(s) (a.cs)')
    expect(screen.queryByTestId('preparation-kept')).toBeNull()
  })
})

describe('a failed preparation', () => {
  const earlier = {
    number: 1, branch: 'conversion/1', state: 'prepared' as const, baseline: 'e89bc6a1', baseline_from: null, scanned_at: null,
    head: null, commits_beyond_inputs: 0, uncommitted: [], untracked: [], run_because: null, worktree: 'D:/runs/wt',
    prepared_at: '2026-11-20T10:00:00Z', runbook_path: 'D:/runs/RUNBOOK.md', runbook: 'runbook', opening_message: 'first message',
    package_step: {}, left_for_agent: {}, verify_refusal: null, verification: null, verifying: false, plan: null,
    superseded_plans: [], one_engine: null,
    engines: { 'github-copilot': { prepared: true, usable: true, opening: 'first message', runbook: 'runbook' } },
  }

  it('shows its message and labels the conversion still shown as older', async () => {
    api.listConversions.mockResolvedValue({
      ...conversions({ at: '2026-11-23T22:00:00Z', status: 'failed', number: null, jobExecutionId: 'j2',
        message: 'ValueError: target v4.7 is not a .NET (5+) framework' }),
      conversions: [earlier],
    })
    render(<ConversionsPanel repositoryId="r" refreshToken={0} />)
    await act(async () => {})
    const note = screen.getByTestId('preparation-failed').textContent ?? ''
    expect(note).toContain('failed; conversion 1 below is older, as an earlier preparation left it')
    expect(note).toContain('target v4.7 is not a .NET (5+) framework')
    expect(screen.getByTestId('conversion-older').textContent).toBe('older: the last preparation failed')
  })

  it('a conversion prepared after a successful preparation is not labelled older', async () => {
    api.listConversions.mockResolvedValue({
      ...conversions({ at: '2026-11-23T22:00:00Z', status: 'refreshed', number: 1, jobExecutionId: 'j2', message: 'x' }),
      conversions: [{ ...earlier, prepared_at: '2026-11-23T22:00:00Z' }],
    })
    render(<ConversionsPanel repositoryId="r" refreshToken={0} />)
    await act(async () => {})
    expect(screen.queryByTestId('preparation-failed')).toBeNull()
    expect(screen.queryByTestId('conversion-older')).toBeNull()
  })
})
