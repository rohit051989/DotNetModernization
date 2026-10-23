using System.Security.Cryptography;

namespace Fingerprinting.StepHost;

/// <summary>
/// <c>file://</c> artifact URI helpers, mirroring
/// steps/step-002-solution-discovery/main.py's <c>_local_path_from_uri</c> /
/// <c>_sha256_uri</c>. <see cref="Uri"/> already resolves Windows drive
/// letters correctly, so this is simpler than the Python original.
/// </summary>
public static class ArtifactUri
{
    public static string ToLocalPath(string uri)
    {
        var parsed = new Uri(uri, UriKind.RelativeOrAbsolute);
        if (!parsed.IsAbsoluteUri)
        {
            return uri; // bare path, already local
        }

        if (parsed.Scheme != Uri.UriSchemeFile)
        {
            throw new InvalidOperationException($"unsupported artifact URI scheme '{parsed.Scheme}' in '{uri}'");
        }

        return parsed.LocalPath;
    }

    public static string FromLocalPath(string path) => new Uri(Path.GetFullPath(path)).AbsoluteUri;

    /// <summary>
    /// The version the written artifact declares — its top-level <c>artifactVersion</c> (or <c>artifact_version</c>),
    /// or, for a SARIF log, its <c>version</c>. A step reports this, never a second constant: the version it reports is
    /// then the version it wrote. The engine checks the same thing (app/workflow/adapters/base.py).
    /// </summary>
    public static string DeclaredVersion(string path)
    {
        using var stream = File.OpenRead(path);
        using var document = System.Text.Json.JsonDocument.Parse(stream);
        var root = document.RootElement;
        foreach (var name in new[] { "artifactVersion", "artifact_version" })
        {
            if (root.TryGetProperty(name, out var value) && value.GetString() is { Length: > 0 } version) return version;
        }

        if (root.TryGetProperty("runs", out _) && root.TryGetProperty("version", out var sarif) && sarif.GetString() is { Length: > 0 } sarifVersion)
        {
            return sarifVersion;
        }

        throw new InvalidOperationException($"{path} declares no artifact version");
    }

    public static string Sha256File(string path)
    {
        using var stream = File.OpenRead(path);
        var digest = SHA256.HashData(stream);
        return $"sha256:{Convert.ToHexStringLower(digest)}";
    }
}
