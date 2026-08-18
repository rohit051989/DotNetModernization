import { useState } from 'react'

export function CopyButton({ value, label = 'Copy' }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard access can be denied by the browser; nothing useful to do.
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="rounded border border-neutral-200 px-1.5 py-0.5 text-[10px] font-medium text-neutral-500 hover:bg-neutral-50"
      title={value}
    >
      {copied ? 'Copied' : label}
    </button>
  )
}
