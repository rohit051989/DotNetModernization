using System.Text.Json.Serialization;
using Fingerprinting.Domain;

namespace Fingerprinting.Dependencies;

// The dependency-assessment@1.1.0 artifact — 30-DEPENDENCY-ASSESSMENT.md
// Parts C, D and F. Serialised through DeterministicJson. Deterministic
// against the lookup cache (Part B6): nothing time-dependent is in here —
// the cache snapshot time travels in StepOutput.metadata instead. Nothing
// derived from a feed credential is in here either (Part B4): feed URLs are
// normalised, userinfo, query and fragment removed.

public static class Outcomes
{
    public const string Current = "current";
    public const string UpgradeSafe = "upgrade_safe";
    public const string UpgradeBreaking = "upgrade_breaking";
    public const string NoCompatibleVersion = "no_compatible_version";
    public const string Unknown = "unknown";

    /// <summary>The UI's order: what blocks first.</summary>
    public static int Rank(string outcome) => outcome switch
    {
        NoCompatibleVersion => 0,
        UpgradeBreaking => 1,
        Unknown => 2,
        UpgradeSafe => 3,
        _ => 4,
    };
}

public static class FeedSources
{
    /// <summary>A package source the client declared — the authority (Part B2).</summary>
    public const string ClientFeed = "client_feed";

    /// <summary>nuget.org, used only because no client source is declared.</summary>
    public const string NuGetOrgFallback = "nuget_org_fallback";
}

public static class ClassificationMethods
{
    public const string ApiDiff = "api_diff";
    public const string SemverHeuristic = "semver_heuristic";

    /// <summary>A build, tools, analyzer or content package: it has no
    /// compile-time assemblies, so no C# call site can break.</summary>
    public const string PackageKind = "package_kind";
}

/// <summary>
/// What a package puts into the project, from its own contents (1.1.0).
/// Only <see cref="Runtime"/> has compile-time assemblies the code can call,
/// so only a runtime package can be breaking by semver or by API diff.
/// </summary>
public static class PackageKinds
{
    /// <summary>Real assemblies under lib/ or ref/ — what the code compiles against.
    /// Also a package with no assets of its own but dependencies (a pure meta-package).</summary>
    public const string Runtime = "runtime";

    /// <summary>MSBuild props/targets (and task assemblies) under build/, buildTransitive/, buildMultiTargeting/.</summary>
    public const string Build = "build";

    /// <summary>Executables and assemblies under tools/ — compilers, CLI tools.</summary>
    public const string Tools = "tools";

    /// <summary>Roslyn analyzers under analyzers/.</summary>
    public const string Analyzer = "analyzer";

    /// <summary>Files copied into the project — content/, contentFiles/, staticwebassets/: scripts, CSS, markup.</summary>
    public const string Content = "content";

    /// <summary>
    /// The kind, from a nupkg's file list. A runtime assembly is a real
    /// .dll under lib/ or ref/ — an empty-folder placeholder (<c>_._</c>) is
    /// not. Precedence when a package has several kinds of asset: runtime,
    /// analyzer, build, tools, content. A package with no assets at all is
    /// runtime when it has dependencies (they carry its API) and build when
    /// it has none (restore-time data such as runtime.json).
    /// </summary>
    public static string Classify(IEnumerable<string> files, bool hasDependencies)
    {
        var paths = files.Select(f => f.Replace('\\', '/')).ToList();
        bool Under(string folder, bool dllOnly = false) => paths.Any(p =>
            p.StartsWith(folder + "/", StringComparison.OrdinalIgnoreCase)
            && !p.EndsWith("/_._", StringComparison.Ordinal)
            && (!dllOnly || p.EndsWith(".dll", StringComparison.OrdinalIgnoreCase)));

        if (Under("lib", dllOnly: true) || Under("ref", dllOnly: true)) return Runtime;
        if (Under("analyzers")) return Analyzer;
        if (Under("build") || Under("buildTransitive") || Under("buildMultiTargeting")) return Build;
        if (Under("tools")) return Tools;
        if (Under("content") || Under("contentFiles") || Under("staticwebassets")) return Content;
        return hasDependencies ? Runtime : Build;
    }
}

/// <summary>What a breaking outcome rests on (1.1.0).</summary>
public static class BreakingEvidence
{
    /// <summary>At least one call site binds to a changed member without doubt.</summary>
    public const string ConfirmedCallSites = "confirmed_call_sites";

    /// <summary>Every call site could bind to an unchanged overload instead: possibly breaking.</summary>
    public const string AmbiguousCallSitesOnly = "ambiguous_call_sites_only";

    /// <summary>No API diff was possible; a major version of a runtime package is presumed breaking.</summary>
    public const string SemverPresumed = "semver_presumed";
}

public static class CallSiteCertainty
{
    public const string Confirmed = "confirmed";

    /// <summary>Syntax cannot tell which overload the call binds to: an
    /// unchanged overload accepts the same number of arguments.</summary>
    public const string Ambiguous = "ambiguous";
}

public sealed record DependencyAssessmentArtifact
{
    public string ArtifactType { get; init; } = "dependency-assessment";
    public string ArtifactVersion { get; init; } = "1.2.0";
    public required string ScannerVersion { get; init; }
    public required Guid RepositoryId { get; init; }
    public required string RepositorySlug { get; init; }

    /// <summary>The engagement's target framework (Part C1), e.g. net10.0.</summary>
    public required string TargetFramework { get; init; }
    public required bool ComparePublicFeed { get; init; }
    public required bool IncludeTransitive { get; init; }
    public required string SkipSource { get; init; }
    public required DependencySummary Summary { get; init; }
    public required IReadOnlyList<ProjectDependencies> Projects { get; init; }
    public IReadOnlyList<Warning> Warnings { get; init; } = [];
}

public sealed record DependencySummary
{
    public int ProjectsScanned { get; init; }
    public int ProjectsSkipped { get; init; }
    public int ProjectsFailed { get; init; }
    public int PackageCount { get; init; }
    public SortedDictionary<string, int> CountByOutcome { get; init; } = new(StringComparer.Ordinal);
    public SortedDictionary<string, int> CountByFeedSource { get; init; } = new(StringComparer.Ordinal);
    public int DeprecatedCount { get; init; }
    public int VulnerableCount { get; init; }
    public int NotInClientFeedCount { get; init; }

    /// <summary>Package ids referenced at more than one version across the
    /// repository's projects (1.1.0). Consolidating first is usually the
    /// sensible order before upgrading.</summary>
    public int VersionDriftCount { get; init; }

    /// <summary>Content packages whose upgrade is a major version (1.1.0).</summary>
    public int ContentBreakingPossibleCount { get; init; }
}

public sealed record ProjectDependencies
{
    public required Guid ProjectId { get; init; }
    public required string ProjectPath { get; init; }
    public required string Status { get; init; }
    public string? SkipReason { get; init; }

    /// <summary>What the project builds for today (from step 2) — the
    /// framework the current package version's assemblies are read for.</summary>
    public string? CurrentFramework { get; init; }

    /// <summary>The package sources NuGet resolves for this project, in
    /// declared order, and the role each plays here.</summary>
    public IReadOnlyList<FeedRecord> Feeds { get; init; } = [];
    public required ProjectDependencySummary Summary { get; init; }
    public IReadOnlyList<PackageAssessment> Packages { get; init; } = [];

    /// <summary>Transitive packages, when resolution was enabled — resolved
    /// in a scratch copy of the project, never in place (Part B5).</summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public IReadOnlyList<TransitivePackage>? Transitive { get; init; }

    /// <summary>The signals this step emitted for the project (Part D1).</summary>
    public IReadOnlyList<Signal> Signals { get; init; } = [];
    public IReadOnlyList<Warning> Warnings { get; init; } = [];
}

public sealed record ProjectDependencySummary
{
    public SortedDictionary<string, int> CountByOutcome { get; init; } = new(StringComparer.Ordinal);
    public int DeprecatedCount { get; init; }
    public int VulnerableCount { get; init; }
    public int NotInClientFeedCount { get; init; }
}

public sealed record FeedRecord
{
    public required string Name { get; init; }

    /// <summary>Normalised: scheme, host, port, path; never userinfo, query or
    /// fragment. A local folder inside the repository is repository-relative.</summary>
    public required string Url { get; init; }

    /// <summary><c>client_feed</c> (an authority), <c>nuget_org</c> (the
    /// fallback, or the public comparison), or <c>ignored</c> (a tooling
    /// folder declared only at user or machine level).</summary>
    public required string Role { get; init; }

    /// <summary><c>repository</c>, <c>user</c> or <c>machine</c> — where the
    /// source is declared; <c>default</c> for the nuget.org fallback.</summary>
    public required string DeclaredIn { get; init; }
}

public sealed record PackageAssessment
{
    /// <summary>Derived, stable: sha256 over repository, project and package id.</summary>
    public required string AssessmentId { get; init; }
    public required string PackageId { get; init; }
    public string? CurrentVersion { get; init; }

    /// <summary><c>project</c>, <c>central</c> (Directory.Packages.props),
    /// <c>packages_config</c>, or <c>unresolved</c>.</summary>
    public required string VersionSource { get; init; }

    /// <summary>The PackageReference (or packages.config) line.</summary>
    public required SourceLine DeclaredAt { get; init; }

    /// <summary>The latest version that supports the target framework, from
    /// the authoritative feed (Part C2) — not merely the latest version.</summary>
    public string? RecommendedVersion { get; init; }

    /// <summary>The newest version on the authoritative feed, compatible or not.</summary>
    public string? LatestVersion { get; init; }
    public required string Outcome { get; init; }
    public string? OutcomeReason { get; init; }

    /// <summary>runtime, build, tools, analyzer or content (<see cref="PackageKinds"/>);
    /// null when no version of the package could be read.</summary>
    public string? PackageKind { get; init; }

    /// <summary><c>api_diff</c>, <c>semver_heuristic</c> or <c>package_kind</c>,
    /// for an upgrade; null when there is nothing to classify.</summary>
    public string? ClassificationMethod { get; init; }

    /// <summary>For upgrade_breaking: what the outcome rests on (<see cref="BreakingEvidence"/>).</summary>
    public string? BreakingEvidence { get; init; }

    /// <summary>A content package (scripts, CSS, markup) moving a major
    /// version: may break markup or CSS, which this step does not analyse.
    /// Kept out of upgrade_breaking, which means C# must change.</summary>
    public bool ContentBreakingPossible { get; init; }

    /// <summary>The same package id is referenced at another version
    /// elsewhere in the repository.</summary>
    public bool VersionDrift { get; init; }

    /// <summary><c>major</c>, <c>minor</c>, <c>patch</c> or null.</summary>
    public string? SemverChange { get; init; }

    public DeprecationFlag? Deprecated { get; init; }
    public VulnerabilityFlag? Vulnerable { get; init; }
    public ClientFeedGap? NotInClientFeed { get; init; }

    /// <summary><c>client_feed</c> or <c>nuget_org_fallback</c>; null when no feed answered.</summary>
    public string? FeedSource { get; init; }
    public string? FeedName { get; init; }
    public string? FeedUrl { get; init; }

    /// <summary>For an API diff: the size of the public-surface change, whether or not the code calls it.</summary>
    public ApiDiffSummary? ApiDiff { get; init; }

    /// <summary>The changed members the code calls.</summary>
    public IReadOnlyList<BreakingMember> BreakingMembers { get; init; } = [];
    public IReadOnlyList<CallSite> CallSites { get; init; } = [];
    public required double Confidence { get; init; }
    public IReadOnlyList<string> ConfidenceReasons { get; init; } = [];
}

public sealed record SourceLine
{
    public required string FilePath { get; init; }
    public int? Line { get; init; }
}

public sealed record DeprecationFlag
{
    public IReadOnlyList<string> Reasons { get; init; } = [];
    public string? Message { get; init; }
    public string? ReplacementId { get; init; }
    public string? ReplacementRange { get; init; }
}

public sealed record VulnerabilityFlag
{
    /// <summary><c>low</c>, <c>moderate</c>, <c>high</c> or <c>critical</c>.</summary>
    public required string MaxSeverity { get; init; }
    public IReadOnlyList<Advisory> Advisories { get; init; } = [];

    /// <summary>The recommended version carries no advisory. Upgrading does
    /// not clear <see cref="DeprecationFlag"/>; it may clear this.</summary>
    public bool? ResolvedByUpgrade { get; init; }
}

public sealed record Advisory
{
    public required string Severity { get; init; }
    public required string Url { get; init; }
}

public sealed record ClientFeedGap
{
    public required string LatestPublicVersion { get; init; }
    public string? LatestInClientFeed { get; init; }
    public required string ClientFeedName { get; init; }
}

public sealed record ApiDiffSummary
{
    public int RemovedTypes { get; init; }
    public int RemovedMembers { get; init; }
    public int ChangedSignatures { get; init; }
    public required string CurrentAssemblies { get; init; }
    public required string RecommendedAssemblies { get; init; }
}

public sealed record BreakingMember
{
    /// <summary><c>type_removed</c>, <c>member_removed</c> or <c>signature_changed</c>.</summary>
    public required string Change { get; init; }
    public required string Type { get; init; }
    public string? Member { get; init; }
    public string? OldSignature { get; init; }
    public IReadOnlyList<string> NewSignatures { get; init; } = [];
}

public sealed record CallSite
{
    public required string FilePath { get; init; }
    public required int LineStart { get; init; }
    public required int LineEnd { get; init; }

    /// <summary>Type.Member as written in the diff.</summary>
    public required string Member { get; init; }

    /// <summary><c>confirmed</c>, or <c>ambiguous</c> when an unchanged
    /// overload accepts the same arguments (<see cref="CallSiteCertainty"/>).</summary>
    public string Certainty { get; init; } = CallSiteCertainty.Confirmed;
}

public sealed record TransitivePackage
{
    public required string PackageId { get; init; }
    public required string Version { get; init; }
    public VulnerabilityFlag? Vulnerable { get; init; }
}
