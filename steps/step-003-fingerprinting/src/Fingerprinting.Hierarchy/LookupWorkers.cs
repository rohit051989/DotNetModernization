using System.Collections.Concurrent;
using Fingerprinting.Dependencies;

namespace Fingerprinting.Hierarchy;

/// <summary>
/// Several package lookups at once (37-DEPENDENCY-HIERARCHY.md Part B6). A cold lookup cache costs a feed round trip
/// per package, and a repository's package closure runs to hundreds of packages: asked one at a time that is minutes.
/// Before the graph walk follows a node's dependencies, their lookups are made together here, at most
/// <c>lookup_concurrency</c> at a time, and the walk then reads the answers from the cache. Each worker is its own
/// <see cref="PackageLookup"/> and is used by one task at a time; they share one <see cref="SynchronizedLookupCache"/>.
/// </summary>
public sealed class LookupWorkers(IReadOnlyList<PackageLookup> lookups)
{
    public int Count => lookups.Count;

    public async Task ForEachAsync(IReadOnlyList<string> packageIds, Func<PackageLookup, string, Task> work)
    {
        var queue = new ConcurrentQueue<string>(packageIds);
        await Task.WhenAll(lookups.Select(async lookup =>
        {
            while (queue.TryDequeue(out var id)) await work(lookup, id);
        }));
    }
}

/// <summary>A lookup cache safe to share between the workers: every read and write takes one lock.</summary>
public sealed class SynchronizedLookupCache(ILookupCache inner) : ILookupCache
{
    private readonly Lock _gate = new();

    public CacheEntry? Get(string feedUrl, string packageId)
    {
        lock (_gate) return inner.Get(feedUrl, packageId);
    }

    public void Put(CacheEntry entry)
    {
        lock (_gate) inner.Put(entry);
    }
}
