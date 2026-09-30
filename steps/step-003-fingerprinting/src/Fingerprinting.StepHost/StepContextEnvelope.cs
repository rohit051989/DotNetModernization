using System.Text.Json;

namespace Fingerprinting.StepHost;

/// <summary>
/// The engine's invocation envelope — see 11-STEP-CONTRACT.md "Invocation —
/// StepContext". Named <c>StepContextEnvelope</c> rather than
/// <c>StepContext</c> only to avoid colliding with its own nested
/// <see cref="StepContext"/> field (the envelope and one of its own fields
/// share a name in the spec).
/// </summary>
public sealed record StepContextEnvelope
{
    public required string EnvelopeVersion { get; init; }
    public required string StepName { get; init; }
    public string? StepVersion { get; init; }
    public string? JobName { get; init; }
    public string? JobExecutionId { get; init; }
    public string? StepExecutionId { get; init; }
    public int? Attempt { get; init; }
    public string? PartitionKey { get; init; }

    public Dictionary<string, JsonElement>? Parameters { get; init; }
    public JsonElement? Config { get; init; }
    public Dictionary<string, ArtifactRef>? Inputs { get; init; }

    public JsonElement? JobContext { get; init; }
    public JsonElement? StepContext { get; init; }

    public required string WorkingDir { get; init; }
    public required string OutputDir { get; init; }

    public string? DatabaseUrl { get; init; }
    public string? LogLevel { get; init; }
}

/// <summary>A resolved upstream artifact reference under <c>inputs</c>.</summary>
public sealed record ArtifactRef
{
    public required string ArtifactType { get; init; }
    public required string ArtifactVersion { get; init; }
    public required string Uri { get; init; }
    public string? Checksum { get; init; }
}
