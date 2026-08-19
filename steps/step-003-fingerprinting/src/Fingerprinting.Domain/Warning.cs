namespace Fingerprinting.Domain;

/// <summary>
/// A processing warning attached to a project fingerprint or the scan as a
/// whole. Distinct from the step envelope's <c>diagnostics</c> — this is
/// artifact content, not run telemetry.
/// </summary>
public sealed record Warning
{
    public required string Code { get; init; }
    public required string Message { get; init; }
    public string Severity { get; init; } = "info";
}

public static class WarningSeverities
{
    public const string Info = "info";
    public const string Warning = "warning";
    public const string Error = "error";
}

public static class WarningCodes
{
    /// <summary>Only file-indicator extraction has run so far — every other
    /// fingerprint dimension in step-3-application-fingerprinting.md section
    /// 19 is still pending a future extractor.</summary>
    public const string ExtractorsPending = "EXTRACTORS_PENDING";

    /// <summary>The project's directory could not be located under the
    /// repository root, so no file-system evidence could be gathered.</summary>
    public const string ProjectDirectoryNotFound = "PROJECT_DIRECTORY_NOT_FOUND";

    public const string SemanticAnalysisDisabled = "SEMANTIC_ANALYSIS_DISABLED";
}
