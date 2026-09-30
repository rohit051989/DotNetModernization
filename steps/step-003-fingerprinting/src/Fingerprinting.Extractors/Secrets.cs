using System.Data.Common;
using System.Text.RegularExpressions;

namespace Fingerprinting.Extractors;

/// <summary>
/// 21-STEP-003-FINGERPRINTING.md Part G, in one place so ConfigurationExtractor
/// and PathLiteralExtractor cannot drift apart on it.
///
/// The invariant is <b>nothing derived from a connection string is ever
/// persisted</b>. A connection string may be read into memory for exactly one
/// purpose — <see cref="UsesWindowsAuthentication"/> — which returns a bool
/// and keeps nothing. No other code in step 3 reads a connection string or a
/// sensitive key's value, and no signal value, evidence field or hash is ever
/// computed from one.
/// </summary>
internal static class Secrets
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
}
