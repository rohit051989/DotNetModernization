using Fingerprinting.Analysis;
using Fingerprinting.Domain;
using Fingerprinting.Extractors;

namespace Fingerprinting.Cli;

/// <summary>
/// Builds the <see cref="ApplicationFingerprintArtifact"/> for one repository
/// from step 2's inventory. One fingerprint per project row, no aggregation,
/// no judgement about which projects are applications
/// (21-APPLICATION-FINGERPRINTING.md Part C).
/// </summary>
public sealed class FingerprintPipeline(SignalRegistry registry, IReadOnlyList<IFingerprintExtractor> extractors)
{
    // 1.1.0: extractor batch 2 (signal registry 1.4.0) — ApiUsageExtractor,
    // PathLiteralExtractor, appsettings*.json, repository-level signals.
    // 1.2.0: WCF_CLIENT_BINDING_CONFIG (signal registry 1.5.0).
    // 1.3.0: Web Deploy SetParameters files read for path literals, sensitive
    // keys and connection strings; UNQUALIFIED_HOSTNAME_URL (registry 1.7.0).
    // 1.4.0: console input — INTERACTIVE_CONSOLE_INPUT and
    // CONSOLE_PAUSE_FOR_INPUT from ApiUsageExtractor (registry 1.9.0).
    // 1.5.0 (registry 1.11.0): IisHostingExtractor (ASPNETCORE_HOSTING_MODEL),
    // USE_IIS_INVOCATION, the CONTAINER_* OpenShift-compliance signals read from
    // Dockerfiles and manifests, and SENSITIVE_CONFIG_KEY as a full key path
    // without descriptive keys (ClientCredentialType, TokenEndpoint).
    // 1.6.0 (registry 1.12.0): SENSITIVE_CONFIG_KEY by the leaf's full path,
    // VAULT_SECRET_REFERENCE, CONFIG_FILE_UNPARSEABLE, CUSTOM_FILE_LOGGER_PROVIDER
    // (FileLoggerProviderExtractor), WINDOWS_BUILD_PIPELINE, and the configuration
    // key on a path literal's evidence.
    // 1.7.0 (rbc-release-5): a project folder holding another project is read
    // without the nested one, so each project's own files are read once; projects in
    // parallel, bounded; a time limit per project, over which it is recorded FAILED with
    // NOT_CHECKED and the reason; progress, a timing profile, and finished projects kept so
    // a rerun continues from there.
    // Matches the application-fingerprinting step registration version.
    public const string ScannerVersion = "1.7.0";

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
        CancellationToken cancellationToken,
        IReadOnlyList<string>? deployParameterGlobs = null,
        StepProgress? progress = null,
        WorkLimits? limits = null,
        ProjectCheckpoints? checkpoints = null)
    {
        progress ??= StepProgress.Silent();
        limits ??= WorkLimits.Default;
        checkpoints ??= ProjectCheckpoints.None;
        var projects = new System.Collections.Concurrent.ConcurrentBag<ProjectFingerprint>();
        var artifactWarnings = new List<Warning>();

        // SetParameters files sit outside project directories; found once
        // and handed to the project they belong to.
        var deployFiles = Fingerprinting.Analysis.DeployParameterFiles.Discover(
            repositoryRoot, deployParameterGlobs ?? [], inventory.Projects.Select(p => p.RelativePath).ToList(), cancellationToken);

        // rbc-release-5: each project once, in parallel (bounded), within its own time limit; saved as it completes,
        // so a rerun continues from the last completed project.
        var resolved = new List<(InventoryProject Project, Guid Id)>();
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

            resolved.Add((inventoryProject, projectId.Value));
        }

        progress.Phase("fingerprint", resolved.Count);
        await Parallel.ForEachAsync(resolved, new ParallelOptions
        {
            MaxDegreeOfParallelism = Math.Clamp(Environment.ProcessorCount - 1, 1, 8), CancellationToken = cancellationToken,
        }, async (entry, ct) =>
        {
            var path = entry.Project.RelativePath;
            using var item = progress.Item(path);
            if (checkpoints.TryGet<ProjectFingerprint>(path, out var saved) && saved is not null)
            {
                projects.Add(saved);
                return;
            }

            using var limit = CancellationTokenSource.CreateLinkedTokenSource(ct);
            limit.CancelAfter(limits.ProjectLoad);
            ProjectFingerprint result;
            try
            {
                result = await BuildProjectFingerprintAsync(entry.Project, repositoryRoot, entry.Id,
                    deployFiles.Where(f => f.ProjectPath == path).ToList(), limit.Token);
            }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested)
            {
                var reason = $"not checked: fingerprinting the project took longer than {limits.ProjectLoad.TotalSeconds:0} s";
                progress.RecordNotChecked(path, "project", reason);
                result = new ProjectFingerprint
                {
                    ProjectId = entry.Id,
                    ProjectPath = path,
                    FingerprintStatus = FingerprintStatuses.Failed,
                    AnalysisCapabilities = new AnalysisCapabilities(),
                    Warnings = [new Warning { Code = WarningCodes.NotChecked, Message = reason, Severity = WarningSeverities.Warning }],
                };
            }

            checkpoints.Save(path, result);
            projects.Add(result);
        });

        // Sort collections per Part B rule 2 — projects by relative path —
        // never rely on inventory or extraction completion order.
        progress.Phase("repository");
        var ordered = projects.OrderBy(p => p.ProjectPath, StringComparer.Ordinal).ToList();
        artifactWarnings = artifactWarnings.OrderBy(w => w.Message, StringComparer.Ordinal).ToList();

        // Deployment files outside every fingerprinted project directory —
        // a root k8s/ folder, a repo-level Dockerfile. Without these, every
        // project in such a repository would read as having no manifests
        // (28-ITEM-AND-CONVERSION-MODEL.md Part E).
        var fingerprintedDirectories = ordered
            .Where(p => p.FingerprintStatus != FingerprintStatuses.Skipped)
            .Select(p => Path.GetDirectoryName(
                Path.Combine(repositoryRoot, p.ProjectPath.Replace('/', Path.DirectorySeparatorChar)))!)
            .ToList();
        var repositorySignals = Stamp(FileIndicatorExtractor.ExtractRepositoryLevel(
            repositoryRoot, fingerprintedDirectories, cancellationToken));

        registry.Validate(ordered.SelectMany(p => p.Signals).Concat(repositorySignals));

        var summary = BuildSummary(ordered);

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
            Projects = ordered,
            RepositorySignals = repositorySignals,
            Warnings = artifactWarnings,
        };
    }

    private async Task<ProjectFingerprint> BuildProjectFingerprintAsync(
        InventoryProject inventoryProject,
        string repositoryRoot,
        Guid projectId,
        IReadOnlyList<Fingerprinting.Analysis.DeployParameterFile> deployFiles,
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
            DeployParameterFiles = deployFiles,
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

        signals = Stamp(signals);

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

    /// <summary>Stamps each signal's evidence kind from the registry and
    /// sorts per Part B rule 2. Value is part of the order because a LITERAL
    /// or API_INVOCATION file carries several rows that differ only by value
    /// — without it their order would be extraction order.</summary>
    private List<Signal> Stamp(IEnumerable<Signal> signals) =>
        signals
            .Select(s => s with
            {
                // Falls back to NONE for a name the registry doesn't have —
                // harmless: registry.Validate fails the whole run for a
                // genuinely unregistered name regardless of this value.
                EvidenceKind = _evidenceKindByName.GetValueOrDefault(s.Name, SignalEvidenceKinds.None),
            })
            .OrderBy(s => s.Category, StringComparer.Ordinal)
            .ThenBy(s => s.Name, StringComparer.Ordinal)
            .ThenBy(s => s.SourcePath, StringComparer.Ordinal)
            .ThenBy(s => s.Value, StringComparer.Ordinal)
            .ToList();

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
