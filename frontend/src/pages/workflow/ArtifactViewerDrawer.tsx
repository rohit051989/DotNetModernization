import { useEffect, useState } from 'react'
import { Drawer } from '../../components/Drawer'
import { CopyButton } from '../../components/CopyButton'
import { artifactDownloadUrl, getArtifact } from '../../api/workflow'
import { ArtifactContentView } from './artifacts/ArtifactContentView'
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
  /** For source links in the readable view. */
  localPath?: string | null
  onClose: () => void
}

export function ArtifactViewerDrawer({ artifactId, localPath = null, onClose }: ArtifactViewerDrawerProps) {
  const [detail, setDetail] = useState<ArtifactDetail | null>(null)

  useEffect(() => {
    let cancelled = false
    getArtifact(artifactId)
      .then((result) => {
        if (!cancelled) setDetail(result)
      })
      .catch(() => {
        if (!cancelled) setDetail(null)
      })
    return () => {
      cancelled = true
    }
  }, [artifactId])

  return (
    <Drawer title={detail ? `${detail.artifact_type}@${detail.artifact_version}` : 'Artifact'} onRequestClose={onClose}>
      {!detail && <p className="text-sm text-neutral-400">Loading…</p>}

      {detail && (
        <>
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
            {!detail.file_exists && detail.in_database && (
              <p className="text-neutral-600">
                {detail.held_on ? `Its file is ${detail.held_on}; ` : 'Its file is not on this machine; '}this is the copy kept in the database.
              </p>
            )}
            {!detail.file_exists && !detail.in_database && detail.held_on && (
              <p className="font-medium text-neutral-700">
                This artifact is {detail.held_on}: only the results the views read are kept in the database, and this is not one of them.
              </p>
            )}
            {!detail.file_exists && !detail.in_database && !detail.held_on && (
              <p className="font-medium text-amber-600">
                The file backing this artifact is missing on disk. The run directory may have been cleaned up.
              </p>
            )}
            {(detail.file_exists || detail.in_database) && (
              <a href={artifactDownloadUrl(artifactId)} className="inline-block font-medium text-violet-600 hover:underline">
                Download
              </a>
            )}
          </div>
          <ArtifactContentView artifactId={artifactId} artifactType={detail.artifact_type} localPath={localPath} jsonMaxHeight="60vh" />
        </>
      )}
    </Drawer>
  )
}
