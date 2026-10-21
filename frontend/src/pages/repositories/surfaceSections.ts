/** The Surface tab's sections, in the order of its jump links. Each is collapsible on its own, says what is in it
 * while closed, and is remembered per repository in this browser (rbc-release-6). */
export const SURFACE_SECTIONS = ['inbound', 'outbound', 'soap', 'reach'] as const

export type SurfaceSection = (typeof SURFACE_SECTIONS)[number]

/** The section's id: unique app-wide, and the key its open state is remembered under. */
export function surfaceSectionId(repositoryId: string, section: SurfaceSection): string {
  return `surface:${repositoryId}:${section}`
}
