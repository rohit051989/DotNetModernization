import { list, num, str, type Json } from './adapters'

/**
 * Per feed, how many of a scan's packages it holds only unlisted versions of (dependency-assessment 1.9.0,
 * summary.feedListing), and the plain note when a feed reports nearly every version unlisted. Nothing for an older
 * artifact, or when no feed holds anything unlisted.
 */
export function FeedListing({ summary }: { summary: Json }) {
  const feeds = list<Json>(summary.feedListing).filter((f) => num(f.packagesOnlyUnlisted) > 0 || f.mostlyUnlisted === true)
  if (feeds.length === 0) return null
  return (
    <span className="block">
      {feeds.map((f) => (
        <span key={str(f.url)} className="block" title={str(f.url) ?? undefined}>
          <span className="text-neutral-500">
            {str(f.name)}: {num(f.packagesOnlyUnlisted)} of {num(f.packagesAnswered)} package{num(f.packagesAnswered) === 1 ? '' : 's'} only as
            unlisted versions ({num(f.versionsUnlisted)} of {num(f.versionsAnswered)} versions unlisted)
          </span>
          {f.mostlyUnlisted === true && str(f.note) && (
            <span className="mt-0.5 block rounded border border-amber-300 bg-amber-50 px-2 py-1 text-amber-800">{str(f.note)}</span>
          )}
        </span>
      ))}
    </span>
  )
}
