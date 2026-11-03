import type { Toolchain } from '../../types/toolchain'

/** Whether the repository's machine can build and test its baseline (36-COPILOT-ENHANCED-CONVERSION Part P), in
 * plain words. `compact`: the page header's line, shown only when it cannot. Otherwise the Conversion tab's: what is
 * missing, for which projects, and what the machine has instead; or that it is ready. */
export function ToolchainNotice({ toolchain, compact = false }: { toolchain: Toolchain | null; compact?: boolean }) {
  if (!toolchain || !toolchain.checked) {
    if (compact || !toolchain) return null
    return <p className="text-xs text-neutral-500" data-testid="toolchain-notice">{toolchain.summary}</p>
  }
  const where = toolchain.held_on ? ` (as ${toolchain.host ?? 'its machine'} last found)` : ''
  if (toolchain.ready) {
    if (compact) return null
    return (
      <p className="text-xs text-emerald-700" data-testid="toolchain-notice">
        {toolchain.summary}{where}.
      </p>
    )
  }
  if (compact) {
    return (
      <p className="mt-1 text-xs text-amber-800" data-testid="toolchain-header">
        {toolchain.summary}{where}.
      </p>
    )
  }
  return (
    <div className="rounded border border-amber-300 bg-amber-50 px-2 py-1.5 text-xs text-amber-900" data-testid="toolchain-notice">
      <p className="font-medium">{toolchain.summary}{where}.</p>
      <p className="mt-0.5">
        A conversion prepared now gets no package step: its package changes go to the agent as instructions. Install
        what is missing on {toolchain.host ?? 'the repository’s machine'}, then start the conversion.
      </p>
      <ul className="mt-1 list-disc space-y-0.5 pl-4">
        {toolchain.missing.map((m) => (
          <li key={m.label}>
            <span className="font-medium">{m.label}</span>, for {m.for === 'build' ? 'the build' : 'the tests'} of{' '}
            {m.projects.length === 1 ? m.projects[0] : `${m.projects.length} projects`}: {m.detail}
          </li>
        ))}
      </ul>
    </div>
  )
}
