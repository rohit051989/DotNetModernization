import { api } from './client'

/** 'vscode', or 'visual_studio:<installation>' for each Visual Studio installation. */
export type EditorId = string

export interface Editor {
  id: EditorId
  kind: 'vscode' | 'visual_studio'
  /** VS Code, or the installation's full name, such as "Visual Studio Enterprise 2026". */
  label: string
  opens_at_line: boolean
  /** Visual Studio only: the installation to open with. */
  installation?: string | null
  version?: string | null
}

export interface OpenResult {
  opened: boolean
  /** False when the file is open but Visual Studio could not be moved to the line. */
  at_line: boolean
  message: string
}

/** The editors installed on the machine the platform runs on: VS Code, then each Visual Studio, newest first. */
export function listEditors() {
  return api.get<{ editors: Editor[] }>('/api/editors')
}

/** The backend opens the file in that Visual Studio installation (the newest when none is named), at the line when
 * it can. 403 for a path outside every registered repository, conversion worktree and RUNS_DIR. */
export function openInVisualStudio(path: string, line: number, installation?: string | null) {
  return api.post<OpenResult>('/api/editors/visual-studio/open', { path, line, installation: installation ?? null })
}
