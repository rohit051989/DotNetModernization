using System.Net;
using System.Net.Http.Headers;
using System.Text;
using NuGet.Configuration;
using NuGet.Protocol;
using NuGet.Protocol.Core.Types;

namespace Fingerprinting.Dependencies;

/// <summary>
/// This machine's login for the artifactories an engagement lists (docs/39-ARTIFACTORY.md), from
/// <c>ARTIFACTORY_TOKEN</c>, <c>ARTIFACTORY_USERNAME</c> and <c>ARTIFACTORY_PASSWORD</c>. The one place that decides how a
/// call to such an artifactory authenticates; every call the step programs make to one goes through it, and preflight's
/// connection check runs the same code (<c>DependencyAssessment.Cli --check-artifactory</c>).
/// <list type="bullet">
/// <item>A token (an empty value counts as not set) is sent as <c>Authorization: Bearer</c>; with a username and
/// password as well, the token wins.</item>
/// <item>A token answered with 401 or 403 when a username and password are set: one warning, then the username and
/// password for the rest of the run; the token is not tried again. Without them, the lookup fails and says the token was
/// rejected.</item>
/// <item>Only a username and password, or nothing: exactly as before the token existed (NuGet's own credential).</item>
/// <item>A network error or a timeout is reported as it is; it never switches the login.</item>
/// </list>
/// No value ever reaches a log, a URL, a result, the database or a file: what may be said is the method
/// (<see cref="Used"/>).
/// </summary>
public sealed class ArtifactoryLogin
{
    public const string TokenVariable = "ARTIFACTORY_TOKEN";
    public const string UsernameVariable = "ARTIFACTORY_USERNAME";
    public const string PasswordVariable = "ARTIFACTORY_PASSWORD";

    public const string MethodToken = "token";
    public const string MethodUsernamePassword = "username and password";
    public const string MethodTokenRejectedFellBack = "token rejected, used username and password";
    public const string MethodTokenRejected = "token rejected";
    public const string MethodNone = "none";

    private readonly string? _token;
    private readonly string? _username;
    private readonly string? _password;
    private readonly TextWriter _log;
    private int _rejected;
    private int _announced;

    private ArtifactoryLogin(string? token, string? username, string? password, TextWriter log)
    {
        _token = string.IsNullOrWhiteSpace(token) ? null : token.Trim();
        // As before the token: a username that is set and a password that is present.
        (_username, _password) = !string.IsNullOrEmpty(username) && password is not null ? (username, password) : (null, null);
        _log = log;
    }

    /// <summary>The login of this process, read once from its environment; its state (a rejected token) lasts the run.</summary>
    public static ArtifactoryLogin Current { get; } = FromEnvironment();

    /// <param name="environment">The environment variables, overridable so tests need not set any.</param>
    /// <param name="log">Where the warning goes; the step's log (standard error) by default.</param>
    public static ArtifactoryLogin FromEnvironment(Func<string, string?>? environment = null, TextWriter? log = null)
    {
        environment ??= Environment.GetEnvironmentVariable;
        return new ArtifactoryLogin(environment(TokenVariable), environment(UsernameVariable), environment(PasswordVariable), log ?? Console.Error);
    }

    public bool HasToken => _token is not null;

    public bool HasUsernameAndPassword => _username is not null;

    /// <summary>Whether an artifactory answered the token with 401 or 403 in this run.</summary>
    public bool TokenRejected => Volatile.Read(ref _rejected) == 1;

    /// <summary>The configured method: "token", "username and password" or "none".</summary>
    public string Configured => HasToken ? MethodToken : HasUsernameAndPassword ? MethodUsernamePassword : MethodNone;

    /// <summary>The method this run has used so far, for a log or the UI; never a value.</summary>
    public string Used => !TokenRejected ? Configured : HasUsernameAndPassword ? MethodTokenRejectedFellBack : MethodTokenRejected;

    /// <summary>
    /// The credential NuGet sends itself, as before the token existed: the username and password when no token is set.
    /// Null with a token (<see cref="AuthenticatesWithHeader"/> sends it instead) and with no login at all.
    /// </summary>
    public PackageSourceCredential? Credential(string sourceName) =>
        !HasToken && HasUsernameAndPassword
            ? new PackageSourceCredential(sourceName, _username!, _password!, isPasswordClearText: true, validAuthenticationTypesText: null)
            : null;

    /// <summary>Whether a feed using the machine login is authenticated by <see cref="Handler"/> (a token is set).</summary>
    public bool AuthenticatesWithHeader => HasToken;

    /// <summary>The header for the next request: the token, or after it was rejected the username and password.</summary>
    internal AuthenticationHeaderValue Header() =>
        TokenRejected && HasUsernameAndPassword
            ? new AuthenticationHeaderValue("Basic", Convert.ToBase64String(Encoding.UTF8.GetBytes($"{_username}:{_password}")))
            : new AuthenticationHeaderValue("Bearer", _token);

    /// <summary>An artifactory answered the token with <paramref name="status"/>. Returns whether to retry with the
    /// username and password. Warns once per run, naming the artifactory by its normalised URL and never a value.</summary>
    internal bool Reject(int status, string artifactory)
    {
        if (Interlocked.Exchange(ref _rejected, 1) == 0)
        {
            _log.WriteLine(HasUsernameAndPassword
                ? $"WARNING: artifactory {artifactory} rejected {TokenVariable} ({status}); this run uses {UsernameVariable} and {PasswordVariable} instead and does not try the token again (login: {MethodTokenRejectedFellBack})."
                : $"WARNING: artifactory {artifactory} rejected {TokenVariable} ({status}), and no {UsernameVariable} and {PasswordVariable} are set: lookups that need the login fail (login: {MethodTokenRejected}).");
        }

        return HasUsernameAndPassword;
    }

    /// <summary>Said once per run, the first time the token is sent.</summary>
    internal void Announce()
    {
        if (Interlocked.Exchange(ref _announced, 1) == 0) _log.WriteLine($"Artifactory login: {MethodToken} ({TokenVariable}).");
    }

    /// <summary>The message for a lookup that failed because the token was rejected and nothing else was set.</summary>
    public string RejectedMessage(string feedName, int? status) =>
        $"artifactory '{feedName}' rejected {TokenVariable}{(status is null ? "" : $" ({status})")}: set a valid token, "
        + $"or {UsernameVariable} and {PasswordVariable} to fall back to";

    /// <summary>A source repository for <paramref name="source"/> whose requests to the source's own host carry this login.</summary>
    public SourceRepository Repository(PackageSource source)
    {
        var providers = new List<Lazy<INuGetResourceProvider>> { new(() => new HandlerProvider(this)) };
        providers.AddRange(NuGet.Protocol.Core.Types.Repository.Provider.GetCoreV3());
        return NuGet.Protocol.Core.Types.Repository.CreateSource(providers, source);
    }

    /// <summary>
    /// Preflight's connection check (<c>DependencyAssessment.Cli --check-artifactory &lt;url&gt;...</c>): asks one
    /// artifactory for its service index with this login, as a scan would ask it. The text names the artifactory by its
    /// normalised URL, the outcome and the method used; never a value.
    /// </summary>
    public async Task<(bool Ok, string Text)> CheckAsync(string url, TimeSpan timeout)
    {
        var shown = FeedResolver.NormaliseUrl(url, Path.GetPathRoot(Path.GetTempPath())!);
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri) || uri.IsFile) return (false, $"{shown}: not an http or https URL");
        const string name = "artifactory-check";
        var source = new PackageSource(url.Trim(), name) { AllowInsecureConnections = uri.Scheme == Uri.UriSchemeHttp, Credentials = Credential(name) };
        var repository = AuthenticatesWithHeader ? Repository(source) : NuGet.Protocol.Core.Types.Repository.Factory.GetCoreV3(source);
        using var limit = new CancellationTokenSource(timeout);
        try
        {
            // The service index asked over the network every time, never from NuGet's disk cache of it (kept for
            // 40 minutes): a check answered from a cache would say nothing about the connection or the login.
            var http = await repository.GetResourceAsync<HttpSourceResource>(limit.Token);
            var status = await http.HttpSource.ProcessResponseAsync(new HttpSourceRequest(url.Trim(), NuGet.Common.NullLogger.Instance),
                response => Task.FromResult((int)response.StatusCode), NuGet.Common.NullLogger.Instance, limit.Token);
            if (status is >= 200 and < 300) return (true, $"{shown}: answered (login: {Used})");
            var refused = status is 401 or 403
                ? HasToken && TokenRejected && !HasUsernameAndPassword ? $"rejected {TokenVariable} ({status})" : $"refused the login ({status})"
                : $"answered {status}";
            return (false, $"{shown}: {refused} (login: {Used})");
        }
        catch (Exception ex) when (ex is NuGet.Protocol.Core.Types.FatalProtocolException or HttpRequestException or OperationCanceledException or IOException or InvalidOperationException)
        {
            var status = PackageLookup.HttpStatusOf(ex);
            var why = status is 401 or 403
                ? HasToken && TokenRejected && !HasUsernameAndPassword ? $"rejected {TokenVariable} ({status})" : $"refused the login ({status})"
                : ex is OperationCanceledException ? $"no answer within {timeout.TotalSeconds:0} seconds"
                : status is { } code ? $"answered {code}"
                : "could not be reached: " + PackageLookup.Message(ex).Split('\n')[0].Trim();
            return (false, $"{shown}: {why} (login: {Used})");
        }
    }

    /// <summary>NuGet's own HTTP handler for the source, with <see cref="TokenHandler"/> in front of it.</summary>
    private sealed class HandlerProvider(ArtifactoryLogin login)
        : ResourceProvider(typeof(HttpHandlerResource), nameof(ArtifactoryLogin) + nameof(HandlerProvider), NuGetResourceProviderPositions.First)
    {
        public override async Task<Tuple<bool, INuGetResource?>> TryCreate(SourceRepository source, CancellationToken token)
        {
            var (created, resource) = await new HttpHandlerResourceV3Provider().TryCreate(source, token);
            if (!created || resource is not HttpHandlerResourceV3 nuget) return Tuple.Create(created, resource);
            var authority = new Uri(source.PackageSource.Source).GetLeftPart(UriPartial.Authority);
            var handler = new TokenHandler(login, authority, source.PackageSource.Source) { InnerHandler = nuget.MessageHandler };
            return Tuple.Create<bool, INuGetResource?>(true, new HttpHandlerResourceV3(nuget.ClientHandler, handler));
        }
    }

    /// <summary>Adds the login to every request to the artifactory's own host (never to another host it links to), and
    /// on a 401 or 403 to the token switches to the username and password when there are any.</summary>
    private sealed class TokenHandler(ArtifactoryLogin login, string authority, string source) : DelegatingHandler
    {
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            if (request.RequestUri is null
                || !request.RequestUri.GetLeftPart(UriPartial.Authority).Equals(authority, StringComparison.OrdinalIgnoreCase))
            {
                return await base.SendAsync(request, cancellationToken);
            }

            var header = login.Header();
            if (header.Scheme == "Bearer") login.Announce();
            request.Headers.Authorization = header;
            var response = await base.SendAsync(request, cancellationToken);
            if (header.Scheme != "Bearer" || response.StatusCode is not (HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden) || request.Content is not null)
            {
                return response;
            }

            if (!login.Reject((int)response.StatusCode, FeedResolver.NormaliseUrl(source, Path.GetPathRoot(Path.GetTempPath())!)))
            {
                return response;
            }

            response.Dispose();
            var retry = Copy(request);
            retry.Headers.Authorization = login.Header();
            return await base.SendAsync(retry, cancellationToken);
        }

        /// <summary>A bodiless request (NuGet's lookups are GETs) sent again: same method, URL, headers and options.</summary>
        private static HttpRequestMessage Copy(HttpRequestMessage request)
        {
            var copy = new HttpRequestMessage(request.Method, request.RequestUri) { Version = request.Version, VersionPolicy = request.VersionPolicy };
            foreach (var header in request.Headers.Where(h => h.Key != "Authorization")) copy.Headers.TryAddWithoutValidation(header.Key, header.Value);
            foreach (var option in request.Options) ((IDictionary<string, object?>)copy.Options)[option.Key] = option.Value;
            return copy;
        }
    }
}
