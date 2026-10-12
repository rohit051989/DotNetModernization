using System.Text.Json;
using System.Text.Json.Serialization;

namespace Fingerprinting.Dependencies;

/// <summary>What one feed says about one package (Part B6): every listed
/// version with the facts the assessment reads. <see cref="FetchedAt"/> is
/// when it was true; it is never written into the artifact.</summary>
public sealed record CacheEntry
{
    public required string FeedUrl { get; init; }
    public required string PackageId { get; init; }
    public required DateTimeOffset FetchedAt { get; init; }

    /// <summary>Newest first.</summary>
    public required IReadOnlyList<CachedVersion> Versions { get; init; }
}

public sealed record CachedVersion
{
    public required string Version { get; init; }
    public bool Listed { get; init; } = true;

    /// <summary>Target frameworks of the package's dependency groups, from
    /// feed metadata. Empty when the package declares none.</summary>
    public IReadOnlyList<string> DependencyFrameworks { get; init; } = [];

    /// <summary>Frameworks of the lib/ and ref/ folders, read from the
    /// package itself — filled when dependency groups do not answer.</summary>
    public IReadOnlyList<string>? LibFrameworks { get; init; }

    /// <summary>The nuspec's dependency groups — each group's framework and
    /// the packages it depends on with their version ranges — from feed
    /// metadata. Null when this entry was cached before dependencies were
    /// recorded; <see cref="PackageLookup.DependenciesAsync"/> fills it then.
    /// The conversion planner orders and groups package units by these.</summary>
    public IReadOnlyList<CachedDependencyGroup>? Dependencies { get; init; }

    /// <summary>The package kind, from the nupkg's contents; null until read (<see cref="PackageKinds"/>).</summary>
    public string? Kind { get; init; }
    public CachedDeprecation? Deprecation { get; init; }
    public IReadOnlyList<CachedVulnerability> Vulnerabilities { get; init; } = [];
}

/// <summary>One nuspec dependency group: its framework (short folder name)
/// and what it depends on, ordered by id.</summary>
public sealed record CachedDependencyGroup
{
    public required string Framework { get; init; }
    public IReadOnlyList<CachedDependency> Packages { get; init; } = [];

    public static IReadOnlyList<CachedDependencyGroup> From(IEnumerable<NuGet.Packaging.PackageDependencyGroup>? groups) =>
        (groups ?? [])
            .Select(g => new CachedDependencyGroup
            {
                Framework = g.TargetFramework.GetShortFolderName(),
                Packages = g.Packages
                    .Select(p => new CachedDependency { Id = p.Id, Range = p.VersionRange.ToNormalizedString() })
                    .OrderBy(p => p.Id, StringComparer.OrdinalIgnoreCase)
                    .ToList(),
            })
            .OrderBy(g => g.Framework, StringComparer.OrdinalIgnoreCase)
            .ToList();
}

public sealed record CachedDependency
{
    public required string Id { get; init; }
    /// <summary>NuGet's normalized range: "[1.0.0, )" is 1.0.0 or higher.</summary>
    public required string Range { get; init; }
}

public sealed record CachedDeprecation
{
    public IReadOnlyList<string> Reasons { get; init; } = [];
    public string? Message { get; init; }
    public string? AlternateId { get; init; }
    public string? AlternateRange { get; init; }
}

public sealed record CachedVulnerability
{
    /// <summary>NuGet's 0-3: low, moderate, high, critical.</summary>
    public required int Severity { get; init; }
    public required string AdvisoryUrl { get; init; }
}

/// <summary>The lookup cache. A run reads an entry younger than the TTL
/// instead of asking the feed, so two runs against the same cache produce
/// the same artifact.</summary>
public interface ILookupCache
{
    CacheEntry? Get(string feedUrl, string packageId);
    void Put(CacheEntry entry);
}

/// <summary>In memory — tests, and a run with no cache configured.</summary>
public sealed class MemoryLookupCache : ILookupCache
{
    private readonly Dictionary<(string, string), CacheEntry> _entries = [];

    public CacheEntry? Get(string feedUrl, string packageId) =>
        _entries.GetValueOrDefault((feedUrl, packageId.ToLowerInvariant()));

    public void Put(CacheEntry entry) => _entries[(entry.FeedUrl, entry.PackageId.ToLowerInvariant())] = entry;
}

/// <summary>A JSON file — the standalone mode's cache, outside the
/// repository (the envelope mode uses the package_lookup_cache table).</summary>
public sealed class FileLookupCache : ILookupCache
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = false,
    };

    private readonly string _path;
    private readonly Dictionary<string, CacheEntry> _entries;

    public FileLookupCache(string path)
    {
        _path = path;
        _entries = File.Exists(path)
            ? (JsonSerializer.Deserialize<List<CacheEntry>>(File.ReadAllText(path), Options) ?? [])
                .ToDictionary(e => Key(e.FeedUrl, e.PackageId), StringComparer.Ordinal)
            : new Dictionary<string, CacheEntry>(StringComparer.Ordinal);
    }

    private static string Key(string feedUrl, string packageId) => $"{feedUrl}|{packageId.ToLowerInvariant()}";

    public CacheEntry? Get(string feedUrl, string packageId) => _entries.GetValueOrDefault(Key(feedUrl, packageId));

    public void Put(CacheEntry entry) => _entries[Key(entry.FeedUrl, entry.PackageId)] = entry;

    public void Save()
    {
        Directory.CreateDirectory(Path.GetDirectoryName(_path)!);
        var ordered = _entries.OrderBy(kv => kv.Key, StringComparer.Ordinal).Select(kv => kv.Value).ToList();
        File.WriteAllText(_path, JsonSerializer.Serialize(ordered, Options));
    }
}
