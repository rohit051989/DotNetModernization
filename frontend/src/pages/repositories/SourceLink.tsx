import { createContext, useContext, useEffect, useRef, useState, type MouseEvent, type ReactNode } from 'react'
import { openInVisualStudio, type Editor } from '../../api/editors'
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

/** Where a repository's files are when it was registered on another machine ("on Ann's machine (PC-17)"), for every
 * file link inside: its results are read from the database, but its files are not here. */
const HeldOn = createContext<string | null>(null)

export function FilesHeldOn({ value, children }: { value: string | null; children: ReactNode }) {
  return <HeldOn.Provider value={value}>{children}</HeldOn.Provider>
}

/** A link that opens the file at its line in the person's chosen editor (04-FRONTEND-SPEC.md "File links"), with a
 * menu beside it to open it in another editor, copy its path and line, or change the choice. With no local path to
 * resolve it against (an artifact viewed outside its repository), the same text without a link. For a repository
 * registered on another machine, the text says where the file is when clicked, instead of a link that cannot work. */
export function SourceLink({ localPath, ...props }: SourceLinkProps) {
  const heldOn = useContext(HeldOn)
  if (heldOn) return <HeldFile heldOn={heldOn} {...props} />
  if (!localPath) {
    return (
      <span className={props.className} title={props.title ?? `${props.filePath}:${props.line}`}>
        {props.children}
      </span>
    )
  }
  return <EditorLink localPath={localPath} {...props} />
}

function HeldFile({ heldOn, filePath, line, className, title, children }: Omit<SourceLinkProps, 'localPath'> & { heldOn: string }) {
  const { showToast } = useToast()
  const where = `${filePath}:${line} is ${heldOn}: the repository was scanned there, and its files are not on this machine.`
  return (
    <span
      role="button"
      tabIndex={0}
      onClick={(event) => {
        event.stopPropagation()
        showToast('success', where)
      }}
      onKeyDown={(event) => event.key === 'Enter' && showToast('success', where)}
      className={`${className ?? ''} cursor-help decoration-dotted hover:underline`}
      title={title ? `${title} — ${heldOn}` : where}
    >
      {children}
    </span>
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
