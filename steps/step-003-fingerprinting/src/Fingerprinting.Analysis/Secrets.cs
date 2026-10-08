using System.Data.Common;
using System.Text.RegularExpressions;

namespace Fingerprinting.Analysis;

/// <summary>
/// 21-APPLICATION-FINGERPRINTING.md Part G and 29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md
/// Part C5, in one place so steps 3 and 5 cannot drift apart on them.
///
/// The invariant is <b>nothing derived from a connection string is ever
/// persisted beyond what these methods return</b>. A connection string may
/// be read into memory for exactly two purposes: <see cref="UsesWindowsAuthentication"/>
/// (step 3), which returns a bool, and <see cref="ReadConnectionFacts"/>
/// (step 5), which returns the server host and port, the provider and the
/// kind of authentication — never the database name, user, password or any
/// other keyword. Nothing else reads a connection string or a sensitive
/// key's value, and no value, evidence field or hash is computed from one.
/// </summary>
public static class Secrets
{
    private static readonly string[] SensitiveKeyPatterns =
        ["password", "pwd", "secret", "token", "apikey", "api_key", "connectionstring", "accountkey", "sharedaccesskey", "credential"];

    /// <summary>A configuration key (or XML attribute) whose name marks its
    /// value as secret: record its presence, never its value.</summary>
    public static bool IsSensitiveKey(string key) =>
        SensitiveKeyPatterns.Any(pattern => key.Contains(pattern, StringComparison.OrdinalIgnoreCase));

    // A keyword=value pair a connection string starts with or contains after
    // a ';'. Used only to recognise a connection string written somewhere
    // other than a ConnectionStrings section (a C# literal, an appSettings
    // value) so it can be skipped wholesale.
    private static readonly Regex ConnectionStringKeyword = new(
        @"(^|;)\s*(server|data source|datasource|initial catalog|database|user id|uid|password|pwd|" +
        @"integrated security|trusted_connection|attachdbfilename|provider|host|port|username|sslmode)\s*=",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

    /// <summary>True for text shaped like a connection string: two or more
    /// <c>keyword=value</c> pairs. PathLiteralExtractor skips such text
    /// entirely, so a Windows path inside a connection string never becomes a
    /// LITERAL row.</summary>
    public static bool LooksLikeConnectionString(string text) =>
        text.Contains('=') && text.Contains(';') && ConnectionStringKeyword.Matches(text).Count >= 2;

    /// <summary>
    /// The one permitted read of a connection string: does it authenticate
    /// with the process's Windows identity (Integrated Security / SSPI /
    /// Trusted_Connection)? Parsed with <see cref="DbConnectionStringBuilder"/>,
    /// inspected for those keywords only, and discarded — the caller receives
    /// a bool and nothing else. An Entity Framework 6 connection string wraps
    /// the provider's string in a <c>provider connection string</c> keyword;
    /// that inner string is checked the same way.
    /// </summary>
    public static bool UsesWindowsAuthentication(string connectionString)
    {
        var builder = new DbConnectionStringBuilder();
        try
        {
            builder.ConnectionString = connectionString;
        }
        catch (ArgumentException)
        {
            // Not parseable as keyword=value pairs — no verdict, and nothing kept.
            return false;
        }

        // "Integrated Security" and "Trusted_Connection" are synonyms, and
        // SqlClient lets the last one written win — eShopOnWeb's Docker
        // settings say "Integrated Security=true;…;Trusted_Connection=false",
        // which is SQL authentication. Keys are visited in the order written.
        bool? windowsAuth = null;
        foreach (string keyword in builder.Keys)
        {
            var value = builder[keyword]?.ToString()?.Trim() ?? string.Empty;
            switch (keyword.ToLowerInvariant())
            {
                case "integrated security":
                case "trusted_connection":
                    windowsAuth = IsTrueOrSspi(value);
                    break;
                case "provider connection string" when value.Length > 0:
                    if (UsesWindowsAuthentication(value))
                    {
                        return true;
                    }
                    break;
            }
        }

        return windowsAuth ?? false;
    }

    private static bool IsTrueOrSspi(string value) =>
        value.Equals("true", StringComparison.OrdinalIgnoreCase)
        || value.Equals("yes", StringComparison.OrdinalIgnoreCase)
        || value.Equals("sspi", StringComparison.OrdinalIgnoreCase);

    /// <summary>
    /// The one permitted read of a connection string for step 5 (Part C5):
    /// server host and port, provider, and how it authenticates. The host
    /// matters for the endpoint register; nothing else does. The string is
    /// parsed, inspected for these facts only, and discarded.
    /// </summary>
    public static ConnectionFacts ReadConnectionFacts(string connectionString, string? declaredProvider = null)
    {
        if (RedisFacts(connectionString) is { } redis)
        {
            return redis;
        }

        var builder = new DbConnectionStringBuilder();
        try
        {
            builder.ConnectionString = connectionString;
        }
        catch (ArgumentException)
        {
            return new ConnectionFacts(null, null, NormaliseProvider(declaredProvider), ConnectionAuthentication.Unknown, false);
        }

        string? server = null, port = null, provider = declaredProvider, inner = null;
        var hasUser = false;
        var hasPassword = false;
        foreach (string keyword in builder.Keys)
        {
            var value = builder[keyword]?.ToString()?.Trim() ?? string.Empty;
            switch (keyword.ToLowerInvariant())
            {
                case "server" or "data source" or "datasource" or "address" or "addr" or "network address" or "host" or "hostname":
                    server ??= value;
                    break;
                case "port":
                    port = value;
                    break;
                case "provider" when provider is null:
                    provider = value;
                    break;
                case "provider connection string":
                    inner = value;
                    break;
                case "user id" or "uid" or "user" or "username" or "user name":
                    hasUser = value.Length > 0;
                    break;
                case "password" or "pwd":
                    hasPassword = value.Length > 0;
                    break;
            }
        }

        if (inner is not null)
        {
            // Entity Framework 6: the provider's own string is inside.
            var facts = ReadConnectionFacts(inner, provider);
            return facts with { Provider = facts.Provider ?? NormaliseProvider(provider) };
        }

        var (host, parsedPort, localDb) = SplitServer(server);
        var windowsAuth = UsesWindowsAuthentication(connectionString);
        var authentication = windowsAuth ? ConnectionAuthentication.Integrated
            : hasUser || hasPassword ? ConnectionAuthentication.Credentials
            : ConnectionAuthentication.Unknown;
        return new ConnectionFacts(host, port ?? parsedPort, NormaliseProvider(provider) ?? InferProvider(builder), authentication, localDb);
    }

    /// <summary>
    /// A StackExchange.Redis configuration string — <c>host:6379,password=…,ssl=True</c>:
    /// comma-separated, no ';', the first option a bare <c>host[:port]</c>.
    /// Host and port only; whether a password option is present, never its value.
    /// </summary>
    private static ConnectionFacts? RedisFacts(string text)
    {
        if (text.Contains(';'))
        {
            return null;
        }

        var options = text.Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);
        if (options.Length == 0 || options[0].Contains('=') || !Regex.IsMatch(options[0], @"^[A-Za-z0-9._\-]+(:\d+)?$"))
        {
            return null;
        }

        var colon = options[0].LastIndexOf(':');
        var hasPassword = options.Skip(1).Any(o => o.StartsWith("password=", StringComparison.OrdinalIgnoreCase) && o.Length > "password=".Length);
        return new ConnectionFacts(
            (colon > 0 ? options[0][..colon] : options[0]).ToLowerInvariant(),
            colon > 0 ? options[0][(colon + 1)..] : null,
            "redis",
            hasPassword ? ConnectionAuthentication.Credentials : ConnectionAuthentication.Unknown,
            false);
    }

    /// <summary><c>tcp:host,1433</c>, <c>host\INSTANCE</c>, <c>(localdb)\x</c>,
    /// <c>host:5432</c> → host (lowercased) and port. An instance name is
    /// dropped: host only.</summary>
    private static (string? Host, string? Port, bool LocalDb) SplitServer(string? server)
    {
        if (string.IsNullOrWhiteSpace(server))
        {
            return (null, null, false);
        }

        var text = server.Trim();
        if (text.StartsWith("tcp:", StringComparison.OrdinalIgnoreCase))
        {
            text = text[4..];
        }

        var localDb = text.StartsWith("(localdb)", StringComparison.OrdinalIgnoreCase);
        string? port = null;
        var comma = text.IndexOf(',');
        if (comma >= 0)
        {
            port = text[(comma + 1)..].Trim();
            text = text[..comma];
        }

        var slash = text.IndexOf('\\');
        if (slash >= 0)
        {
            text = text[..slash];
        }

        var colon = text.LastIndexOf(':');
        if (colon > 0 && port is null && int.TryParse(text[(colon + 1)..], out _))
        {
            port = text[(colon + 1)..];
            text = text[..colon];
        }

        return (text.Trim().ToLowerInvariant(), port, localDb);
    }

    private static string? NormaliseProvider(string? provider) => provider?.Trim() switch
    {
        null or "" => null,
        var p when p.Contains("SqlClient", StringComparison.OrdinalIgnoreCase) => "sqlserver",
        var p when p.Contains("Npgsql", StringComparison.OrdinalIgnoreCase) => "postgresql",
        var p when p.Contains("MySql", StringComparison.OrdinalIgnoreCase) => "mysql",
        var p when p.Contains("Sqlite", StringComparison.OrdinalIgnoreCase) => "sqlite",
        var p when p.Contains("Oracle", StringComparison.OrdinalIgnoreCase) => "oracle",
        var p => p,
    };

    /// <summary>Only keywords unique to one provider decide; anything else
    /// is left unknown rather than guessed.</summary>
    private static string? InferProvider(DbConnectionStringBuilder builder)
    {
        var keys = builder.Keys.Cast<string>().Select(k => k.ToLowerInvariant()).ToHashSet();
        if (keys.Contains("initial catalog") || keys.Contains("integrated security") || keys.Contains("trusted_connection")
            || keys.Contains("multipleactiveresultsets") || keys.Contains("trustservercertificate"))
        {
            return "sqlserver";
        }

        return null;
    }
}

public enum ConnectionAuthentication
{
    Unknown,

    /// <summary>Integrated Security / SSPI / Trusted_Connection — the
    /// process's Windows identity.</summary>
    Integrated,

    /// <summary>A user or password is present (never kept).</summary>
    Credentials,
}

/// <summary>What step 5 may keep from a connection string — Part C5.</summary>
public sealed record ConnectionFacts(string? Host, string? Port, string? Provider, ConnectionAuthentication Authentication, bool LocalDb);
