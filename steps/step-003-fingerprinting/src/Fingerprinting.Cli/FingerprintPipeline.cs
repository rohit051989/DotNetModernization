using Fingerprinting.Domain;
using Fingerprinting.Extractors;

namespace Fingerprinting.Cli;

/// <summary>
/// Builds the <see cref="ApplicationFingerprintArtifact"/> for one repository
/// from step 2's inventory. One fingerprint per project row, no aggregation,
/// no judgement about which projects are applications
/// (21-STEP-003-FINGERPRINTING.md Part C).
/// </summary>
public sealed class FingerprintPipeline(SignalRegistry registry, IReadOnlyList<IFingerprintExtractor> extractors)
{
    public const string ScannerVersion = "1.0.0";

    // The registry is the single source of truth for evidence_kind per
    // signal name (25-STANDARDS-AND-VIEWPOINTS.md Part A3 addendum) —
    // stamped onto every Signal here, once, so the native artifact and
    // fingerprint_signals self-describe file-vs-folder-vs-neither instead of
    // every downstream consumer (SARIF builder, step 4, a future evidence
    // viewer) re-deriving it from the signal name.
    private readonly IReadOnlyDictionary<string, string> _evidenceKindByName =
        registry.Entries.ToDictionary(e => e.Name, e => e.EvidenceKind, StringComparer.Ordinal);

    /// <param name="resolveProjectId">Looks up a project's database row id by
    /// its repository-relative path. Returns null if no matching row exists —
    /// the artifact carries no project id of its own (see
    /// SolutionProjectInventory.cs), so a project that cannot be resolved is
    /// dropped from the artifact with a repository-level warning rather than
    /// failing the whole scan (a fabricated id would violate the
    /// project_fingerprints -> projects foreign key anyway).</param>
    public async Task<ApplicationFingerprintArtifact> RunAsync(
        SolutionProjectInventory inventory,
        string repositoryRoot,
        Func<string, Guid?> resolveProjectId,
        CancellationToken cancellationToken)
    {
        var projects = new List<ProjectFingerprint>();
        var artifactWarnings = new List<Warning>();

        foreach (var inventoryProject in inventory.Projects)
        {
            var projectId = resolveProjectId(inventoryProject.RelativePath);
            if (projectId is null)
            {
                artifactWarnings.Add(new Warning
                {
                    Code = WarningCodes.ProjectDirectoryNotFound,
                    Message = $"'{inventoryProject.RelativePath}' has no matching row in the projects table " +
                              "(repository_id, relative_path) — dropped from this fingerprint.",
                    Severity = WarningSeverities.Warning,
                });
                continue;
            }

            projects.Add(await BuildProjectFingerprintAsync(inventoryProject, repositoryRoot, projectId.Value, cancellationToken));
        }

        // Sort collections per Part B rule 2 — projects by relative path —
        // never rely on inventory or extraction completion order.
        projects = projects.OrderBy(p => p.ProjectPath, StringComparer.Ordinal).ToList();
        artifactWarnings = artifactWarnings.OrderBy(w => w.Message, StringComparer.Ordinal).ToList();

        registry.Validate(projects.SelectMany(p => p.Signals));

        var summary = BuildSummary(projects);

        return new ApplicationFingerprintArtifact
        {
            ScannerVersion = ScannerVersion,
            SignalRegistryVersion = registry.RegistryVersion,
            RepositoryId = inventory.RepositoryId,
            RepositorySlug = inventory.RepositorySlug,
            RepositoryCommitSha = null,
            ScanStatus = DetermineScanStatus(summary),
            SemanticAnalysisEnabled = false,
            Summary = summary,
            Projects = projects,
            RepositorySignals = [],
            Warnings = artifactWarnings,
        };
    }

    private async Task<ProjectFingerprint> BuildProjectFingerprintAsync(
        InventoryProject inventoryProject,
        string repositoryRoot,
        Guid projectId,
        CancellationToken cancellationToken)
    {
        var outOfScope = inventoryProject.ParseStatus == "out_of_scope"
            || OutOfScopeStructuralTypes.Values.Contains(inventoryProject.StructuralType);

        if (outOfScope)
        {
            return new ProjectFingerprint
            {
                ProjectId = projectId,
                ProjectPath = inventoryProject.RelativePath,
                FingerprintStatus = FingerprintStatuses.Skipped,
                AnalysisCapabilities = new AnalysisCapabilities(),
            };
        }

        var projectDirectory = Path.GetDirectoryName(
            Path.Combine(repositoryRoot, inventoryProject.RelativePath.Replace('/', Path.DirectorySeparatorChar)))!;

        var context = new ProjectContext
        {
            ProjectId = projectId,
            RepositoryRoot = repositoryRoot,
            ProjectRelativePath = inventoryProject.RelativePath,
            ProjectDirectory = projectDirectory,
            Packages = inventoryProject.Packages
                .Select(p => new PackageReferenceInfo { PackageName = p.PackageName, VersionRaw = p.VersionRaw })
                .ToList(),
        };

        var signals = new List<Signal>();
        var warnings = new List<Warning>();

        foreach (var extractor in extractors)
        {
            if (!extractor.CanProcess(context))
            {
                continue;
            }

            var result = await extractor.ExtractAsync(context, cancellationToken);
            signals.AddRange(result.Signals);
            warnings.AddRange(result.Warnings);
        }

        signals = signals
            .Select(s => s with
            {
                // Falls back to NONE for a name the registry doesn't have —
                // harmless: registry.Validate below fails the whole run for
                // a genuinely unregistered name regardless of this value.
                EvidenceKind = _evidenceKindByName.GetValueOrDefault(s.Name, SignalEvidenceKinds.None),
            })
            .OrderBy(s => s.Category, StringComparer.Ordinal)
            .ThenBy(s => s.Name, StringComparer.Ordinal)
            .ThenBy(s => s.SourcePath, StringComparer.Ordinal)
            .ToList();

        var directoryFound = Directory.Exists(projectDirectory);
        if (directoryFound)
        {
            warnings.Add(new Warning
            {
                Code = WarningCodes.AnalysisLevelsPending,
                Message = "MSBuild evaluation and project metadata parsing (Level 2) have not run yet — " +
                          "projectSdk, nullableEnabled, implicitUsings and evaluatedProperties are unavailable. " +
                          "Semantic analysis (Level 4) is disabled by default (Part A4).",
                Severity = WarningSeverities.Info,
            });
        }
        else
        {
            warnings.Add(new Warning
            {
                Code = WarningCodes.ProjectDirectoryNotFound,
                Message = $"Project directory not found on disk: {projectDirectory}",
                Severity = WarningSeverities.Warning,
            });
        }

        warnings = warnings.OrderBy(w => w.Code, StringComparer.Ordinal).ToList();

        return new ProjectFingerprint
        {
            ProjectId = projectId,
            ProjectPath = inventoryProject.RelativePath,
            FingerprintStatus = directoryFound ? FingerprintStatuses.Partial : FingerprintStatuses.Failed,
            AnalysisCapabilities = new AnalysisCapabilities
            {
                FileDiscovery = directoryFound,
                SyntaxAnalysis = directoryFound,
                ConfigurationParsed = directoryFound,
                GeneratedCodeExcluded = directoryFound,
            },
            Signals = signals,
            Warnings = warnings,
        };
    }

    private static ScanSummary BuildSummary(IReadOnlyList<ProjectFingerprint> projects)
    {
        var byCategory = new SortedDictionary<string, int>(StringComparer.Ordinal);
        var totalSignals = 0;
        var totalEvidence = 0;

        foreach (var signal in projects.SelectMany(p => p.Signals))
        {
            totalSignals++;
            totalEvidence += signal.Evidence.Count;
            byCategory[signal.Category] = byCategory.GetValueOrDefault(signal.Category) + 1;
        }

        return new ScanSummary
        {
            ProjectsEligible = projects.Count(p => p.FingerprintStatus != FingerprintStatuses.Skipped),
            ProjectsComplete = projects.Count(p => p.FingerprintStatus == FingerprintStatuses.Complete),
            ProjectsPartial = projects.Count(p => p.FingerprintStatus == FingerprintStatuses.Partial),
            ProjectsFailed = projects.Count(p => p.FingerprintStatus == FingerprintStatuses.Failed),
            ProjectsSkipped = projects.Count(p => p.FingerprintStatus == FingerprintStatuses.Skipped),
            TotalSignals = totalSignals,
            TotalEvidence = totalEvidence,
            SignalsByCategory = byCategory,
        };
    }

    private static string DetermineScanStatus(ScanSummary summary)
    {
        if (summary.ProjectsEligible == 0)
        {
            return ScanStatuses.Complete;
        }

        if (summary.ProjectsFailed == summary.ProjectsEligible)
        {
            return ScanStatuses.Failed;
        }

        return summary.ProjectsPartial > 0 || summary.ProjectsFailed > 0
            ? ScanStatuses.Partial
            : ScanStatuses.Complete;
    }
}
