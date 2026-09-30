import { useEffect, useState } from 'react'
import { listPatterns } from '../../api/catalog'
import { createPatternDraft, decideQueueItem, deferQueueItem, getMergeProposal } from '../../api/validationQueue'
import type { PatternSummary } from '../../types/catalog'
import type { DraftPattern, MergeProposal, PatternCandidatePayload, QueueItem } from '../../types/validationQueue'
import { useToast } from '../../components/Toast'

type Action = 'create_pattern' | 'merge_into_pattern' | 'reject' | 'defer'

const ACTION_LABEL: Record<Action, string> = {
  create_pattern: 'Create pattern',
  merge_into_pattern: 'Merge into existing',
  reject: 'Reject',
  defer: 'Defer',
}

/** Reject and defer both require a note: one discards a shape, the other
 * postpones it, and in six months neither is interpretable without a reason. */
const NOTE_REQUIRED: Action[] = ['reject', 'defer']

interface DecisionPanelProps {
  engagementId: string
  clusterId: string
  item: QueueItem
  payload: PatternCandidatePayload
  onDecided: () => void
}

export function DecisionPanel({ engagementId, clusterId, item, payload, onDecided }: DecisionPanelProps) {
  const [action, setAction] = useState<Action | null>(null)
  const [note, setNote] = useState('')
  const [decidedBy, setDecidedBy] = useState('')
  const [patterns, setPatterns] = useState<PatternSummary[]>([])
  // Defaults to the top proximity match — the human is choosing between
  // candidates the platform already ranked, not searching blind.
  const [mergeTarget, setMergeTarget] = useState(payload.similar_patterns[0]?.pattern_id ?? '')
  const [untilMembers, setUntilMembers] = useState<string>('')
  const [untilCoverage, setUntilCoverage] = useState<string>('')
  const [draft, setDraft] = useState<DraftPattern | null>(null)
  const [proposal, setProposal] = useState<MergeProposal | null>(null)
  const [busy, setBusy] = useState(false)
  const { showToast } = useToast()

  useEffect(() => {
    if (action === 'merge_into_pattern' && patterns.length === 0) {
      listPatterns()
        .then((all) =>
          setPatterns(
            all.filter(
              // A discovered application shape cannot merge into a project-role
              // pattern, and a deprecated one is retired from the catalog —
              // offering either is offering a choice that cannot be right.
              (p) => p.classification_role !== 'PROJECT_ROLE' && p.status !== 'deprecated',
            ),
          ),
        )
        .catch(() => setPatterns([]))
    }
  }, [action, patterns.length])

  // Preview whichever proposal the chosen action implies. Both are read-only:
  // create-pattern returns a draft that is never persisted, merge-proposal a
  // diff that never touches the target.
  useEffect(() => {
    setDraft(null)
    setProposal(null)
    if (action === 'create_pattern') {
      createPatternDraft(engagementId, clusterId).then(setDraft).catch(() => setDraft(null))
    }
    if (action === 'merge_into_pattern' && mergeTarget) {
      getMergeProposal(engagementId, clusterId, mergeTarget).then(setProposal).catch(() => setProposal(null))
    }
  }, [action, mergeTarget, engagementId, clusterId])

  function reset() {
    setAction(null)
    setNote('')
    setDraft(null)
    setProposal(null)
  }

  async function submit() {
    if (!action) return
    if (NOTE_REQUIRED.includes(action) && !note.trim()) {
      showToast('error', `${ACTION_LABEL[action]} requires a note.`)
      return
    }
    if (action === 'merge_into_pattern' && !mergeTarget) {
      showToast('error', 'Choose the pattern to merge into.')
      return
    }
    if (action === 'defer' && !untilMembers && !untilCoverage) {
      showToast('error', 'A deferral needs a member or coverage threshold, or nothing can resurface it.')
      return
    }

    setBusy(true)
    try {
      if (action === 'defer') {
        await deferQueueItem(item.id, {
          until_member_count: untilMembers ? Number(untilMembers) : null,
          until_coverage: untilCoverage ? Number(untilCoverage) / 100 : null,
          note,
          deferred_by: decidedBy || 'unknown',
        })
        showToast('success', 'Deferred. It will resurface when the threshold is met.')
      } else {
        await decideQueueItem(item.id, {
          outcome: action,
          outcome_detail: action === 'merge_into_pattern' ? { pattern_id: mergeTarget } : null,
          note: note || null,
          decided_by: decidedBy || 'unknown',
        })
        // Deciding records the answer; the step applies it on the next
        // resume, and deciding never resumes the job on its own.
        showToast('success', 'Decision recorded. It applies when the job is resumed.')
      }
      reset()
      onDecided()
    } catch (err) {
      showToast('error', (err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="border-t border-neutral-100 bg-white px-4 py-3">
      <div className="flex flex-wrap gap-2">
        {(Object.keys(ACTION_LABEL) as Action[]).map((candidate) => (
          <button
            key={candidate}
            type="button"
            onClick={() => setAction((current) => (current === candidate ? null : candidate))}
            className={`rounded border px-3 py-1.5 text-xs font-medium ${
              action === candidate
                ? 'border-sky-500 bg-sky-50 text-sky-800'
                : 'border-neutral-300 text-neutral-700 hover:bg-neutral-50'
            }`}
          >
            {ACTION_LABEL[candidate]}
          </button>
        ))}
      </div>

      {action && (
        <div className="mt-3 space-y-3 text-xs">
          {action === 'merge_into_pattern' && (
            <div>
              <label className="mb-1 block font-medium text-neutral-700">Merge into</label>
              <select
                value={mergeTarget}
                onChange={(event) => setMergeTarget(event.target.value)}
                className="w-full rounded border border-neutral-300 px-2 py-1"
              >
                <option value="">Choose a pattern…</option>
                {payload.similar_patterns.length > 0 && (
                  <optgroup label="Closest by signature">
                    {payload.similar_patterns.map((s) => (
                      <option key={s.pattern_id} value={s.pattern_id}>
                        {s.pattern_id} — {Math.round(s.similarity * 100)}% similar
                      </option>
                    ))}
                  </optgroup>
                )}
                <optgroup label="All patterns">
                  {patterns.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.id}
                    </option>
                  ))}
                </optgroup>
              </select>
            </div>
          )}

          {action === 'defer' && (
            <div className="flex flex-wrap gap-3">
              <label className="flex items-center gap-1.5 text-neutral-700">
                Ask again at
                <input
                  type="number"
                  min={1}
                  value={untilMembers}
                  onChange={(event) => setUntilMembers(event.target.value)}
                  className="w-16 rounded border border-neutral-300 px-2 py-1"
                />
                members
              </label>
              <label className="flex items-center gap-1.5 text-neutral-700">
                or at
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={untilCoverage}
                  onChange={(event) => setUntilCoverage(event.target.value)}
                  className="w-16 rounded border border-neutral-300 px-2 py-1"
                />
                % coverage
              </label>
            </div>
          )}

          {/* Both previews are proposals. Saying so on the control itself is
              the only place a reviewer reliably reads it. */}
          {draft && (
            <div className="rounded border border-neutral-200 bg-neutral-50 p-3">
              <p className="font-medium text-neutral-700">
                Draft pattern <code className="font-mono">{draft.pattern.id}</code> ·{' '}
                <span className="text-amber-700">rules_status: {draft.pattern.rules_status}</span>
              </p>
              <p className="mt-1 text-neutral-600">
                Anchors, rarest first: {draft.pattern.anchor_signals.join(', ') || '—'}
              </p>
              <p className="text-neutral-600">
                {draft.pattern.detection_rules.all.length} required signal(s),{' '}
                {draft.pattern.detection_rules.supporting.length} supporting
              </p>
              <ul className="mt-1 list-inside list-disc text-neutral-500">
                {draft.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </div>
          )}

          {proposal && (
            <div className="rounded border border-neutral-200 bg-neutral-50 p-3">
              <p className="font-medium text-neutral-700">
                Proposed amendment to <code className="font-mono">{proposal.pattern_id}</code> ·{' '}
                <span className="text-amber-700">not applied</span>
              </p>
              {proposal.signals_missing_from_pattern.length === 0 ? (
                <p className="mt-1 text-neutral-600">
                  The pattern already references every signal in this cluster — it failed on a threshold or a
                  disqualifier, not on coverage.
                </p>
              ) : (
                <p className="mt-1 text-neutral-600">
                  Would add {proposal.proposed_additions.length} supporting condition(s):{' '}
                  {proposal.signals_missing_from_pattern.join(', ')}
                </p>
              )}
              <ul className="mt-1 list-inside list-disc text-neutral-500">
                {proposal.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex flex-wrap items-end gap-3">
            <label className="flex-1">
              <span className="mb-1 block font-medium text-neutral-700">
                Note{NOTE_REQUIRED.includes(action) ? ' (required)' : ' (optional)'}
              </span>
              <textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={2}
                className="w-full rounded border border-neutral-300 px-2 py-1"
                placeholder={
                  action === 'reject'
                    ? 'Why this shape is out of modernization scope…'
                    : action === 'defer'
                      ? 'What you are waiting to see…'
                      : 'Rationale…'
                }
              />
            </label>
            <label>
              <span className="mb-1 block font-medium text-neutral-700">Decided by</span>
              <input
                type="text"
                value={decidedBy}
                onChange={(event) => setDecidedBy(event.target.value)}
                className="rounded border border-neutral-300 px-2 py-1"
                placeholder="your name"
              />
            </label>
            <button
              type="button"
              onClick={submit}
              disabled={busy}
              className="rounded bg-sky-600 px-3 py-1.5 font-medium text-white hover:bg-sky-700 disabled:opacity-50"
            >
              {busy ? 'Saving…' : ACTION_LABEL[action]}
            </button>
            <button type="button" onClick={reset} className="px-2 py-1.5 text-neutral-500 hover:underline">
              Cancel
            </button>
          </div>
          <p className="text-neutral-500">
            Recording a decision does not resume the job — resume it from the Workflow tab once you have worked
            through the queue.
          </p>
        </div>
      )}
    </div>
  )
}
