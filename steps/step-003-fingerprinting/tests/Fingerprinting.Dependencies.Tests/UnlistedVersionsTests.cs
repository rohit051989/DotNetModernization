using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using Fingerprinting.Dependencies;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>
/// Unlisted versions (30-DEPENDENCY-ASSESSMENT.md "Unlisted versions", artifact 1.9.0). NuGet's unlisting only hides a
/// version from search; it still restores by exact version. A local stand-in artifactory serves registrations whose
/// versions are listed or not, and the step's real pipeline runs against it; every artifact is validated as a whole
/// against the schema file of the version it declares.
/// </summary>
public sealed class UnlistedVersionsTests : IDisposable
{
    private const string Target = "net10.0";
    private readonly string _root = Path.Combine(Path.GetTempPath(), "unlisted-" + Guid.NewGuid().ToString("N"));

    public UnlistedVersionsTests() => Directory.CreateDirectory(_root);

    public void Dispose()
    {
        try { Directory.Delete(_root, recursive: true); } catch (IOException) { }
    }

    /// <summary>One version on the stand-in: listed or not, and the framework its dependency group declares. An
    /// unlisted version is served as nuget.org serves one in a v3 registration: <c>"listed": false</c> and a published
    /// date of 1900-01-01. NuGet's v3 client reads the <c>listed</c> property; the 1900 date is what a v2 feed's answer is
    /// read by (<c>V2FeedPackageInfo.IsListed</c>).</summary>
    private sealed record V(string Version, bool Listed = true, string Framework = "net8.0");

    [Fact]
    public async Task An_unlisted_version_is_looked_up_and_marked_unlisted()
    {
        using var feed = new Feed(new() { ["Example.Widgets"] = [new V("1.0.0"), new V("1.1.0", Listed: false)] });
        var lookup = Lookup(new MemoryLookupCache());
        var result = await lookup.GetAsync(feed.Of("private"), "Example.Widgets", CancellationToken.None);

        Assert.Equal([("1.1.0", false), ("1.0.0", true)], result.Entry!.Versions.Select(v => (v.Version, v.Listed)));
        Assert.Equal(PackageLookup.AnswerRule, result.Entry.Rule);
    }

    [Fact]
    public async Task A_referenced_unlisted_version_resolves_with_a_note_and_no_unknown_cause()
    {
        using var feed = new Feed(new() { ["Example.Widgets"] = [new V("1.0.0"), new V("1.2.0", Listed: false)] });
        var (artifact, package) = await RunAsync(feed, ("Example.Widgets", "1.2.0"));

        Assert.Equal(Outcomes.Current, package.Outcome);
        Assert.Null(package.UnknownCause);
        Assert.Equal("1.2.0", package.RecommendedVersion);
        Assert.Contains("1.2.0 is unlisted on 'private'", package.ListingNote);
        Assert.Contains("still restores by exact version", package.ListingNote);
        Valid(artifact);
    }

    [Fact]
    public async Task A_package_with_only_unlisted_versions_and_the_referenced_one_missing_is_only_unlisted()
    {
        using var feed = new Feed(new() { ["Example.Gadgets"] = [new V("2.0.0", Listed: false), new V("2.1.0", Listed: false)] });
        var (artifact, package) = await RunAsync(feed, ("Example.Gadgets", "1.0.0"));

        Assert.Equal((Outcomes.Unknown, UnknownCauses.OnlyUnlisted), (package.Outcome, package.UnknownCause));
        var holder = Assert.Single(package.UnlistedFeeds!);
        Assert.Equal(("private", feed.Index), (holder.Name, holder.Url));
        Assert.Equal(["2.1.0", "2.0.0"], holder.Versions);
        Assert.Contains("'private' holds 2.1.0, 2.0.0", package.OutcomeReason);
        Assert.Null(package.ConsultedFeeds);
        Assert.Null(package.ListingNote);
        Valid(artifact);
    }

    [Fact]
    public async Task Listed_versions_are_proposed_before_unlisted_ones()
    {
        using var feed = new Feed(new() { ["Example.Widgets"] = [new V("1.0.0"), new V("2.0.0"), new V("3.0.0", Listed: false)] });
        var (artifact, package) = await RunAsync(feed, ("Example.Widgets", "1.0.0"));

        Assert.Equal("2.0.0", package.RecommendedVersion);
        Assert.Equal("2.0.0", package.LatestVersion);
        Assert.Null(package.ListingNote);
        Valid(artifact);
    }

    [Fact]
    public async Task An_unlisted_version_is_proposed_only_when_no_listed_one_fits_and_the_note_says_so()
    {
        // Compatibility is judged from every version: the listed ones support only .NET Framework, an unlisted one net8.0.
        using var feed = new Feed(new()
        {
            ["Example.Widgets"] = [new V("1.0.0", Framework: "net472"), new V("2.0.0", Framework: "net472"), new V("1.5.0", Listed: false)],
        });
        var (artifact, package) = await RunAsync(feed, ("Example.Widgets", "1.0.0"));

        Assert.Equal("1.5.0", package.RecommendedVersion);
        Assert.NotEqual(Outcomes.NoCompatibleVersion, package.Outcome);
        Assert.Equal($"no listed version supports {Target} at or above 1.0.0: 1.5.0 is unlisted on 'private'", package.ListingNote);
        Valid(artifact);
    }

    [Fact]
    public async Task A_feed_that_reports_nearly_every_version_unlisted_is_said_to_once_per_scan()
    {
        var versions = Enumerable.Range(0, 12).Select(i => new V($"1.{i}.0", Listed: false)).ToList();
        using var feed = new Feed(new()
        {
            ["Example.Widgets"] = versions,
            ["Example.Gadgets"] = [new V("4.0.0", Listed: false)],
        });
        var (artifact, _) = await RunAsync(feed, ("Example.Widgets", "1.3.0"), ("Example.Gadgets", "3.0.0"), ("Example.Widgets", "1.3.0"));

        var listing = Assert.Single(artifact.Summary.FeedListing);
        Assert.Equal(("private", 2, 2, 13, 13, true), (listing.Name, listing.PackagesAnswered, listing.PackagesOnlyUnlisted,
            listing.VersionsAnswered, listing.VersionsUnlisted, listing.MostlyUnlisted));
        Assert.Contains("reports 13 of the 13 versions it answered as unlisted", listing.Note);
        Assert.Contains("1900-01-01", listing.Note);
        Assert.Contains("not that the packages were unlisted on purpose", listing.Note);
        Valid(artifact);
    }

    [Fact]
    public async Task A_feed_with_a_few_unlisted_versions_is_counted_without_the_note()
    {
        using var feed = new Feed(new() { ["Example.Widgets"] = [new V("1.0.0"), new V("1.1.0", Listed: false)] });
        var (artifact, _) = await RunAsync(feed, ("Example.Widgets", "1.0.0"));

        var listing = Assert.Single(artifact.Summary.FeedListing);
        Assert.Equal((1, 0, 2, 1, false, (string?)null), (listing.PackagesAnswered, listing.PackagesOnlyUnlisted, listing.VersionsAnswered,
            listing.VersionsUnlisted, listing.MostlyUnlisted, listing.Note));
        Valid(artifact);
    }

    [Fact]
    public async Task A_package_missing_everywhere_is_not_on_feed_and_the_artifactory_hint_follows_the_engagement()
    {
        using var feed = new Feed(new() { ["Example.Widgets"] = [new V("1.0.0")] });

        // The engagement lists an artifactory and every feed answered: adding another URL is not suggested.
        var (listed, package) = await RunAsync(feed, ("Example.Missing", "1.0.0"));
        Assert.Equal((Outcomes.Unknown, UnknownCauses.NotOnFeed), (package.Outcome, package.UnknownCause));
        Assert.Equal("Example.Missing was not found on the artifactories consulted: private.", package.OutcomeReason);
        Assert.DoesNotContain(DependencyPipeline.AddArtifactoryHint, package.OutcomeReason);
        Valid(listed);

        // The engagement lists none (the feed comes from NuGet.config): the Artifactory tab is suggested.
        var (declared, fromConfig) = await RunAsync(feed, engagement: false, packages: ("Example.Missing", "1.0.0"));
        Assert.Equal((Outcomes.Unknown, UnknownCauses.NotOnFeed), (fromConfig.Outcome, fromConfig.UnknownCause));
        Assert.EndsWith(DependencyPipeline.AddArtifactoryHint, fromConfig.OutcomeReason);
        Valid(declared);
    }

    [Fact]
    public async Task A_cached_answer_from_the_old_rule_is_asked_again_however_fresh_except_offline()
    {
        using var feed = new Feed(new() { ["Example.Gadgets"] = [new V("2.0.0", Listed: false)] });
        var now = DateTimeOffset.Parse("2026-11-20T00:00:00Z");
        // What the old rule cached a minute ago: listed versions only, so nothing at all for this package.
        var old = new CacheEntry { FeedUrl = feed.Index, PackageId = "example.gadgets", FetchedAt = now.AddMinutes(-1), Versions = [] };

        var offlineCache = new MemoryLookupCache();
        offlineCache.Put(old);
        var offline = await Lookup(offlineCache, now, offline: true).GetAsync(feed.Of("private"), "Example.Gadgets", CancellationToken.None);
        Assert.Empty(offline.Entry!.Versions);
        Assert.Empty(feed.Requests);

        var cache = new MemoryLookupCache();
        cache.Put(old);
        var asked = await Lookup(cache, now).GetAsync(feed.Of("private"), "Example.Gadgets", CancellationToken.None);
        Assert.Equal([("2.0.0", false)], asked.Entry!.Versions.Select(v => (v.Version, v.Listed)));
        Assert.Equal(PackageLookup.AnswerRule, cache.Get(feed.Index, "Example.Gadgets")!.Rule);
        Assert.NotEmpty(feed.Requests);

        // Under the current rule, a fresh entry is reused.
        var before = feed.Requests.Count;
        await Lookup(cache, now).GetAsync(feed.Of("private"), "Example.Gadgets", CancellationToken.None);
        Assert.Equal(before, feed.Requests.Count);
    }

    [Fact]
    public void A_file_cache_written_before_the_rule_reads_as_the_old_rule()
    {
        var path = Path.Combine(_root, "cache.json");
        File.WriteAllText(path, """[{"feedUrl":"http://127.0.0.1:1/v3/index.json","packageId":"example.widgets","fetchedAt":"2026-11-19T00:00:00+00:00","versions":[]}]""");
        Assert.Equal(1, new FileLookupCache(path).Get("http://127.0.0.1:1/v3/index.json", "Example.Widgets")!.Rule);
    }

    // ---------- helpers ----------

    private PackageLookup Lookup(ILookupCache cache, DateTimeOffset? now = null, bool offline = false) =>
        new(cache, Path.Combine(_root, "packages"), TimeSpan.FromHours(24), forceRefresh: false, now ?? DateTimeOffset.Parse("2026-11-20T00:00:00Z"), offline);

    private Task<(DependencyAssessmentArtifact, PackageAssessment)> RunAsync(Feed feed, params (string Id, string Version)[] packages) =>
        RunAsync(feed, engagement: true, packages);

    /// <summary>One project referencing <paramref name="packages"/>, scanned with the stand-in as its only feed: listed
    /// on the engagement's Artifactory tab, or (<paramref name="engagement"/> false) declared in the repository's
    /// NuGet.config. Returns the artifact and the first package's assessment.</summary>
    private async Task<(DependencyAssessmentArtifact, PackageAssessment)> RunAsync(Feed feed, bool engagement, params (string Id, string Version)[] packages)
    {
        var repo = Path.Combine(_root, "repo-" + Guid.NewGuid().ToString("N")[..8]);
        var project = Path.Combine(repo, "src", "App");
        Directory.CreateDirectory(project);
        var source = engagement ? "" : $"""<add key="private" value="{feed.Index}" />""";
        File.WriteAllText(Path.Combine(repo, "NuGet.config"),
            $"""<?xml version="1.0" encoding="utf-8"?><configuration><packageSources><clear />{source}</packageSources></configuration>""");
        var distinct = packages.DistinctBy(p => p.Id).ToList();
        File.WriteAllText(Path.Combine(project, "App.csproj"), $"""
            <Project Sdk="Microsoft.NET.Sdk">
              <PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>
              <ItemGroup>{string.Concat(distinct.Select(p => $"""<PackageReference Include="{p.Id}" Version="{p.Version}" />"""))}</ItemGroup>
            </Project>
            """);
        File.WriteAllText(Path.Combine(project, "Program.cs"), "class P { }");

        // A second project referencing the same packages: each is counted once per scan, not once per project.
        var second = Path.Combine(repo, "src", "Other");
        Directory.CreateDirectory(second);
        File.Copy(Path.Combine(project, "App.csproj"), Path.Combine(second, "Other.csproj"));

        var pipeline = new DependencyPipeline(Lookup(new MemoryLookupCache()), new DependencyOptions(Target, ComparePublicFeed: false,
            EngagementFeeds: engagement ? [new EngagementFeed("private", feed.Index)] : null));
        var inputs = distinct.Select(p => new InputPackage(p.Id, p.Version, "packagereference")).ToList();
        var input = new DependencyInput(Guid.Parse("11111111-2222-3333-4444-555555555555"), "fixture", "application-fingerprint",
            [
                new DependencyInputProject("src/App/App.csproj", Guid.Parse("22222222-3333-4444-5555-666666666666"), null, "net8.0", inputs),
                new DependencyInputProject("src/Other/Other.csproj", Guid.Parse("33333333-4444-5555-6666-777777777777"), null, "net8.0", inputs),
            ], []);
        var artifact = await pipeline.RunAsync(input, repo, CancellationToken.None);
        var first = artifact.Projects.First(p => p.ProjectPath == "src/App/App.csproj");
        Assert.Equal(feed.Index, Assert.Single(first.Feeds).Url);
        return (artifact, first.Packages.First(p => p.PackageId == packages[0].Id));
    }

    /// <summary>The whole artifact against the schema file of the version it declares, as the step validates it.</summary>
    private static void Valid(DependencyAssessmentArtifact artifact)
    {
        Assert.Equal(DependencyAssessmentArtifact.Version, artifact.ArtifactVersion);
        ArtifactSchemas.Validate(artifact);
    }

    /// <summary>A local, anonymous stand-in artifactory: a NuGet v3 service index and a registration per package.
    /// Package files are not served, so nothing is downloaded.</summary>
    private sealed class Feed : IDisposable
    {
        private readonly TcpListener _listener = new(IPAddress.Loopback, 0);
        private readonly CancellationTokenSource _stop = new();
        private readonly Dictionary<string, List<V>> _packages;

        public Feed(Dictionary<string, List<V>> packages)
        {
            _packages = packages.ToDictionary(kv => kv.Key.ToLowerInvariant(), kv => kv.Value);
            _listener.Start();
            Base = $"http://127.0.0.1:{((IPEndPoint)_listener.LocalEndpoint).Port}";
            _ = Task.Run(async () =>
            {
                try
                {
                    while (!_stop.IsCancellationRequested)
                    {
                        var client = await _listener.AcceptTcpClientAsync(_stop.Token);
                        _ = Task.Run(() => ServeAsync(client));
                    }
                }
                catch (Exception e) when (e is OperationCanceledException or ObjectDisposedException or SocketException) { }
            });
        }

        private string Base { get; }

        public string Index => Base + "/v3/index.json";

        public List<string> Requests { get; } = [];

        public Dependencies.Feed Of(string name) => new(name, new NuGet.Configuration.PackageSource(Index, name), Index, Dependencies.Feed.RoleClient, "engagement");

        private async Task ServeAsync(TcpClient client)
        {
            using (client)
            {
                try
                {
                    var stream = client.GetStream();
                    var buffer = new byte[16384];
                    var text = new StringBuilder();
                    while (!text.ToString().Contains("\r\n\r\n"))
                    {
                        var read = await stream.ReadAsync(buffer, _stop.Token);
                        if (read == 0) break;
                        text.Append(Encoding.ASCII.GetString(buffer, 0, read));
                    }

                    var path = text.ToString().Split("\r\n")[0].Split(' ')[1];
                    lock (Requests) Requests.Add(path);
                    var body = Answer(path);
                    var bytes = Encoding.UTF8.GetBytes(body ?? "");
                    var head = Encoding.ASCII.GetBytes(
                        $"HTTP/1.1 {(body is null ? "404 Not Found" : "200 OK")}\r\nContent-Type: application/json\r\nContent-Length: {bytes.Length}\r\nConnection: close\r\n\r\n");
                    await stream.WriteAsync(head.Concat(bytes).ToArray(), _stop.Token);
                }
                catch (Exception e) when (e is IOException or OperationCanceledException or ObjectDisposedException) { }
            }
        }

        private string? Answer(string path)
        {
            if (path == "/v3/index.json")
            {
                return JsonSerializer.Serialize(new Dictionary<string, object>
                {
                    ["version"] = "3.0.0",
                    ["resources"] = new[]
                    {
                        new Dictionary<string, string> { ["@id"] = Base + "/registration/", ["@type"] = "RegistrationsBaseUrl/3.6.0" },
                        new Dictionary<string, string> { ["@id"] = Base + "/flat/", ["@type"] = "PackageBaseAddress/3.0.0" },
                    },
                });
            }

            var parts = path.Split('/', StringSplitOptions.RemoveEmptyEntries);
            if (parts is not ["registration", var id, "index.json"] || !_packages.TryGetValue(id, out var versions)) return null;
            var items = versions.Select(v =>
            {
                var entry = new Dictionary<string, object>
                {
                    ["@id"] = $"{Base}/catalog/{id}.{v.Version}.json",
                    ["id"] = id,
                    ["version"] = v.Version,
                    ["listed"] = v.Listed,
                    ["published"] = v.Listed ? "2026-01-01T00:00:00+00:00" : "1900-01-01T00:00:00+00:00",
                    ["dependencyGroups"] = new[] { new Dictionary<string, string> { ["targetFramework"] = v.Framework } },
                };
                return new Dictionary<string, object>
                {
                    ["@id"] = $"{Base}/registration/{id}/{v.Version}.json",
                    ["catalogEntry"] = entry,
                    ["packageContent"] = $"{Base}/flat/{id}/{v.Version}/{id}.{v.Version}.nupkg",
                };
            }).ToList();
            return JsonSerializer.Serialize(new Dictionary<string, object>
            {
                ["count"] = 1,
                ["items"] = new[]
                {
                    new Dictionary<string, object>
                    {
                        ["@id"] = $"{Base}/registration/{id}/index.json#page",
                        ["count"] = items.Count,
                        ["lower"] = versions.First().Version,
                        ["upper"] = versions.Last().Version,
                        ["items"] = items,
                    },
                },
            });
        }

        public void Dispose()
        {
            _stop.Cancel();
            _listener.Stop();
        }
    }
}
