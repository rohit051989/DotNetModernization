/** `vscode://file/D:/repo/src/Web/X.cs:42` — forward slashes, each segment
 * encoded. Opens only on the machine that registered the repository (the
 * single-operator model; CLAUDE.md "Operating model"). */
export function sourceHref(localPath: string, filePath: string, line: number) {
  const root = localPath.replace(/\\/g, '/').replace(/\/+$/, '')
  const path = `${root}/${filePath}`.split('/').map(encodeURIComponent).join('/').replace(/^([A-Za-z])%3A/, '$1:')
  return `vscode://file/${path}:${line}`
}
