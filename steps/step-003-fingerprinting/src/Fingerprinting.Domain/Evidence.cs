using System.Text.Json.Serialization;

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

    /// <summary>
    /// <c>LITERAL</c> signals only: exactly the text the signal's pattern
    /// matched at this span (Part D "Signal types"). Omitted from JSON when
    /// null — application-fingerprint@1.2.0 forbids the key on every other
    /// signal type, so it must be absent, not <c>null</c>. Never populated
    /// from a connection string or a sensitive-key value (Part G).
    /// </summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? MatchedValue { get; init; }

    /// <summary>
    /// <c>confirmed</c> or <c>ambiguous</c>, where the producer can tell —
    /// today only step 6's PACKAGE_UPGRADE_BREAKING call sites, where an
    /// unchanged overload may take the same call. Item detection marks an
    /// occurrence "possible" when every evidence entry behind it is
    /// ambiguous. Omitted when null, so step 3's artifacts are unchanged.
    /// </summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Certainty { get; init; }
}
