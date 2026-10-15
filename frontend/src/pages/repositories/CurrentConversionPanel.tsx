import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import { getCurrentConversion, startNextConversion, verifyConversion } from '../../api/conversion'
import { CopyButton } from '../../components/CopyButton'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import type { ConversionState, CurrentConversion, JobRef } from '../../types/conversion'

/** The repository's current conversion (36-COPILOT-ENHANCED-CONVERSION Part N): what discovery prepared, whether it
 * has been run or verified, the runbook and the opening message to send, and the buttons that verify it or start
 * the next one. Polls while a discovery or verification job of this repository is running. */

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

function running(job: JobRef | null) {
  return !!job && RUNNING.includes(job.batch_status)
}

function Pre({ text }: { text: string }) {
  return (
    <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded border border-neutral-200 bg-neutral-50 p-2 font-mono text-[11px] leading-snug text-neutral-800">
      {text}
    </pre>
  )
}

export function CurrentConversionPanel({ repositoryId, refreshToken }: { repositoryId: string; refreshToken: number }) {
  const [data, setData] = useState<CurrentConversion | null>(null)
  const [failed, setFailed] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [confirmNext, setConfirmNext] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    getCurrentConversion(repositoryId)
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

  async function onVerify() {
    if (!data?.number) return
    setBusy(true)
    setMessage(null)
    try {
      await verifyConversion(repositoryId, data.number)
      setMessage('Verification started. It runs as a workflow job; this section shows its verdict when it ends.')
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

  if (failed && !data) return <p className="text-sm text-red-600">Could not load the current conversion.</p>
  if (!data) return <div className="h-16 animate-pulse rounded bg-neutral-100" />

  const last = data.last_prepare
  const step = data.package_step ?? {}
  const items = data.left_for_agent?.items ?? []

  return (
    <div className="space-y-3 text-sm" data-testid="current-conversion">
      {running(data.discovery_job) && (
        <p className="rounded border border-sky-200 bg-sky-50 px-2 py-1 text-xs text-sky-800">
          Discovery is running; it prepares the conversion when it ends.
        </p>
      )}
      {running(data.verification_job) && (
        <p className="rounded border border-sky-200 bg-sky-50 px-2 py-1 text-xs text-sky-800">Verification is running.</p>
      )}
      {last && (last.status === 'failed' || last.status === 'kept') && (
        <p className={`rounded border px-2 py-1 text-xs ${last.status === 'failed' ? 'border-red-200 bg-red-50 text-red-800' : 'border-neutral-200 bg-neutral-50 text-neutral-600'}`}>
          Last preparation ({last.at?.slice(0, 16).replace('T', ' ')}): {last.message}
        </p>
      )}

      {data.number === null ? (
        <p className="text-sm text-neutral-400">No conversion prepared yet. Discovery prepares one when it ends.</p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-neutral-800">Conversion {data.number}</span>
            {data.state && (
              <span className={`rounded border px-1.5 text-[11px] ${STATE_STYLE[data.state]}`} title={STATE_LABEL[data.state]}>
                {data.state}
              </span>
            )}
            <span className="text-xs text-neutral-500">
              prepared {data.prepared_at?.slice(0, 16).replace('T', ' ')} · {data.commits_beyond_inputs} commit(s) beyond its inputs
              {data.uncommitted.length > 0 && ` · ${data.uncommitted.length} uncommitted change(s)`}
            </span>
          </div>

          <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 text-xs">
            <dt className="text-neutral-500">Branch</dt>
            <dd className="font-mono">{data.branch}</dd>
            <dt className="text-neutral-500">Worktree</dt>
            <dd className="flex items-center gap-2 font-mono break-all">
              {data.worktree} {data.worktree && <CopyButton value={data.worktree} />}
            </dd>
            <dt className="text-neutral-500">Baseline</dt>
            <dd className="font-mono">{data.baseline?.slice(0, 10)}</dd>
            <dt className="text-neutral-500">Package step</dt>
            <dd>
              {step.skipped
                ? `skipped: ${step.skipped}`
                : `${step.cycles ?? 0} build-and-test cycle(s), ${step.seconds ?? 0} s`}
              {step.flaky && step.flaky.length > 0 && ` · flaky: ${step.flaky.map((f) => f.test).join(', ')}`}
            </dd>
            <dt className="text-neutral-500">Left for the engine</dt>
            <dd>{items.length === 0 ? 'nothing' : items.map((i) => `${i.item} (${i.places})`).join(', ')}</dd>
          </dl>

          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-neutral-700">Opening message</span>
              {data.opening_message && <CopyButton value={data.opening_message} label="Copy message" />}
            </div>
            {data.opening_message && <Pre text={data.opening_message} />}
          </div>

          {data.runbook && (
            <details className="rounded border border-neutral-200">
              <summary className="cursor-pointer px-2 py-1 text-xs font-medium text-neutral-700">
                Runbook <span className="font-mono font-normal text-neutral-500">{data.runbook_path}</span>
              </summary>
              <div className="p-2">
                <Pre text={data.runbook} />
              </div>
            </details>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={onVerify}
              disabled={busy || running(data.verification_job)}
              className="rounded border border-violet-300 bg-violet-50 px-2 py-1 text-xs font-medium text-violet-800 hover:bg-violet-100 disabled:opacity-50"
              title={data.verify_refusal ?? 'Verify this conversion, independent of the engine'}
            >
              Verify
            </button>
            {data.verify_refusal && <span className="text-xs text-neutral-500">Verify refuses now: {data.verify_refusal}.</span>}
          </div>

          {data.verification && (
            <div className="space-y-1 rounded border border-neutral-200 p-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded border px-1.5 py-0.5 text-xs font-semibold ${VERDICT_STYLE[data.verification.verdict] ?? ''}`}>
                  {data.verification.verdict}
                </span>
                <span className="text-xs text-neutral-500">
                  verified {data.verification.verifiedAt.slice(0, 16).replace('T', ' ')} at{' '}
                  <span className="font-mono">{data.verification.tip.slice(0, 8)}</span>
                  {!data.verification.current && ' — the branch has moved on since'}
                </span>
              </div>
              {data.verification.reasons.length > 0 && (
                <ul className="list-disc pl-5 text-xs text-neutral-700">
                  {data.verification.reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              )}
              <details>
                <summary className="cursor-pointer text-xs font-medium text-neutral-700">VERIFICATION.md</summary>
                <Pre text={data.verification.markdown} />
              </details>
            </div>
          )}
        </>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-neutral-100 pt-2">
        <button
          type="button"
          onClick={() => setConfirmNext(true)}
          disabled={busy || running(data.discovery_job)}
          className="rounded border border-neutral-300 px-2 py-1 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
        >
          Start the next conversion
        </button>
        {message && <span className="text-xs text-neutral-600">{message}</span>}
      </div>

      <ConfirmDialog
          open={confirmNext}
          title="Start the next conversion?"
          message="Discovery runs again on the repository, then prepares a new conversion with its own branch and worktree. The current one is kept as it is."
          confirmLabel="Start"
          onConfirm={onStartNext}
          onCancel={() => setConfirmNext(false)}
        />
    </div>
  )
}
