namespace Fingerprinting.Domain;

/// <summary>
/// One project's fingerprint within the artifact — see
/// 21-STEP-003-FINGERPRINTING.md Part F. One row per project row from step 2;
/// no aggregation, no judgement about which projects are applications
/// (Part C).
/// </summary>
public sealed record ProjectFingerprint
{
    public required Guid ProjectId { get; init; }
    public required string ProjectPath { get; init; }
    public required string FingerprintStatus { get; init; }
    public required AnalysisCapabilities AnalysisCapabilities { get; init; }
    public string? ProjectSdk { get; init; }
    public bool? NullableEnabled { get; init; }
    public bool? ImplicitUsings { get; init; }
    public SortedDictionary<string, EvaluatedProperty>? EvaluatedProperties { get; init; }
    public IReadOnlyList<Signal> Signals { get; init; } = [];
    public IReadOnlyList<Warning> Warnings { get; init; } = [];
}
