import { api } from './client'

export type EditorId = 'vscode' | 'visual_studio'

export interface Editor {
  id: EditorId
  label: string
  opens_at_line: boolean
}

export interface OpenResult {
  opened: boolean
  /** False when the file is open but Visual Studio could not be moved to the line. */
  at_line: boolean
  message: string
}

/** The editors installed on the machine the platform runs on. */
export function listEditors() {
  return api.get<{ editors: Editor[] }>('/api/editors')
}

/** The backend opens the file in Visual Studio, at the line when it can. 403 for a path outside every registered
 * repository, conversion worktree and RUNS_DIR. */
export function openInVisualStudio(path: string, line: number) {
  return api.post<OpenResult>('/api/editors/visual-studio/open', { path, line })
}
