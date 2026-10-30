import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import { listConversions, startNextConversion, verifyConversion } from '../../api/conversion'
import { CopyButton } from '../../components/CopyButton'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { LimitedList } from '../../components/LimitedList'
import type { ConversionEntry, ConversionState, Conversions, JobRef, PlanRef } from '../../types/conversion'
import { RepositoryConversionSection } from './RepositoryConversionSection'

/** Every conversion of the repository, newest first (36-COPILOT-ENHANCED-CONVERSION Part N): number, branch, status
 * and verdict; in each, where it starts from, its runbook and opening message, Verify, its verification, and its own
 * package-step plan (earlier plans of a refreshed conversion hidden as superseded). "Start the next conversion" says
 * what it does and which commit it starts from. Polls while a discovery or verification job runs. */

const STATE_STYLE: Record<ConversionState, string> = {
  prepared: 'border-sky-200 bg-sky-50 text-sky-800',
  run: 'border-amber-200 bg-amber-50 text-amber-800',
  verified: 'border-emerald-200 bg-emerald-50 text-emerald-800',
}

const STATE_LABEL: Record<ConversionState, string> = {
  prepared: 'prepared — ready for the engine, not run yet',
  run: 'run — the branch has the engine’s commits; not verified',
  verified: 'verified — a verification of the branch’s current head',
}

const VERDICT_STYLE: Record<string, string> = {
  PROVEN: 'border-emerald-300 bg-emerald-50 text-emerald-800',
  'PARTLY PROVEN': 'border-amber-300 bg-amber-50 text-amber-800',
  'NOT PROVEN': 'border-red-300 bg-red-50 text-red-800',
}

const RUNNING = ['STARTING', 'STARTED']

/** A preparation's problem as a short summary and the full list. An attempt recorded before the two were kept apart
 *  has one long message of "file: check (detail)" findings joined by "; ": summarised here the same way. */
export function preparationProblem(message: string | null, details?: string[]): { summary: string; details: string[] } {
  const text = message ?? ''
  if (details && details.length) return { summary: text, details }
  const parts = text.split('; ')
  if (parts.length < 3) return { summary: text, details: [] }
  const head = /^(\w+): /.exec(parts[0])
  const findings = head ? [parts[0].slice(head[0].length), ...parts.slice(1)] : parts
  const files = new Set(findings.map((f) => f.split(/:(?:\d+:)? /)[0]))
  return { summary: `${head ? `${head[1]}: ` : ''}${findings.length} finding(s) in ${files.size} file(s)`, details: findings }
}

function PreparationNote({ tone, label, summary, details }: { tone: 'failed' | 'kept' | 'warning'; label: string; summary: string; details: string[] }) {
  const style = tone === 'failed' ? 'border-red-200 bg-red-50 text-red-800'
    : tone === 'warning' ? 'border-amber-200 bg-amber-50 text-amber-900' : 'border-neutral-200 bg-neutral-50 text-neutral-600'
  return (
    <div className={`rounded border px-2 py-1 text-xs ${style}`} data-testid={`preparation-${tone}`}>
      <p>{label}: {summary}</p>
      {details.length > 0 && (
        <details className="mt-1">
          <summary className="cursor-pointer select-none underline decoration-dotted">details ({details.length})</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 font-mono text-[11px]">
            {details.map((d, i) => <li key={i} className="break-all">{d}</li>)}
          </ul>
        </details>
      )}
    </div>
  )
}

function running(job: JobRef | null) {
  return !!job && RUNNING.includes(job.batch_status)
}

/** In local time, as every other time on the page: the stored times are UTC. */
function when(iso: string | null | undefined) {
  if (!iso) return ''
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
}

function Pre({ text }: { text: string }) {
  return (
    <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded border border-neutral-200 bg-neutral-50 p-2 font-mono text-[11px] leading-snug text-neutral-800">
      {text}
    </pre>
  )
}

function SupersededPlans({ repositoryId, plans, refreshToken, label }: { repositoryId: string; plans: PlanRef[]; refreshToken: number; label: string }) {
  const [shown, setShown] = useState(false)
  if (plans.length === 0) return null
  return (
    <div className="space-y-2">
      <button type="button" onClick={() => setShown(!shown)} className="text-xs text-violet-700 hover:underline">
        {shown ? 'Hide' : 'Show'} {plans.length} {label}
      </button>
      {shown && (
        <LimitedList items={plans} name={(p) => p.id.slice(0, 8)} noun="plans">
          {(visible) => (
            <div className="space-y-2">
              {visible.map((p) => (
                <div key={p.id} className="space-y-1 rounded border border-dashed border-neutral-300 p-2 opacity-80">
                  <p className="text-[11px] font-medium uppercase tracking-wide text-neutral-500">
                    Superseded · plan <span className="font-mono">{p.id.slice(0, 8)}</span> of {when(p.created_at)} · {p.status}
                  </p>
                  <RepositoryConversionSection repositoryId={repositoryId} planId={p.id} refreshToken={refreshToken} />
                </div>
              ))}
            </div>
          )}
        </LimitedList>
      )}
    </div>
  )
}

function ConversionCard({
  repositoryId,
  entry,
  refreshToken,
  defaultOpen,
  verifyBusy,
  onVerify,
  refusal,
}: {
  repositoryId: string
  entry: ConversionEntry
  refreshToken: number
  defaultOpen: boolean
  verifyBusy: boolean
  onVerify: (number: number) => void
  refusal: string | null
}) {
  const step = entry.package_step ?? {}
  const items = entry.left_for_agent?.items ?? []
  const verifiable = entry.state !== 'prepared'
  return (
    <details open={defaultOpen} className="rounded border border-neutral-200" data-testid={`conversion-${entry.number}`}>
      <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-3 py-2">
        <span className="font-medium text-neutral-800">Conversion {entry.number}</span>
        <span className="font-mono text-xs text-neutral-600">{entry.branch}</span>
        <span className={`rounded border px-1.5 text-[11px] ${STATE_STYLE[entry.state]}`} title={STATE_LABEL[entry.state]}>
          {entry.state}
        </span>
        {entry.verification && (
          <span className={`rounded border px-1.5 text-[11px] font-semibold ${VERDICT_STYLE[entry.verification.verdict] ?? ''}`}>
            {entry.verification.verdict}
            {!entry.verification.current && ' (older head)'}
          </span>
        )}
        {entry.verifying && <span className="text-[11px] text-sky-700">verifying…</span>}
        <span className="text-xs text-neutral-500">
          from <span className="font-mono">{entry.baseline.slice(0, 8)}</span> · prepared {when(entry.prepared_at)}
        </span>
      </summary>

      <div className="space-y-3 border-t border-neutral-100 p-3">
        <dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-1 text-xs">
          <dt className="text-neutral-500">Starts from</dt>
          <dd>
            <span className="font-mono">{entry.baseline.slice(0, 10)}</span>
            {entry.baseline_from && <span className="text-neutral-500"> — {entry.baseline_from}</span>}
            {entry.scanned_at && <span className="text-neutral-500"> ({when(entry.scanned_at)})</span>}
          </dd>
          <dt className="text-neutral-500">Worktree</dt>
          <dd className="flex items-center gap-2 break-all font-mono">
            {entry.worktree} <CopyButton value={entry.worktree} />
          </dd>
          <dt className="text-neutral-500">Engine’s commits</dt>
          <dd>
            {entry.commits_beyond_inputs} beyond its inputs
            {entry.uncommitted.length > 0 && ` · ${entry.uncommitted.length} uncommitted change(s)`}
          </dd>
          <dt className="text-neutral-500">Package step</dt>
          <dd>
            {step.skipped ? `skipped: ${step.skipped}` : `${step.cycles ?? 0} build-and-test cycle(s), ${step.seconds ?? 0} s`}
            {step.flaky && step.flaky.length > 0 && ` · flaky: ${step.flaky.map((f) => f.test).join(', ')}`}
          </dd>
          <dt className="text-neutral-500">Left for the engine</dt>
          <dd>{items.length === 0 ? 'nothing' : items.map((i) => `${i.item} (${i.places})`).join(', ')}</dd>
        </dl>

        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-neutral-700">Opening message</span>
            {entry.opening_message && <CopyButton value={entry.opening_message} label="Copy message" />}
          </div>
          {entry.opening_message && <Pre text={entry.opening_message} />}
        </div>

        {entry.runbook && (
          <details className="rounded border border-neutral-200">
            <summary className="cursor-pointer px-2 py-1 text-xs font-medium text-neutral-700">
              Runbook <span className="font-mono font-normal text-neutral-500">{entry.runbook_path}</span>
            </summary>
            <div className="p-2">
              <Pre text={entry.runbook} />
            </div>
          </details>
        )}

        <div className="flex flex-wrap items-center gap-2">
          {verifiable ? (
            <button
              type="button"
              onClick={() => onVerify(entry.number)}
              disabled={verifyBusy || !!entry.verify_refusal || !!refusal}
              className="rounded border border-violet-300 bg-violet-50 px-2 py-1 text-xs font-medium text-violet-800 hover:bg-violet-100 disabled:opacity-50"
              title={refusal ?? entry.verify_refusal ?? `Verify conversion ${entry.number}, independent of the engine`}
            >
              Verify conversion {entry.number}
            </button>
          ) : null}
          {entry.verify_refusal && (
            <span className="text-xs text-neutral-500">{verifiable ? 'Verify refuses now: ' : ''}{entry.verify_refusal}.</span>
          )}
        </div>

        {entry.verification && (
          <div className="space-y-1 rounded border border-neutral-200 p-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded border px-1.5 py-0.5 text-xs font-semibold ${VERDICT_STYLE[entry.verification.verdict] ?? ''}`}>
                {entry.verification.verdict}
              </span>
              <span className="text-xs text-neutral-500">
                verified {when(entry.verification.verifiedAt)} at <span className="font-mono">{entry.verification.tip.slice(0, 8)}</span>
                {!entry.verification.current && ' — the branch has moved on since'}
              </span>
            </div>
            <LimitedList items={entry.verification.reasons} name={(r) => r} noun="reasons">
              {(visible) => (
                <ul className="list-disc pl-5 text-xs text-neutral-700">
                  {visible.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              )}
            </LimitedList>
            <details>
              <summary className="cursor-pointer text-xs font-medium text-violet-700">Open VERIFICATION.md</summary>
              <Pre text={entry.verification.markdown} />
            </details>
          </div>
        )}

        <div className="space-y-2 border-t border-neutral-100 pt-2">
          <p className="text-xs font-medium text-neutral-600">Package step — the plan</p>
          {entry.plan ? (
            <RepositoryConversionSection repositoryId={repositoryId} planId={entry.plan.id} refreshToken={refreshToken} />
          ) : (
            <p className="text-xs text-neutral-400">No package-step plan{step.skipped ? `: ${step.skipped}` : ''}.</p>
          )}
          <SupersededPlans
            repositoryId={repositoryId}
            plans={entry.superseded_plans}
            refreshToken={refreshToken}
            label={`superseded plan(s), from earlier preparations of conversion ${entry.number} that a refresh replaced`}
          />
        </div>
      </div>
    </details>
  )
}

/** `refusal`: why the signed-in person may not prepare or verify this repository's conversions (only its owner or an
 * admin, on the machine it was registered on), shown on the disabled buttons; null when they may. */
export function ConversionsPanel({ repositoryId, refreshToken, refusal = null }: { repositoryId: string; refreshToken: number; refusal?: string | null }) {
  const [data, setData] = useState<Conversions | null>(null)
  const [failed, setFailed] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [confirmNext, setConfirmNext] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    listConversions(repositoryId)
      .then((result) => {
        setData(result)
        setFailed(false)
      })
      .catch(() => setFailed(true))
  }, [repositoryId])

  useEffect(() => {
    load()
  }, [load, refreshToken])

  const active = running(data?.discovery_job ?? null) || running(data?.verification_job ?? null)
  useEffect(() => {
    if (!active) return
    const timer = setInterval(load, 5000)
    return () => clearInterval(timer)
  }, [active, load])

  async function onVerify(number: number) {
    setBusy(true)
    setMessage(null)
    try {
      await verifyConversion(repositoryId, number)
      setMessage(`Verification of conversion ${number} started. It runs as a workflow job; its entry shows the verdict when it ends.`)
      load()
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : 'Could not start the verification.')
    } finally {
      setBusy(false)
    }
  }

  async function onStartNext() {
    setConfirmNext(false)
    setBusy(true)
    setMessage(null)
    try {
      await startNextConversion(repositoryId)
      setMessage('Discovery started. When it ends, it prepares the next conversion.')
      load()
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : 'Could not start the next conversion.')
    } finally {
      setBusy(false)
    }
  }

  if (failed && !data) return <p className="text-sm text-red-600">Could not load the conversions.</p>
  if (!data) return <div className="h-16 animate-pulse rounded bg-neutral-100" />

  const last = data.last_prepare
  const next = data.next
  const from = next.starts_from ? next.starts_from.slice(0, 8) : 'the repository’s current commit'
  const subject = next.starts_from_subject ? ` (“${next.starts_from_subject}”)` : ''

  return (
    <div className="space-y-3 text-sm" data-testid="conversions">
      {data.held && (
        <p className="rounded border border-neutral-200 bg-neutral-50 px-2 py-1 text-xs text-neutral-600" data-testid="conversions-held">
          These conversions are {data.held.held_on}: shown as that machine last published them
          {data.held.as_of ? ` (${when(data.held.as_of)})` : ''}. Their worktrees and evidence stay there.
        </p>
      )}
      {running(data.discovery_job) && (
        <p className="rounded border border-sky-200 bg-sky-50 px-2 py-1 text-xs text-sky-800">
          Discovery is running; it prepares the conversion when it ends.
        </p>
      )}
      {last && (last.status === 'failed' || last.status === 'kept') && (
        <PreparationNote tone={last.status === 'failed' ? 'failed' : 'kept'} label={`Last preparation (${when(last.at)})`}
          {...preparationProblem(last.message, last.details)} />
      )}
      {last && last.status !== 'failed' && last.warnings && (
        <PreparationNote tone="warning" label={`Last preparation (${when(last.at)})`}
          summary={last.warnings.summary} details={last.warnings.details} />
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setConfirmNext(true)}
          disabled={busy || running(data.discovery_job) || !!refusal}
          title={refusal ?? undefined}
          className="rounded border border-neutral-300 px-2 py-1 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
        >
          Start the next conversion
        </button>
        <span className="text-xs text-neutral-500">
          Conversion {next.number} would start from <span className="font-mono">{from}</span>
          {subject}, the commit discovery scans first.
        </span>
      </div>
      {message && <p className="text-xs text-neutral-600">{message}</p>}

      <LimitedList
        items={data.conversions}
        name={(entry) => [`Conversion ${entry.number}`, entry.branch]}
        noun="conversions"
        empty={<p className="text-sm text-neutral-400">No conversion prepared yet. Discovery prepares one when it ends.</p>}
      >
        {(visible) => (
          <div className="space-y-2">
            {visible.map((entry) => (
              <ConversionCard
                key={entry.number}
                repositoryId={repositoryId}
                entry={entry}
                refreshToken={refreshToken}
                defaultOpen={entry === data.conversions[0]}
                verifyBusy={busy || running(data.verification_job)}
                onVerify={onVerify}
                refusal={refusal}
              />
            ))}
          </div>
        )}
      </LimitedList>

      <SupersededPlans
        repositoryId={repositoryId}
        plans={data.other_plans}
        refreshToken={refreshToken}
        label="package-step plan(s) not tied to a conversion (from experiments)"
      />

      <ConfirmDialog
        open={confirmNext}
        title={`Start conversion ${next.number}?`}
        message={
          `Discovery scans the repository again, then prepares conversion ${next.number} on a new branch, ${next.branch}, ` +
          `starting from ${from}${subject}: the commit discovery scans. It gets fresh package changes, the agent's ` +
          `instructions and a runbook. No existing conversion is changed, and no engine runs: you run the conversion ` +
          `yourself, from its runbook.`
        }
        confirmLabel={`Start conversion ${next.number}`}
        onConfirm={onStartNext}
        onCancel={() => setConfirmNext(false)}
      />
    </div>
  )
}
