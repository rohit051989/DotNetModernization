import type { ReactNode } from 'react'
import { IdentifierText } from '../../components/IdentifierText'
import type {
  CatalogSignal,
  ItemDetection,
  ItemMetadataCondition,
  ItemRuleCondition,
  ItemSignalCondition,
  ItemValueMatch,
} from '../../types/items'

interface DetectionViewProps {
  detection: ItemDetection
  /** Registered signals by name, for colouring each reference by readiness.
   * Optional — without it names render neutrally. */
  signals?: Map<string, CatalogSignal>
  /** Opens the signal in the Signals view. Without it names are plain text. */
  onSelectSignal?: (name: string) => void
}

type SignalLinking = Pick<DetectionViewProps, 'signals' | 'onSelectSignal'>

function quote(value: string) {
  return <span className="font-mono text-neutral-800">"{value}"</span>
}

function list(values: string[]) {
  return (
    <span className="font-mono text-neutral-800">
      [{values.map((v) => `"${v}"`).join(', ')}]
    </span>
  )
}

/** Renders the value predicates of a ValueMatch (or the value part of a
 * metadata condition) as readable phrases. */
function valuePredicates(value: ItemValueMatch): ReactNode[] {
  const parts: ReactNode[] = []
  if (value.equals !== undefined && value.equals !== null) parts.push(<>equals {quote(value.equals)}</>)
  if (value.in) parts.push(<>is one of {list(value.in)}</>)
  if (value.startsWith !== undefined && value.startsWith !== null) parts.push(<>starts with {quote(value.startsWith)}</>)
  if (value.contains !== undefined && value.contains !== null) parts.push(<>contains {quote(value.contains)}</>)
  if (value.regex !== undefined && value.regex !== null) parts.push(<>matches regex {quote(value.regex)}</>)
  return parts
}

function signalQualifiers(signal: ItemSignalCondition): ReactNode[] {
  const parts: ReactNode[] = []
  if (signal.value) {
    for (const predicate of valuePredicates(signal.value)) parts.push(<>value {predicate}</>)
  }
  if (signal.sourceType) parts.push(<>source type {quote(signal.sourceType)}</>)
  if (signal.category) parts.push(<>category {quote(signal.category)}</>)
  if (signal.type) parts.push(<>type {quote(signal.type)}</>)
  if (signal.minimumOccurrences != null) parts.push(<>≥ {signal.minimumOccurrences} occurrence(s)</>)
  if (signal.maximumOccurrences != null) parts.push(<>≤ {signal.maximumOccurrences} occurrence(s)</>)
  if (signal.minimumDistinctValues != null) parts.push(<>≥ {signal.minimumDistinctValues} distinct value(s)</>)
  if (signal.minimumDistinctSourceFiles != null)
    parts.push(<>≥ {signal.minimumDistinctSourceFiles} distinct source file(s)</>)
  if (signal.minimumExtractionConfidence != null)
    parts.push(<>extraction confidence ≥ {signal.minimumExtractionConfidence}</>)
  return parts
}

function SignalName({ name, signals, onSelectSignal }: { name: string } & SignalLinking) {
  let tone = 'bg-neutral-100 text-neutral-800'
  let title = name
  if (signals) {
    const signal = signals.get(name)
    if (!signal) {
      tone = 'bg-red-50 text-red-700'
      title = `${name} — not registered`
    } else if (signal.state !== 'ready') {
      tone = 'bg-amber-50 text-amber-800'
      title = `${name} — not ready (expected extractor: ${signal.expected_extractor})`
    } else {
      title = `${name} — ready (${signal.expected_extractor})${signal.description ? `: ${signal.description}` : ''}`
    }
  }
  const className = `rounded px-1.5 py-0.5 font-mono text-xs ${tone}`
  if (onSelectSignal) {
    return (
      <button
        type="button"
        onClick={() => onSelectSignal(name)}
        title={`${title}\nOpen in Signals — every item that uses it`}
        className={`${className} text-left underline decoration-dotted underline-offset-2 hover:decoration-solid hover:ring-1 hover:ring-violet-300`}
      >
        <IdentifierText name={name} />
      </button>
    )
  }
  return (
    <span title={title} className={className}>
      <IdentifierText name={name} />
    </span>
  )
}

function joinParts(parts: ReactNode[]) {
  return parts.map((part, index) => (
    <span key={index}>
      {index > 0 && <span className="text-neutral-300"> · </span>}
      {part}
    </span>
  ))
}

function RuleLine({ condition, signals, onSelectSignal }: { condition: ItemRuleCondition } & SignalLinking) {
  const qualifiers = signalQualifiers(condition.signal)
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm text-neutral-600">
      {condition.id && <span className="font-mono text-[11px] text-neutral-400">{condition.id}</span>}
      <SignalName name={condition.signal.name} signals={signals} onSelectSignal={onSelectSignal} />
      {qualifiers.length > 0 && <span className="text-xs">{joinParts(qualifiers)}</span>}
    </li>
  )
}

function MetadataLine({ condition }: { condition: ItemMetadataCondition }) {
  const parts = valuePredicates(condition)
  if (condition.notEquals !== undefined && condition.notEquals !== null)
    parts.push(<>does not equal {quote(condition.notEquals)}</>)
  if (condition.notIn) parts.push(<>is not one of {list(condition.notIn)}</>)
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm text-neutral-600">
      {condition.id && <span className="font-mono text-[11px] text-neutral-400">{condition.id}</span>}
      <span className="rounded bg-sky-50 px-1.5 py-0.5 font-mono text-xs text-sky-800">{condition.field}</span>
      <span className="text-xs">{parts.length > 0 ? joinParts(parts) : 'is present'}</span>
    </li>
  )
}

function Group({ label, hint, children }: { label: string; hint: string; children: ReactNode }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
        {label} <span className="font-normal normal-case tracking-normal text-neutral-400">— {hint}</span>
      </p>
      <ul className="mt-1.5 space-y-1.5 border-l-2 border-neutral-100 pl-3">{children}</ul>
    </div>
  )
}

export function DetectionView({ detection, signals, onSelectSignal }: DetectionViewProps) {
  const match = detection.match ?? {}
  const all = match.all ?? []
  const any = match.any ?? []
  const atLeast = match.atLeast ?? []
  const none = match.none ?? []
  const metadata = match.metadata ?? []
  const empty = all.length + any.length + atLeast.length + none.length + metadata.length === 0

  return (
    <div className="space-y-4">
      {empty && (
        <p className="text-sm text-neutral-400">
          No conditions yet — the item has nothing to match, so it is not ready (signal mapping pending).
        </p>
      )}
      {all.length > 0 && (
        <Group label="All of" hint="every condition must hold">
          {all.map((c, i) => (
            <RuleLine key={c.id ?? i} condition={c} signals={signals} onSelectSignal={onSelectSignal} />
          ))}
        </Group>
      )}
      {any.length > 0 && (
        <Group label="Any of" hint="at least one must hold">
          {any.map((c, i) => (
            <RuleLine key={c.id ?? i} condition={c} signals={signals} onSelectSignal={onSelectSignal} />
          ))}
        </Group>
      )}
      {atLeast.map((group, gi) => (
        <Group
          key={group.id ?? gi}
          label={`At least ${group.count} of`}
          hint={group.id ? `group ${group.id}` : `${group.of.length} candidate(s)`}
        >
          {group.of.map((c, i) => (
            <RuleLine key={c.id ?? i} condition={c} signals={signals} onSelectSignal={onSelectSignal} />
          ))}
        </Group>
      ))}
      {none.length > 0 && (
        <Group label="None of" hint="excluded when any of these holds">
          {none.map((c, i) => (
            <RuleLine key={c.id ?? i} condition={c} signals={signals} onSelectSignal={onSelectSignal} />
          ))}
        </Group>
      )}
      {metadata.length > 0 && (
        <Group label="Project metadata" hint="every condition must hold">
          {metadata.map((c, i) => (
            <MetadataLine key={c.id ?? i} condition={c} />
          ))}
        </Group>
      )}

      <div className="rounded bg-neutral-50 px-3 py-2 text-sm">
        <span className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Occurrence source </span>
        {detection.occurrence_source ? (
          <span className="text-neutral-600">
            — one occurrence per{' '}
            {detection.occurrence_source.group_by === 'source_path_and_value'
              ? 'distinct path and value'
              : 'distinct source path'}{' '}
            in the evidence of <SignalName name={detection.occurrence_source.signal} signals={signals} onSelectSignal={onSelectSignal} />
          </span>
        ) : (
          <span className="text-neutral-400">— none (the project is the unit)</span>
        )}
      </div>
    </div>
  )
}
