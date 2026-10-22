import { useState, type FormEvent } from 'react'
import { Drawer } from '../../components/Drawer'
import { Field, inputClass } from '../../components/FormField'
import { LimitedList } from '../../components/LimitedList'
import { TagInput } from '../../components/TagInput'
import { useToast } from '../../components/Toast'
import { ApiError } from '../../api/client'
import { inspectPath, inspectUrl, registerRepository } from '../../api/repositories'
import type { Criticality, InspectPathResult, InspectUrlResult, RetirementStatus } from '../../types/repositories'

interface RegisterRepositoryDrawerProps {
  engagementId: string
  onClose: () => void
  onRegistered: (repositoryId: string) => void
}

/** Registering by git URL is the main path: the discovery job clones the repository (docs/VDI-SETUP.md: Registering a client repository).
 * A folder already on this machine can still be registered by its path. */
const SOURCE_OPTIONS = [
  { key: 'git_url', label: 'Git URL' },
  { key: 'local_path', label: 'Local folder path' },
]

export function RegisterRepositoryDrawer({ engagementId, onClose, onRegistered }: RegisterRepositoryDrawerProps) {
  const { showToast } = useToast()
  const [source, setSource] = useState('git_url')

  const [gitUrl, setGitUrl] = useState('')
  const [branch, setBranch] = useState('')
  const [targetFolder, setTargetFolder] = useState('')
  const [inspectingUrl, setInspectingUrl] = useState(false)
  const [urlInspection, setUrlInspection] = useState<InspectUrlResult | null>(null)

  const [localPath, setLocalPath] = useState('')
  const [inspecting, setInspecting] = useState(false)
  const [inspection, setInspection] = useState<InspectPathResult | null>(null)

  const [cloneUrl, setCloneUrl] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [technicalOwner, setTechnicalOwner] = useState('')
  const [criticality, setCriticality] = useState<Criticality>('medium')
  const [retirementStatus, setRetirementStatus] = useState<RetirementStatus>('active')
  const [defaultBranch, setDefaultBranch] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [notes, setNotes] = useState('')

  const [submitting, setSubmitting] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)

  async function handlePathBlur() {
    if (!localPath.trim()) {
      setInspection(null)
      return
    }
    setInspecting(true)
    try {
      const result = await inspectPath(engagementId, localPath.trim())
      setInspection(result)
      if (result.suggested_name && !name) setName(result.suggested_name)
      if (result.detected_branch && !defaultBranch) setDefaultBranch(result.detected_branch)
      if (result.detected_clone_url && !cloneUrl) setCloneUrl(result.detected_clone_url)
    } catch {
      setInspection(null)
    } finally {
      setInspecting(false)
    }
  }

  async function handleUrlBlur() {
    if (!gitUrl.trim()) {
      setUrlInspection(null)
      return
    }
    setInspectingUrl(true)
    try {
      const result = await inspectUrl(engagementId, gitUrl.trim(), targetFolder.trim() || null)
      setUrlInspection(result)
      if (result.suggested_name && !name) setName(result.suggested_name)
    } catch {
      setUrlInspection(null)
    } finally {
      setInspectingUrl(false)
    }
  }

  function cloneUrlVerificationHint() {
    if (!inspection) return null
    if (!inspection.has_git) {
      if (!cloneUrl.trim()) {
        return { tone: 'text-neutral-400', text: 'No .git directory found — this folder was never under source control. Leave this blank, or enter a URL if it is being migrated into source control.' }
      }
      return { tone: 'text-neutral-400', text: 'Cannot be verified — no git remote found in this folder. It will be recorded unverified.' }
    }
    const detected = inspection.detected_clone_url
    if (!cloneUrl.trim()) {
      return detected ? null : { tone: 'text-neutral-400', text: 'No origin remote — nothing to verify against. Leave this blank, or enter the canonical URL to record it unverified.' }
    }
    if (!detected) return { tone: 'text-neutral-400', text: 'Cannot be verified — this repository has no origin remote. It will be recorded unverified.' }
    // As the backend's normalize_clone_url: an SSH remote (git@host:org/repo or ssh://[user@]host[:port]/org/repo)
    // is the same repository as https://host/org/repo.
    const normalize = (u: string) => {
      let s = u.trim()
      const scp = /^git@([^:/]+):(.+)$/.exec(s)
      if (scp) s = `https://${scp[1]}/${scp[2]}`
      const ssh = /^ssh:\/\/(?:[^@/]+@)?([^/:]+)(?::\d+)?(\/.*)$/.exec(s)
      if (ssh) s = `https://${ssh[1]}${ssh[2]}`
      return s.replace(/\/$/, '').replace(/\.git$/, '').replace(/\/$/, '').toLowerCase()
    }
    if (normalize(detected) === normalize(cloneUrl)) {
      return { tone: 'text-emerald-600', text: "Verified against the folder's git remote" }
    }
    return {
      tone: 'text-amber-600',
      text: `Does not match the folder's remote: ${detected}. Check the path is correct. You can continue if this is intentional.`,
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setFormError(null)
    setFieldErrors({})
    setSubmitting(true)
    try {
      const details = {
        name: name.trim() || undefined,
        description: description.trim() || null,
        technical_owner: technicalOwner.trim() || null,
        criticality,
        retirement_status: retirementStatus,
        tags,
        notes: notes.trim() || null,
      }
      const result = source === 'git_url'
        ? await registerRepository(engagementId, {
            source_type: 'git_clone',
            clone_url: gitUrl.trim(),
            branch: branch.trim() || null,
            target_folder: targetFolder.trim() || null,
            ...details,
          })
        : await registerRepository(engagementId, {
        source_type: 'local_path',
        local_path: localPath.trim(),
        name: name.trim() || undefined,
        clone_url: cloneUrl.trim() || null,
        description: description.trim() || null,
        technical_owner: technicalOwner.trim() || null,
        criticality,
        retirement_status: retirementStatus,
        default_branch: defaultBranch.trim() || null,
        tags,
        notes: notes.trim() || null,
      })
      showToast('success', source === 'git_url'
        ? `Registered "${result.slug}". Cloning, then discovery.`
        : `Registered "${result.slug}". Discovery is running.`)
      onRegistered(result.repository_id)
    } catch (err) {
      if (err instanceof ApiError) {
        const byField: Record<string, string> = {}
        for (const fe of err.fieldErrors) {
          if (fe.field && fe.field !== '__root__') byField[fe.field] = fe.message
        }
        setFieldErrors(byField)
        setFormError(err.fieldErrors.length && Object.keys(byField).length === 0 ? err.message : null)
        if (Object.keys(byField).length === 0) setFormError(err.message)
      } else {
        setFormError('Could not register this repository.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const hint = cloneUrlVerificationHint()
  const blockingConflict = inspection?.duplicate_conflict ?? null
  // Required only when the repository has an origin remote to verify it
  // against — a folder never under source control, or a repository with no
  // remote at all, has no canonical URL to check (15-REPOSITORY-INGEST-UI.md
  // Part C). Not yet inspected is treated as "not required" so the button
  // isn't blocked before inspection has had a chance to run; the backend
  // still validates this regardless.
  const cloneUrlRequired = inspection?.has_git === true && !!inspection.detected_clone_url
  const urlBlocked = !!urlInspection && (urlInspection.problems.length > 0 || !!urlInspection.duplicate_conflict)
  const canSubmit =
    !submitting &&
    (source === 'git_url'
      ? !!gitUrl.trim() && !urlBlocked
      : !!localPath.trim() && (!cloneUrlRequired || !!cloneUrl.trim()) && !blockingConflict)

  return (
    <Drawer title="Register a repository" onRequestClose={onClose}>
      <div className="mb-5 flex flex-wrap gap-1.5">
        {SOURCE_OPTIONS.map((option) => (
          <button
            key={option.key}
            type="button"
            onClick={() => setSource(option.key)}
            className={`rounded-full border px-3 py-1 text-xs font-medium ${
              source === option.key
                ? 'border-violet-500 bg-violet-50 text-violet-700'
                : 'border-neutral-300 text-neutral-600 hover:bg-neutral-50'
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          {source === 'git_url' && (
            <section className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">Location</h3>

              <Field label="Git URL" error={fieldErrors.clone_url}>
                <input
                  type="text"
                  value={gitUrl}
                  onChange={(event) => setGitUrl(event.target.value)}
                  onBlur={handleUrlBlur}
                  placeholder="https://git.client.com/team/repo.git , git@host:org/repo.git or ssh://host/org/repo.git"
                  className={inputClass(!!fieldErrors.clone_url)}
                />
                <p className="mt-1 text-xs text-neutral-400">
                  git signs in as you, with Git Credential Manager or your SSH key. The platform never asks for or stores
                  a credential: a host that needs a sign-in fails at once, saying how to sign in once outside the platform.
                </p>
              </Field>

              <Field label="Branch (optional)">
                <input
                  type="text"
                  value={branch}
                  onChange={(event) => setBranch(event.target.value)}
                  placeholder="the repository's default branch"
                  className={inputClass(false)}
                />
              </Field>

              <Field
                label={urlInspection && !urlInspection.repos_dir ? 'Target folder' : 'Target folder (optional)'}
                error={fieldErrors.target_folder}
              >
                <input
                  type="text"
                  value={targetFolder}
                  onChange={(event) => setTargetFolder(event.target.value)}
                  onBlur={handleUrlBlur}
                  placeholder={urlInspection?.repos_dir ? `${urlInspection.repos_dir}\\${engagementId}\\<repository>` : 'D:\\repos\\my-repository'}
                  className={`${inputClass(!!fieldErrors.target_folder)} font-mono`}
                />
                <p className="mt-1 text-xs text-neutral-400">
                  {urlInspection?.repos_dir
                    ? `Default: under REPOS_DIR (${urlInspection.repos_dir}). A new or empty folder, or an existing clone of this URL, which is used as it is.`
                    : 'A new or empty folder, or an existing clone of this URL, which is used as it is. Set REPOS_DIR in backend\\.env to clone under one folder by default.'}
                </p>
              </Field>

              {inspectingUrl && <p className="text-xs text-neutral-400">Checking…</p>}
              {urlInspection && !inspectingUrl && (
                <div className="space-y-1.5 rounded border border-neutral-200 bg-neutral-50 p-3 text-xs text-neutral-600">
                  {urlInspection.target_message && urlInspection.target_action !== 'refuse' && <p>{urlInspection.target_message}</p>}
                  <LimitedList items={urlInspection.problems} name={(problem) => problem} noun="problems">
                    {(visible) => (
                      <div className="space-y-1.5">
                        {visible.map((problem) => (
                          <p key={problem} className="text-red-600">
                            {problem}
                          </p>
                        ))}
                      </div>
                    )}
                  </LimitedList>
                  {urlInspection.duplicate_conflict && (
                    <p className="font-medium text-red-600">{urlInspection.duplicate_conflict.message}</p>
                  )}
                </div>
              )}
            </section>
          )}

          {source === 'local_path' && (
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">Location</h3>

            <Field label="Local folder path" error={fieldErrors.local_path}>
              <input
                type="text"
                value={localPath}
                onChange={(event) => setLocalPath(event.target.value)}
                onBlur={handlePathBlur}
                placeholder="D:\repos\my-repository"
                className={`${inputClass(!!fieldErrors.local_path)} font-mono`}
              />
            </Field>

            {inspecting && <p className="text-xs text-neutral-400">Inspecting…</p>}

            {inspection && !inspecting && (
              <div className="space-y-1.5 rounded border border-neutral-200 bg-neutral-50 p-3 text-xs text-neutral-600">
                {!inspection.exists && <p className="text-red-600">This path does not exist.</p>}
                {inspection.exists && !inspection.is_directory && <p className="text-red-600">This path is not a directory.</p>}
                {inspection.exists && inspection.is_directory && (
                  <>
                    <p>
                      Folder: <span className="font-medium text-neutral-800">{inspection.root_folder_name}</span>
                      {' · '}
                      {inspection.has_git ? `git, branch ${inspection.detected_branch ?? '?'}` : 'no git history'}
                    </p>
                    <p>
                      Est. {inspection.estimated_file_count ?? 0} files, {inspection.solution_files_found ?? 0} .sln,{' '}
                      {inspection.project_files_found ?? 0} .csproj
                    </p>
                    <LimitedList items={inspection.warnings} name={(warning) => warning} noun="warnings">
                      {(visible) => (
                        <div className="space-y-1.5">
                          {visible.map((warning) => (
                            <p key={warning} className="text-amber-600">
                              {warning}
                            </p>
                          ))}
                        </div>
                      )}
                    </LimitedList>
                  </>
                )}
                {blockingConflict && <p className="font-medium text-red-600">{blockingConflict.message}</p>}
              </div>
            )}

            <Field label={cloneUrlRequired ? 'Git clone URL' : 'Git clone URL (optional)'} error={fieldErrors.clone_url}>
              <input
                type="text"
                value={cloneUrl}
                onChange={(event) => setCloneUrl(event.target.value)}
                placeholder="https://… , git@host:org/repo.git or ssh://host/org/repo.git"
                className={inputClass(!!fieldErrors.clone_url)}
              />
              {cloneUrlRequired && (
                <p className="mt-1 text-xs text-neutral-400">
                  The repository's canonical URL. It identifies this repository independently of where it sits on disk.
                </p>
              )}
              {hint && <p className={`mt-1 text-xs ${hint.tone}`}>{hint.text}</p>}
            </Field>
          </section>
          )}

          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">Details</h3>

            <Field label="Repository name">
              <input
                type="text"
                value={name}
                onChange={(event) => setName(event.target.value)}
                className={inputClass(false)}
              />
            </Field>

            <Field label="Description">
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={2}
                className={inputClass(false)}
              />
            </Field>

            <Field label="Technical owner">
              <input
                type="text"
                value={technicalOwner}
                onChange={(event) => setTechnicalOwner(event.target.value)}
                className={inputClass(false)}
              />
            </Field>

            <Field label="Business criticality">
              <select
                value={criticality}
                onChange={(event) => setCriticality(event.target.value as Criticality)}
                className={inputClass(false)}
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
              <p className="mt-1 text-xs text-neutral-400">Feeds review tier assignment (risk-scoring-tier-assignment).</p>
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
              {retirementStatus !== 'active' && (
                <p className="mt-1 text-xs text-amber-600">
                  This repository will be inventoried but excluded from modernization scope counts.
                </p>
              )}
            </Field>

            {source === 'local_path' && (
            <Field label="Default branch">
              <input
                type="text"
                value={defaultBranch}
                onChange={(event) => setDefaultBranch(event.target.value)}
                className={inputClass(false)}
              />
            </Field>
            )}

            <TagInput label="Tags" values={tags} onChange={setTags} placeholder="Add a tag…" />

            <Field label="Notes">
              <textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={2} className={inputClass(false)} />
            </Field>
          </section>

          {formError && <p className="text-sm text-red-600">{formError}</p>}

          <div className="flex justify-end gap-2 border-t border-neutral-100 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? 'Registering…' : source === 'git_url' ? 'Register, clone & launch discovery' : 'Register & launch discovery'}
            </button>
          </div>
        </form>
    </Drawer>
  )
}
