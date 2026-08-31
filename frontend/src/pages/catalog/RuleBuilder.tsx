import { useEffect, useMemo, useState } from 'react'
import { getSignalRegistry, listPatterns } from '../../api/catalog'
import { Field, inputClass } from '../../components/FormField'
import type {
  AtLeastGroup,
  ClassificationRole,
  MetadataCondition,
  NoneCondition,
  PatternClassificationFields,
  PatternScope,
  PatternSummary,
  RequiredSignalPending,
  RuleCondition,
  RulesStatus,
  SignalRegistryEntry,
  SupportingCondition,
} from '../../types/catalog'
import { emptySignalRuleSet } from '../../types/catalog'

const CLASSIFICATION_ROLES: ClassificationRole[] = ['PRIMARY', 'SECONDARY', 'PROJECT_ROLE']
const PATTERN_SCOPES: PatternScope[] = ['PROJECT', 'REPOSITORY']
const RULES_STATUSES: RulesStatus[] = ['active', 'awaiting_signals', 'draft']
const FINGERPRINT_STATUSES = ['COMPLETE', 'PARTIAL', 'FAILED', 'SKIPPED', 'NOT_SUPPORTED']
const PROJECT_ROLES = ['TEST', 'DATABASE', 'DEPLOYMENT', 'LIBRARY', 'APPLICATION', 'UNKNOWN']
const ANALYSIS_CAPABILITIES = [
  'fileDiscovery',
  'syntaxAnalysis',
  'msbuildEvaluated',
  'semanticAnalysis',
  'configurationParsed',
  'generatedCodeExcluded',
  'projectMetadataParsed',
  'deploymentArtifactsParsed',
]
const METADATA_FIELDS = [
  'outputType',
  'projectFormat',
  'frameworkFamily',
  'frameworkVersion',
  'projectSdk',
  'structuralType',
  'extension',
  'fingerprintStatus',
]

interface RuleBuilderProps {
  patternId: string | null
  value: PatternClassificationFields
  onChange: (value: PatternClassificationFields) => void
}

function SectionHeader({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="mb-2">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-neutral-500">{title}</h4>
      {hint && <p className="text-xs text-neutral-400">{hint}</p>}
    </div>
  )
}

function Checkbox({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-neutral-700">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  )
}

function SignalSelect({
  value,
  onChange,
  registry,
}: {
  value: string
  onChange: (name: string) => void
  registry: SignalRegistryEntry[]
}) {
  const selected = registry.find((s) => s.name === value)
  return (
    <div>
      <select value={value} onChange={(e) => onChange(e.target.value)} className={inputClass(false)}>
        <option value="">Select a signal…</option>
        {registry.map((s) => (
          <option key={s.name} value={s.name}>
            {s.name} {s.weak_anchor ? '(weak)' : ''}
          </option>
        ))}
      </select>
      {selected && <p className="mt-1 text-xs text-neutral-400">{selected.description}</p>}
      {!selected && value && <p className="mt-1 text-xs text-amber-600">'{value}' is not in the active registry.</p>}
    </div>
  )
}

function ConditionRow({
  condition,
  onChange,
  onRemove,
  registry,
  extra,
}: {
  condition: RuleCondition
  onChange: (c: RuleCondition) => void
  onRemove: () => void
  registry: SignalRegistryEntry[]
  extra?: React.ReactNode
}) {
  return (
    <div className="space-y-2 rounded border border-neutral-200 bg-neutral-50 p-2.5">
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={condition.id ?? ''}
          onChange={(e) => onChange({ ...condition, id: e.target.value })}
          placeholder="rule id (auto if blank)"
          className={`${inputClass(false)} w-40 font-mono text-xs`}
        />
        <div className="flex-1">
          <SignalSelect
            value={condition.signal.name}
            onChange={(name) => onChange({ ...condition, signal: { ...condition.signal, name } })}
            registry={registry}
          />
        </div>
        <button type="button" onClick={onRemove} className="text-xs text-red-500 hover:underline">
          Remove
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <input
          type="number"
          value={condition.signal.minimumOccurrences ?? ''}
          onChange={(e) =>
            onChange({
              ...condition,
              signal: { ...condition.signal, minimumOccurrences: e.target.value ? Number(e.target.value) : null },
            })
          }
          placeholder="min occurrences"
          className={`${inputClass(false)} text-xs`}
        />
        <input
          type="text"
          value={condition.signal.value?.equals ?? ''}
          onChange={(e) =>
            onChange({
              ...condition,
              signal: { ...condition.signal, value: { ...condition.signal.value, equals: e.target.value || null } },
            })
          }
          placeholder="value equals"
          className={`${inputClass(false)} text-xs`}
        />
        <input
          type="text"
          value={condition.signal.category ?? ''}
          onChange={(e) => onChange({ ...condition, signal: { ...condition.signal, category: e.target.value || null } })}
          placeholder="category (narrows)"
          className={`${inputClass(false)} text-xs`}
        />
        <input
          type="number"
          step="0.01"
          min="0"
          max="1"
          value={condition.signal.minimumExtractionConfidence ?? ''}
          onChange={(e) =>
            onChange({
              ...condition,
              signal: {
                ...condition.signal,
                minimumExtractionConfidence: e.target.value ? Number(e.target.value) : null,
              },
            })
          }
          placeholder="min confidence"
          className={`${inputClass(false)} text-xs`}
        />
      </div>
      {extra}
    </div>
  )
}

function ConditionList({
  title,
  conditions,
  onChange,
  registry,
}: {
  title: string
  conditions: RuleCondition[]
  onChange: (list: RuleCondition[]) => void
  registry: SignalRegistryEntry[]
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <p className="text-xs font-medium text-neutral-600">{title}</p>
        <button
          type="button"
          onClick={() => onChange([...conditions, { signal: { name: '' } }])}
          className="text-xs text-violet-600 hover:underline"
        >
          + Add condition
        </button>
      </div>
      <div className="space-y-2">
        {conditions.map((c, i) => (
          <ConditionRow
            key={i}
            condition={c}
            registry={registry}
            onChange={(updated) => onChange(conditions.map((existing, j) => (j === i ? updated : existing)))}
            onRemove={() => onChange(conditions.filter((_, j) => j !== i))}
          />
        ))}
        {conditions.length === 0 && <p className="text-xs text-neutral-400">None — imposes no constraint.</p>}
      </div>
    </div>
  )
}

function SupportingList({
  conditions,
  onChange,
  registry,
}: {
  conditions: SupportingCondition[]
  onChange: (list: SupportingCondition[]) => void
  registry: SignalRegistryEntry[]
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <p className="text-xs font-medium text-neutral-600">supporting (weighted, capped at 50 total)</p>
        <button
          type="button"
          onClick={() => onChange([...conditions, { signal: { name: '' }, weight: 10 }])}
          className="text-xs text-violet-600 hover:underline"
        >
          + Add condition
        </button>
      </div>
      <div className="space-y-2">
        {conditions.map((c, i) => (
          <ConditionRow
            key={i}
            condition={c}
            registry={registry}
            onChange={(updated) =>
              onChange(conditions.map((existing, j) => (j === i ? { ...existing, ...updated } : existing)))
            }
            onRemove={() => onChange(conditions.filter((_, j) => j !== i))}
            extra={
              <div className="flex items-center gap-2">
                <label className="text-xs text-neutral-500">weight</label>
                <input
                  type="number"
                  value={c.weight}
                  onChange={(e) =>
                    onChange(conditions.map((existing, j) => (j === i ? { ...existing, weight: Number(e.target.value) } : existing)))
                  }
                  className={`${inputClass(false)} w-20 text-xs`}
                />
              </div>
            }
          />
        ))}
        {conditions.length === 0 && <p className="text-xs text-neutral-400">None.</p>}
      </div>
    </div>
  )
}

function NoneList({
  conditions,
  onChange,
  registry,
}: {
  conditions: NoneCondition[]
  onChange: (list: NoneCondition[]) => void
  registry: SignalRegistryEntry[]
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <p className="text-xs font-medium text-neutral-600">
          none — negative evidence (disqualify rules the match out entirely; penalty subtracts from score)
        </p>
        <button
          type="button"
          onClick={() => onChange([...conditions, { signal: { name: '' }, disqualify: true }])}
          className="text-xs text-violet-600 hover:underline"
        >
          + Add condition
        </button>
      </div>
      <div className="space-y-2">
        {conditions.map((c, i) => (
          <ConditionRow
            key={i}
            condition={c}
            registry={registry}
            onChange={(updated) =>
              onChange(conditions.map((existing, j) => (j === i ? { ...existing, ...updated } : existing)))
            }
            onRemove={() => onChange(conditions.filter((_, j) => j !== i))}
            extra={
              <div className="flex items-center gap-3">
                <Checkbox
                  checked={!!c.disqualify}
                  onChange={(v) =>
                    onChange(conditions.map((existing, j) => (j === i ? { ...existing, disqualify: v, penalty: v ? null : existing.penalty } : existing)))
                  }
                  label="disqualify"
                />
                {!c.disqualify && (
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-neutral-500">penalty</label>
                    <input
                      type="number"
                      value={c.penalty ?? ''}
                      onChange={(e) =>
                        onChange(
                          conditions.map((existing, j) =>
                            j === i ? { ...existing, penalty: e.target.value ? Number(e.target.value) : null } : existing,
                          ),
                        )
                      }
                      className={`${inputClass(false)} w-20 text-xs`}
                    />
                  </div>
                )}
              </div>
            }
          />
        ))}
        {conditions.length === 0 && <p className="text-xs text-neutral-400">None.</p>}
      </div>
    </div>
  )
}

function AtLeastList({
  groups,
  onChange,
  registry,
}: {
  groups: AtLeastGroup[]
  onChange: (list: AtLeastGroup[]) => void
  registry: SignalRegistryEntry[]
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <p className="text-xs font-medium text-neutral-600">atLeast — each group needs `count` of its conditions to match</p>
        <button
          type="button"
          onClick={() => onChange([...groups, { count: 1, of: [] }])}
          className="text-xs text-violet-600 hover:underline"
        >
          + Add group
        </button>
      </div>
      <div className="space-y-3">
        {groups.map((g, i) => (
          <div key={i} className="rounded border border-neutral-200 p-2.5">
            <div className="mb-2 flex items-center gap-2">
              <label className="text-xs text-neutral-500">count</label>
              <input
                type="number"
                min={1}
                value={g.count}
                onChange={(e) => onChange(groups.map((existing, j) => (j === i ? { ...existing, count: Number(e.target.value) } : existing)))}
                className={`${inputClass(false)} w-16 text-xs`}
              />
              <div className="flex-1" />
              <button type="button" onClick={() => onChange(groups.filter((_, j) => j !== i))} className="text-xs text-red-500 hover:underline">
                Remove group
              </button>
            </div>
            <ConditionList
              title="of"
              conditions={g.of}
              registry={registry}
              onChange={(of) => onChange(groups.map((existing, j) => (j === i ? { ...existing, of } : existing)))}
            />
          </div>
        ))}
        {groups.length === 0 && <p className="text-xs text-neutral-400">None.</p>}
      </div>
    </div>
  )
}

function MetadataList({
  conditions,
  onChange,
}: {
  conditions: MetadataCondition[]
  onChange: (list: MetadataCondition[]) => void
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <p className="text-xs font-medium text-neutral-600">metadata — step 2/3 project fields, not signals</p>
        <button
          type="button"
          onClick={() => onChange([...conditions, { field: METADATA_FIELDS[0], equals: '' }])}
          className="text-xs text-violet-600 hover:underline"
        >
          + Add condition
        </button>
      </div>
      <div className="space-y-2">
        {conditions.map((c, i) => (
          <div key={i} className="flex items-center gap-2 rounded border border-neutral-200 bg-neutral-50 p-2">
            <input
              type="text"
              value={c.id ?? ''}
              onChange={(e) => onChange(conditions.map((existing, j) => (j === i ? { ...existing, id: e.target.value } : existing)))}
              placeholder="rule id"
              className={`${inputClass(false)} w-32 font-mono text-xs`}
            />
            <select
              value={c.field}
              onChange={(e) => onChange(conditions.map((existing, j) => (j === i ? { ...existing, field: e.target.value } : existing)))}
              className={`${inputClass(false)} text-xs`}
            >
              {METADATA_FIELDS.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
            <input
              type="text"
              value={c.equals ?? ''}
              onChange={(e) => onChange(conditions.map((existing, j) => (j === i ? { ...existing, equals: e.target.value || null } : existing)))}
              placeholder="equals"
              className={`${inputClass(false)} flex-1 text-xs`}
            />
            <button type="button" onClick={() => onChange(conditions.filter((_, j) => j !== i))} className="text-xs text-red-500 hover:underline">
              Remove
            </button>
          </div>
        ))}
        {conditions.length === 0 && <p className="text-xs text-neutral-400">None.</p>}
      </div>
    </div>
  )
}

export function RuleBuilder({ patternId, value, onChange }: RuleBuilderProps) {
  const [registry, setRegistry] = useState<SignalRegistryEntry[]>([]);
  const [otherPatterns, setOtherPatterns] = useState<PatternSummary[]>([]);
  const [rawMode, setRawMode] = useState(false);
  const [rawText, setRawText] = useState(() => JSON.stringify(value, null, 2));
  const [rawError, setRawError] = useState<string | null>(null);

  useEffect(() => {
    getSignalRegistry().then((r) => setRegistry(r.signals))
    listPatterns({}).then((patterns) => setOtherPatterns(patterns.filter((p) => p.id !== patternId)))
  }, [patternId])

  const ruleset = value.detection_rules ?? emptySignalRuleSet()

  function set<K extends keyof PatternClassificationFields>(key: K, v: PatternClassificationFields[K]) {
    onChange({ ...value, [key]: v })
  }

  function setRuleset(next: typeof ruleset) {
    set('detection_rules', next)
  }

  const weakAnchorWarning = useMemo(() => {
    if (value.anchor_signals.length !== 1) return null
    const only = registry.find((s) => s.name === value.anchor_signals[0])
    if (only?.weak_anchor) return `'${only.name}' is a weak signal (§7) — it should not be a pattern's only anchor.`
    return null
  }, [value.anchor_signals, registry])

  function toggleInList(list: string[], item: string): string[] {
    return list.includes(item) ? list.filter((x) => x !== item) : [...list, item]
  }

  function applyRaw() {
    try {
      const parsed = JSON.parse(rawText)
      onChange(parsed)
      setRawError(null)
    } catch (e) {
      setRawError(e instanceof Error ? e.message : 'Invalid JSON')
    }
  }

  return (
    <div className="space-y-5 rounded border border-neutral-200 p-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-neutral-900">Classification & detection rules</h3>
        <button
          type="button"
          onClick={() => {
            if (!rawMode) setRawText(JSON.stringify(value, null, 2))
            setRawMode((v) => !v)
          }}
          className="text-xs font-medium text-violet-600 hover:underline"
        >
          {rawMode ? 'Back to form' : 'Edit raw JSON'}
        </button>
      </div>

      {rawMode ? (
        <div>
          <textarea
            value={rawText}
            onChange={(e) => setRawText(e.target.value)}
            onBlur={applyRaw}
            rows={24}
            className="w-full rounded border border-neutral-300 p-2 font-mono text-xs"
          />
          {rawError && <p className="mt-1 text-xs text-red-600">{rawError}</p>}
        </div>
      ) : (
        <>
          <div>
            <SectionHeader title="Classification" />
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Field label="Role">
                <select value={value.classification_role} onChange={(e) => set('classification_role', e.target.value as ClassificationRole)} className={inputClass(false)}>
                  {CLASSIFICATION_ROLES.map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </Field>
              <Field label="Family">
                <input type="text" value={value.classification_family ?? ''} onChange={(e) => set('classification_family', e.target.value || null)} className={inputClass(false)} placeholder="APPLICATION_TYPE" />
              </Field>
              <Field label="Value">
                <input type="text" value={value.classification_value ?? ''} onChange={(e) => set('classification_value', e.target.value || null)} className={inputClass(false)} placeholder="REST_API" />
              </Field>
              <Field label="Priority">
                <input type="number" value={value.priority} onChange={(e) => set('priority', Number(e.target.value))} className={inputClass(false)} />
              </Field>
            </div>
            <Field label="Scope">
              <select value={value.scope} onChange={(e) => set('scope', e.target.value as PatternScope)} className={`${inputClass(false)} mt-1 w-40`}>
                {PATTERN_SCOPES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              {value.scope === 'REPOSITORY' && (
                <p className="mt-1 text-xs text-amber-600">REPOSITORY-scoped patterns are skipped by the engine (Part A8) — v1 evaluates PROJECT scope only.</p>
              )}
            </Field>
          </div>

          <div>
            <SectionHeader title="Compatibility" hint="Pattern ids — a pattern cannot appear in both lists." />
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="mb-1 text-xs text-neutral-500">compatible_with</p>
                <div className="max-h-32 space-y-1 overflow-y-auto rounded border border-neutral-200 p-2">
                  {otherPatterns.map((p) => (
                    <Checkbox key={p.id} checked={value.compatible_with.includes(p.id)} onChange={() => set('compatible_with', toggleInList(value.compatible_with, p.id))} label={p.id} />
                  ))}
                </div>
              </div>
              <div>
                <p className="mb-1 text-xs text-neutral-500">conflicts_with</p>
                <div className="max-h-32 space-y-1 overflow-y-auto rounded border border-neutral-200 p-2">
                  {otherPatterns.map((p) => (
                    <Checkbox key={p.id} checked={value.conflicts_with.includes(p.id)} onChange={() => set('conflicts_with', toggleInList(value.conflicts_with, p.id))} label={p.id} />
                  ))}
                </div>
              </div>
            </div>
            {value.compatible_with.some((id) => value.conflicts_with.includes(id)) && (
              <p className="mt-1 text-xs text-red-600">A pattern cannot be in both compatible_with and conflicts_with.</p>
            )}
          </div>

          <div>
            <SectionHeader title="Anchor signals" hint="Used for the candidate-selection index. Avoid a lone weak signal (§7)." />
            <div className="flex flex-wrap gap-2">
              {value.anchor_signals.map((name) => (
                <span key={name} className="flex items-center gap-1 rounded bg-violet-50 px-2 py-1 text-xs text-violet-700">
                  {name}
                  <button type="button" onClick={() => set('anchor_signals', value.anchor_signals.filter((n) => n !== name))} className="text-violet-400 hover:text-violet-700">×</button>
                </span>
              ))}
            </div>
            <select
              value=""
              onChange={(e) => e.target.value && set('anchor_signals', [...value.anchor_signals, e.target.value])}
              className={`${inputClass(false)} mt-2`}
            >
              <option value="">+ Add anchor signal…</option>
              {registry.filter((s) => !value.anchor_signals.includes(s.name)).map((s) => (
                <option key={s.name} value={s.name}>{s.name}{s.weak_anchor ? ' (weak)' : ''}</option>
              ))}
            </select>
            {weakAnchorWarning && <p className="mt-1 text-xs text-amber-600">{weakAnchorWarning}</p>}
          </div>

          <div>
            <SectionHeader title="Eligibility" />
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="mb-1 text-xs text-neutral-500">fingerprintStatuses (empty = no constraint)</p>
                <div className="flex flex-wrap gap-2">
                  {FINGERPRINT_STATUSES.map((s) => (
                    <Checkbox
                      key={s}
                      checked={value.eligibility?.fingerprintStatuses.includes(s) ?? false}
                      onChange={() =>
                        set('eligibility', {
                          fingerprintStatuses: toggleInList(value.eligibility?.fingerprintStatuses ?? [], s),
                          excludedProjectRoles: value.eligibility?.excludedProjectRoles ?? [],
                        })
                      }
                      label={s}
                    />
                  ))}
                </div>
              </div>
              <div>
                <p className="mb-1 text-xs text-neutral-500">excludedProjectRoles</p>
                <div className="flex flex-wrap gap-2">
                  {PROJECT_ROLES.map((r) => (
                    <Checkbox
                      key={r}
                      checked={value.eligibility?.excludedProjectRoles.includes(r) ?? false}
                      onChange={() =>
                        set('eligibility', {
                          fingerprintStatuses: value.eligibility?.fingerprintStatuses ?? [],
                          excludedProjectRoles: toggleInList(value.eligibility?.excludedProjectRoles ?? [], r),
                        })
                      }
                      label={r}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div>
            <SectionHeader title="Analysis requirements" />
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="mb-1 text-xs text-neutral-500">required — capability_factor is 0 if absent</p>
                <div className="flex flex-wrap gap-2">
                  {ANALYSIS_CAPABILITIES.map((c) => (
                    <Checkbox
                      key={c}
                      checked={!!value.analysis_requirements?.required[c]}
                      onChange={(v) =>
                        set('analysis_requirements', {
                          required: { ...value.analysis_requirements?.required, [c]: v },
                          preferred: value.analysis_requirements?.preferred ?? {},
                        })
                      }
                      label={c}
                    />
                  ))}
                </div>
              </div>
              <div>
                <p className="mb-1 text-xs text-neutral-500">preferred — capability_factor is 0.9 if absent</p>
                <div className="flex flex-wrap gap-2">
                  {ANALYSIS_CAPABILITIES.map((c) => (
                    <Checkbox
                      key={c}
                      checked={!!value.analysis_requirements?.preferred[c]}
                      onChange={(v) =>
                        set('analysis_requirements', {
                          required: value.analysis_requirements?.required ?? {},
                          preferred: { ...value.analysis_requirements?.preferred, [c]: v },
                        })
                      }
                      label={c}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div>
            <SectionHeader title="Thresholds" />
            <div className="flex gap-3">
              <Field label="minimumScore">
                <input type="number" min={0} max={100} value={value.thresholds.minimumScore} onChange={(e) => set('thresholds', { ...value.thresholds, minimumScore: Number(e.target.value) })} className={`${inputClass(false)} w-24`} />
              </Field>
              <Field label="highConfidenceScore">
                <input type="number" min={0} max={100} value={value.thresholds.highConfidenceScore} onChange={(e) => set('thresholds', { ...value.thresholds, highConfidenceScore: Number(e.target.value) })} className={`${inputClass(false)} w-24`} />
              </Field>
            </div>
          </div>

          <div>
            <SectionHeader title="Rules status" />
            <select value={value.rules_status} onChange={(e) => set('rules_status', e.target.value as RulesStatus)} className={`${inputClass(false)} w-48`}>
              {RULES_STATUSES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            {value.rules_status !== 'active' && (
              <p className="mt-1 text-xs text-neutral-400">
                {value.rules_status === 'awaiting_signals'
                  ? 'Unregistered signals are permitted if declared below. The pattern is not evaluated until promoted to active.'
                  : 'Draft patterns are never evaluated; unregistered signals are warned, not rejected.'}
              </p>
            )}

            {value.rules_status === 'awaiting_signals' && (
              <div className="mt-3">
                <div className="mb-1 flex items-center justify-between">
                  <p className="text-xs font-medium text-neutral-600">required_signals_pending</p>
                  <button
                    type="button"
                    onClick={() =>
                      set('required_signals_pending', [
                        ...value.required_signals_pending,
                        { signal_name: '', purpose: '', expected_extractor: '', blocking: true },
                      ])
                    }
                    className="text-xs text-violet-600 hover:underline"
                  >
                    + Add pending signal
                  </button>
                </div>
                <div className="space-y-2">
                  {value.required_signals_pending.map((pending, i) => (
                    <PendingSignalRow
                      key={i}
                      pending={pending}
                      onChange={(updated) =>
                        set(
                          'required_signals_pending',
                          value.required_signals_pending.map((existing, j) => (j === i ? updated : existing)),
                        )
                      }
                      onRemove={() => set('required_signals_pending', value.required_signals_pending.filter((_, j) => j !== i))}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>

          <div>
            <SectionHeader title="Rule groups" hint="Part E: all/any/atLeast/metadata gate the match; none applies negative evidence; supporting adds score." />
            <div className="space-y-4">
              <ConditionList title="all — every condition must match" conditions={ruleset.all} registry={registry} onChange={(all) => setRuleset({ ...ruleset, all })} />
              <ConditionList title="any — at least one must match" conditions={ruleset.any} registry={registry} onChange={(any) => setRuleset({ ...ruleset, any })} />
              <AtLeastList groups={ruleset.atLeast} registry={registry} onChange={(atLeast) => setRuleset({ ...ruleset, atLeast })} />
              <SupportingList conditions={ruleset.supporting} registry={registry} onChange={(supporting) => setRuleset({ ...ruleset, supporting })} />
              <NoneList conditions={ruleset.none} registry={registry} onChange={(none) => setRuleset({ ...ruleset, none })} />
              <MetadataList conditions={ruleset.metadata} onChange={(metadata) => setRuleset({ ...ruleset, metadata })} />
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function PendingSignalRow({
  pending,
  onChange,
  onRemove,
}: {
  pending: RequiredSignalPending
  onChange: (p: RequiredSignalPending) => void
  onRemove: () => void
}) {
  return (
    <div className="space-y-1.5 rounded border border-neutral-200 bg-neutral-50 p-2.5">
      <div className="flex items-center gap-2">
        <input type="text" value={pending.signal_name} onChange={(e) => onChange({ ...pending, signal_name: e.target.value })} placeholder="signal_name" className={`${inputClass(false)} flex-1 font-mono text-xs`} />
        <input type="text" value={pending.expected_extractor} onChange={(e) => onChange({ ...pending, expected_extractor: e.target.value })} placeholder="expected_extractor" className={`${inputClass(false)} flex-1 text-xs`} />
        <Checkbox checked={pending.blocking} onChange={(v) => onChange({ ...pending, blocking: v })} label="blocking" />
        <button type="button" onClick={onRemove} className="text-xs text-red-500 hover:underline">Remove</button>
      </div>
      <input type="text" value={pending.purpose} onChange={(e) => onChange({ ...pending, purpose: e.target.value })} placeholder="purpose" className={`${inputClass(false)} w-full text-xs`} />
    </div>
  )
}
