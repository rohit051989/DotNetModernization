import type { HostingOs } from '../../types/repositories'

/** The words shown for a hosting OS. */
export const HOSTING_LABEL: Record<HostingOs, string> = { windows: 'Windows', linux: 'Linux' }

/** Whether the Compatibility tab's Linux list (and the Linux part of the Overview's compatibility count) applies: only a
 * move from Windows hosting to Linux hosting has anything to say about running on Linux. One rule for every place. */
export function showsLinux(repo: { current_hosting_os: HostingOs; target_hosting_os: HostingOs }): boolean {
  return repo.current_hosting_os === 'windows' && repo.target_hosting_os === 'linux'
}
