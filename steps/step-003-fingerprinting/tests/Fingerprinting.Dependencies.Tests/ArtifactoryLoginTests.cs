using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using Fingerprinting.Dependencies;
using NuGet.Configuration;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>
/// The machine's Artifactory login (docs/39-ARTIFACTORY.md, <see cref="ArtifactoryLogin"/>): a token, a username and
/// password, both, or neither, against a local stand-in for an artifactory that serves one package. A fake environment
/// stands in for the real one, so no test sets a variable; the values here are examples and must appear nowhere.
/// </summary>
public sealed class ArtifactoryLoginTests : IDisposable
{
    private const string Token = "example-token-7Qx";
    private const string User = "example-user";
    private const string Password = "example-pw-9Lm";

    private readonly string _root = Path.Combine(Path.GetTempPath(), "artifactory-login-" + Guid.NewGuid().ToString("N"));

    public ArtifactoryLoginTests() => Directory.CreateDirectory(_root);

    public void Dispose()
    {
        try { Directory.Delete(_root, recursive: true); } catch (IOException) { }
    }

    private static Func<string, string?> Env(string? token = null, string? user = null, string? password = null) => name => name switch
    {
        ArtifactoryLogin.TokenVariable => token,
        ArtifactoryLogin.UsernameVariable => user,
        ArtifactoryLogin.PasswordVariable => password,
        _ => null,
    };

    private static void NoSecretIn(params string?[] texts)
    {
        var basic = Convert.ToBase64String(Encoding.UTF8.GetBytes($"{User}:{Password}"));
        foreach (var text in texts.Where(t => t is not null))
        {
            Assert.DoesNotContain(Token, text);
            Assert.DoesNotContain(Password, text);
            Assert.DoesNotContain(basic, text);
        }
    }

    /// <summary>A lookup of the stand-in's one package through the feed, as a scan makes it.</summary>
    private async Task<LookupResult> Lookup(StandIn standIn, ArtifactoryLogin login)
    {
        var source = new PackageSource(standIn.Index, "nuget-private") { AllowInsecureConnections = true, Credentials = login.Credential("nuget-private") };
        var feed = new Feed("nuget-private", source, standIn.Index, Feed.RoleClient, "engagement") { HeaderLogin = login.AuthenticatesWithHeader ? login : null };
        var lookup = new PackageLookup(new MemoryLookupCache(), Path.Combine(_root, "packages"), TimeSpan.FromHours(24), forceRefresh: false,
            DateTimeOffset.Parse("2026-11-19T00:00:00Z"));
        return await lookup.GetAsync(feed, "Acme.Json", CancellationToken.None);
    }

    [Fact]
    public async Task Token_only_is_sent_as_a_bearer_header_and_the_log_names_the_method_never_the_value()
    {
        using var standIn = new StandIn(acceptToken: Token);
        var log = new StringWriter();
        var login = ArtifactoryLogin.FromEnvironment(Env(token: Token), log);

        var (ok, text) = await login.CheckAsync(standIn.Index, TimeSpan.FromSeconds(30));
        var result = await Lookup(standIn, login);

        Assert.True(ok, text);
        Assert.Equal("1.0.0", Assert.Single(result.Entry!.Versions).Version);
        Assert.All(standIn.Requests, r => Assert.Equal("Bearer", r.Scheme));
        Assert.Equal((ArtifactoryLogin.MethodToken, ArtifactoryLogin.MethodToken), (login.Configured, login.Used));
        Assert.Contains("(login: token)", text);
        Assert.Contains("Artifactory login: token", log.ToString());
        Assert.DoesNotContain("WARNING", log.ToString());
        NoSecretIn(text, log.ToString(), JsonSerializer.Serialize(result));
    }

    [Fact]
    public async Task With_a_token_and_a_username_and_password_the_token_wins()
    {
        using var standIn = new StandIn(acceptToken: Token, acceptBasic: true);
        var login = ArtifactoryLogin.FromEnvironment(Env(Token, User, Password), new StringWriter());

        var result = await Lookup(standIn, login);

        Assert.NotNull(result.Entry);
        Assert.NotEmpty(standIn.Requests);
        Assert.All(standIn.Requests, r => Assert.Equal("Bearer", r.Scheme));
        Assert.Null(login.Credential("nuget-private"));          // NuGet is not handed the password beside the token
        Assert.Equal(ArtifactoryLogin.MethodToken, login.Used);
    }

    [Fact]
    public async Task A_rejected_token_falls_back_to_the_username_and_password_once_with_one_warning_and_is_not_retried()
    {
        using var standIn = new StandIn(acceptToken: null, acceptBasic: true);
        var log = new StringWriter();
        var login = ArtifactoryLogin.FromEnvironment(Env(Token, User, Password), log);

        var (ok, text) = await login.CheckAsync(standIn.Index, TimeSpan.FromSeconds(30));
        var first = await Lookup(standIn, login);
        var second = await Lookup(standIn, login);

        Assert.True(ok, text);
        Assert.NotNull(first.Entry);
        Assert.NotNull(second.Entry);
        Assert.Single(standIn.Requests, r => r.Scheme == "Bearer");          // the token was tried once, then never again
        Assert.True(standIn.Requests.Count(r => r.Scheme == "Basic") >= 3);
        Assert.Equal(ArtifactoryLogin.MethodTokenRejectedFellBack, login.Used);
        Assert.Contains("(login: token rejected, used username and password)", text);
        var warnings = log.ToString().Split('\n').Where(l => l.StartsWith("WARNING")).ToList();
        Assert.Single(warnings);
        Assert.Contains($"rejected {ArtifactoryLogin.TokenVariable} (401)", warnings[0]);
        Assert.Contains(standIn.Index, warnings[0]);
        NoSecretIn(text, log.ToString(), JsonSerializer.Serialize(first), JsonSerializer.Serialize(second));
    }

    [Theory]
    [InlineData(401)]
    [InlineData(403)]
    public async Task A_rejected_token_without_a_username_and_password_fails_saying_the_token_was_rejected(int status)
    {
        using var standIn = new StandIn(acceptToken: null, refusal: status);
        var log = new StringWriter();
        var login = ArtifactoryLogin.FromEnvironment(Env(token: Token), log);

        var (ok, text) = await login.CheckAsync(standIn.Index, TimeSpan.FromSeconds(30));
        var result = await Lookup(standIn, login);

        Assert.False(ok);
        Assert.Contains($"rejected {ArtifactoryLogin.TokenVariable} ({status})", text);
        Assert.Null(result.Entry);
        Assert.Equal(LookupFailure.Auth, result.Failure);
        Assert.Equal($"artifactory 'nuget-private' rejected {ArtifactoryLogin.TokenVariable} ({status}): set a valid token, "
                     + $"or {ArtifactoryLogin.UsernameVariable} and {ArtifactoryLogin.PasswordVariable} to fall back to", result.Error);
        Assert.Equal(ArtifactoryLogin.MethodTokenRejected, login.Used);
        Assert.Single(log.ToString().Split('\n'), l => l.StartsWith("WARNING"));
        // The token, and NuGet's own empty answer to the 401 challenge (as for any anonymous feed); never a login.
        Assert.Contains(standIn.Requests, r => r.Scheme == "Bearer");
        Assert.DoesNotContain(standIn.Requests, r => r.Login);
        NoSecretIn(text, log.ToString(), JsonSerializer.Serialize(result));
    }

    [Fact]
    public async Task Only_a_username_and_password_is_exactly_as_before_nugets_own_credential_and_nothing_logged()
    {
        using var standIn = new StandIn(acceptToken: null, acceptBasic: true);
        var log = new StringWriter();
        var login = ArtifactoryLogin.FromEnvironment(Env(user: User, password: Password), log);

        var credential = login.Credential("nuget-private");
        var result = await Lookup(standIn, login);

        Assert.False(login.AuthenticatesWithHeader);                         // no handler in front of NuGet's
        Assert.Equal((User, Password), (credential!.Username, credential.Password));
        Assert.NotNull(result.Entry);
        Assert.DoesNotContain(standIn.Requests, r => r.Scheme == "Bearer");
        Assert.Contains(standIn.Requests, r => r.Scheme == "Basic");
        Assert.Equal(ArtifactoryLogin.MethodUsernamePassword, login.Used);
        Assert.Equal("", log.ToString());
    }

    [Fact]
    public async Task Nothing_set_asks_anonymously_as_before_and_an_empty_token_counts_as_not_set()
    {
        using var standIn = new StandIn(acceptToken: null, anonymous: true);
        foreach (var env in new[] { Env(), Env(token: ""), Env(token: "  ") })
        {
            var log = new StringWriter();
            var login = ArtifactoryLogin.FromEnvironment(env, log);
            var result = await Lookup(standIn, login);

            Assert.False(login.HasToken);
            Assert.Null(login.Credential("nuget-private"));
            Assert.NotNull(result.Entry);
            Assert.Equal(ArtifactoryLogin.MethodNone, login.Used);
            Assert.Equal("", log.ToString());
        }

        Assert.All(standIn.Requests, r => Assert.Null(r.Scheme));
        var withPassword = ArtifactoryLogin.FromEnvironment(Env(token: "", user: User, password: Password), new StringWriter());
        Assert.Equal(ArtifactoryLogin.MethodUsernamePassword, withPassword.Configured);
    }

    [Fact]
    public async Task The_connection_check_asks_the_artifactory_every_time_never_a_cache_of_its_answer()
    {
        using var standIn = new StandIn(acceptToken: null, acceptBasic: true);

        var first = await ArtifactoryLogin.FromEnvironment(Env(user: User, password: Password), new StringWriter())
            .CheckAsync(standIn.Index, TimeSpan.FromSeconds(30));
        var asked = standIn.Requests.Count;
        var second = await ArtifactoryLogin.FromEnvironment(Env(Token, User, Password), new StringWriter())
            .CheckAsync(standIn.Index, TimeSpan.FromSeconds(30));

        Assert.True(first.Ok, first.Text);
        Assert.True(second.Ok, second.Text);
        Assert.Contains("(login: token rejected, used username and password)", second.Text);
        Assert.Contains(standIn.Requests.Skip(asked), r => r.Scheme == "Bearer");        // the second check was sent
    }

    [Fact]
    public async Task A_timeout_is_reported_as_it_is_and_never_switches_to_the_username_and_password()
    {
        using var standIn = new StandIn(acceptToken: Token, hang: true);
        var log = new StringWriter();
        var login = ArtifactoryLogin.FromEnvironment(Env(Token, User, Password), log);

        var (ok, text) = await login.CheckAsync(standIn.Index, TimeSpan.FromSeconds(2));

        Assert.False(ok);
        Assert.Contains("no answer within 2 seconds", text);
        Assert.False(login.TokenRejected);
        Assert.Equal(ArtifactoryLogin.MethodToken, login.Used);
        Assert.DoesNotContain("WARNING", log.ToString());
        Assert.All(standIn.Requests, r => Assert.Equal("Bearer", r.Scheme));
    }

    [Fact]
    public async Task An_unreachable_artifactory_never_switches_the_login()
    {
        var log = new StringWriter();
        var login = ArtifactoryLogin.FromEnvironment(Env(Token, User, Password), log);

        var (ok, text) = await login.CheckAsync("http://127.0.0.1:9/v3/index.json", TimeSpan.FromSeconds(20));

        Assert.False(ok);
        Assert.Contains("could not be reached", text);
        Assert.False(login.TokenRejected);
        Assert.DoesNotContain("WARNING", log.ToString());
        NoSecretIn(text, log.ToString());
    }

    [Fact]
    public async Task The_token_and_the_username_and_password_give_the_same_answer()
    {
        using var withToken = new StandIn(acceptToken: Token);
        using var withPassword = new StandIn(acceptToken: null, acceptBasic: true);

        var a = await Lookup(withToken, ArtifactoryLogin.FromEnvironment(Env(token: Token), new StringWriter()));
        var b = await Lookup(withPassword, ArtifactoryLogin.FromEnvironment(Env(user: User, password: Password), new StringWriter()));

        Assert.Equal(JsonSerializer.Serialize(a.Entry!.Versions), JsonSerializer.Serialize(b.Entry!.Versions));
    }

    // ---------- which feeds the machine token reaches (FeedResolver) ----------

    private FeedSet Resolve(string config, Func<string, string?> env) =>
        ResolveIn(_root, config, env);

    private static FeedSet ResolveIn(string root, string config, Func<string, string?> env)
    {
        File.WriteAllText(Path.Combine(root, "NuGet.config"), $"""<?xml version="1.0" encoding="utf-8"?><configuration>{config}</configuration>""");
        return FeedResolver.Resolve(root, root, comparePublicFeed: false,
            engagementFeeds: [new EngagementFeed("nuget-private", "http://localhost:8081/repository/nuget-private/index.json")], environment: env);
    }

    [Fact]
    public void An_engagement_feed_without_a_login_of_its_own_is_asked_with_the_token_and_not_handed_to_nuget()
    {
        var feed = Assert.Single(Resolve("<packageSources><clear /></packageSources>", Env(Token, User, Password)).All);
        Assert.NotNull(feed.HeaderLogin);
        Assert.Null(feed.Source.Credentials);
        NoSecretIn(feed.Url, JsonSerializer.Serialize(feed.ToRecord()));
    }

    [Fact]
    public void A_feeds_own_variable_and_nuget_config_credentials_still_win_over_the_token()
    {
        Func<string, string?> own = name => name == EngagementFeeds.PerFeedPrefix + "nuget-private" ? "Username=own;Password=example-own" : Env(Token)(name);
        var feed = Assert.Single(Resolve("<packageSources><clear /></packageSources>", own).All);
        Assert.Null(feed.HeaderLogin);
        Assert.Equal("own", feed.Source.Credentials!.Username);

        var declared = Assert.Single(Resolve("""
            <packageSources><clear /><add key="declared" value="http://localhost:8081/repository/nuget-private/index.json" /></packageSources>
            <packageSourceCredentials><declared><add key="Username" value="fromconfig" /><add key="ClearTextPassword" value="example-cfgpw" /></declared></packageSourceCredentials>
            """, Env(Token)).All);
        Assert.Null(declared.HeaderLogin);
        Assert.Equal("fromconfig", declared.Source.Credentials!.Username);
    }

    [Fact]
    public void A_declared_source_without_credentials_is_asked_with_the_token()
    {
        var feed = Assert.Single(Resolve("""<packageSources><clear /><add key="declared" value="http://localhost:8081/repository/nuget-private/index.json" /></packageSources>""",
            Env(Token)).All);
        Assert.Equal("declared", feed.Name);
        Assert.NotNull(feed.HeaderLogin);
        Assert.Null(feed.Source.Credentials);
    }

    /// <summary>
    /// A local stand-in for an artifactory: a NuGet v3 service index and one package's registration, behind a login.
    /// It accepts the given bearer token, the example username and password (with a Basic challenge, as Artifactory
    /// sends), or anyone; refuses everything else with <c>refusal</c>; or never answers. Every request's
    /// authorization scheme is recorded, never its value.
    /// </summary>
    private sealed class StandIn : IDisposable
    {
        private readonly TcpListener _listener = new(IPAddress.Loopback, 0);
        private readonly CancellationTokenSource _stop = new();

        public StandIn(string? acceptToken, bool acceptBasic = false, bool anonymous = false, int refusal = 401, bool hang = false)
        {
            _listener.Start();
            var port = ((IPEndPoint)_listener.LocalEndpoint).Port;
            Base = $"http://127.0.0.1:{port}";
            var basic = "Basic " + Convert.ToBase64String(Encoding.UTF8.GetBytes($"{User}:{Password}"));
            _ = Task.Run(async () =>
            {
                try
                {
                    while (!_stop.IsCancellationRequested)
                    {
                        var client = await _listener.AcceptTcpClientAsync(_stop.Token);
                        _ = Task.Run(async () =>
                        {
                            using (client)
                            {
                                try
                                {
                                    var (path, authorization) = await ReadRequest(client.GetStream());
                                    Requests.Enqueue(new Request(path, authorization?.Split(' ')[0], authorization == basic));
                                    if (hang)
                                    {
                                        await Task.Delay(Timeout.Infinite, _stop.Token);
                                        return;
                                    }

                                    var allowed = anonymous
                                                  || (acceptToken is not null && authorization == "Bearer " + acceptToken)
                                                  || (acceptBasic && authorization == basic);
                                    var (status, body, extra) = !allowed
                                        ? (refusal, "", "WWW-Authenticate: Basic realm=\"stand-in\"\r\n")
                                        : Answer(path) is { } json ? (200, json, "Content-Type: application/json\r\n") : (404, "", "");
                                    var bytes = Encoding.UTF8.GetBytes(body);
                                    var head = Encoding.ASCII.GetBytes(
                                        $"HTTP/1.1 {status} {(HttpStatusCode)status}\r\n{extra}Content-Length: {bytes.Length}\r\nConnection: close\r\n\r\n");
                                    await client.GetStream().WriteAsync(head.Concat(bytes).ToArray(), _stop.Token);
                                }
                                catch (Exception e) when (e is IOException or OperationCanceledException or ObjectDisposedException) { }
                            }
                        });
                    }
                }
                catch (Exception e) when (e is OperationCanceledException or ObjectDisposedException or SocketException) { }
            });
        }

        /// <param name="Login">Whether the request carried the example username and password.</param>
        public sealed record Request(string Path, string? Scheme, bool Login);

        public ConcurrentQueue<Request> Requests { get; } = new();

        private string Base { get; }

        public string Index => Base + "/v3/index.json";

        private static async Task<(string Path, string? Authorization)> ReadRequest(NetworkStream stream)
        {
            var buffer = new byte[16384];
            var text = new StringBuilder();
            while (!text.ToString().Contains("\r\n\r\n"))
            {
                var read = await stream.ReadAsync(buffer);
                if (read == 0) break;
                text.Append(Encoding.ASCII.GetString(buffer, 0, read));
            }

            var lines = text.ToString().Split("\r\n");
            var path = lines[0].Split(' ')[1];
            var authorization = lines.Skip(1).FirstOrDefault(l => l.StartsWith("Authorization:", StringComparison.OrdinalIgnoreCase))?[14..].Trim();
            return (path, authorization);
        }

        private string? Answer(string path) => path switch
        {
            "/v3/index.json" => $$"""
                {"version":"3.0.0","resources":[
                  {"@id":"{{Base}}/registration/","@type":"RegistrationsBaseUrl/3.6.0"},
                  {"@id":"{{Base}}/flat/","@type":"PackageBaseAddress/3.0.0"}]}
                """,
            "/registration/acme.json/index.json" => $$"""
                {"count":1,"items":[{"@id":"{{Base}}/registration/acme.json/index.json#page/1.0.0/1.0.0","count":1,"lower":"1.0.0","upper":"1.0.0",
                  "items":[{"@id":"{{Base}}/registration/acme.json/1.0.0.json",
                    "catalogEntry":{"@id":"{{Base}}/catalog/acme.json.1.0.0.json","id":"Acme.Json","version":"1.0.0","listed":true,
                      "dependencyGroups":[{"targetFramework":"net8.0"}]},
                    "packageContent":"{{Base}}/flat/acme.json/1.0.0/acme.json.1.0.0.nupkg"}]}]}
                """,
            _ => null,
        };

        public void Dispose()
        {
            _stop.Cancel();
            _listener.Stop();
        }
    }
}
