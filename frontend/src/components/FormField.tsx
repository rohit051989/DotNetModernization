import type { ReactNode } from 'react'

export function inputClass(hasError: boolean) {
  return `w-full rounded border px-3 py-1.5 text-sm focus:outline-none ${
    hasError ? 'border-red-400 focus:border-red-500' : 'border-neutral-300 focus:border-violet-400'
  }`
}

interface FieldProps {
  label: string
  error?: string
  children: ReactNode
}

export function Field({ label, error, children }: FieldProps) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-neutral-600">{label}</label>
      {children}
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  )
}
