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

    public static string Sha256File(string path)
    {
        using var stream = File.OpenRead(path);
        var digest = SHA256.HashData(stream);
        return $"sha256:{Convert.ToHexStringLower(digest)}";
    }
}
