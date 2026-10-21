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
    /// <summary>MSBuild evaluation and project metadata parsing (Level 2) have
    /// not run yet — projectSdk, nullableEnabled, implicitUsings and
    /// evaluatedProperties remain unavailable. Semantic analysis (Level 4)
    /// stays off by default regardless (Part A4).</summary>
    public const string AnalysisLevelsPending = "ANALYSIS_LEVELS_PENDING";

    /// <summary>The project's directory could not be located under the
    /// repository root, so no file-system evidence could be gathered.</summary>
    public const string ProjectDirectoryNotFound = "PROJECT_DIRECTORY_NOT_FOUND";

    public const string SemanticAnalysisDisabled = "SEMANTIC_ANALYSIS_DISABLED";

    /// <summary>A project's source file count exceeded
    /// SourceFileScanner.MaxFilesPerProject (Part G) — analysis stopped at
    /// the cap rather than continuing unbounded.</summary>
    public const string SourceFileCapExceeded = "SOURCE_FILE_CAP_EXCEEDED";

    /// <summary>A web.config/app.config/appsettings.json file could not be
    /// parsed — recorded as a warning, never a step failure (one bad config
    /// file must not fail the whole project).</summary>
    public const string ConfigurationParseFailed = "CONFIGURATION_PARSE_FAILED";

    /// <summary>release 5: something the step could not check within its time limit — a project whose load or
    /// analysis, or a file whose parse, took longer than allowed. The message says what and why; the step carried on.</summary>
    public const string NotChecked = "NOT_CHECKED";
}
