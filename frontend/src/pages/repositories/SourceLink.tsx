import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from 'react'
import { openInVisualStudio } from '../../api/editors'
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

/** A link that opens the file at its line in the person's chosen editor (04-FRONTEND-SPEC.md "File links"), with a
 * menu beside it to open it in another editor, copy its path and line, or change the choice. With no local path to
 * resolve it against (an artifact viewed outside its repository), the same text without a link. */
export function SourceLink({ localPath, ...props }: SourceLinkProps) {
  if (!localPath) {
    return (
      <span className={props.className} title={props.title ?? `${props.filePath}:${props.line}`}>
        {props.children}
      </span>
    )
  }
  return <EditorLink localPath={localPath} {...props} />
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
  const visualStudio = editors?.find((e) => e.id === 'visual_studio')

  async function copy() {
    const text = `${path}:${line}`
    if (await copyText(text)) showToast('success', `Copied ${text}`)
    else showToast('error', `The browser would not copy to the clipboard. The path is ${text}`)
  }

  async function openVisualStudio() {
    showToast('success', `Opening ${filePath.split(/[\\/]/).pop()} in Visual Studio…`)
    try {
      const result = await openInVisualStudio(path, line)
      showToast(result.opened ? 'success' : 'error', result.message)
    } catch (err) {
      showToast('error', err instanceof Error ? err.message : 'Visual Studio did not open the file')
    }
  }

  function act(action: EditorChoice) {
    setMenuOpen(false)
    if (action === 'copy') void copy()
    else if (action === 'visual_studio') void openVisualStudio()
    else window.location.href = vscodeHref
  }

  function onLinkClick(event: MouseEvent) {
    if (choice === 'vscode') return // the vscode:// link opens it
    event.preventDefault()
    act(choice)
  }

  const verb = choice === 'copy' ? 'copies its path and line' : `opens in ${choice === 'vscode' ? 'VS Code' : 'Visual Studio'}`
  const choices: { id: EditorChoice; label: string }[] = [
    ...(editors ?? []).map((e) => ({ id: e.id as EditorChoice, label: e.id === 'vscode' ? 'VS Code' : 'Visual Studio' })),
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
          {editors?.some((e) => e.id === 'vscode') && (
            <button type="button" role="menuitem" onClick={() => act('vscode')} className="px-3 py-1 text-left hover:bg-neutral-50">
              Open in VS Code
            </button>
          )}
          {visualStudio && (
            <button type="button" role="menuitem" onClick={() => act('visual_studio')} className="px-3 py-1 text-left hover:bg-neutral-50" title={visualStudio.label}>
              Open in Visual Studio
            </button>
          )}
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
          {editors !== null && editors.length < 2 && (
            <span className="px-3 pt-1 text-[10px] text-neutral-400">
              {editors.length === 0 ? 'Neither VS Code nor Visual Studio was found' : `${editors[0].id === 'vscode' ? 'Visual Studio' : 'VS Code'} was not found`} on this
              machine.
            </span>
          )}
        </span>
      )}
    </span>
  )
}
