import { useEffect, useSyncExternalStore, useState } from 'react'
import { listEditors, type Editor, type EditorId } from '../../api/editors'

/** What a file link does when clicked: open in one of the editors on this machine (by its id: 'vscode', or
 * 'visual_studio:<installation>'), or copy the path and line. */
export type EditorChoice = EditorId | 'copy'

const STORAGE_KEY = 'file-links:editor'
const listeners = new Set<() => void>()

function stored(): EditorChoice | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY) || null
  } catch {
    return null
  }
}

/** Remembers the choice in this browser, and every file link on the page follows it. */
export function setEditorChoice(choice: EditorChoice) {
  try {
    window.localStorage.setItem(STORAGE_KEY, choice)
  } catch {
    // Storage blocked: the choice lasts until the page is reloaded.
  }
  remembered = choice
  listeners.forEach((listener) => listener())
}

let remembered: EditorChoice | null = null

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

let editorsRequest: Promise<Editor[]> | null = null

/** Asked once per page load: what is installed does not change while the page is open. */
function installedEditors(): Promise<Editor[]> {
  editorsRequest ??= listEditors().then(
    (result) => result.editors,
    () => [],
  )
  return editorsRequest
}

/** For tests: forget what was asked and remembered. */
export function resetEditorChoiceForTests() {
  editorsRequest = null
  remembered = null
}

/** The editors on this machine (null while being asked), and the choice in effect: the remembered one when that
 * editor is installed; a remembered Visual Studio that is not (or the 'visual_studio' remembered before
 * installations were told apart) becomes the newest Visual Studio installed; else the first installed editor, else
 * copying. */
export function useEditorChoice(): { editors: Editor[] | null; choice: EditorChoice } {
  const [editors, setEditors] = useState<Editor[] | null>(null)
  const choice = useSyncExternalStore(subscribe, () => remembered ?? stored())
  useEffect(() => {
    let live = true
    installedEditors().then((found) => live && setEditors(found))
    return () => {
      live = false
    }
  }, [])
  if (editors === null) return { editors, choice: choice ?? 'vscode' }
  if (choice === 'copy' || editors.some((e) => e.id === choice)) return { editors, choice: choice! }
  const newestVisualStudio = editors.find((e) => e.kind === 'visual_studio')
  if (choice?.startsWith('visual_studio') && newestVisualStudio) return { editors, choice: newestVisualStudio.id }
  return { editors, choice: editors[0]?.id ?? 'copy' }
}

/** The file's full path on this machine, in the repository path's own style: `D:\repo\src\Web\X.cs`. */
export function fullPath(localPath: string, filePath: string) {
  const separator = localPath.includes('\\') ? '\\' : '/'
  const root = localPath.replace(/[\\/]+$/, '')
  return `${root}${separator}${filePath.replace(/[\\/]+/g, separator).replace(/^[\\/]+/, '')}`
}

/** Copies text to the clipboard; false when the browser refused. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    const area = document.createElement('textarea')
    area.value = text
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    const copied = document.execCommand('copy')
    area.remove()
    return copied
  }
}
