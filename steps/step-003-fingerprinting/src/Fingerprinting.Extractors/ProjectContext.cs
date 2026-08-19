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
}
