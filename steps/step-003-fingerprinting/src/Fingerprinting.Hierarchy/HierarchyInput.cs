namespace Fingerprinting.Hierarchy;

/// <summary>One project as the step receives it, from solution-discovery's inventory and the projects table.</summary>
public sealed record HierarchyInputProject(
    string RelativePath,
    Guid? ProjectId,
    string Name,
    string StructuralType,
    string ParseStatus,
    string ProjectFormat,
    string? OutputType,
    string? ProjectSdk,
    IReadOnlyList<string> TargetFrameworks,
    string? CurrentFramework,
    string PackageManagement,
    IReadOnlyList<InventoryPackageRef> Packages);

/// <summary>A package as solution-discovery recorded it — used when dependency-assessment has nothing for the project.</summary>
public sealed record InventoryPackageRef(string PackageId, string? VersionRaw, string DeclarationSource);

/// <summary>A ProjectReference, resolved by solution-discovery: the referenced path, or null with the raw path.</summary>
public sealed record InventoryReference(string Source, string? Target, string RawPath, string? ResolutionStatus);

public sealed record HierarchyInput(
    Guid RepositoryId,
    string RepositorySlug,
    IReadOnlyList<HierarchyInputProject> Projects,
    IReadOnlyList<InventoryReference> ProjectReferences,
    AssessmentSlice? Assessment,
    IReadOnlyDictionary<string, PackageProducer> Producers);

/// <summary>The slice of dependency-assessment's artifact this step reads (camelCase, as it is written).</summary>
public sealed record AssessmentSlice
{
    public IReadOnlyList<AssessedProject> Projects { get; init; } = [];
}

public sealed record AssessedProject
{
    public required string ProjectPath { get; init; }
    public required string Status { get; init; }
    public string? SkipReason { get; init; }
    public IReadOnlyList<AssessedPackage> Packages { get; init; } = [];
}

public sealed record AssessedPackage
{
    public required string PackageId { get; init; }
    public string? CurrentVersion { get; init; }
    public required string VersionSource { get; init; }
    public AssessedLine? DeclaredAt { get; init; }
    public string? RecommendedVersion { get; init; }
    public required string Outcome { get; init; }
    public string? OutcomeReason { get; init; }
    public AssessedFlag? Deprecated { get; init; }
    public AssessedVulnerability? Vulnerable { get; init; }
    public string? FeedSource { get; init; }
}

public sealed record AssessedLine
{
    public required string FilePath { get; init; }
    public int? Line { get; init; }
}

public sealed record AssessedFlag
{
    public string? Message { get; init; }
}

public sealed record AssessedVulnerability
{
    public required string MaxSeverity { get; init; }
}
