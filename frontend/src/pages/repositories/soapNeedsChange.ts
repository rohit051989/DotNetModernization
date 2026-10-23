import type { RepositorySoap } from '../../types/surface'

/** A verdict that asks for a change in some environment: the runtime does not support it, or only with a caveat, or
 * Linux needs a change or cannot run it. The SOAP panel flags these, and the Overview counts the calls with one. */
export function needsChange(env: RepositorySoap['calls'][number]['environments'][number]): boolean {
  return ['unsupported', 'supported_with_caveat'].includes(env.runtime.verdict ?? '') || ['incompatible', 'requires_change'].includes(env.platform.verdict ?? '')
}
