import { createContext, useContext, useEffect, useRef, useState, type FormEvent, type MouseEvent, type ReactNode } from 'react'
import { openInVisualStudio, type Editor } from '../../api/editors'
import { forgetRepositoryClone, recordRepositoryClone } from '../../api/repositories'
import type { RepositoryDetail } from '../../types/repositories'
import { useToast } from '../../components/Toast'
import { copyText, fullPath, setEditorChoice, useEditorChoice, type EditorChoice } from './editorChoice'
import { sourceHref } from './sourceHref'

type SourceLinkProps = {
  localPath: string | null | undefined
  filePath: string
  line: number
  className?: string
  title?: string
  children: ReactNode
}

/** A repository's files, for every file link inside its page: file locations are relative to the repository, and a
 * link joins them with the viewer's own clone on this machine (the owner's is the folder it was registered from). */
interface RepositoryFilesValue {
  repositoryName: string
  /** The viewer's own clone here; null when they have recorded none. */
  clonePath: string | null
  /** Opens the dialog that records the viewer's clone. */
  askForClone: () => void
}

const Files = createContext<RepositoryFilesValue | null>(null)

/** Provides a repository's files to the links inside, and the dialog that records the viewer's own clone. */
export function RepositoryFiles({ repository, onRecorded, children }: {
  repository: Pick<RepositoryDetail, 'id' | 'name' | 'my_clone_path' | 'clone_command'>
  onRecorded: (repository: RepositoryDetail) => void
  children: ReactNode
}) {
  const [asking, setAsking] = useState(false)
  return (
    <Files.Provider value={{ repositoryName: repository.name, clonePath: repository.my_clone_path ?? null, askForClone: () => setAsking(true) }}>
      {children}
      {asking && (
        <RecordCloneDialog
          repository={repository}
          onClose={() => setAsking(false)}
          onRecorded={(updated) => {
            setAsking(false)
            onRecorded(updated)
          }}
        />
      )}
    </Files.Provider>
  )
}

/** Opens the dialog that records the viewer's clone, from outside a link (the repository page's own line). */
export function useAskForClone(): (() => void) | null {
  return useContext(Files)?.askForClone ?? null
}

/** A link that opens the file at its line in the person's chosen editor (04-FRONTEND-SPEC.md "File links"), with a
 * menu beside it to open it in another editor, copy its path and line, or change the choice. Inside a repository's
 * page, it opens from the viewer's own clone; with none recorded, it offers to record one, or to copy the file's path
 * relative to the repository. With no local path to resolve it against (an artifact viewed outside its repository),
 * the same text without a link. */
export function SourceLink({ localPath, ...props }: SourceLinkProps) {
  const files = useContext(Files)
  if (files) {
    if (files.clonePath) return <EditorLink localPath={files.clonePath} {...props} />
    return <NoCloneLink files={files} {...props} />
  }
  if (!localPath) {
    return (
      <span className={props.className} title={props.title ?? `${props.filePath}:${props.line}`}>
        {props.children}
      </span>
    )
  }
  return <EditorLink localPath={localPath} {...props} />
}

function NoCloneLink({ files, filePath, line, className, title, children }: Omit<SourceLinkProps, 'localPath'> & { files: RepositoryFilesValue }) {
  const { showToast } = useToast()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLSpanElement>(null)
  const why = `You have no clone of ${files.repositoryName} recorded on this machine`

  useEffect(() => {
    if (!menuOpen) return
    const close = (event: Event) => {
      if (event instanceof KeyboardEvent ? event.key === 'Escape' : !menuRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [menuOpen])

  async function copyRelative() {
    setMenuOpen(false)
    const text = `${filePath}:${line}`
    if (await copyText(text)) showToast('success', `Copied ${text}`)
    else showToast('error', `The browser would not copy to the clipboard. The path is ${text}`)
  }

  return (
    <span ref={menuRef} className="group/source relative inline" onClick={(event) => event.stopPropagation()}>
      <span
        role="button"
        tabIndex={0}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        onClick={() => setMenuOpen((open) => !open)}
        onKeyDown={(event) => event.key === 'Enter' && setMenuOpen((open) => !open)}
        className={`${className ?? ''} cursor-pointer decoration-dotted hover:underline`}
        title={`${title ?? filePath} — ${why}: record your clone to open it`}
      >
        {children}
      </span>
      {menuOpen && (
        <span
          role="menu"
          className="absolute left-0 top-full z-40 mt-1 flex w-64 flex-col rounded border border-neutral-200 bg-white py-1 text-left font-sans text-xs text-neutral-700 shadow-lg"
        >
          <span className="px-3 pb-1 text-[11px] text-neutral-500">{why}.</span>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenuOpen(false)
              files.askForClone()
            }}
            className="px-3 py-1 text-left hover:bg-neutral-50"
          >
            Record your clone…
          </button>
          <button type="button" role="menuitem" onClick={() => void copyRelative()} className="px-3 py-1 text-left hover:bg-neutral-50"
            title={`${filePath}:${line}`}>
            Copy the relative path ({filePath.split('/').pop()}:{line})
          </button>
        </span>
      )}
    </span>
  )
}

/** Recording the viewer's own clone: the git command that makes one, and its folder, checked by the backend to be a
 * clone of the same repository (the same remote URL). */
function RecordCloneDialog({ repository, onClose, onRecorded }: {
  repository: Pick<RepositoryDetail, 'id' | 'name' | 'my_clone_path' | 'clone_command'>
  onClose: () => void
  onRecorded: (repository: RepositoryDetail) => void
}) {
  const { showToast } = useToast()
  // The folder the command clones into, as the default answer.
  const suggested = repository.my_clone_path ?? repository.clone_command?.match(/"([^"]+)"\s*$/)?.[1] ?? ''
  const [folder, setFolder] = useState(suggested)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const updated = await recordRepositoryClone(repository.id, folder.trim())
      showToast('success', `Recorded your clone of ${repository.name}: file links open from ${updated.my_clone_path}.`)
      onRecorded(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not record the clone.')
    } finally {
      setBusy(false)
    }
  }

  async function forget() {
    setBusy(true)
    try {
      onRecorded(await forgetRepositoryClone(repository.id))
      showToast('success', `Forgot your clone of ${repository.name} on this machine. Nothing on disk changed.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not forget the clone.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4" role="dialog" aria-modal="true" aria-label={`Your clone of ${repository.name}`}>
      <form onSubmit={submit} className="w-full max-w-lg space-y-3 rounded border border-neutral-200 bg-white p-5 text-sm shadow-lg">
        <h2 className="text-base font-semibold text-neutral-900">Your clone of {repository.name}</h2>
        <p className="text-xs text-neutral-600">
          File links open from your own clone, on this machine. The platform checks that the folder is a clone of this repository
          (the same remote URL) before recording it.
        </p>
        {repository.clone_command ? (
          <div>
            <p className="text-xs text-neutral-600">If you have none yet, make one in PowerShell:</p>
            <div className="mt-1 flex items-start gap-2">
              <code className="block flex-1 break-all rounded bg-neutral-100 px-2 py-1 font-mono text-[11px] text-neutral-800">{repository.clone_command}</code>
              <button
                type="button"
                className="shrink-0 text-xs text-violet-700 hover:underline"
                onClick={() => void copyText(repository.clone_command!).then((ok) => showToast(ok ? 'success' : 'error', ok ? 'Copied the command.' : 'The browser would not copy it.'))}
              >
                Copy
              </button>
            </div>
          </div>
        ) : (
          <p className="text-xs text-amber-800">This repository has no remote URL to clone from or check against: its owner can set its clone URL.</p>
        )}
        <label className="block text-xs text-neutral-700">
          Your clone's folder
          <input autoFocus required value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="C:\MP\repos\OrderService"
            className="mt-1 w-full rounded border border-neutral-300 px-2 py-1.5 font-mono text-xs" />
        </label>
        {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
        <div className="flex items-center gap-2">
          <button type="submit" disabled={busy} className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-60">
            {busy ? 'Checking…' : 'Record'}
          </button>
          <button type="button" onClick={onClose} className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50">
            Cancel
          </button>
          {repository.my_clone_path && (
            <button type="button" disabled={busy} onClick={() => void forget()} className="ml-auto text-xs text-neutral-500 hover:underline">
              Forget my clone here
            </button>
          )}
        </div>
      </form>
    </div>
  )
}

function EditorLink({ localPath, filePath, line, className, title, children }: SourceLinkProps & { localPath: string }) {
  const { editors, choice } = useEditorChoice()
  const { showToast } = useToast()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const close = (event: Event) => {
      if (event instanceof KeyboardEvent ? event.key === 'Escape' : !menuRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [menuOpen])

  const path = fullPath(localPath, filePath)
  const vscodeHref = sourceHref(localPath, filePath, line)
  const visualStudios = (editors ?? []).filter((e) => e.kind === 'visual_studio')
  const hasVsCode = editors?.some((e) => e.kind === 'vscode') ?? false

  async function copy() {
    const text = `${path}:${line}`
    if (await copyText(text)) showToast('success', `Copied ${text}`)
    else showToast('error', `The browser would not copy to the clipboard. The path is ${text}`)
  }

  async function openVisualStudio(editor: Editor) {
    showToast('success', `Opening ${filePath.split(/[\\/]/).pop()} in ${editor.label}…`)
    try {
      const result = await openInVisualStudio(path, line, editor.installation)
      showToast(result.opened ? 'success' : 'error', result.message)
    } catch (err) {
      showToast('error', err instanceof Error ? err.message : 'Visual Studio did not open the file')
    }
  }

  function act(action: EditorChoice) {
    setMenuOpen(false)
    const visualStudio = visualStudios.find((e) => e.id === action)
    if (action === 'copy') void copy()
    else if (visualStudio) void openVisualStudio(visualStudio)
    else window.location.href = vscodeHref
  }

  function onLinkClick(event: MouseEvent) {
    if (choice === 'vscode') return // the vscode:// link opens it
    event.preventDefault()
    act(choice)
  }

  const chosen = editors?.find((e) => e.id === choice)
  const verb = choice === 'copy' ? 'copies its path and line' : `opens in ${chosen?.label ?? 'VS Code'}`
  const choices: { id: EditorChoice; label: string }[] = [
    ...(editors ?? []).map((e) => ({ id: e.id, label: e.label })),
    { id: 'copy', label: 'Copy only' },
  ]

  return (
    // Clicks on the menu stay here: a link often sits in a row that expands when clicked.
    <span ref={menuRef} className="group/source relative inline" onClick={(event) => menuOpen && event.stopPropagation()}>
      <a
        href={choice === 'vscode' ? vscodeHref : '#'}
        onClick={onLinkClick}
        className={`${className ?? ''} hover:underline`}
        title={`${title ?? filePath} — ${verb}`}
      >
        {children}
      </a>
      <button
        type="button"
        aria-label={`More ways to open ${filePath}`}
        aria-expanded={menuOpen}
        onClick={(event) => {
          event.stopPropagation()
          setMenuOpen((open) => !open)
        }}
        className="ml-0.5 rounded px-0.5 align-baseline text-[10px] text-neutral-400 opacity-40 hover:bg-neutral-100 hover:text-neutral-700 group-hover/source:opacity-100 focus-visible:opacity-100"
      >
        ▾
      </button>
      {menuOpen && (
        <span
          role="menu"
          className="absolute left-0 top-full z-40 mt-1 flex w-60 flex-col rounded border border-neutral-200 bg-white py-1 text-left font-sans text-xs text-neutral-700 shadow-lg"
        >
          <span className="truncate px-3 pb-1 font-mono text-[10px] text-neutral-400" title={`${path}:${line}`}>
            {filePath}:{line}
          </span>
          {hasVsCode && (
            <button type="button" role="menuitem" onClick={() => act('vscode')} className="px-3 py-1 text-left hover:bg-neutral-50">
              Open in VS Code
            </button>
          )}
          {visualStudios.map((vs) => (
            <button key={vs.id} type="button" role="menuitem" onClick={() => act(vs.id)} className="px-3 py-1 text-left hover:bg-neutral-50" title={`${vs.label} ${vs.version ?? ''}`.trim()}>
              Open in {vs.label}
            </button>
          ))}
          <button type="button" role="menuitem" onClick={() => act('copy')} className="px-3 py-1 text-left hover:bg-neutral-50">
            Copy path and line
          </button>
          <span className="mt-1 border-t border-neutral-100 px-3 pt-1.5 text-[10px] uppercase tracking-wide text-neutral-400">
            File links in this browser
          </span>
          {choices.map((c) => (
            <label key={c.id} className="flex cursor-pointer items-center gap-2 px-3 py-0.5 hover:bg-neutral-50">
              <input type="radio" name="file-link-editor" checked={choice === c.id} onChange={() => setEditorChoice(c.id)} />
              {c.label}
            </label>
          ))}
          {editors !== null && (!hasVsCode || visualStudios.length === 0) && (
            <span className="px-3 pt-1 text-[10px] text-neutral-400">
              {!hasVsCode && visualStudios.length === 0 ? 'Neither VS Code nor Visual Studio was found' : `${hasVsCode ? 'Visual Studio' : 'VS Code'} was not found`} on this
              machine.
            </span>
          )}
        </span>
      )}
    </span>
  )
}
