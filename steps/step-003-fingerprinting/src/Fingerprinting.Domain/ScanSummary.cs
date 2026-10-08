namespace Fingerprinting.Domain;

/// <summary>
/// Repository-level rollup embedded in the artifact — see
/// 21-APPLICATION-FINGERPRINTING.md Part F. <c>SignalsByCategory</c> is a
/// <see cref="SortedDictionary{TKey,TValue}"/> so its keys serialize in
/// alphabetical order without a separate sort pass.
/// </summary>
public sealed record ScanSummary
{
    public int ProjectsEligible { get; init; }
    public int ProjectsComplete { get; init; }
    public int ProjectsPartial { get; init; }
    public int ProjectsFailed { get; init; }
    public int ProjectsSkipped { get; init; }
    public int TotalSignals { get; init; }
    public int TotalEvidence { get; init; }
    public SortedDictionary<string, int> SignalsByCategory { get; init; } = new(StringComparer.Ordinal);
}
