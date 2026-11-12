import { describe, expect, it } from 'vitest'
import { showsLinux } from './hosting'

describe('showsLinux', () => {
  it('is true only for a move from Windows hosting to Linux hosting', () => {
    expect(showsLinux({ current_hosting_os: 'windows', target_hosting_os: 'linux' })).toBe(true)
    expect(showsLinux({ current_hosting_os: 'windows', target_hosting_os: 'windows' })).toBe(false)
    expect(showsLinux({ current_hosting_os: 'linux', target_hosting_os: 'linux' })).toBe(false)
    expect(showsLinux({ current_hosting_os: 'linux', target_hosting_os: 'windows' })).toBe(false)
  })
})
