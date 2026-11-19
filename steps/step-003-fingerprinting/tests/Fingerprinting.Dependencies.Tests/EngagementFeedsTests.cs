using System.Text.Json;
using Fingerprinting.Dependencies;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>The engagement's feeds and their login (docs/39-ARTIFACTORY.md): NuGet.config first, then the
/// environment. A fake environment stands in for the real one, so no test sets a variable.</summary>
public sealed class EngagementFeedsTests : IDisposable
{
    private const string Url = "http://localhost:8081/repository/nuget-private/index.json";
    private readonly string _root = Path.Combine(Path.GetTempPath(), "engagement-feeds-" + Guid.NewGuid().ToString("N"));

    public EngagementFeedsTests() => Directory.CreateDirectory(_root);

    public void Dispose()
    {
        try { Directory.Delete(_root, recursive: true); } catch (IOException) { }
    }

    private static Func<string, string?> Env(params (string Name, string Value)[] variables) =>
        name => variables.Where(v => v.Name == name).Select(v => v.Value).FirstOrDefault();

    private FeedSet Resolve(string config, IReadOnlyList<EngagementFeed> feeds, Func<string, string?> env)
    {
        File.WriteAllText(Path.Combine(_root, "NuGet.config"),
            $"""<?xml version="1.0" encoding="utf-8"?><configuration>{config}</configuration>""");
        return FeedResolver.Resolve(_root, _root, comparePublicFeed: false, engagementFeeds: feeds, environment: env);
    }

    [Fact]
    public void Feeds_are_read_from_the_step_context_and_a_missing_list_is_empty()
    {
        using var document = JsonDocument.Parse("""{"artifactories":[{"name":"nuget-private","url":"http://h/f"},{"name":"","url":"x"},{"url":"y"}]}""");
        Assert.Equal([new EngagementFeed("nuget-private", "http://h/f")], EngagementFeeds.From(document.RootElement));
        Assert.Empty(EngagementFeeds.From(null));
    }

    [Fact]
    public void The_machine_login_is_used_for_a_feed_nuget_config_does_not_declare_and_the_feed_is_a_client_feed()
    {
        var feeds = Resolve("<packageSources><clear /></packageSources>", [new EngagementFeed("nuget-private", Url)],
            Env((EngagementFeeds.UsernameVariable, "me"), (EngagementFeeds.PasswordVariable, "pw")));

        var feed = Assert.Single(feeds.All, f => f.Name == "nuget-private");
        Assert.Equal((Feed.RoleClient, "engagement"), (feed.Role, feed.DeclaredIn));
        Assert.Equal("me", feed.Source.Credentials!.Username);
        Assert.Equal("pw", feed.Source.Credentials.Password);
        Assert.DoesNotContain("pw", feed.Url);                    // the stored form never holds a login
        Assert.Contains(feed, feeds.Authorities);
    }

    [Fact]
    public void A_feed_with_its_own_variable_uses_it_before_the_machine_login()
    {
        var feeds = Resolve("<packageSources><clear /></packageSources>", [new EngagementFeed("nuget-private", Url)],
            Env((EngagementFeeds.PerFeedPrefix + "nuget-private", "Username=own;Password=ownpw"),
                (EngagementFeeds.UsernameVariable, "me"), (EngagementFeeds.PasswordVariable, "pw")));

        Assert.Equal("own", Assert.Single(feeds.All).Source.Credentials!.Username);
    }

    [Fact]
    public void Without_any_login_the_feed_is_still_listed_and_asked_anonymously()
    {
        var feeds = Resolve("<packageSources><clear /></packageSources>", [new EngagementFeed("nuget-private", Url)], Env());
        Assert.Null(Assert.Single(feeds.All, f => f.Name == "nuget-private").Source.Credentials);
    }

    [Fact]
    public void A_source_nuget_config_declares_with_the_same_url_keeps_its_own_credentials()
    {
        var config = $"""
            <packageSources><clear /><add key="declared" value="{Url}" /></packageSources>
            <packageSourceCredentials><declared><add key="Username" value="fromconfig" /><add key="ClearTextPassword" value="example-cfgpw" /></declared></packageSourceCredentials>
            """;
        var feeds = Resolve(config, [new EngagementFeed("nuget-private", Url.Replace("http://", "HTTP://"))],
            Env((EngagementFeeds.UsernameVariable, "me"), (EngagementFeeds.PasswordVariable, "pw")));

        var feed = Assert.Single(feeds.All);                      // not added twice
        Assert.Equal("declared", feed.Name);
        Assert.Equal("fromconfig", feed.Source.Credentials!.Username);
    }

    [Fact]
    public void A_declared_source_without_credentials_gets_the_machine_login()
    {
        var feeds = Resolve($"""<packageSources><clear /><add key="declared" value="{Url}" /></packageSources>""",
            [new EngagementFeed("nuget-private", Url)], Env((EngagementFeeds.UsernameVariable, "me"), (EngagementFeeds.PasswordVariable, "pw")));

        Assert.Equal("me", Assert.Single(feeds.All).Source.Credentials!.Username);
    }

    [Fact]
    public void The_variable_format_is_nugets_own()
    {
        Assert.Equal(("u", "p"), EngagementFeeds.Parse("Username=u;Password=p"));
        Assert.Null(EngagementFeeds.Parse("Username=u"));
        Assert.Null(EngagementFeeds.Parse(null));
    }
}
