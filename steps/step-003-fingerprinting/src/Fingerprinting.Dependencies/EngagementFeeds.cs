using System.Text.Json;
using NuGet.Configuration;

namespace Fingerprinting.Dependencies;

/// <summary>A feed the engagement lists in the platform's Artifactory tab (docs/39-ARTIFACTORY.md): a name and a
/// URL, never a login. The engine passes them in <c>step_context.artifactories</c>.</summary>
public sealed record EngagementFeed(string Name, string Url);

/// <summary>
/// The engagement's feeds and the login they are asked with. Order of authority, per feed:
/// 1. NuGet.config — a source it declares with the same URL, with its own credentials, is used as it is.
/// 2. <c>NuGetPackageSourceCredentials_&lt;name&gt;</c> in the environment, NuGet's own format
///    (<c>Username=...;Password=...</c>), for a feed with its own login.
/// 3. <c>ARTIFACTORY_USERNAME</c> and <c>ARTIFACTORY_PASSWORD</c>: one login for every engagement feed that has neither of the above.
/// The login lives in memory for the run; nothing derived from it is recorded or cached (Part B4).
/// </summary>
public static class EngagementFeeds
{
    public const string UsernameVariable = "ARTIFACTORY_USERNAME";
    public const string PasswordVariable = "ARTIFACTORY_PASSWORD";
    public const string PerFeedPrefix = "NuGetPackageSourceCredentials_";

    /// <summary>The feeds in <c>step_context.artifactories</c>; empty when the engine gave none.</summary>
    public static IReadOnlyList<EngagementFeed> From(JsonElement? stepContext)
    {
        if (stepContext is not { ValueKind: JsonValueKind.Object } context
            || !context.TryGetProperty("artifactories", out var feeds) || feeds.ValueKind != JsonValueKind.Array) return [];
        var list = new List<EngagementFeed>();
        foreach (var item in feeds.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object) continue;
            var name = item.TryGetProperty("name", out var n) && n.ValueKind == JsonValueKind.String ? n.GetString() : null;
            var url = item.TryGetProperty("url", out var u) && u.ValueKind == JsonValueKind.String ? u.GetString() : null;
            if (!string.IsNullOrWhiteSpace(name) && !string.IsNullOrWhiteSpace(url)) list.Add(new EngagementFeed(name!, url!));
        }

        return list;
    }

    /// <summary>The feeds as a short text for a checkpoint key: a changed list means earlier answers are not reused.</summary>
    public static string Key(IReadOnlyList<EngagementFeed>? feeds) =>
        feeds is { Count: > 0 } ? "|feeds:" + string.Join(",", feeds.Select(f => f.Url)) : "";

    /// <summary>The login for a feed called <paramref name="name"/>, or null when the environment has none.</summary>
    public static PackageSourceCredential? Credential(string name, Func<string, string?>? environment = null)
    {
        environment ??= Environment.GetEnvironmentVariable;
        if (Parse(environment(PerFeedPrefix + name)) is { } own) return Build(name, own.User, own.Password);
        var user = environment(UsernameVariable);
        var password = environment(PasswordVariable);
        return !string.IsNullOrEmpty(user) && password is not null ? Build(name, user, password) : null;
    }

    /// <summary>NuGet's <c>Username=...;Password=...</c> form.</summary>
    public static (string User, string Password)? Parse(string? value)
    {
        if (string.IsNullOrWhiteSpace(value)) return null;
        string? user = null, password = null;
        foreach (var part in value.Split(';', StringSplitOptions.RemoveEmptyEntries))
        {
            var at = part.IndexOf('=');
            if (at < 0) continue;
            var key = part[..at].Trim();
            var text = part[(at + 1)..];
            if (key.Equals("Username", StringComparison.OrdinalIgnoreCase)) user = text;
            else if (key.Equals("Password", StringComparison.OrdinalIgnoreCase)) password = text;
        }

        return user is null || password is null ? null : (user, password);
    }

    private static PackageSourceCredential Build(string name, string user, string password) =>
        new(name, user, password, isPasswordClearText: true, validAuthenticationTypesText: null);
}
