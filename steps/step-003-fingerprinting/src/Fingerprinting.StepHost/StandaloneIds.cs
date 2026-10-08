using System.Security.Cryptography;
using System.Text;

namespace Fingerprinting.StepHost;

/// <summary>Ids for runs with no database (standalone mode).</summary>
public static class StandaloneIds
{
    /// <summary>A stable id derived from (repository, relative path) —
    /// deterministic across reruns, unlike <see cref="Guid.NewGuid"/>, which
    /// the checksum determinism requirement (21-APPLICATION-FINGERPRINTING.md
    /// Part B rule 2) rules out.</summary>
    public static Guid ProjectId(Guid repositoryId, string relativePath)
    {
        var bytes = Encoding.UTF8.GetBytes($"{repositoryId:D}|{relativePath}");
        var hash = SHA256.HashData(bytes);
        return new Guid(hash[..16]);
    }
}

/// <summary>The slice of step 3's <c>application-fingerprint</c> that
/// downstream steps read: which projects were fingerprinted, under which
/// id, and which were skipped. Steps 4 and 5 skip what step 3 skipped
/// (29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md Part A3) rather than re-deriving it.</summary>
public sealed record ApplicationFingerprintSlice
{
    public required Guid RepositoryId { get; init; }
    public required IReadOnlyList<FingerprintedProject> Projects { get; init; }
}

public sealed record FingerprintedProject
{
    public required Guid ProjectId { get; init; }
    public required string ProjectPath { get; init; }
    public required string FingerprintStatus { get; init; }

    /// <summary>Step 5 reads <c>UNC_PATH_LITERAL</c> signals for file
    /// shares; step 4 reads none. Only the fields step 5 uses are modelled.</summary>
    public IReadOnlyList<FingerprintSignal> Signals { get; init; } = [];
}

public sealed record FingerprintSignal
{
    public required string Name { get; init; }
    public string? Value { get; init; }
    public string? SourcePath { get; init; }
    public IReadOnlyList<FingerprintEvidence> Evidence { get; init; } = [];
}

public sealed record FingerprintEvidence
{
    public int? LineStart { get; init; }
    public int? LineEnd { get; init; }
    public string? MatchedValue { get; init; }
}

/// <summary>Caret ranges, as a <c>consumes</c> entry writes them — the
/// same check the engine makes (backend app/workflow/semver.py), repeated
/// by a step that located an optional input itself.</summary>
public static class ArtifactVersions
{
    public static bool SatisfiesCaret(string version, string range)
    {
        if (!range.StartsWith('^') || !TryParse(range[1..], out var minimum) || !TryParse(version, out var actual))
        {
            return false;
        }

        return actual.Major == minimum.Major && actual.CompareTo(minimum) >= 0;
    }

    private static bool TryParse(string text, out Version version)
    {
        var core = text.Split('-', '+')[0];
        return Version.TryParse(core, out version!) && core.Count(c => c == '.') == 2;
    }
}
