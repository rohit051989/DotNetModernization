import { num } from '../workflow/artifacts/adapters'

/** The work list and the Impact tab state the same figures: the work items found on confirmed evidence, plus those
 * resting only on possible evidence (item-detection's `possible_only_found`), shown in both and counted apart. */
export function workItemFigures(summary: Record<string, unknown>) {
  const possible = num(summary.possible_only_found)
  return { workItems: num(summary.found) - possible, possible }
}

/** "46 work items, plus 2 possible". */
export function workItemsLine(workItems: number, possible: number) {
  return `${workItems} work item${workItems === 1 ? '' : 's'}${possible > 0 ? `, plus ${possible} possible` : ''}`
}
