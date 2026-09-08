namespace Fingerprinting.Domain;

/// <summary>
/// The <c>application-fingerprint@1.1.0</c> artifact — see
/// 21-STEP-003-FINGERPRINTING.md Part F. The artifact version is the schema
/// version (Part A2); no <c>schemaVersion</c>, <c>scanId</c> or timestamp
/// field belongs here (Part A3) — those are volatile and go in
/// <c>StepOutput.metadata</c> instead. Bumped to 1.1.0 for
/// <c>Signal.EvidenceKind</c> (25-STANDARDS-AND-VIEWPOINTS.md Part A3
/// addendum) — additive, so pattern-classification's <c>^1.0.0</c> consumes
/// range still accepts it.
/// </summary>
public sealed record ApplicationFingerprintArtifact
{
    public string ArtifactType { get; init; } = "application-fingerprint";
    public string ArtifactVersion { get; init; } = "1.1.0";
    public required string ScannerVersion { get; init; }
    public required string SignalRegistryVersion { get; init; }
    public required Guid RepositoryId { get; init; }
    public required string RepositorySlug { get; init; }
    public string? RepositoryCommitSha { get; init; }
    public required string ScanStatus { get; init; }
    public required bool SemanticAnalysisEnabled { get; init; }
    public required ScanSummary Summary { get; init; }
    public required IReadOnlyList<ProjectFingerprint> Projects { get; init; }
    public IReadOnlyList<Signal> RepositorySignals { get; init; } = [];
    public IReadOnlyList<Warning> Warnings { get; init; } = [];
}
