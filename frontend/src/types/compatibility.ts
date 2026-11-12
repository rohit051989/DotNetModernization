// The repository Compatibility section's Linux list (backend app.routers.compatibility_pages).
// SOAP compatibility has its own types (types/surface.ts).

export interface CompatibilitySummary {
  linux: number
  linux_items: number
  linux_packages: number
  linux_blockers: number
  linux_container: number
  linux_other: number
  scanned_at: string | null
}

/** What a Linux finding means for the move: it fails on Linux (blocker), runs but needs a change for an OpenShift
 * container (container), or behaves differently (other). */
export type Treatment = 'blocker' | 'container' | 'other'

/** One finding: a found catalog item ('item') or a Windows-only package ('package'). */
export interface CompatibilityFinding {
  kind: 'item' | 'package'
  treatment?: Treatment | null
  id: string
  itemId: string | null
  itemName: string
  category: string
  project: string
  file: string | null
  value: string | null
  certainty: 'confirmed' | 'possible'
  /** What to do: the item's default resolution, or the package's replacement. */
  whatToDo?: string | null
  whatToDoDetail?: string | null
  /** Packages: why it cannot run on Linux. */
  whyBlocked?: string | null
  packageId?: string
  currentVersion?: string | null
}
