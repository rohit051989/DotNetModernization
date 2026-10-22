using Fingerprinting.Domain;

namespace Fingerprinting.Hierarchy;

// The dependency-hierarchy@1.0.0 artifact — 37-DEPENDENCY-HIERARCHY.md Part C. Serialised through DeterministicJson:
// nodes ordered by id, edges by (from, to, kind), so two runs over the same repository and lookup cache write
// identical bytes. It is a graph, not a tree: a node is written once, whatever number of parents it has, and an edge
// once, whatever number of times it was reached.

public static class NodeTypes
{
    public const string Project = "project";
    public const string Package = "package";
    public const string Assembly = "assembly";
}

/// <summary>What a project is for, read from the project file alone (Part B2).</summary>
public static class ProjectKinds
{
    public const string Application = "application";
    public const string Library = "library";
    public const string Test = "test";
    /// <summary>Not a .NET code project: a database, shared or out-of-scope project, or one that could not be read.</summary>
    public const string Other = "other";
}

public static class PackageOrigins
{
    /// <summary>From the client's own feeds: a client feed answers it and nuget.org does not have it, or estate
    /// consolidation knows the repository that produces it.</summary>
    public const string Internal = "internal";
    public const string External = "external";
    /// <summary>No feed answered for it; the reason is the node's notCheckedReason.</summary>
    public const string Unknown = "unknown";
}

public static class AssemblyLocations
{
    /// <summary>A HintPath to a DLL inside the repository.</summary>
    public const string Repository = "repository";
    /// <summary>A HintPath outside the repository.</summary>
    public const string OutsideRepository = "outside_repository";
    /// <summary>No HintPath, and not part of .NET Framework: resolved from the GAC.</summary>
    public const string Gac = "gac";
    /// <summary>No HintPath, and part of .NET Framework itself (System, System.Web, mscorlib, …).</summary>
    public const string Framework = "framework";
}

public static class EdgeKinds
{
    public const string ProjectReference = "project_reference";
    public const string PackageReference = "package_reference";
    /// <summary>A PackageReference whose version comes from Directory.Packages.props.</summary>
    public const string CentralPackageVersion = "central_package_version";
    public const string PackagesConfig = "packages_config";
    public const string AssemblyReference = "assembly_reference";
    /// <summary>A package's own dependency.</summary>
    public const string PackageDependency = "package_dependency";
}

/// <summary>Where an edge came from.</summary>
public static class Resolutions
{
    /// <summary>Declared in a project file or packages.config.</summary>
    public const string Declared = "declared";
    /// <summary>From the project's restored obj/project.assets.json: what restore actually chose.</summary>
    public const string AssetsFile = "assets_file";
    /// <summary>From the feed's metadata for the project's target framework, the lowest version the range allows:
    /// what restore would choose, not what it chose.</summary>
    public const string FeedMetadata = "feed_metadata";
}

public static class NodeStatuses
{
    public const string Checked = "checked";
    public const string NotChecked = "not_checked";
}

public sealed record DependencyHierarchyArtifact
{
    public string ArtifactType { get; init; } = "dependency-hierarchy";
    public string ArtifactVersion { get; init; } = "1.0.0";
    public required string ScannerVersion { get; init; }
    public required Guid RepositoryId { get; init; }
    public required string RepositorySlug { get; init; }
    public required HierarchyLimits Limits { get; init; }
    public required HierarchySummary Summary { get; init; }

    /// <summary>The projects no other project in the repository references — usually the applications.</summary>
    public required IReadOnlyList<string> Roots { get; init; }
    public required IReadOnlyList<HierarchyNode> Nodes { get; init; }
    public required IReadOnlyList<HierarchyEdge> Edges { get; init; }

    /// <summary>Each cycle once, as the node ids around it, starting from its smallest id.</summary>
    public IReadOnlyList<IReadOnlyList<string>> Cycles { get; init; } = [];
    public IReadOnlyList<Warning> Warnings { get; init; } = [];
}

public sealed record HierarchyLimits
{
    /// <summary>How deep a package's own dependencies are followed below the project that declares it.</summary>
    public required int MaxPackageDepth { get; init; }
    /// <summary>How many package nodes the graph may hold.</summary>
    public required int MaxPackages { get; init; }
}

public sealed record HierarchySummary
{
    public int ProjectCount { get; init; }
    public SortedDictionary<string, int> CountByProjectKind { get; init; } = new(StringComparer.Ordinal);
    public int PackageCount { get; init; }
    public int InternalPackageCount { get; init; }
    public int ExternalPackageCount { get; init; }
    public int TransitivePackageCount { get; init; }
    public int AssemblyCount { get; init; }
    public int EdgeCount { get; init; }
    public SortedDictionary<string, int> CountByEdgeKind { get; init; } = new(StringComparer.Ordinal);
    public int RootCount { get; init; }
    public int CycleCount { get; init; }
    public int NotCheckedCount { get; init; }
    /// <summary>The longest path from a root, in edges.</summary>
    public int Depth { get; init; }
}

public sealed record HierarchyNode
{
    /// <summary>Stable: <c>project:&lt;path&gt;</c>, <c>package:&lt;id&gt;@&lt;version&gt;</c> (lower case),
    /// <c>assembly:&lt;location&gt;:&lt;name or path&gt;</c>.</summary>
    public required string Id { get; init; }
    public required string Type { get; init; }
    public required string Name { get; init; }
    public string Status { get; init; } = NodeStatuses.Checked;
    public string? NotCheckedReason { get; init; }
    public ProjectNodeDetail? Project { get; init; }
    public PackageNodeDetail? Package { get; init; }
    public AssemblyNodeDetail? Assembly { get; init; }
}

public sealed record ProjectNodeDetail
{
    /// <summary>The projects table's id; null for a referenced project that is not in the inventory.</summary>
    public Guid? ProjectId { get; init; }
    public required string Path { get; init; }
    public required string Kind { get; init; }
    /// <summary>Why the kind is what it is: "test SDK package Microsoft.NET.Test.Sdk", "OutputType Exe", …</summary>
    public required string KindBasis { get; init; }
    public IReadOnlyList<string> TargetFrameworks { get; init; } = [];
    /// <summary><c>sdk_style</c>, <c>legacy_msbuild</c> or <c>unknown</c>.</summary>
    public required string ProjectFormat { get; init; }
    /// <summary><c>packagereference</c>, <c>packages_config</c>, <c>mixed</c> or <c>none</c>.</summary>
    public required string PackageManagement { get; init; }
}

public sealed record PackageNodeDetail
{
    public required string PackageId { get; init; }
    /// <summary>The version in use; null when it could not be read.</summary>
    public string? Version { get; init; }
    public required string Origin { get; init; }
    public required string OriginBasis { get; init; }
    public string? FeedName { get; init; }
    public string? FeedUrl { get; init; }
    /// <summary>No project declares it: only another package depends on it.</summary>
    public bool Transitive { get; init; }
    /// <summary>For an internal package, the repository in the estate that produces it, where estate consolidation knows it.</summary>
    public PackageProducer? Producer { get; init; }
    /// <summary>dependency-assessment's findings for a package a project declares; null for a transitive one.</summary>
    public PackageFindings? Findings { get; init; }
    /// <summary>Known advisories of this version, from the feed's metadata — for transitive packages too.</summary>
    public string? VulnerabilityMaxSeverity { get; init; }
    /// <summary>How its own dependencies were found: assets_file, feed_metadata, or null when they were not checked
    /// (the reason is in the node's notCheckedReason, or in dependenciesNotCheckedReason when the package itself was).</summary>
    public string? DependenciesResolution { get; init; }
    public string? DependenciesNotCheckedReason { get; init; }
}

public sealed record PackageProducer
{
    public required Guid RepositoryId { get; init; }
    public required string RepositoryName { get; init; }
    public required string ProjectPath { get; init; }
}

public sealed record PackageFindings
{
    /// <summary>The worst outcome across the projects that declare it, in dependency-assessment's order.</summary>
    public required string Outcome { get; init; }
    public string? OutcomeReason { get; init; }
    public string? RecommendedVersion { get; init; }
    public bool Outdated { get; init; }
    public bool Deprecated { get; init; }
    public bool Vulnerable { get; init; }
    public string? VulnerabilityMaxSeverity { get; init; }
}

public sealed record AssemblyNodeDetail
{
    /// <summary>The simple name, as the Reference's Include gives it before any comma.</summary>
    public required string AssemblyName { get; init; }
    /// <summary>From the Include's strong name, when it carries one.</summary>
    public string? Version { get; init; }
    public required string Location { get; init; }
    /// <summary>Repository-relative for a DLL in the repository; as written for one outside it; null for the GAC.</summary>
    public string? Path { get; init; }
    /// <summary>Whether the HintPath's file exists; null where there is no HintPath.</summary>
    public bool? Exists { get; init; }
}

public sealed record HierarchyEdge
{
    public required string From { get; init; }
    public required string To { get; init; }
    public required string Kind { get; init; }
    public required string Resolution { get; init; }
    /// <summary>The version or range as declared (project to package) or as the depending package asks (package to package).</summary>
    public string? VersionRequested { get; init; }
    /// <summary>For a package dependency: the frameworks it was found for (one package version can depend on
    /// different packages per framework).</summary>
    public IReadOnlyList<string> Frameworks { get; init; } = [];
    /// <summary>The line that declares it, for a project's edge.</summary>
    public SourceAt? DeclaredAt { get; init; }
    /// <summary>The edge closes a cycle: it was recorded, and not followed.</summary>
    public bool ClosesCycle { get; init; }
}

public sealed record SourceAt
{
    public required string FilePath { get; init; }
    public int? Line { get; init; }
}
