namespace Fingerprinting.StepHost;

/// <summary>
/// The slice of step 2's <c>solution-project-inventory</c> artifact that
/// steps 3 and 4 actually read. Step 3 must not re-extract what step 2 already
/// captured (21-STEP-003-FINGERPRINTING.md Part A7) — everything else in
/// that file (packages, project references, solutions, ...) is left for a
/// future extractor to read directly rather than modelled here unused.
/// </summary>
public sealed record SolutionProjectInventory
{
    public required Guid RepositoryId { get; init; }
    public required string RepositorySlug { get; init; }
    public required IReadOnlyList<InventoryProject> Projects { get; init; }
}

public sealed record InventoryProject
{
    public required string RelativePath { get; init; }
    public required string ParseStatus { get; init; }

    /// <summary>One of step 2's structural types — see
    /// steps/step-002-solution-discovery/discovery/project_parser.py.
    /// Despite 21-STEP-003-FINGERPRINTING.md Part C's wording ("parse_status
    /// of out_of_scope"), step 2 actually records a known non-.NET project
    /// type (Docker Compose, Node.js, ...) with <c>parse_status: success</c>
    /// and the out-of-scope-ness carried entirely in this field — see
    /// 19-STEP-002-SOLUTION-DISCOVERY.md's acceptance criteria. Both signals
    /// are checked; see <see cref="OutOfScopeStructuralTypes"/>.</summary>
    public required string StructuralType { get; init; }

    /// <summary>Package references step 2 already recorded — read directly
    /// here for FrameworkReferenceExtractor's package axis rather than
    /// re-parsed from the project file (Part A7). Step 2's <c>version_raw</c>
    /// and <c>declaration_source</c> fields are left unmodeled; only what
    /// FrameworkReferenceExtractor needs is carried.</summary>
    public IReadOnlyList<InventoryPackage> Packages { get; init; } = [];
}

public sealed record InventoryPackage
{
    public required string PackageName { get; init; }
    public string? VersionRaw { get; init; }
}

public static class OutOfScopeStructuralTypes
{
    public static readonly IReadOnlySet<string> Values = new HashSet<string>(StringComparer.Ordinal)
    {
        "docker_compose_project",
        "nodejs_project",
        "python_project",
        "javascript_project",
        "windows_packaging_project",
        "wix_installer_project",
        "deployment_project",
        "modeling_project",
        "unknown_project",
    };
}
