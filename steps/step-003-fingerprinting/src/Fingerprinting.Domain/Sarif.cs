using System.Text.Json.Serialization;

namespace Fingerprinting.Domain;

/// <summary>
/// A minimal SARIF 2.1.0 object model — only the subset
/// 25-STANDARDS-AND-VIEWPOINTS.md Part A3 maps signals onto: one
/// <see cref="SarifRun"/> per project, the signal registry as
/// <c>tool.driver.rules</c>, signal instances as <c>results</c> with
/// <c>level: "none"</c> (observations, not defects), evidence spans as
/// region locations, and signal categories as a taxonomy. Serialize with
/// <see cref="DeterministicJson.SerializeOmitNulls{T}"/> — SARIF's schema
/// types most optional properties without "null", so an omitted key is
/// required where our own native artifact would happily write null.
/// </summary>
public sealed record SarifLog
{
    [JsonPropertyName("$schema")]
    public string Schema { get; init; } =
        "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json";

    public string Version { get; init; } = "2.1.0";
    public required IReadOnlyList<SarifRun> Runs { get; init; }
}

public sealed record SarifRun
{
    public required SarifTool Tool { get; init; }
    public required IReadOnlyList<SarifResult> Results { get; init; }
    public IReadOnlyList<SarifToolComponent>? Taxonomies { get; init; }

    /// <summary>Declares which base a <c>uriBaseId</c> on an
    /// <see cref="SarifArtifactLocation"/> resolves against, without
    /// necessarily saying what that base is. The registered artifact sets
    /// the <c>REPOROOT</c> entry's <see cref="SarifArtifactLocation.Uri"/>
    /// to null — present, resolvable-relative-URI-wise, but carrying no
    /// absolute machine path — so the checksum stays stable across
    /// machines; the local-only sibling file fills it in with this
    /// machine's actual repository path for the viewer to resolve
    /// against.</summary>
    public IReadOnlyDictionary<string, SarifArtifactLocation>? OriginalUriBaseIds { get; init; }

    public IReadOnlyDictionary<string, object?>? Properties { get; init; }
}

public sealed record SarifTool
{
    public required SarifToolComponent Driver { get; init; }
}

/// <summary>Used for both <c>tool.driver</c> (the registry as a rule
/// catalog) and each entry in <c>run.taxonomies</c> (the category
/// vocabulary) — SARIF defines both as the same <c>toolComponent</c> shape.</summary>
public sealed record SarifToolComponent
{
    public required string Name { get; init; }
    public string? Version { get; init; }
    public IReadOnlyList<SarifReportingDescriptor>? Rules { get; init; }
    public IReadOnlyList<SarifReportingDescriptor>? Taxa { get; init; }
}

/// <summary>A rule (from <c>tool.driver.rules</c>) or a taxon (from a
/// taxonomy's <c>taxa</c>) — SARIF defines both as <c>reportingDescriptor</c>.</summary>
public sealed record SarifReportingDescriptor
{
    public required string Id { get; init; }
    public string? Name { get; init; }
    public SarifMessage? ShortDescription { get; init; }
    public IReadOnlyDictionary<string, object?>? Properties { get; init; }
}

public sealed record SarifResult
{
    public required string RuleId { get; init; }

    /// <summary>Always "none" — a signal is an observation the classification
    /// catalog interprets, never a defect SARIF's severity scale describes.</summary>
    public required string Level { get; init; }

    public required SarifMessage Message { get; init; }
    public IReadOnlyList<SarifLocation>? Locations { get; init; }
    public IReadOnlyDictionary<string, object?>? Properties { get; init; }
}

public sealed record SarifMessage
{
    public required string Text { get; init; }
}

public sealed record SarifLocation
{
    public required SarifPhysicalLocation PhysicalLocation { get; init; }
}

public sealed record SarifPhysicalLocation
{
    public required SarifArtifactLocation ArtifactLocation { get; init; }
    public SarifRegion? Region { get; init; }
}

public sealed record SarifArtifactLocation
{
    /// <summary>Repository-relative, forward-slashed, never absolute — Part
    /// A3's "no absolute paths" determinism rule. Null only when this
    /// record is used as the <c>REPOROOT</c> entry of the registered
    /// file's <see cref="SarifRun.OriginalUriBaseIds"/>, where the base
    /// itself is deliberately left unresolved.</summary>
    public string? Uri { get; init; }

    /// <summary>Names the entry in <see cref="SarifRun.OriginalUriBaseIds"/>
    /// this location resolves against — <c>"REPOROOT"</c> for every
    /// location this builder emits, so a viewer with the repository open
    /// (or told where it is, via the local file's populated base) resolves
    /// <see cref="Uri"/> relative to it instead of the platform's own
    /// working directory.</summary>
    public string? UriBaseId { get; init; }
}

public sealed record SarifRegion
{
    public int? StartLine { get; init; }
    public int? EndLine { get; init; }
}
