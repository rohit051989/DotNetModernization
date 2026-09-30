import { Fragment } from 'react'

// After an underscore, or between a lowercase letter and a capital.
const BREAK_POINTS = /(?<=_)|(?<=[a-z])(?=[A-Z])/

/** An identifier that wraps at word boundaries rather than mid-token:
 * MICROSOFT_EXTENSIONS_HOSTING_WINDOWSSERVICES_PACKAGE breaks after each `_`,
 * ConfigurationExtractor before `Extractor`. `break-words` is only the last
 * resort for a single token wider than its container. */
export function IdentifierText({ name }: { name: string }) {
  const parts = name.split(BREAK_POINTS)
  return (
    <span className="break-words">
      {parts.map((part, index) => (
        <Fragment key={index}>
          {index > 0 && <wbr />}
          {part}
        </Fragment>
      ))}
    </span>
  )
}
