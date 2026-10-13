using Fingerprinting.Dependencies;
using NuGet.Configuration;
using Xunit;

namespace Fingerprinting.Dependencies.Tests;

/// <summary>1.4.1, <c>lookup_offline</c> (36-COPILOT-ENHANCED-CONVERSION Part L): an experiment's verification answers
/// package lookups from its frozen snapshot only. The feed here does not exist: any attempt to reach it would fail
/// with "could not be reached", never the offline answer.</summary>
public sealed class OfflineLookupTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "offline-lookup-" + Guid.NewGuid().ToString("N"));
    private static readonly Feed Unreachable =
        new("nowhere", new PackageSource("https://nowhere.invalid/v3/index.json"), "https://nowhere.invalid/v3/index.json", Feed.RoleNuGetOrg, "test");
    private static readonly DateTimeOffset Now = DateTimeOffset.Parse("2026-10-14T00:00:00Z");

    public void Dispose()
    {
        if (Directory.Exists(_root)) Directory.Delete(_root, true);
    }

    private static MemoryLookupCache Frozen()
    {
        var cache = new MemoryLookupCache();
        cache.Put(new CacheEntry
        {
            FeedUrl = Unreachable.Url, PackageId = "system.text.json", FetchedAt = Now.AddDays(-30),   // long past any TTL
            Versions = [new CachedVersion { Version = "10.0.12" }, new CachedVersion { Version = "8.0.3" }],
        });
        return cache;
    }

    private PackageLookup Lookup(bool offline) =>
        new(Frozen(), Path.Combine(_root, "packages"), TimeSpan.FromHours(24), forceRefresh: false, Now, offline);

    [Fact]
    public async Task Offline_a_frozen_answer_is_used_whatever_its_age()
    {
        var result = await Lookup(offline: true).GetAsync(Unreachable, "System.Text.Json", CancellationToken.None);
        Assert.True(result.Reachable);
        Assert.Equal(["10.0.12", "8.0.3"], result.Entry!.Versions.Select(v => v.Version));
    }

    [Fact]
    public async Task Offline_a_package_the_snapshot_does_not_hold_is_not_answered_and_no_feed_is_asked()
    {
        var result = await Lookup(offline: true).GetAsync(Unreachable, "Newtonsoft.Json", CancellationToken.None);
        Assert.False(result.Reachable);
        Assert.Contains("not in the frozen package lookups", result.Error);
        Assert.Null(await Lookup(offline: true).DownloadAsync(Unreachable, "Newtonsoft.Json", "13.0.3", CancellationToken.None));
        Assert.False(Directory.Exists(Path.Combine(_root, "packages")));                            // nothing downloaded
    }

    [Fact]
    public async Task Online_an_expired_answer_is_refreshed_from_the_feed()
    {
        // The contrast: without offline, the 30-day-old entry is past its TTL, so the feed is asked (and here fails).
        var result = await Lookup(offline: false).GetAsync(Unreachable, "System.Text.Json", CancellationToken.None);
        Assert.False(result.Reachable);
        Assert.Contains("could not be reached", result.Error);
    }
}
