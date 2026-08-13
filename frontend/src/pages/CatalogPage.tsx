interface CatalogPageProps {
  engagementId: string | null
}

export function CatalogPage({ engagementId }: CatalogPageProps) {
  return (
    <div className="flex h-full items-center justify-center p-12 text-center">
      <div>
        <p className="text-sm font-medium text-neutral-500">Catalog</p>
        <p className="mt-1 text-neutral-400">
          Pattern list and detail view are not built yet.
          {engagementId && (
            <>
              {' '}
              Selected engagement: <span className="font-mono">{engagementId}</span>
            </>
          )}
        </p>
      </div>
    </div>
  )
}
