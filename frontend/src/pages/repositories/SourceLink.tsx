import type { ReactNode } from 'react'
import { sourceHref } from './sourceHref'

/** A link that opens the file in VS Code — or, with no local path to
 * resolve it against (an artifact viewed outside its repository), the
 * same text without a link. */
export function SourceLink({
  localPath,
  filePath,
  line,
  className,
  title,
  children,
}: {
  localPath: string | null | undefined
  filePath: string
  line: number
  className?: string
  title?: string
  children: ReactNode
}) {
  if (!localPath) {
    return (
      <span className={className} title={title ?? `${filePath}:${line}`}>
        {children}
      </span>
    )
  }
  return (
    <a href={sourceHref(localPath, filePath, line)} className={`${className ?? ''} hover:underline`} title={title ?? filePath}>
      {children}
    </a>
  )
}
