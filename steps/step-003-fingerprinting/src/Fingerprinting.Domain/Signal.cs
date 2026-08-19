namespace Fingerprinting.Domain;

/// <summary>
/// One emitted signal — a fact an extractor observed, not an interpretation.
/// <c>name</c> must exist in the signal registry; an unregistered name is a
/// validation failure, not a warning. See
/// 21-STEP-003-FINGERPRINTING.md Parts D and F.
/// </summary>
public sealed record Signal
{
    public required string Name { get; init; }
    public required string Category { get; init; }
    public required string Type { get; init; }
    public string? Value { get; init; }
    public required string SourceType { get; init; }
    public string? SourcePath { get; init; }
    public int OccurrenceCount { get; init; } = 1;
    public IReadOnlyList<Evidence> Evidence { get; init; } = [];
    public required string Extractor { get; init; }
    public required decimal ExtractionConfidence { get; init; }
}
