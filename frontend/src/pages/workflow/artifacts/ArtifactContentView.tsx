import { useEffect, useState } from 'react'
import { ApiError } from '../../../api/client'
import { artifactDownloadUrl, getArtifactContent } from '../../../api/workflow'
import { JsonTreeView } from '../../../components/JsonTreeView'
import { rendererFor } from './registry'
import type { Json } from './adapters'

type ContentState =
  | { kind: 'loading' }
  | { kind: 'json'; data: unknown }
  | { kind: 'too_large' }
  | { kind: 'not_json' }
  | { kind: 'mismatch'; message: string }
  | { kind: 'missing'; message: string }
  | { kind: 'error'; message: string }

/** Loads an artifact's content, reporting the failure modes the content
 * endpoint distinguishes (too large, not JSON, checksum mismatch, missing). */
export function useArtifactContent(artifactId: string): ContentState {
  const [content, setContent] = useState<ContentState>({ kind: 'loading' })
  useEffect(() => {
    let cancelled = false
    setContent({ kind: 'loading' })
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
  return content
}

interface ArtifactContentViewProps {
  artifactId: string
  artifactType: string
  localPath: string | null
  /** Taller JSON area in the drawer than inline in the timeline. */
  jsonMaxHeight?: string
}

/** An artifact's readable view (from the renderer registry) with the raw
 * JSON one toggle away; JSON only when no renderer exists. */
export function ArtifactContentView({ artifactId, artifactType, localPath, jsonMaxHeight = '24rem' }: ArtifactContentViewProps) {
  const content = useArtifactContent(artifactId)
  const Renderer = rendererFor(artifactType)
  const [mode, setMode] = useState<'readable' | 'json'>(Renderer ? 'readable' : 'json')
  const [plainText, setPlainText] = useState(false)

  if (content.kind === 'loading') return <p className="text-xs text-neutral-400">Loading…</p>
  if (content.kind === 'too_large' || content.kind === 'not_json') {
    return (
      <p className="text-xs text-neutral-500">
        {content.kind === 'too_large' ? 'Too large to show inline.' : 'Not JSON, so it cannot be shown inline.'}{' '}
        <a href={artifactDownloadUrl(artifactId)} className="text-violet-600 hover:underline">
          Download
        </a>
      </p>
    )
  }
  if (content.kind === 'mismatch') return <p className="text-xs text-red-700">Checksum mismatch: {content.message}</p>
  if (content.kind === 'missing') return <p className="text-xs text-amber-700">File missing on disk: {content.message}</p>
  if (content.kind === 'error') return <p className="text-xs text-red-600">{content.message}</p>

  const isObject = content.data !== null && typeof content.data === 'object' && !Array.isArray(content.data)
  const readable = Renderer && isObject

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex overflow-hidden rounded border border-neutral-300 text-[11px]" role="group" aria-label="View">
          <button
            type="button"
            disabled={!readable}
            onClick={() => setMode('readable')}
            className={`px-2 py-0.5 ${mode === 'readable' && readable ? 'bg-violet-600 text-white' : 'text-neutral-600 hover:bg-neutral-50'} disabled:cursor-not-allowed disabled:text-neutral-300`}
            title={readable ? undefined : `No readable view for ${artifactType} yet`}
          >
            Readable
          </button>
          <button
            type="button"
            onClick={() => setMode('json')}
            className={`border-l border-neutral-300 px-2 py-0.5 ${mode === 'json' || !readable ? 'bg-violet-600 text-white' : 'text-neutral-600 hover:bg-neutral-50'}`}
          >
            JSON
          </button>
        </div>
        {(mode === 'json' || !readable) && (
          <button type="button" onClick={() => setPlainText((v) => !v)} className="text-[11px] text-violet-600 hover:underline">
            {plainText ? 'Tree view' : 'Plain text'}
          </button>
        )}
        {!Renderer && <span className="text-[11px] text-neutral-400">No readable view for {artifactType} yet.</span>}
      </div>
      {mode === 'readable' && readable ? (
        <Renderer data={content.data as Json} localPath={localPath} />
      ) : (
        <div className="overflow-auto rounded border border-neutral-200 bg-neutral-50 p-3" style={{ maxHeight: jsonMaxHeight }}>
          {plainText ? (
            <pre className="whitespace-pre-wrap font-mono text-xs text-neutral-700">{JSON.stringify(content.data, null, 2)}</pre>
          ) : (
            <JsonTreeView value={content.data} />
          )}
        </div>
      )}
    </div>
  )
}
