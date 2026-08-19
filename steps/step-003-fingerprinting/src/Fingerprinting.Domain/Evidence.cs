namespace Fingerprinting.Domain;

/// <summary>
/// One evidence entry backing a <see cref="Signal"/>. Capped at 20 entries per
/// signal — <c>occurrenceCount</c> carries the true total. Never carries a
/// source snippet, only a hash of one — see 21-STEP-003-FINGERPRINTING.md
/// Part G.
/// </summary>
public sealed record Evidence
{
    public int? LineStart { get; init; }
    public int? LineEnd { get; init; }
    public string? DeclaringType { get; init; }
    public string? Member { get; init; }
    public string? SnippetHash { get; init; }
}
