namespace Fingerprinting.Domain;

/// <summary>
/// Repository-level scan status values. Lower-case in both the JSON artifact
/// and the database — see 21-STEP-003-FINGERPRINTING.md Part E and Part F.
/// </summary>
public static class ScanStatuses
{
    public const string Complete = "complete";
    public const string Partial = "partial";
    public const string Failed = "failed";
}
