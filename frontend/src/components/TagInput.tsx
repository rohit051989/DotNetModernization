import { useState, type KeyboardEvent } from 'react'

interface TagInputProps {
  label: string
  values: string[]
  onChange: (values: string[]) => void
  placeholder?: string
}

export function TagInput({ label, values, onChange, placeholder }: TagInputProps) {
  const [draft, setDraft] = useState('')

  function commitDraft() {
    const trimmed = draft.trim()
    if (trimmed && !values.includes(trimmed)) {
      onChange([...values, trimmed])
    }
    setDraft('')
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault()
      commitDraft()
    } else if (event.key === 'Backspace' && draft === '' && values.length > 0) {
      onChange(values.slice(0, -1))
    }
  }

  function removeAt(index: number) {
    onChange(values.filter((_, i) => i !== index))
  }

  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-neutral-600">{label}</label>
      <div className="flex flex-wrap items-center gap-1.5 rounded border border-neutral-300 p-1.5 focus-within:border-violet-400">
        {values.map((value, index) => (
          <span
            key={`${value}-${index}`}
            className="flex items-center gap-1 rounded bg-neutral-100 px-2 py-0.5 text-xs text-neutral-700"
          >
            {value}
            <button
              type="button"
              onClick={() => removeAt(index)}
              aria-label={`Remove ${value}`}
              className="text-neutral-400 hover:text-neutral-700"
            >
              ✕
            </button>
          </span>
        ))}
        <input
          type="text"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={commitDraft}
          placeholder={values.length === 0 ? placeholder : ''}
          className="min-w-[120px] flex-1 border-none text-sm outline-none"
        />
      </div>
    </div>
  )
}
