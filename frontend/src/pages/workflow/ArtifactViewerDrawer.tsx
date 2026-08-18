import { useEffect, useState } from 'react'
import { Drawer } from '../../components/Drawer'
import { CopyButton } from '../../components/CopyButton'
import { JsonTreeView } from '../../components/JsonTreeView'
import { ApiError } from '../../api/client'
import { artifactDownloadUrl, getArtifact, getArtifactContent } from '../../api/workflow'
import type { ArtifactDetail } from '../../types/workflow'

function formatSize(bytes: number | null): string {
  if (bytes === null) return '—'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`
}

interface ArtifactViewerDrawerProps {
  artifactId: string
  onClose: () => void
}

type ContentState =
  | { kind: 'loading' }
  | { kind: 'json'; data: unknown }
  | { kind: 'too_large' }
  | { kind: 'not_json' }
  | { kind: 'mismatch'; message: string }
  | { kind: 'missing'; message: string }
  | { kind: 'error'; message: string }

export function ArtifactViewerDrawer({ artifactId, onClose }: ArtifactViewerDrawerProps) {
  const [detail, setDetail] = useState<ArtifactDetail | null>(null)
  const [content, setContent] = useState<ContentState>({ kind: 'loading' })
  const [plainText, setPlainText] = useState(false)

  useEffect(() => {
    let cancelled = false
    getArtifact(artifactId)
      .then((result) => {
        if (!cancelled) setDetail(result)
      })
      .catch(() => {
        if (!cancelled) setDetail(null)
      })

    getArtifactContent(artifactId)
      .then((data) => {
        if (!cancelled) setContent({ kind: 'json', data })
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError) {
          if (err.status === 413) setContent({ kind: 'too_large' })
          else if (err.status === 415) setContent({ kind: 'not_json' })
          else if (err.status === 409) setContent({ kind: 'mismatch', message: err.message })
          else if (err.status === 404) setContent({ kind: 'missing', message: err.message })
          else setContent({ kind: 'error', message: err.message })
        } else {
          setContent({ kind: 'error', message: 'Could not load this artifact.' })
        }
      })
    return () => {
      cancelled = true
    }
  }, [artifactId])

  async function handleCopyAll() {
    if (content.kind !== 'json') return
    await navigator.clipboard.writeText(JSON.stringify(content.data, null, 2))
  }

  return (
    <Drawer title={detail ? `${detail.artifact_type}@${detail.artifact_version}` : 'Artifact'} onRequestClose={onClose}>
      {!detail && content.kind === 'loading' && <p className="text-sm text-neutral-400">Loading…</p>}

      {detail && (
        <div className="mb-4 space-y-1.5 rounded border border-neutral-200 bg-neutral-50 p-3 text-xs text-neutral-600">
          <p>
            Size: <span className="font-medium text-neutral-800">{formatSize(detail.size_bytes)}</span>
          </p>
          <p className="flex items-center gap-1.5">
            Checksum: <span className="truncate font-mono text-neutral-500">{detail.checksum}</span>
            <CopyButton value={detail.checksum} />
          </p>
          <p>
            Produced by <span className="font-medium text-neutral-800">{detail.step_name}</span> at{' '}
            {new Date(detail.created_at).toLocaleString()}
          </p>
          {!detail.file_exists && (
            <p className="font-medium text-amber-600">
              The file backing this artifact is missing on disk. The run directory may have been cleaned up.
            </p>
          )}
        </div>
      )}

      {content.kind === 'json' && (
        <div className="space-y-2">
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setPlainText((v) => !v)}
              className="rounded border border-neutral-300 px-2 py-1 text-xs text-neutral-600 hover:bg-neutral-50"
            >
              {plainText ? 'Tree view' : 'Plain text'}
            </button>
            <button
              type="button"
              onClick={handleCopyAll}
              className="rounded border border-neutral-300 px-2 py-1 text-xs text-neutral-600 hover:bg-neutral-50"
            >
              Copy all
            </button>
            <a
              href={artifactDownloadUrl(artifactId)}
              className="rounded bg-violet-600 px-2 py-1 text-xs font-medium text-white hover:bg-violet-700"
            >
              Download
            </a>
          </div>
          <div className="max-h-[60vh] overflow-auto rounded border border-neutral-200 bg-neutral-50 p-3">
            {plainText ? (
              <pre className="whitespace-pre-wrap font-mono text-xs text-neutral-700">{JSON.stringify(content.data, null, 2)}</pre>
            ) : (
              <JsonTreeView value={content.data} />
            )}
          </div>
        </div>
      )}

      {(content.kind === 'too_large' || content.kind === 'not_json') && (
        <div className="space-y-3 rounded border border-neutral-200 bg-neutral-50 p-4 text-sm text-neutral-600">
          <p>
            {content.kind === 'too_large'
              ? 'This artifact is too large to view inline.'
              : 'This artifact is not JSON, so it cannot be viewed inline.'}
          </p>
          <a
            href={artifactDownloadUrl(artifactId)}
            className="inline-block rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700"
          >
            Download instead
          </a>
        </div>
      )}

      {content.kind === 'mismatch' && (
        <div className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          <p className="font-medium">Checksum mismatch</p>
          <p className="mt-1">{content.message}</p>
        </div>
      )}

      {content.kind === 'missing' && (
        <div className="rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-700">
          <p className="font-medium">File missing on disk</p>
          <p className="mt-1">{content.message}</p>
        </div>
      )}

      {content.kind === 'error' && <p className="text-sm text-red-600">{content.message}</p>}
    </Drawer>
  )
}
