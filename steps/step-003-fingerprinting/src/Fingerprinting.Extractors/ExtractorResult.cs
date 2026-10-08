using Fingerprinting.Domain;

namespace Fingerprinting.Extractors;

/// <summary>
/// What one extractor produced for one project. Signals only, never a
/// classification — see application-fingerprinting-v1.md section 31.
/// </summary>
public sealed record ExtractorResult
{
    public IReadOnlyList<Signal> Signals { get; init; } = [];
    public IReadOnlyList<Warning> Warnings { get; init; } = [];

    public static readonly ExtractorResult Empty = new();
}
