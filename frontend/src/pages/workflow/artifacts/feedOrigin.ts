/** Where a feed came from (dependency-assessment's `declaredIn`), in words. Every value the step writes has one; an
 * unknown value is shown as it is. */
export const FEED_ORIGIN: Record<string, string> = {
  repository: "the repository's NuGet.config",
  parent: 'a NuGet.config in a parent folder',
  user: "the user's NuGet.config",
  machine: "the machine's NuGet.config",
  default: "NuGet's default source",
  engagement: "the engagement's Artifactory tab",
}

export function feedOrigin(declaredIn: string | null | undefined): string {
  if (!declaredIn) return 'an unknown place'
  return FEED_ORIGIN[declaredIn] ?? declaredIn
}
