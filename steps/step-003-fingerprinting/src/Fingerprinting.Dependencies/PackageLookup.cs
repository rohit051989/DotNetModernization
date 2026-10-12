using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using NuGet.Common;
using NuGet.Frameworks;
using NuGet.Packaging;
using NuGet.Protocol;
using NuGet.Protocol.Core.Types;
using NuGet.Versioning;

namespace Fingerprinting.Dependencies;

/// <summary>A feed's answer for one package: the entry, or why there is none.</summary>
public sealed record LookupResult(CacheEntry? Entry, string? Error)
{
    public bool Reachable => Error is null;
}

/// <summary>
/// Deterministic version lookup through the NuGet protocol (Part B1) — no
/// guessing, no model. Metadata goes into the lookup cache; package files
/// are downloaded only into <see cref="PackageCacheDirectory"/>, outside every
/// repository (Part B5). Nothing is restored, nothing is written beside a
/// project.
/// </summary>
public sealed partial class PackageLookup(ILookupCache cache, string packageCacheDirectory, TimeSpan ttl, bool forceRefresh, DateTimeOffset now)
{
    private readonly SourceCacheContext _sourceCache = new() { NoCache = true, DirectDownload = true };
    private readonly Dictionary<string, SourceRepository> _repositories = new(StringComparer.Ordinal);
    private readonly HashSet<string> _refreshed = new(StringComparer.Ordinal);

    public string PackageCacheDirectory => packageCacheDirectory;

    /// <summary>The fetched_at of every cache entry this run read or wrote —
    /// its minimum is the snapshot the artifact is true as of (Part B6).</summary>
    public List<DateTimeOffset> SnapshotTimes { get; } = [];

    [GeneratedRegex(@"[A-Za-z][A-Za-z0-9+.\-]*://[^\s'""]+")]
    private static partial Regex UrlPattern();

    private SourceRepository RepositoryFor(Feed feed)
    {
        if (!_repositories.TryGetValue(feed.Url, out var repository))
        {
            repository = Repository.Factory.GetCoreV3(feed.Source);
            _repositories[feed.Url] = repository;
        }

        return repository;
    }

    /// <summary>A protocol error, with any URL in it normalised — an
    /// exception message must not carry a credential into the artifact.</summary>
    private static string Describe(Feed feed, Exception ex)
    {
        var message = ex.InnerException?.Message ?? ex.Message;
        message = UrlPattern().Replace(message, m => FeedResolver.NormaliseUrl(m.Value.TrimEnd('.', ','), Path.GetPathRoot(Path.GetTempPath())!));
        return $"feed '{feed.Name}' could not be reached: {message.Trim()}";
    }

    public async Task<LookupResult> GetAsync(Feed feed, string packageId, CancellationToken ct)
    {
        var key = $"{feed.Url}|{packageId.ToLowerInvariant()}";
        var cached = cache.Get(feed.Url, packageId);
        if (cached is not null && (_refreshed.Contains(key) || (!forceRefresh && now - cached.FetchedAt < ttl)))
        {
            SnapshotTimes.Add(cached.FetchedAt);
            return new LookupResult(cached, null);
        }

        try
        {
            var resource = await RepositoryFor(feed).GetResourceAsync<PackageMetadataResource>(ct);
            var metadata = await resource.GetMetadataAsync(packageId, includePrerelease: true, includeUnlisted: false, _sourceCache, NullLogger.Instance, ct);
            var versions = new List<CachedVersion>();
            foreach (var item in metadata.OrderByDescending(m => m.Identity.Version))
            {
                var deprecation = await item.GetDeprecationMetadataAsync();
                versions.Add(new CachedVersion
                {
                    Version = item.Identity.Version.ToNormalizedString(),
                    Listed = item.IsListed,
                    DependencyFrameworks = (item.DependencySets ?? [])
                        .Select(g => g.TargetFramework.GetShortFolderName())
                        .Distinct(StringComparer.OrdinalIgnoreCase)
                        .Order(StringComparer.OrdinalIgnoreCase)
                        .ToList(),
                    Dependencies = CachedDependencyGroup.From(item.DependencySets),
                    Deprecation = deprecation is null
                        ? null
                        : new CachedDeprecation
                        {
                            Reasons = (deprecation.Reasons ?? []).Order(StringComparer.Ordinal).ToList(),
                            Message = deprecation.Message,
                            AlternateId = deprecation.AlternatePackage?.PackageId,
                            AlternateRange = deprecation.AlternatePackage?.Range?.ToNormalizedString(),
                        },
                    Vulnerabilities = (item.Vulnerabilities ?? [])
                        .Select(v => new CachedVulnerability { Severity = v.Severity, AdvisoryUrl = v.AdvisoryUrl?.ToString() ?? "" })
                        .OrderBy(v => v.AdvisoryUrl, StringComparer.Ordinal)
                        .ToList(),
                });
            }

            var entry = new CacheEntry { FeedUrl = feed.Url, PackageId = packageId.ToLowerInvariant(), FetchedAt = now, Versions = versions };
            cache.Put(entry);
            _refreshed.Add(key);
            SnapshotTimes.Add(now);
            return new LookupResult(entry, null);
        }
        catch (Exception ex) when (ex is FatalProtocolException or HttpRequestException or TaskCanceledException or IOException or InvalidOperationException)
        {
            return new LookupResult(null, Describe(feed, ex));
        }
    }

    /// <summary>
    /// The frameworks one version supports: its dependency groups when it
    /// declares any; otherwise its lib/ and ref/ folders, read from the package
    /// (downloaded to the cache once and remembered in the cache entry).
    /// </summary>
    public async Task<IReadOnlyList<NuGetFramework>?> FrameworksAsync(Feed feed, CacheEntry entry, CachedVersion version, CancellationToken ct)
    {
        if (version.DependencyFrameworks.Count > 0)
        {
            return version.DependencyFrameworks.Select(NuGetFramework.Parse).ToList();
        }

        return await AssetFrameworksAsync(feed, entry, version, ct);
    }

    /// <summary>
    /// The frameworks of the package's lib/ and ref/ folders — what restore
    /// actually checks. Used directly when there are no dependency groups,
    /// and as the second opinion when the dependency groups look incompatible:
    /// an MSBuild-targets package can declare a net472 dependency group and
    /// still install anywhere, because it ships no compile-time assemblies.
    /// </summary>
    public async Task<IReadOnlyList<NuGetFramework>?> AssetFrameworksAsync(Feed feed, CacheEntry entry, CachedVersion version, CancellationToken ct)
    {
        if (version.LibFrameworks is null)
        {
            var path = await DownloadAsync(feed, entry.PackageId, version.Version, ct);
            if (path is null) return null;
            using var reader = new PackageArchiveReader(path);
            var frameworks = reader.GetLibItems().Concat(reader.GetReferenceItems())
                .Select(g => g.TargetFramework.GetShortFolderName())
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .Order(StringComparer.OrdinalIgnoreCase)
                .ToList();
            // Re-read: another project may have filled a different version since.
            entry = cache.Get(entry.FeedUrl, entry.PackageId) ?? entry;
            var updated = entry.Versions.Select(v => v.Version == version.Version ? v with { LibFrameworks = frameworks } : v).ToList();
            entry = entry with { Versions = updated };
            cache.Put(entry);
            version = updated.First(v => v.Version == version.Version);
        }

        return version.LibFrameworks!.Select(NuGetFramework.Parse).ToList();
    }

    /// <summary>
    /// The package kind (<see cref="PackageKinds"/>) from the nupkg's own
    /// file list and nuspec dependencies, read once and remembered in the
    /// lookup cache, so a rerun against the same cache classifies identically.
    /// Null when the package cannot be downloaded.
    /// </summary>
    public async Task<string?> KindAsync(Feed feed, CacheEntry entry, CachedVersion version, CancellationToken ct)
    {
        if (version.Kind is not null) return version.Kind;
        var path = await DownloadAsync(feed, entry.PackageId, version.Version, ct);
        if (path is null) return null;

        string kind;
        using (var reader = new PackageArchiveReader(path))
        {
            var hasDependencies = reader.GetPackageDependencies().Any(g => g.Packages.Any());
            kind = PackageKinds.Classify(reader.GetFiles(), hasDependencies);
        }

        entry = cache.Get(entry.FeedUrl, entry.PackageId) ?? entry;
        cache.Put(entry with { Versions = entry.Versions.Select(v => v.Version == version.Version ? v with { Kind = kind } : v).ToList() });
        return kind;
    }

    /// <summary>
    /// One version's nuspec dependency groups. Read from feed metadata when
    /// the entry was fetched; for an entry cached before dependencies were
    /// recorded, from the nupkg's nuspec, once, and remembered in the cache.
    /// Null when the package cannot be downloaded.
    /// </summary>
    public async Task<IReadOnlyList<CachedDependencyGroup>?> DependenciesAsync(Feed feed, CacheEntry entry, CachedVersion version, CancellationToken ct)
    {
        if (version.Dependencies is not null) return version.Dependencies;
        var path = await DownloadAsync(feed, entry.PackageId, version.Version, ct);
        if (path is null) return null;

        IReadOnlyList<CachedDependencyGroup> groups;
        using (var reader = new PackageArchiveReader(path))
        {
            groups = CachedDependencyGroup.From(reader.GetPackageDependencies());
        }

        entry = cache.Get(entry.FeedUrl, entry.PackageId) ?? entry;
        cache.Put(entry with { Versions = entry.Versions.Select(v => v.Version == version.Version ? v with { Dependencies = groups } : v).ToList() });
        return groups;
    }

    /// <summary>The package file, downloaded once into the cache folder —
    /// keyed by feed, id and version, so a client feed's copy and nuget.org's
    /// are never mixed.</summary>
    public async Task<string?> DownloadAsync(Feed feed, string packageId, string version, CancellationToken ct)
    {
        var feedKey = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(feed.Url)))[..12];
        var directory = Path.Combine(packageCacheDirectory, feedKey, packageId.ToLowerInvariant(), version.ToLowerInvariant());
        var path = Path.Combine(directory, $"{packageId.ToLowerInvariant()}.{version.ToLowerInvariant()}.nupkg");
        if (File.Exists(path)) return path;

        try
        {
            var resource = await RepositoryFor(feed).GetResourceAsync<FindPackageByIdResource>(ct);
            Directory.CreateDirectory(directory);
            var partial = path + ".partial";
            await using (var stream = File.Create(partial))
            {
                if (!await resource.CopyNupkgToStreamAsync(packageId, NuGetVersion.Parse(version), stream, _sourceCache, NullLogger.Instance, ct))
                {
                    stream.Close();
                    File.Delete(partial);
                    return null;
                }
            }

            File.Move(partial, path, overwrite: true);
            return path;
        }
        catch (Exception ex) when (ex is FatalProtocolException or HttpRequestException or TaskCanceledException or IOException or InvalidOperationException)
        {
            return null;
        }
    }
}
