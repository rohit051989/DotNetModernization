import { useEffect, useState } from 'react'
import { getExtractorBacklog, getItemCoverage, getSignalCoverage } from '../../api/items'
import { getEntryPointCapabilities } from '../../api/surface'
import type { ExtractorBacklog, ItemCoverage, SignalCoverage } from '../../types/items'
import type { EntryPointCapabilities } from '../../types/surface'

/**
 * What the platform can see, declared — so the absence of a finding is
 * interpretable. Step 3's side is extractor readiness (a catalog item whose
 * signals no extractor produces is not ready, not "absent"); step 4's side
 * is its capability manifest (a kind listed was looked for; a pattern under
 * "not covered" was not).
 */
export function DetectionCapabilitiesSection() {
  const [manifest, setManifest] = useState<EntryPointCapabilities | null>(null)
  const [backlog, setBacklog] = useState<ExtractorBacklog | null>(null)
  const [items, setItems] = useState<ItemCoverage | null>(null)
  const [signals, setSignals] = useState<SignalCoverage | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([getEntryPointCapabilities(), getExtractorBacklog(), getItemCoverage(), getSignalCoverage()])
      .then(([m, b, i, s]) => {
        if (cancelled) return
        setManifest(m)
        setBacklog(b)
        setItems(i)
        setSignals(s)
      })
      .catch(() => {
        if (!cancelled) setError('Could not load detection capabilities.')
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (error) return <p className="text-sm text-red-600">{error}</p>
  if (!manifest || !backlog || !items || !signals) return <p className="text-sm text-neutral-400">Loading detection capabilities…</p>

  const found = manifest.kinds.filter((k) => k.found_in_estate > 0).length

  return (
    <div className="space-y-4">
      <p className="text-sm text-neutral-500">
        What each detecting step declares it can see. A kind or signal listed here was looked for, so finding none of it is a result;
        anything not listed was not looked for, so its absence means nothing.
      </p>

      <div className="grid gap-4 lg:grid-cols-3">
        <section className="rounded border border-neutral-200 bg-white p-4">
          <h3 className="text-sm font-semibold text-neutral-900">Signal extractors — step 3</h3>
          <p className="mt-0.5 text-xs text-neutral-400">Extractor readiness decides which catalog items can be detected at all.</p>
          <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
            <div className="rounded bg-neutral-50 px-3 py-2">
              <dt className="text-xs text-neutral-400">Catalog items ready</dt>
              <dd className="text-lg font-semibold text-emerald-700">{items.ready_count}</dd>
            </div>
            <div className="rounded bg-neutral-50 px-3 py-2">
              <dt className="text-xs text-neutral-400">Not ready</dt>
              <dd className={`text-lg font-semibold ${items.not_ready_count ? 'text-amber-700' : 'text-neutral-400'}`}>{items.not_ready_count}</dd>
            </div>
            <div className="col-span-2 rounded bg-neutral-50 px-3 py-2">
              <dt className="text-xs text-neutral-400">Ready signals referenced by an item</dt>
              <dd className="text-lg font-semibold text-neutral-900">
                {signals.referenced_ready_count}
                <span className="text-sm font-normal text-neutral-400"> / {signals.ready_signal_count}</span>
              </dd>
            </div>
          </dl>
          <h4 className="mt-4 text-xs font-semibold uppercase tracking-wide text-neutral-400">Extractor backlog</h4>
          {backlog.entries.length === 0 ? (
            <p className="mt-1 text-xs text-neutral-500">Nothing blocked: every active catalog item's signals have an implemented extractor.</p>
          ) : (
            <ul className="mt-1 space-y-1 text-xs">
              {backlog.entries.map((e) => (
                <li key={e.expected_extractor ?? '(none)'} className="flex justify-between gap-2">
                  <span className="font-mono text-neutral-700">{e.expected_extractor ?? 'no extractor declared'}</span>
                  <span className="text-neutral-400">blocks {e.items_blocked.length}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-[11px] text-neutral-400">Full backlog and signal index: Catalog → Extractor backlog &amp; coverage.</p>
        </section>

        <section className="rounded border border-neutral-200 bg-white p-4 lg:col-span-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold text-neutral-900">Entry-point kinds — step 4</h3>
            <span className="text-xs text-neutral-400">
              capability manifest {manifest.manifest_version} · scanner {manifest.scanner_version} · {manifest.repositories_on_this_manifest} of{' '}
              {manifest.repositories_scanned} repositories scanned on it
            </span>
          </div>
          <p className="mt-0.5 text-xs text-neutral-400">
            {manifest.kinds.length} kinds detected; {found} found somewhere in the estate.
          </p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-neutral-400">
                <tr className="border-b border-neutral-200">
                  <th className="py-1.5 pr-3 font-medium">Kind</th>
                  <th className="py-1.5 pr-3 font-medium">Detects</th>
                  <th className="py-1.5 pr-3 font-medium">Class</th>
                  <th className="py-1.5 pr-3 font-medium">Authentication</th>
                  <th className="py-1.5 pr-3 font-medium">Since</th>
                  <th className="py-1.5 text-right font-medium">Found</th>
                </tr>
              </thead>
              <tbody>
                {manifest.kinds.map((k) => (
                  <tr key={k.kind} className="border-b border-neutral-100 align-top">
                    <td className="py-1.5 pr-3">
                      <p className="font-medium text-neutral-800">{k.label}</p>
                      <p className="font-mono text-[10px] text-neutral-400">{k.kind}</p>
                    </td>
                    <td className="py-1.5 pr-3 text-neutral-600" title={k.identified_by}>
                      {k.detects}
                    </td>
                    <td className="py-1.5 pr-3 text-neutral-500">{k.entry_class}</td>
                    <td className="py-1.5 pr-3 text-neutral-500">{k.auth_declared}</td>
                    <td className="py-1.5 pr-3 whitespace-nowrap text-neutral-500">{k.added_in}</td>
                    <td className="py-1.5 text-right whitespace-nowrap">
                      {k.found_in_estate > 0 ? (
                        <span className="text-neutral-800">
                          {k.found_in_estate} <span className="text-neutral-400">in {k.repositories_with_kind}</span>
                        </span>
                      ) : (
                        <span className="text-neutral-300" title="Looked for in every scan on this manifest; none found">
                          none found
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h4 className="mt-4 text-xs font-semibold uppercase tracking-wide text-neutral-400">
            Not covered — not looked for, so absence means nothing
          </h4>
          <ul className="mt-1 grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
            {manifest.not_covered.map((p) => (
              <li key={p.pattern} title={p.note || undefined}>
                <span className="text-neutral-700">{p.pattern}</span>
                <span className="text-neutral-400"> — {p.marker}</span>
              </li>
            ))}
          </ul>

          <p className="mt-3 rounded border border-amber-100 bg-amber-50/60 px-2 py-1.5 text-[11px] text-amber-900">{manifest.auth_declared_scope}</p>
        </section>
      </div>
    </div>
  )
}
