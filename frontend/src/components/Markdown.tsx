import type { ReactNode } from 'react'

const INLINE_PATTERN = /(\*\*[^*]+\*\*|`[^`]+`)/g

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const parts: ReactNode[] = []
  let lastIndex = 0
  let index = 0
  let match: RegExpExecArray | null

  while ((match = INLINE_PATTERN.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index))
    }
    const token = match[0]
    if (token.startsWith('**')) {
      parts.push(<strong key={`${keyPrefix}-${index++}`}>{token.slice(2, -2)}</strong>)
    } else {
      parts.push(
        <code key={`${keyPrefix}-${index++}`} className="rounded bg-neutral-100 px-1 py-0.5 text-[0.85em]">
          {token.slice(1, -1)}
        </code>,
      )
    }
    lastIndex = INLINE_PATTERN.lastIndex
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }
  return parts
}

type ListBuffer = { type: 'ul' | 'ol'; items: string[] } | null

/** Minimal, dependency-free renderer for the small subset of markdown used in
 * the catalog (headings, numbered/bulleted lists, bold, inline code). */
export function Markdown({ text }: { text: string }) {
  const lines = text.split('\n')
  const blocks: ReactNode[] = []
  let listBuffer: ListBuffer = null
  let paragraphBuffer: string[] = []
  let blockSeq = 0

  function nextKey(): string {
    return `b-${blockSeq++}`
  }

  function flushParagraph() {
    if (paragraphBuffer.length > 0) {
      const key = nextKey()
      blocks.push(
        <p key={key} className="mb-2 last:mb-0">
          {renderInline(paragraphBuffer.join(' '), key)}
        </p>,
      )
      paragraphBuffer = []
    }
  }

  function flushList() {
    if (listBuffer) {
      const { type, items } = listBuffer
      const key = nextKey()
      blocks.push(
        type === 'ul' ? (
          <ul key={key} className="mb-2 list-disc pl-5">
            {items.map((item, idx) => (
              <li key={idx}>{renderInline(item, `${key}-${idx}`)}</li>
            ))}
          </ul>
        ) : (
          <ol key={key} className="mb-2 list-decimal pl-5">
            {items.map((item, idx) => (
              <li key={idx}>{renderInline(item, `${key}-${idx}`)}</li>
            ))}
          </ol>
        ),
      )
      listBuffer = null
    }
  }

  lines.forEach((rawLine) => {
    const line = rawLine.trim()

    if (line === '') {
      flushParagraph()
      flushList()
      return
    }

    const headingMatch = /^#{1,4}\s+(.*)$/.exec(line)
    if (headingMatch) {
      flushParagraph()
      flushList()
      blocks.push(
        <h4 key={nextKey()} className="mb-1 mt-3 text-sm font-semibold text-neutral-800 first:mt-0">
          {headingMatch[1]}
        </h4>,
      )
      return
    }

    const orderedMatch = /^\d+\.\s+(.*)$/.exec(line)
    if (orderedMatch) {
      flushParagraph()
      if (!listBuffer || listBuffer.type !== 'ol') {
        flushList()
        listBuffer = { type: 'ol', items: [] }
      }
      listBuffer.items.push(orderedMatch[1])
      return
    }

    const bulletMatch = /^[-*]\s+(.*)$/.exec(line)
    if (bulletMatch) {
      flushParagraph()
      if (!listBuffer || listBuffer.type !== 'ul') {
        flushList()
        listBuffer = { type: 'ul', items: [] }
      }
      listBuffer.items.push(bulletMatch[1])
      return
    }

    flushList()
    paragraphBuffer.push(line)
  })

  flushParagraph()
  flushList()

  return <div className="text-sm leading-relaxed text-neutral-700">{blocks}</div>
}
