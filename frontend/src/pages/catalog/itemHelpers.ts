import { ApiError } from '../../api/client'
import { CONSUMER_IMPACT_RANK, type ItemMatch, type ItemResolution } from '../../types/items'

/** Signals whose presence can make an item apply: `all`, `any` and
 * `atLeast.of` — the only ones an occurrence_source may name (Part E).
 * Mirrors positive_signal_names in backend/app/items/detection.py. */
export function positiveSignalNames(match: ItemMatch | null | undefined): string[] {
  if (!match) return []
  const names = new Set<string>()
  for (const condition of [...(match.all ?? []), ...(match.any ?? [])]) {
    if (condition?.signal?.name) names.add(condition.signal.name)
  }
  for (const group of match.atLeast ?? []) {
    for (const condition of group?.of ?? []) {
      if (condition?.signal?.name) names.add(condition.signal.name)
    }
  }
  return [...names].sort()
}

/** Collects API errors by field. Several messages on one field are joined;
 * errors with no field land under '__root__' (see api/client.ts). */
export function fieldErrorMap(err: ApiError): Record<string, string> {
  const mapped: Record<string, string> = {}
  for (const fieldError of err.fieldErrors) {
    mapped[fieldError.field] = mapped[fieldError.field]
      ? `${mapped[fieldError.field]} ${fieldError.message}`
      : fieldError.message
  }
  return mapped
}

/** Same heuristic as backend/app/routers/item_decisions.py targets_linux —
 * `target_platform` is free text. The server's warning is authoritative. */
export function targetsLinux(targetPlatform: string | null | undefined): boolean {
  const platform = (targetPlatform ?? '').toLowerCase()
  return ['linux', 'openshift', 'ocp'].some((marker) => platform.includes(marker))
}

/** Live resolutions the API judges "lowest impact" against: not deleted and
 * status active. */
export function liveResolutions(resolutions: ItemResolution[]): ItemResolution[] {
  return resolutions.filter((r) => r.deleted_at === null && r.status === 'active')
}

export function lowestImpactResolution(resolutions: ItemResolution[]): ItemResolution | null {
  const live = liveResolutions(resolutions)
  if (live.length === 0) return null
  return live.reduce((lowest, current) =>
    CONSUMER_IMPACT_RANK[current.consumer_impact] < CONSUMER_IMPACT_RANK[lowest.consumer_impact] ? current : lowest,
  )
}

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

/** Drops empty groups so a stored detection reads cleanly in the editor. */
export function compactMatch(match: ItemMatch | null | undefined): ItemMatch {
  const result: ItemMatch = {}
  if (!match) return result
  if (match.all?.length) result.all = match.all
  if (match.any?.length) result.any = match.any
  if (match.atLeast?.length) result.atLeast = match.atLeast
  if (match.none?.length) result.none = match.none
  if (match.metadata?.length) result.metadata = match.metadata
  return result
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString()
}
