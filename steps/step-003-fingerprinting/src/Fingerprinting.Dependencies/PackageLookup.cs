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

/// <summary>Why a feed gave no answer (38-PACKAGE-ACCESS.md Part B). <c>None</c> for an answer, and for a lookup that was
/// never made (offline, answered from a frozen snapshot).</summary>
public enum LookupFailure
{
    None,

    /// <summary>The feed answered 401 or 403: it needs a login the machine has not made.</summary>
    Auth,

    /// <summary>The feed could not be reached, or failed in any other way: DNS, timeout, TLS, refused, a protocol error.</summary>
    Unreachable,
}

/// <summary>A feed's answer for one package: the entry, or why there is none. <paramref name="Failure"/> and
/// <paramref name="HttpStatus"/> classify an error for the package-access view; <paramref name="Error"/> stays the text.</summary>
public sealed record LookupResult(CacheEntry? Entry, string? Error, LookupFailure Failure = LookupFailure.None, int? HttpStatus = null)
{
    public bool Reachable => Error is null;
}

/// <summary>
/// Deterministic version lookup through the NuGet protocol (Part B1) — no
/// guessing, no model. Metadata goes into the lookup cache; package files
/// are downloaded only into <see cref="PackageCacheDirectory"/>, outside every
/// repository (Part B5). Nothing is restored, nothing is written beside a
/// project.
/// <para>
/// <paramref name="offline"/> (1.4.1, <c>lookup_offline</c>; 36-COPILOT-ENHANCED-CONVERSION Part L): every answer
/// comes from the cache, whatever its age, and no feed is contacted. A package the cache does not hold is reported as
/// not answered, and a package file not already downloaded is not downloaded. An experiment's verifier loads its
/// frozen snapshot into the cache and runs this way, so a release published between two verifications changes
/// nothing.
/// </para>
/// </summary>
public sealed partial class PackageLookup(ILookupCache cache, string packageCacheDirectory, TimeSpan ttl, bool forceRefresh, DateTimeOffset now,
    bool offline = false)
{
    private readonly SourceCacheContext _sourceCache = new() { NoCache = true, DirectDownload = true };
    private readonly Dictionary<string, SourceRepository> _repositories = new(StringComparer.Ordinal);
    private readonly HashSet<string> _refreshed = new(StringComparer.Ordinal);

    public string PackageCacheDirectory => packageCacheDirectory;

    /// <summary>The rule answers are asked under, recorded on each cache entry (<see cref="CacheEntry.Rule"/>). 2: every
    /// version, unlisted ones included and marked. NuGet's unlisting only hides a version from search: it still restores
    /// by exact version, so a package whose versions are all unlisted is on the feed. An entry under an older rule held
    /// listed versions only and is asked again.</summary>
    public const int AnswerRule = 2;

    /// <summary>The fetched_at of every cache entry this run read or wrote —
    /// its minimum is the snapshot the artifact is true as of (Part B6).</summary>
    public List<DateTimeOffset> SnapshotTimes { get; } = [];

    [GeneratedRegex(@"[A-Za-z][A-Za-z0-9+.\-]*://[^\s'""]+")]
    private static partial Regex UrlPattern();

    private SourceRepository RepositoryFor(Feed feed)
    {
        if (_repositories.TryGetValue(feed.Url, out var known)) return known;

        // A feed asked with the machine's token goes through ArtifactoryLogin; every other feed as NuGet asks it.
        SourceRepository repository = feed.HeaderLogin is { } login ? login.Repository(feed.Source) : Repository.Factory.GetCoreV3(feed.Source);
        _repositories[feed.Url] = repository;
        return repository;
    }

    /// <summary>A protocol error, with any URL in it normalised — an
    /// exception message must not carry a credential into the artifact.</summary>
    private static string Describe(Feed feed, Exception ex) => $"artifactory '{feed.Name}' could not be reached: {Message(ex)}";

    /// <summary>An exception's message with every URL in it normalised, so no login in a URL reaches a result or a log.</summary>
    public static string Message(Exception ex)
    {
        var message = ex.InnerException?.Message ?? ex.Message;
        return UrlPattern().Replace(message, m => FeedResolver.NormaliseUrl(m.Value.TrimEnd('.', ','), Path.GetPathRoot(Path.GetTempPath())!)).Trim();
    }

    public async Task<LookupResult> GetAsync(Feed feed, string packageId, CancellationToken ct)
    {
        var key = $"{feed.Url}|{packageId.ToLowerInvariant()}";
        var cached = cache.Get(feed.Url, packageId);
        // Offline, an entry is used whatever its rule: a frozen snapshot answers as it was frozen.
        if (cached is not null && (offline || _refreshed.Contains(key) || (!forceRefresh && cached.Rule >= AnswerRule && now - cached.FetchedAt < ttl)))
        {
            SnapshotTimes.Add(cached.FetchedAt);
            return new LookupResult(cached, null);
        }

        if (offline)
        {
            return new LookupResult(null, $"artifactory '{feed.Name}' was not asked: '{packageId}' is not in the frozen package lookups, and lookups are offline");
        }

        try
        {
            var resource = await RepositoryFor(feed).GetResourceAsync<PackageMetadataResource>(ct);
            var metadata = await resource.GetMetadataAsync(packageId, includePrerelease: true, includeUnlisted: true, _sourceCache, NullLogger.Instance, ct);
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

            var entry = new CacheEntry { FeedUrl = feed.Url, PackageId = packageId.ToLowerInvariant(), FetchedAt = now, Rule = AnswerRule, Versions = versions };
            cache.Put(entry);
            _refreshed.Add(key);
            SnapshotTimes.Add(now);
            return new LookupResult(entry, null);
        }
        catch (Exception ex) when (ex is FatalProtocolException or HttpRequestException or TaskCanceledException or IOException or InvalidOperationException)
        {
            var status = HttpStatusOf(ex);
            var message = status is 401 or 403 && feed.HeaderLogin is { TokenRejected: true, HasUsernameAndPassword: false } login
                ? login.RejectedMessage(feed.Name, status)
                : Describe(feed, ex);
            return new LookupResult(null, message, status is 401 or 403 ? LookupFailure.Auth : LookupFailure.Unreachable, status);
        }
    }

    [GeneratedRegex(@"status code[^0-9]{0,40}(\d{3})", RegexOptions.IgnoreCase)]
    private static partial Regex StatusCodeText();

    /// <summary>The HTTP status behind a protocol error: the <see cref="HttpRequestException.StatusCode"/> found
    /// anywhere in the exception chain, else the one NuGet writes into its message ("Response status code does not
    /// indicate success: 401 (Unauthorized)"). Null when the failure had no HTTP answer (DNS, timeout, TLS).</summary>
    public static int? HttpStatusOf(Exception ex)
    {
        var chain = new List<Exception>();
        for (Exception? e = ex; e is not null; e = e.InnerException) chain.Add(e);

        foreach (var e in chain)
        {
            if (e is HttpRequestException { StatusCode: { } code }) return (int)code;
        }

        foreach (var e in chain)
        {
            var match = StatusCodeText().Match(e.Message);
            if (match.Success) return int.Parse(match.Groups[1].Value);
        }

        return null;
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
        if (offline) return null;                   // never downloaded while lookups are offline

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
