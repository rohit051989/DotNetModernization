/** Phase boundaries by lifecycle_step_no — see 17-LIFECYCLE-STEPS.md's four
 * section headers. Static and fixed: renumbering the 51-step register is a
 * "changing this file" event per that doc, not something derived at
 * runtime. */
export interface Phase {
  name: string
  min: number
  max: number
}

export const PHASES: Phase[] = [
  { name: 'Phase 0 — Estate discovery & inventory', min: 1, max: 12 },
  { name: 'Phase 1 — Target state governance', min: 13, max: 16 },
  { name: 'Track A — Dev track (per application)', min: 17, max: 40 },
  { name: 'Track B — DevOps track (per wave)', min: 41, max: 51 },
]

export const UNASSIGNED_PHASE_NAME = 'Unassigned'

export function phaseForStep(lifecycleStepNo: number | null): string {
  if (lifecycleStepNo === null) return UNASSIGNED_PHASE_NAME
  const phase = PHASES.find((p) => lifecycleStepNo >= p.min && lifecycleStepNo <= p.max)
  return phase?.name ?? UNASSIGNED_PHASE_NAME
}
