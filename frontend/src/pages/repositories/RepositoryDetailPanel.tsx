import { useEffect, useState } from 'react'
import {
  deleteRepository,
  getRepository,
  listRepositoryExecutions,
  rescanRepository,
  restoreRepository,
  updateRepository,
  verifyRepositoryPath,
} from '../../api/repositories'
import type { Criticality, RepositoryDetail, RetirementStatus } from '../../types/repositories'
import type { JobExecution } from '../../types/workflow'
import { ApiError } from '../../api/client'
import { EmptyState } from '../../components/EmptyState'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Field, inputClass } from '../../components/FormField'
import { TagInput } from '../../components/TagInput'
import { useToast } from '../../components/Toast'
import { CriticalityBadge, CloneUrlVerificationBadge, IngestStatusBadge, RetirementBadge } from '../../components/RepositoryBadges'
import { BatchStatusBadge, ExitStatusBadge } from '../../components/WorkflowBadges'
import { RepositoryStructureSection } from './RepositoryStructureSection'

interface RepositoryDetailPanelProps {
  repositoryId: string
  refreshToken: number
  onChanged: () => void
  onDeleted: () => void
  onNavigateToExecution: (executionId: string) => void
}

export function RepositoryDetailPanel({
  repositoryId,
  refreshToken,
  onChanged,
  onDeleted,
  onNavigateToExecution,
}: RepositoryDetailPanelProps) {
  const { showToast } = useToast()
  const [repo, setRepo] = useState<RepositoryDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [busy, setBusy] = useState(false)

  const [localRefresh, setLocalRefresh] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getRepository(repositoryId)
      .then((result) => {
        if (!cancelled) setRepo(result)
      })
      .catch(() => {
        if (!cancelled) setError('Could not load this repository.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [repositoryId, refreshToken, localRefresh])

  function refreshLocal() {
    setLocalRefresh((token) => token + 1)
  }

  async function handleRescan() {
    setBusy(true)
    try {
      await rescanRepository(repositoryId)
      showToast('success', 'Rescan launched.')
      refreshLocal()
      onChanged()
    } catch {
      showToast('error', 'Could not launch a rescan.')
    } finally {
      setBusy(false)
    }
  }

  async function handleVerifyPath() {
    setBusy(true)
    try {
      const result = await verifyRepositoryPath(repositoryId)
      showToast(result.exists ? 'success' : 'error', result.exists ? 'Path confirmed.' : 'Path is missing.')
      refreshLocal()
    } catch {
      showToast('error', 'Could not verify the path.')
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete() {
    setBusy(true)
    try {
      await deleteRepository(repositoryId)
      showToast('success', 'Repository deleted.')
      setShowDeleteConfirm(false)
      onDeleted()
    } catch {
      showToast('error', 'Could not delete this repository.')
    } finally {
      setBusy(false)
    }
  }

  async function handleRestore() {
    setBusy(true)
    try {
      await restoreRepository(repositoryId)
      showToast('success', 'Repository restored.')
      refreshLocal()
      onChanged()
    } catch {
      showToast('error', 'Could not restore this repository.')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <div className="p-6 text-sm text-neutral-400">Loading…</div>
  if (error || !repo) return <EmptyState title="Could not load repository" description={error ?? undefined} />

  return (
    <div className="max-w-3xl space-y-6 p-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold text-neutral-900">{repo.name}</h2>
          <p className="font-mono text-xs text-neutral-400">{repo.id}</p>
        </div>
        <div className="flex gap-2">
          {repo.deleted_at ? (
            <button
              type="button"
              onClick={handleRestore}
              disabled={busy}
              className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
            >
              Restore
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={handleVerifyPath}
                disabled={busy}
                className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
              >
                Verify path
              </button>
              <button
                type="button"
                onClick={handleRescan}
                disabled={busy}
                className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
              >
                Rescan
              </button>
              <button
                type="button"
                onClick={() => setEditing((value) => !value)}
                className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
              >
                {editing ? 'Cancel edit' : 'Edit'}
              </button>
              <button
                type="button"
                onClick={() => setShowDeleteConfirm(true)}
                disabled={busy}
                className="rounded border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50"
              >
                Delete
              </button>
            </>
          )}
        </div>
      </div>

      {repo.deleted_at && (
        <p className="rounded bg-neutral-100 px-3 py-2 text-sm text-neutral-600">
          Soft-deleted at {new Date(repo.deleted_at).toLocaleString()}.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <IngestStatusBadge status={repo.ingest_status} />
        <CriticalityBadge criticality={repo.criticality} />
        <CloneUrlVerificationBadge verification={repo.clone_url_verification} />
        <RetirementBadge status={repo.retirement_status} />
      </div>

      {repo.ingest_status === 'path_missing' && (
        <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          The registered folder is currently missing at <code className="font-mono">{repo.local_path}</code>.
        </p>
      )}

      {editing ? (
        <EditForm repo={repo} onCancel={() => setEditing(false)} onSaved={() => { setEditing(false); refreshLocal(); onChanged() }} />
      ) : (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
          <Metadata label="Root folder">{repo.root_folder_name}</Metadata>
          <Metadata label="Local path">
            <span className="font-mono text-xs">{repo.local_path}</span>
          </Metadata>
          <Metadata label="Clone URL">
            <span className="font-mono text-xs">{repo.clone_url}</span>
          </Metadata>
          <Metadata label="Detected remote">
            {repo.detected_clone_url ? <span className="font-mono text-xs">{repo.detected_clone_url}</span> : '—'}
          </Metadata>
          <Metadata label="Provider">{repo.provider ?? '—'}</Metadata>
          <Metadata label="Organization">{repo.organization ?? '—'}</Metadata>
          <Metadata label="Default branch">{repo.default_branch ?? '—'}</Metadata>
          <Metadata label="Commit SHA">
            {repo.has_git_history ? <span className="font-mono text-xs">{repo.ingest_commit_sha?.slice(0, 12)}</span> : 'no git history'}
          </Metadata>
          <Metadata label="Last commit">
            {repo.last_commit_date ? new Date(repo.last_commit_date).toLocaleString() : '—'}
          </Metadata>
          <Metadata label="Size / files">
            {repo.size_bytes !== null ? `${(repo.size_bytes / 1024 / 1024).toFixed(2)} MB` : '—'} / {repo.file_count ?? '—'}
          </Metadata>
          <Metadata label="Primary languages">
            {repo.primary_languages && repo.primary_languages.length > 0
              ? repo.primary_languages.map((entry) => `${entry.language} (${entry.percentage}%)`).join(', ')
              : '—'}
          </Metadata>
          <Metadata label="Source status">{repo.source_status ?? '—'}</Metadata>
          <Metadata label="Technical owner">{repo.technical_owner ?? '—'}</Metadata>
          <Metadata label="Description">{repo.description ?? '—'}</Metadata>
          <Metadata label="Tags">{repo.tags.length ? repo.tags.join(', ') : '—'}</Metadata>
          <Metadata label="Notes">{repo.notes ?? '—'}</Metadata>
          <Metadata label="First registered">
            {repo.first_registered_at ? new Date(repo.first_registered_at).toLocaleString() : '—'}
          </Metadata>
          <Metadata label="Last scanned">
            {repo.last_scanned_at ? new Date(repo.last_scanned_at).toLocaleString() : 'never'}
          </Metadata>
        </dl>
      )}

      {!editing && (
        <section className="border-t border-neutral-100 pt-4">
          <RepositoryStructureSection repositoryId={repo.id} refreshToken={localRefresh} />
        </section>
      )}

      <section>
        <h3 className="mb-2 text-sm font-semibold text-neutral-900">Discovery execution history</h3>
        <ExecutionHistory repositoryId={repo.id} refreshToken={localRefresh} onNavigateToExecution={onNavigateToExecution} />
      </section>

      <ConfirmDialog
        open={showDeleteConfirm}
        title="Delete repository"
        message={`Soft-delete "${repo.name}"? It will disappear from lists until restored.`}
        confirmLabel={busy ? 'Deleting…' : 'Delete'}
        destructive
        onConfirm={handleDelete}
        onCancel={() => setShowDeleteConfirm(false)}
      />
    </div>
  )
}

function ExecutionHistory({
  repositoryId,
  refreshToken,
  onNavigateToExecution,
}: {
  repositoryId: string
  refreshToken: number
  onNavigateToExecution: (executionId: string) => void
}) {
  const [executions, setExecutions] = useState<JobExecution[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listRepositoryExecutions(repositoryId)
      .then((result) => {
        if (!cancelled) setExecutions(result)
      })
      .catch(() => {
        if (!cancelled) setExecutions([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [repositoryId, refreshToken])

  if (loading) return <p className="text-sm text-neutral-400">Loading…</p>
  if (executions.length === 0) return <p className="text-sm text-neutral-400">Discovery has not run yet.</p>

  return (
    <table className="w-full text-left text-sm">
      <thead className="text-xs uppercase tracking-wide text-neutral-500">
        <tr>
          <th className="py-1.5 pr-3 font-medium">Batch status</th>
          <th className="py-1.5 pr-3 font-medium">Exit status</th>
          <th className="py-1.5 pr-3 font-medium">Steps</th>
          <th className="py-1.5 pr-3 font-medium">Started</th>
          <th className="py-1.5 font-medium">Triggered by</th>
        </tr>
      </thead>
      <tbody>
        {executions.map((execution) => (
          <tr
            key={execution.id}
            onClick={() => onNavigateToExecution(execution.id)}
            className="cursor-pointer border-t border-neutral-100 hover:bg-neutral-50"
          >
            <td className="py-1.5 pr-3">
              <BatchStatusBadge status={execution.batch_status} />
            </td>
            <td className="py-1.5 pr-3">
              <ExitStatusBadge status={execution.exit_status} />
            </td>
            <td className="py-1.5 pr-3 text-neutral-500">
              {execution.step_summary.completed + execution.step_summary.not_implemented}/{execution.step_summary.total}
            </td>
            <td className="py-1.5 pr-3 whitespace-nowrap text-neutral-500">
              {execution.started_at ? new Date(execution.started_at).toLocaleString() : '—'}
            </td>
            <td className="py-1.5 text-neutral-500">{execution.triggered_by ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Metadata({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-neutral-400">{label}</dt>
      <dd className="mt-0.5 text-neutral-800">{children}</dd>
    </div>
  )
}

function EditForm({
  repo,
  onCancel,
  onSaved,
}: {
  repo: RepositoryDetail
  onCancel: () => void
  onSaved: () => void
}) {
  const { showToast } = useToast()
  const [name, setName] = useState(repo.name)
  const [description, setDescription] = useState(repo.description ?? '')
  const [technicalOwner, setTechnicalOwner] = useState(repo.technical_owner ?? '')
  const [criticality, setCriticality] = useState<Criticality>(repo.criticality)
  const [retirementStatus, setRetirementStatus] = useState<RetirementStatus>(repo.retirement_status)
  const [defaultBranch, setDefaultBranch] = useState(repo.default_branch ?? '')
  const [tags, setTags] = useState<string[]>(repo.tags)
  const [notes, setNotes] = useState(repo.notes ?? '')
  const [saving, setSaving] = useState(false)

  async function handleSubmit() {
    setSaving(true)
    try {
      await updateRepository(repo.id, {
        name,
        description: description.trim() || null,
        technical_owner: technicalOwner.trim() || null,
        criticality,
        retirement_status: retirementStatus,
        tags,
        notes: notes.trim() || null,
        default_branch: defaultBranch.trim() || null,
      })
      showToast('success', 'Repository updated.')
      onSaved()
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : 'Could not update this repository.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3 rounded border border-neutral-200 p-4">
      <Field label="Name">
        <input value={name} onChange={(event) => setName(event.target.value)} className={inputClass(false)} />
      </Field>
      <Field label="Description">
        <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={2} className={inputClass(false)} />
      </Field>
      <Field label="Technical owner">
        <input value={technicalOwner} onChange={(event) => setTechnicalOwner(event.target.value)} className={inputClass(false)} />
      </Field>
      <Field label="Criticality">
        <select value={criticality} onChange={(event) => setCriticality(event.target.value as Criticality)} className={inputClass(false)}>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
          <option value="critical">Critical</option>
        </select>
      </Field>
      <Field label="Retirement status">
        <select
          value={retirementStatus}
          onChange={(event) => setRetirementStatus(event.target.value as RetirementStatus)}
          className={inputClass(false)}
        >
          <option value="active">Active</option>
          <option value="slated_for_retirement">Slated for retirement</option>
          <option value="decommissioned">Decommissioned</option>
        </select>
      </Field>
      <Field label="Default branch">
        <input value={defaultBranch} onChange={(event) => setDefaultBranch(event.target.value)} className={inputClass(false)} />
      </Field>
      <TagInput label="Tags" values={tags} onChange={setTags} />
      <Field label="Notes">
        <textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={2} className={inputClass(false)} />
      </Field>
      <div className="flex justify-end gap-2 pt-2">
        <button type="button" onClick={onCancel} className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50">
          Cancel
        </button>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={saving}
          className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  )
}
