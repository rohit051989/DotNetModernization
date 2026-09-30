using System.Text.Json.Serialization;

namespace Fingerprinting.StepHost;

/// <summary>The step's response envelope — see 11-STEP-CONTRACT.md "Response
/// — StepResult". <c>exit_status</c> is the only required field.</summary>
public sealed record StepResult
{
    public string EnvelopeVersion { get; init; } = "1.0";
    public required string ExitStatus { get; init; }
    public string? ExitMessage { get; init; }
    public Dictionary<string, long>? Metrics { get; init; }
    public List<StepOutput>? Outputs { get; init; }
    public Dictionary<string, object?>? JobContextUpdates { get; init; }
    public Dictionary<string, object?>? StepContextUpdates { get; init; }
    public object? Next { get; init; }
    public List<Diagnostic>? Diagnostics { get; init; }
}

public sealed record StepOutput
{
    public required string ArtifactType { get; init; }
    public required string ArtifactVersion { get; init; }
    public required string Uri { get; init; }
    public required string Checksum { get; init; }
    public Dictionary<string, object?>? Metadata { get; init; }
}

public sealed record Diagnostic
{
    public required string Level { get; init; }
    public required string Code { get; init; }
    public required string Message { get; init; }

    [JsonPropertyName("ref")]
    public string? Ref { get; init; }
}

public static class ExitStatuses
{
    public const string Completed = "COMPLETED";
    public const string Failed = "FAILED";
}
