import type { CatalogItem } from '../../types/items'
import { IdentifierText } from '../../components/IdentifierText'
import { LimitedList } from '../../components/LimitedList'

const REASON_LABEL: Record<string, string> = {
  signal_mapping_pending: 'Signal mapping pending — the detection has nothing to match yet',
  signal_not_ready: 'Signal not ready — a referenced signal cannot be extracted yet',
  extractor_not_implemented: 'extractor not implemented',
  signal_not_registered: 'signal not registered',
}

/** 28-ITEM-AND-CONVERSION-MODEL.md Part C "Structured reason". `compact` is
 * the one-glance form for list rows. */
export function ReadinessReason({
  item,
  compact = false,
  onSelectSignal,
}: {
  item: CatalogItem
  compact?: boolean
  /** Links each blocking signal to the Signals view (full form only). */
  onSelectSignal?: (name: string) => void
}) {
  if (item.state === 'ready' || !item.state_reason) return null
  const reason = item.state_reason
  const blocking = reason.blocking_signals ?? []

  if (compact) {
    return (
      <div className="mt-1 space-y-0.5 text-[11px] leading-snug text-amber-700">
        <p className="font-mono">{reason.reason_code}</p>
        {blocking.map((b) => (
          <p key={b.signal} className="truncate" title={`${b.signal}: ${b.reason_code}`}>
            <span className="font-mono">{b.signal}</span>
            <span className="text-amber-600/80"> → {b.expected_extractor ?? 'no extractor declared'}</span>
          </p>
        ))}
      </div>
    )
  }

  return (
    <div className="rounded border border-amber-200 bg-amber-50 px-4 py-3 text-sm">
      <p className="font-medium text-amber-800">
        {REASON_LABEL[reason.reason_code] ?? reason.reason_code}{' '}
        <span className="font-mono text-xs font-normal text-amber-700">({reason.reason_code})</span>
      </p>
      <p className="mt-1 text-xs text-amber-700">
        A not-ready item is inert: detection does not evaluate it. It promotes automatically once every signal it
        references is ready — nobody edits the item.
      </p>
      <LimitedList items={blocking} name={(b) => [b.signal, b.expected_extractor]} noun="blocking signals" className="mt-3">
        {(visible) => (
          <table className="w-full text-left text-xs">
            <thead className="text-amber-700">
              <tr>
                <th className="py-1 pr-3 font-medium">Blocking signal</th>
                <th className="py-1 pr-3 font-medium">Reason</th>
                <th className="py-1 font-medium">Expected extractor</th>
              </tr>
            </thead>
            <tbody className="text-amber-900">
              {visible.map((b) => (
                <tr key={b.signal} className="border-t border-amber-200">
                  <td className="py-1 pr-3 font-mono">
                    {onSelectSignal ? (
                      <button
                        type="button"
                        onClick={() => onSelectSignal(b.signal)}
                        title="Open in Signals"
                        className="text-left underline decoration-dotted underline-offset-2 hover:text-violet-700 hover:decoration-solid"
                      >
                        <IdentifierText name={b.signal} />
                      </button>
                    ) : (
                      <IdentifierText name={b.signal} />
                    )}
                  </td>
                  <td className="py-1 pr-3">{REASON_LABEL[b.reason_code] ?? b.reason_code}</td>
                  <td className="py-1 font-mono">{b.expected_extractor ?? '— none declared —'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </LimitedList>
    </div>
  )
}
