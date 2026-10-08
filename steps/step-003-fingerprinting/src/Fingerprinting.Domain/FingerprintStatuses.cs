namespace Fingerprinting.Domain;

/// <summary>
/// Project-level fingerprint status values, per 21-APPLICATION-FINGERPRINTING.md
/// Part E. JSON (and this class) use SCREAMING_SNAKE_CASE; the database column
/// stores the lower-cased form — see <see cref="ToDbValue"/>.
/// </summary>
public static class FingerprintStatuses
{
    public const string Complete = "COMPLETE";
    public const string Partial = "PARTIAL";
    public const string Failed = "FAILED";
    public const string Skipped = "SKIPPED";
    public const string NotSupported = "NOT_SUPPORTED";

    public static string ToDbValue(string status) => status.ToLowerInvariant();
}
