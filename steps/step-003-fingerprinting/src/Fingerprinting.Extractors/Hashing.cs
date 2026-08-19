using System.Security.Cryptography;
using System.Text;

namespace Fingerprinting.Extractors;

/// <summary>
/// Evidence carries a hash of a source snippet, never the snippet itself
/// (21-STEP-003-FINGERPRINTING.md Part G) — snippets risk carrying secrets
/// and inflate storage; a hash still lets a consumer detect change between
/// scans.
/// </summary>
internal static class Hashing
{
    public static string Sha256Hex(string text) =>
        Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text)));
}
