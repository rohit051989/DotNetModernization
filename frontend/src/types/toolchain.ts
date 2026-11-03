/** One runtime or build tool a repository's baseline needs (36-COPILOT-ENHANCED-CONVERSION Part P). */
export interface ToolchainItem {
  kind: 'sdk' | 'runtime' | 'reference-assemblies' | 'netfx-runtime' | 'web-targets'
  /** In plain words: "the .NET 8 runtime (x64)". */
  label: string
  /** build: the baseline cannot build without it; test: its tests cannot run. */
  for: 'build' | 'test'
  projects: string[]
  /** What the machine has instead, and where. */
  detail: string
}

/** Whether the repository's machine can build and test its baseline on the repository's own frameworks. */
export interface Toolchain {
  checked: boolean
  ready: boolean | null
  summary: string
  missing: ToolchainItem[]
  present: ToolchainItem[]
  host: string | null
  checked_at: string | null
  /** Set when the repository is registered on another machine: what that machine last found. */
  held_on: string | null
}
