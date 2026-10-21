import { useEffect, useState } from 'react'
import { apiUrl } from '../../api/client'
import { getCatalogExportStatus } from '../../api/items'
import { LimitedList } from '../../components/LimitedList'
import type { CatalogExportChange, CatalogExportStatus } from '../../types/items'

const CHANGE_STYLE: Record<CatalogExportChange['change'], string> = {
  added: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  edited: 'border-amber-200 bg-amber-50 text-amber-800',
  deleted: 'border-red-200 bg-red-50 text-red-700',
}

/** The export link and whether git is behind the database (28-ITEM Part W).
 * Master view only. Never exports: writing into the repository from a web
 * request would couple the server to the working tree, so a person runs the
 * export command and commits. */
export function CatalogExportPanel({ refreshToken, onSelectItem }: { refreshToken: number; onSelectItem: (itemId: string) => void }) {
  const [status, setStatus] = useState<CatalogExportStatus | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    getCatalogExportStatus()
      .then((result) => {
        if (!cancelled) {
          setStatus(result)
          setFailed(false)
        }
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [refreshToken])

  return (
    <div className="mb-3 rounded border border-neutral-200 text-xs">
      <a
        href={apiUrl('/api/catalog/export/items')}
        download="catalog-items.zip"
        title="One YAML file per item — the item, its resolutions and their derivations, soft-deleted rows marked — for review and history in git. Read-only."
        className="block w-full border-b border-neutral-200 py-1.5 text-center font-medium text-neutral-700 hover:bg-neutral-50"
      >
        Export catalog (YAML per item)
      </a>
      <div className="px-2 py-1.5">
        {failed && <p className="text-red-600">Could not check the export.</p>}
        {!failed && !status && <p className="text-neutral-400">Checking the export…</p>}
        {status?.is_current && (
          <p className="text-emerald-700">
            <span className="font-medium">Export is current</span>
            {status.last_export && <span className="text-neutral-500"> · exported {new Date(status.last_export.exported_at).toLocaleString()}</span>}
          </p>
        )}
        {status && !status.is_current && (
          <>
            <p className="font-medium text-amber-800">
              {status.last_export
                ? `${status.changed} item${status.changed === 1 ? '' : 's'} changed since the last export`
                : `No export recorded — ${status.changed} item${status.changed === 1 ? '' : 's'} not in git`}
            </p>
            {status.last_export && (
              <p className="text-neutral-500">last exported {new Date(status.last_export.exported_at).toLocaleString()}</p>
            )}
            <LimitedList items={status.changes} name={(c) => [c.item_id, c.item_name]} noun="changed items" className="mt-1">
              {(visible) => (
                <ul className="space-y-0.5">
                  {visible.map((c) => (
                    <li key={c.item_id} className="flex items-baseline gap-1.5">
                      <span className={`shrink-0 rounded border px-1 text-[10px] ${CHANGE_STYLE[c.change]}`}>{c.change}</span>
                      {c.item_name !== null ? (
                        <button type="button" onClick={() => onSelectItem(c.item_id)} className="truncate text-left text-violet-700 hover:underline" title={c.item_name}>
                          {c.item_id}
                        </button>
                      ) : (
                        <span className="truncate text-neutral-600">{c.item_id}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </LimitedList>
            <p className="mt-1 text-neutral-500">
              Export into the repository and commit (from <span className="font-mono">backend/</span>):
              <code className="mt-0.5 block break-all rounded bg-neutral-100 px-1 py-0.5 font-mono text-[11px] text-neutral-800">
                {status.command}
              </code>
            </p>
          </>
        )}
      </div>
    </div>
  )
}
