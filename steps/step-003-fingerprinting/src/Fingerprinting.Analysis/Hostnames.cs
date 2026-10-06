using System.Net;
using System.Text.RegularExpressions;

namespace Fingerprinting.Analysis;

/// <summary>
/// Unqualified hostnames — a single label such as <c>appsrv0341</c> in an
/// endpoint URL. On Windows one resolves through NetBIOS or the DNS suffix
/// search list; in an OpenShift pod, only if the cluster's DNS search domains
/// cover it. Shared by step 3's UNQUALIFIED_HOSTNAME_URL signal and step 5's
/// verdict so the two cannot disagree.
/// </summary>
public static partial class Hostnames
{
    [GeneratedRegex(@"^[A-Za-z0-9][A-Za-z0-9-]*$", RegexOptions.CultureInvariant)]
    private static partial Regex SingleLabel();

    // scheme://[userinfo@]host[:port] — the host only, never userinfo, path or query.
    [GeneratedRegex(@"\b(?:https?|net\.tcp|net\.pipe|wss?|ftp)://(?:[^/@\s""'<>]*@)?(?<host>[^/:\s""'<>?#]+)", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex UrlHost();

    public const string Reason =
        "unqualified hostname '{0}': resolves on Windows through NetBIOS or the DNS suffix search, " +
        "but in an OpenShift pod only if the cluster's DNS search domains cover it — use the fully qualified name";

    /// <summary>True for a single-label name that is not a loopback name, an
    /// IP address, a placeholder or a wildcard.</summary>
    public static bool IsUnqualified(string? host)
    {
        if (string.IsNullOrWhiteSpace(host))
        {
            return false;
        }

        var value = host.Trim().TrimEnd('.');
        return SingleLabel().IsMatch(value)
               && value.Any(char.IsLetter)
               && !value.Equals("localhost", StringComparison.OrdinalIgnoreCase)
               && !IPAddress.TryParse(value, out _);
    }

    /// <summary>The unqualified hosts of the URLs in <paramref name="text"/>, lowercased.</summary>
    public static IEnumerable<string> UnqualifiedInUrls(string text) =>
        UrlHost().Matches(text).Select(m => m.Groups["host"].Value.ToLowerInvariant()).Where(IsUnqualified).Distinct(StringComparer.Ordinal);
}
