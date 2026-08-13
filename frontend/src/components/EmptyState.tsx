interface EmptyStateProps {
  title: string
  description?: string
  action?: { label: string; onClick: () => void }
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 p-10 text-center">
      <p className="text-sm font-medium text-neutral-700">{title}</p>
      {description && <p className="text-sm text-neutral-400">{description}</p>}
      {action && (
        <button
          type="button"
          onClick={action.onClick}
          className="mt-2 text-sm font-medium text-violet-600 hover:text-violet-700"
        >
          {action.label}
        </button>
      )}
    </div>
  )
}
