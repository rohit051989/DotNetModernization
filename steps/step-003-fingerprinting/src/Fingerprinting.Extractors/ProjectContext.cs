namespace Fingerprinting.Extractors;

/// <summary>
/// Everything an <see cref="IFingerprintExtractor"/> needs about one project.
/// See step-3-application-fingerprinting.md section 30.
/// </summary>
public sealed record ProjectContext
{
    public required Guid ProjectId { get; init; }

    /// <summary>Absolute path to the repository root on disk.</summary>
    public required string RepositoryRoot { get; init; }

    /// <summary>Repository-relative path to the project file, forward-slash
    /// separated, e.g. <c>src/Web/Web.csproj</c> — matches step 2's
    /// <c>projects.relative_path</c>.</summary>
    public required string ProjectRelativePath { get; init; }

    /// <summary>Absolute path to the directory containing the project file.</summary>
    public required string ProjectDirectory { get; init; }

    /// <summary>Package references step 2 already recorded for this project —
    /// read here, never re-parsed from the project file
    /// (21-STEP-003-FINGERPRINTING.md Part A7). Empty for projects step 2
    /// found no packages for.</summary>
    public IReadOnlyList<PackageReferenceInfo> Packages { get; init; } = [];

    /// <summary>Web Deploy SetParameters files belonging to this project —
    /// in a folder named after it, or under its directory — found by the
    /// engagement's globs (registry 1.7.0). They usually sit outside the
    /// project directory (CustomFiles\Catalog.Host\SetParamFiles\PROD\).</summary>
    public IReadOnlyList<Fingerprinting.Analysis.DeployParameterFile> DeployParameterFiles { get; init; } = [];
}

/// <summary>One package reference as step 2 recorded it — the slice
/// FrameworkReferenceExtractor needs, not a full re-model of step 2's schema.</summary>
public sealed record PackageReferenceInfo
{
    public required string PackageName { get; init; }
    public string? VersionRaw { get; init; }
}
