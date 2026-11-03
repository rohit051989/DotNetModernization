import { api } from './client'
import type { Toolchain } from '../types/toolchain'

/** Whether the repository's machine has the runtimes and build tools its baseline needs: checked now on that machine,
 * else as it last found. */
export function getToolchain(repositoryId: string) {
  return api.get<Toolchain>(`/api/repositories/${encodeURIComponent(repositoryId)}/toolchain`)
}
