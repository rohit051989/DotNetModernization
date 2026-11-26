using Fingerprinting.Dependencies;
using NuGet.Configuration;
using NuGet.Frameworks;
using Xunit;

namespace Fingerprinting.Dependencies.Tests;

/// <summary>1.11.0: a nuspec that lists its dependencies without framework groups (a flat list, cached as one "any"
/// group) says nothing about the package's assets, so its lib/ref folders decide what it supports. A package built only
/// for .NET Framework (lib/net45) is then not compatible with a .NET (5+) target, which NuGet reaches only through
/// AssetTargetFallback (NU1701). The package and feed are made up; the lib/ref frameworks are in the cache already, so
/// nothing is downloaded.</summary>
public sealed class FlatDependencyListTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "flat-dependencies-" + Guid.NewGuid().ToString("N"));
    private static readonly Feed Unreachable =
        new("nowhere", new PackageSource("https://nowhere.invalid/v3/index.json"), "https://nowhere.invalid/v3/index.json", Feed.RoleNuGetOrg, "test");
    private static readonly DateTimeOffset Now = DateTimeOffset.Parse("2026-11-26T00:00:00Z");
    private static readonly NuGetFramework Target = NuGetFramework.Parse("net10.0");

    public void Dispose()
    {
        if (Directory.Exists(_root)) Directory.Delete(_root, true);
    }

    private async Task<IReadOnlyList<NuGetFramework>?> Frameworks(IReadOnlyList<string> dependencyGroups, IReadOnlyList<string> lib)
    {
        var version = new CachedVersion { Version = "6.0.1304", DependencyFrameworks = dependencyGroups, LibFrameworks = lib };
        var entry = new CacheEntry { FeedUrl = Unreachable.Url, PackageId = "contoso.legacyblocks.data", FetchedAt = Now, Versions = [version] };
        var cache = new MemoryLookupCache();
        cache.Put(entry);
        var lookup = new PackageLookup(cache, Path.Combine(_root, "packages"), TimeSpan.FromHours(24), forceRefresh: false, Now, offline: true);
        return await lookup.FrameworksAsync(Unreachable, entry, version, CancellationToken.None);
    }

    private static bool Compatible(IReadOnlyList<NuGetFramework>? frameworks) =>
        frameworks is not null && (frameworks.Count == 0
                                   || frameworks.Any(f => f.IsAny || f.IsAgnostic || DefaultCompatibilityProvider.Instance.IsCompatible(Target, f)));

    [Fact]
    public async Task A_flat_dependency_list_with_only_net45_assets_is_not_compatible_with_net10()
    {
        var frameworks = await Frameworks(["any"], ["net45"]);
        Assert.Equal(["net45"], frameworks!.Select(f => f.GetShortFolderName()));
        Assert.False(Compatible(frameworks));
    }

    [Fact]
    public async Task A_flat_dependency_list_with_netstandard20_assets_is_compatible_with_net10()
    {
        var frameworks = await Frameworks(["any"], ["net45", "netstandard2.0"]);
        Assert.True(Compatible(frameworks));
    }

    [Fact]
    public async Task Framework_groups_still_decide_when_the_nuspec_declares_them()
    {
        var frameworks = await Frameworks(["net45", "netstandard2.0"], ["net45"]);
        Assert.Equal(["net45", "netstandard2.0"], frameworks!.Select(f => f.GetShortFolderName()));
        Assert.True(Compatible(frameworks));
    }
}
