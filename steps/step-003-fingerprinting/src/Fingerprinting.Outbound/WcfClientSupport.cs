using System.Security.Cryptography;
using System.Text.Json;

namespace Fingerprinting.Outbound;

/// <summary>
/// A WCF client matrix — schemas/wcf-client-support-*.json (runtime: does the
/// target's WCF client support it) or schemas/wcf-client-platform-*.json
/// (platform: does it work on Linux), one shape for both:
/// versioned, reviewed reference data, never rules in code. Each entry says
/// whether the target .NET's WCF client supports a binding, an effective
/// security mode and the credential type that mode uses, with the sources it
/// rests on (the dotnet/wcf supported-features chart and release notes) and
/// whether a person has confirmed it. <c>*</c> in an entry matches any value;
/// an exact entry wins over a wildcard one.
/// </summary>
public sealed class WcfClientSupport
{
    public sealed record Entry(
        string Id, string Target, string Binding, string SecurityMode, string CredentialType, string Verdict,
        IReadOnlyList<string> Sources, string Basis, string? Caveat, bool Confirmed, Fix? Fix = null);

    /// <summary>Platform entries that are not compatible: what must change, and
    /// who changes it — <c>we</c>, <c>backend_owner</c> or <c>we_or_backend_owner</c>.</summary>
    public sealed record Fix(string Who, string Change);

    public sealed record Default(string SecurityMode, string? TransportCredential, string? MessageCredential);

    public required string MatrixVersion { get; init; }
    public required string Sha256 { get; init; }
    public required IReadOnlyList<Entry> Entries { get; init; }
    public required IReadOnlyDictionary<string, Default> Defaults { get; init; }

    /// <summary>Every source id an entry may cite, with its title and version.</summary>
    public required IReadOnlyDictionary<string, string> Sources { get; init; }

    public static WcfClientSupport Load(string path)
    {
        var bytes = File.ReadAllBytes(path);
        using var document = JsonDocument.Parse(bytes);
        var root = document.RootElement;
        string? Text(JsonElement e, string name) => e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;

        var sources = root.GetProperty("sources").EnumerateArray()
            .ToDictionary(s => Text(s, "id")!, s => $"{Text(s, "title")} ({Text(s, "version")})", StringComparer.Ordinal);
        var entries = root.GetProperty("entries").EnumerateArray().Select(e => new Entry(
            Text(e, "id")!, Text(e, "target")!, Text(e, "binding")!, Text(e, "securityMode")!, Text(e, "credentialType")!,
            Text(e, "verdict")!, e.GetProperty("sources").EnumerateArray().Select(x => x.GetString()!).ToList(), Text(e, "basis")!,
            Text(e, "caveat"), Text(e.GetProperty("confirmation"), "status") == "confirmed",
            e.TryGetProperty("fix", out var fix) && fix.ValueKind == JsonValueKind.Object ? new Fix(Text(fix, "who")!, Text(fix, "change")!) : null)).ToList();
        // The runtime matrix carries the bindings' sourced defaults; the platform matrix need not.
        var defaults = root.TryGetProperty("defaults", out var d0)
            ? d0.EnumerateObject().ToDictionary(
                d => d.Name, d => new Default(Text(d.Value, "securityMode")!, Text(d.Value, "transportCredential"), Text(d.Value, "messageCredential")),
                StringComparer.Ordinal)
            : new Dictionary<string, Default>(StringComparer.Ordinal);

        return new WcfClientSupport
        {
            MatrixVersion = Text(root, "matrixVersion")!,
            Sha256 = Convert.ToHexStringLower(SHA256.HashData(bytes)),
            Entries = entries,
            Defaults = defaults,
            Sources = sources,
        };
    }

    public bool HasTarget(string target) => Entries.Any(e => e.Target == target);

    /// <summary>The entry for this combination: exact first, then the most specific wildcard.</summary>
    public Entry? Find(string target, string binding, string securityMode, string credentialType) =>
        Entries
            .Where(e => e.Target == target && e.Binding == binding
                        && (e.SecurityMode == securityMode || e.SecurityMode == "*")
                        && (e.CredentialType == credentialType || e.CredentialType == "*"))
            .OrderBy(e => (e.SecurityMode == "*" ? 2 : 0) + (e.CredentialType == "*" ? 1 : 0))
            .FirstOrDefault();

    public int UnconfirmedCount => Entries.Count(e => !e.Confirmed);
}
