using Fingerprinting.Domain;

namespace Fingerprinting.Extractors;

/// <summary>
/// Aggregates repeated occurrences of the same (name, sourcePath, value) into
/// one <see cref="Signal"/> row with a running <c>occurrenceCount</c> and
/// evidence capped at 20 entries — 21-STEP-003-FINGERPRINTING.md Part E:
/// "twenty-one OperationContract attributes in one file is one row with
/// occurrence_count: 21, not twenty-one rows." Shared by every extractor that
/// walks source or configuration files looking for repeated constructs.
/// </summary>
internal sealed class SignalAccumulator
{
    private const int MaxEvidencePerSignal = 20;

    private sealed class Entry
    {
        public required string Category { get; init; }
        public required string Type { get; init; }
        public required string SourceType { get; init; }
        public required string Extractor { get; init; }
        public decimal Confidence { get; init; } = 1.00m;
        public int Count;
        public List<Evidence> Evidence { get; } = [];
    }

    private readonly Dictionary<(string Name, string? SourcePath, string? Value), Entry> _entries = [];

    public void Add(
        string name,
        string category,
        string type,
        string? value,
        string sourceType,
        string? sourcePath,
        string extractor,
        decimal confidence = 1.00m,
        Evidence? evidence = null)
    {
        var key = (name, sourcePath, value);
        if (!_entries.TryGetValue(key, out var entry))
        {
            entry = new Entry { Category = category, Type = type, SourceType = sourceType, Extractor = extractor, Confidence = confidence };
            _entries[key] = entry;
        }

        entry.Count++;
        if (evidence is not null && entry.Evidence.Count < MaxEvidencePerSignal)
        {
            entry.Evidence.Add(evidence);
        }
    }

    public IReadOnlyList<Signal> Build() =>
        _entries.Select(kv => new Signal
        {
            Name = kv.Key.Name,
            Category = kv.Value.Category,
            Type = kv.Value.Type,
            Value = kv.Key.Value,
            SourceType = kv.Value.SourceType,
            SourcePath = kv.Key.SourcePath,
            OccurrenceCount = kv.Value.Count,
            Evidence = kv.Value.Evidence,
            Extractor = kv.Value.Extractor,
            ExtractionConfidence = kv.Value.Confidence,
        }).ToList();
}
