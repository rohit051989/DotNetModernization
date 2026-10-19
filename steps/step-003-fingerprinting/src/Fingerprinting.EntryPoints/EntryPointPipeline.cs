using System.Security.Cryptography;
using System.Text;
using Fingerprinting.Domain;

namespace Fingerprinting.EntryPoints;

/// <summary>One project as the pipeline receives it: step 2's path and
/// packages, the database id, and step 3's verdict on whether to scan it.</summary>
public sealed record InputProject(string RelativePath, Guid ProjectId, string? SkipReason, IReadOnlyList<string> Packages)
{
    /// <summary>Step 2's project SDK (Microsoft.NET.Sdk.Web, ...), for the framework delta signals.</summary>
    public string? ProjectSdk { get; init; }
}

public sealed record InventoryInput(
    Guid RepositoryId,
    string RepositorySlug,
    string SkipSource,
    IReadOnlyList<InputProject> Projects,
    IReadOnlyList<Warning> Warnings)
{
    /// <summary>Step 2's resolved project references: (source, referenced).</summary>
    public IReadOnlyList<(string Source, string Referenced)> ProjectReferences { get; init; } = [];
}

/// <summary>
/// Builds the entry-point-inventory@1.0.0 artifact for one repository —
/// 29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md Part B. Deterministic per step 3's rules:
/// every collection sorted, ids derived, nothing time- or machine-dependent.
/// </summary>
public sealed class EntryPointPipeline
{
    /// <summary>Matches the entry-point-inventory step registration version. 2.4.0 (rbc-release-5): each project's own
    /// files only (a nested project's are its own); projects loaded in parallel, bounded, each within a time limit,
    /// over which it is recorded NOT_CHECKED with the reason; progress and a timing profile. Artifact unchanged.</summary>
    public const string ScannerVersion = "2.4.0";

    private static readonly IReadOnlyList<IEntryPointDetector> Detectors =
    [
        new ControllerActionDetector(),
        new MinimalApiDetector(),
        new RazorPageDetector(),
        new WcfOperationDetector(),
        new AsmxWebMethodDetector(),
        new GrpcServiceMethodDetector(),
        new SignalRHubMethodDetector(),
        new MessageConsumerDetector(),
        new HostedServiceDetector(),
        new ScheduledJobDetector(),
        new WebFormsPageDetector(),
        // 2.0.0.
        new WindowsServiceDetector(),
        new HttpHandlerDetector(),
        new GlobalAsaxDetector(),
        new OwinStartupDetector(),
        new BlazorComponentDetector(),
        new AzureFunctionDetector(),
        new DesktopAppDetector(),
    ];

    private static readonly ConsoleMainDetector ConsoleMain = new();

    public async Task<EntryPointInventoryArtifact> RunAsync(
        InventoryInput input, string repositoryRoot, CancellationToken cancellationToken, StepProgress? progress = null,
        WorkLimits? limits = null, ProjectCheckpoints? checkpoints = null)
    {
        progress ??= StepProgress.Silent();
        limits ??= WorkLimits.Default;
        checkpoints ??= ProjectCheckpoints.None;
        var loadedByPath = new System.Collections.Concurrent.ConcurrentDictionary<string, (InputProject Input, ProjectSource Source)>(StringComparer.Ordinal);
        var other = new System.Collections.Concurrent.ConcurrentBag<ProjectEntryPoints>();

        // rbc-release-5: each project read once, in parallel (bounded), within its own time limit.
        progress.Phase("load", input.Projects.Count);
        await Parallel.ForEachAsync(input.Projects, new ParallelOptions
        {
            MaxDegreeOfParallelism = Math.Clamp(Environment.ProcessorCount - 1, 1, 8), CancellationToken = cancellationToken,
        }, async (project, ct) =>
        {
            using var item = progress.Item(project.RelativePath);
            if (project.SkipReason is not null)
            {
                other.Add(Empty(project, ProjectScanStatuses.Skipped, project.SkipReason, []));
                return;
            }

            var directory = Path.GetDirectoryName(Path.Combine(repositoryRoot, project.RelativePath.Replace('/', Path.DirectorySeparatorChar)))!;
            if (!Directory.Exists(directory))
            {
                other.Add(Empty(project, ProjectScanStatuses.Failed, null,
                [
                    new Warning
                    {
                        Code = WarningCodes.ProjectDirectoryNotFound,
                        Message = $"Project directory not found on disk: {project.RelativePath}",
                        Severity = WarningSeverities.Warning,
                    },
                ]));
                return;
            }

            if (checkpoints.Skipped(project.RelativePath, out var skipped))
            {
                // Not retried: an earlier, interrupted run recorded it, or was stuck on it (rbc-release-5).
                progress.RecordNotChecked(project.RelativePath, "project", skipped);
                other.Add(Empty(project, ProjectScanStatuses.Failed, null,
                    [new Warning { Code = WarningCodes.NotChecked, Message = skipped, Severity = WarningSeverities.Warning }]));
                return;
            }

            using var limit = CancellationTokenSource.CreateLinkedTokenSource(ct);
            limit.CancelAfter(limits.ProjectLoad);
            try
            {
                loadedByPath[project.RelativePath] = (project, await ProjectSource.LoadAsync(
                    repositoryRoot, project.RelativePath, project.Packages, EntryPointAuxiliaryFiles.Instance, limit.Token,
                    fileTimed: (path, took) => progress.Timed(path, "file", took), fileLimit: limits.File));
            }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested)
            {
                var reason = $"not checked: loading the project took longer than {limits.ProjectLoad.TotalSeconds:0} s";
                progress.RecordNotChecked(project.RelativePath, "project", reason);
                checkpoints.MarkNotChecked(project.RelativePath, reason);
                other.Add(Empty(project, ProjectScanStatuses.Failed, null,
                    [new Warning { Code = WarningCodes.NotChecked, Message = reason, Severity = WarningSeverities.Warning }]));
            }
        });

        var loaded = loadedByPath.Values.OrderBy(l => l.Input.RelativePath, StringComparer.Ordinal).ToList();
        var results = other.ToList();
        progress.Phase("index");

        // Contracts, implementations and hosts can sit in different
        // projects — or, for an IIS folder of .svc files, in none — so the
        // WCF index spans the whole repository before any project is detected.
        var repository = LoadRepositoryFiles(repositoryRoot, cancellationToken);
        var wcf = WcfContractIndex.Build(loaded.Select(l => l.Source).ToList(), repository);

        // Every type the repository declares, fully named — what decides
        // whether a registered handler or module is the application's own.
        var repositoryTypes = loaded
            .SelectMany(l => l.Source.Types)
            .Select(t => t.Namespace is null ? t.Name : $"{t.Namespace}.{t.Name}")
            .ToHashSet(StringComparer.Ordinal);

        progress.Phase("detect", loaded.Count);
        foreach (var (project, source) in loaded)
        {
            using var item = progress.Item(project.RelativePath);
            results.Add(Detect(input.RepositoryId, project, source, wcf, repository, repositoryTypes));
        }

        progress.Phase("architecture");

        // 2.2.0: what each project exposes or hosts, across projects.
        var signals = ArchitectureSignals.Build(results, input.Projects.Select(p => p.RelativePath).ToList());
        // 2.3.0: known breaking changes of a later framework (the framework delta catalog).
        var deltas = FrameworkDeltaSignals.Build(
            loaded.Select(l => (l.Input.RelativePath, l.Input.ProjectSdk, l.Source)).ToList(), input.ProjectReferences);
        results = results
            .Select(r => r with
            {
                Signals = (signals.GetValueOrDefault(r.ProjectPath) ?? []).Concat(deltas.GetValueOrDefault(r.ProjectPath) ?? [])
                    .OrderBy(s => s.Name, StringComparer.Ordinal).ThenBy(s => s.SourcePath ?? "", StringComparer.Ordinal)
                    .ThenBy(s => s.Value ?? "", StringComparer.Ordinal).ToList(),
            })
            .OrderBy(r => r.ProjectPath, StringComparer.Ordinal).ToList();
        return new EntryPointInventoryArtifact
        {
            ScannerVersion = ScannerVersion,
            RepositoryId = input.RepositoryId,
            RepositorySlug = input.RepositorySlug,
            SemanticAnalysisEnabled = false,
            SkipSource = input.SkipSource,
            Capabilities = CapabilityManifest.Stamp(),
            Summary = Summarise(results),
            Projects = results,
            Warnings = input.Warnings.OrderBy(w => w.Message, StringComparer.Ordinal).ToList(),
        };
    }

    /// <summary>Every .svc, web.config and app.config in the repository,
    /// with the same directory exclusions as every other walk.</summary>
    public static RepositoryFiles LoadRepositoryFiles(string repositoryRoot, CancellationToken cancellationToken)
    {
        var svc = new List<(string, string)>();
        var configs = new List<ConfigFile>();
        foreach (var path in Analysis.FileSystemWalk.EnumerateFiles(repositoryRoot, cancellationToken))
        {
            var relative = Analysis.FileSystemWalk.ToRepositoryRelativePath(repositoryRoot, path);
            if (path.EndsWith(".svc", StringComparison.OrdinalIgnoreCase))
            {
                svc.Add((relative, File.ReadAllText(path)));
            }
            else if (ConfigFile.IsConfigFileName(path))
            {
                configs.Add(ConfigFile.Parse(relative, File.ReadAllText(path)));
            }
        }

        return new RepositoryFiles(
            svc.OrderBy(s => s.Item1, StringComparer.Ordinal).ToList(),
            configs.OrderBy(c => c.RelativePath, StringComparer.Ordinal).ToList());
    }

    public static ProjectEntryPoints Detect(
        Guid repositoryId, InputProject project, ProjectSource source, WcfContractIndex wcf, RepositoryFiles? repository = null,
        IReadOnlySet<string>? repositoryTypes = null)
    {
        var conventions = ProjectConventions.Read(source);
        var context = new DetectionContext(source, conventions, wcf, repository ?? RepositoryFiles.Empty);

        var detected = Detectors.SelectMany(d => d.Detect(context)).ToList();
        if (detected.Count == 0)
        {
            // Part B1: Main or top-level statements count only for a project
            // with no other entry points.
            detected = ConsoleMain.Detect(context).ToList();
        }

        var entries = AssignIds(repositoryId, source.ProjectPath, detected)
            .Select(e => Classify(e, repositoryTypes ?? source.Types.Select(t => t.Namespace is null ? t.Name : $"{t.Namespace}.{t.Name}").ToHashSet(StringComparer.Ordinal)))
            .OrderBy(e => e.Kind, StringComparer.Ordinal)
            .ThenBy(e => e.Http?.RouteTemplate ?? e.Http?.MappedTemplate ?? "", StringComparer.Ordinal)
            .ThenBy(e => e.Http?.Verb ?? "", StringComparer.Ordinal)
            .ThenBy(e => e.Handler.Type, StringComparer.Ordinal)
            .ThenBy(e => e.Handler.Member ?? "", StringComparer.Ordinal)
            .ThenBy(e => e.Handler.FilePath, StringComparer.Ordinal)
            .ThenBy(e => e.Handler.LineStart)
            .ThenBy(e => e.EntryPointId, StringComparer.Ordinal)
            .ToList();

        var warnings = new List<Warning>();
        if (source.Truncated)
        {
            warnings.Add(new Warning
            {
                Code = WarningCodes.SourceFileCapExceeded,
                Message = $"More than {Analysis.SourceFileScanner.MaxFilesPerProject} C# files; the rest were not read.",
                Severity = WarningSeverities.Warning,
            });
        }

        return new ProjectEntryPoints
        {
            ProjectId = project.ProjectId,
            ProjectPath = project.RelativePath,
            Status = ProjectScanStatuses.Scanned,
            Summary = new ProjectEntryPointSummary
            {
                RequestEntryPointCount = entries.Count(e => e.EntryClass == EntryClasses.Request),
                LifecycleHookCount = entries.Count(e => e.EntryClass == EntryClasses.Lifecycle),
                CountByKind = Count(entries.Select(e => e.Kind)),
                CountByOrigin = Count(entries.Select(e => e.Origin)),
                CountByVerb = Count(entries.Where(e => e.Http is not null).Select(e => e.Http!.Verb)),
                NoDeclaredAuthenticationCount = entries.Count(e => e.AuthDeclared == AuthDeclared.NoneDeclared),
                AuthorisationNotAssessedCount = entries.Count(e => e.AuthDeclared == AuthDeclared.NotAssessed),
                GlobalAuthorisation = conventions.AllGlobalAuthorisation,
                ConventionalRoutes = conventions.ConventionalRoutes,
            },
            EntryPoints = entries,
            Warnings = warnings,
        };
    }

    /// <summary>
    /// Part B3: <c>entryPointId</c> is derived — sha256 over repository,
    /// project, kind, handler, route and verb, truncated to 32 hex digits —
    /// so it is stable across rescans and anything keyed to it survives one.
    /// The repository is in the hash because the id is the table's primary
    /// key and two repositories can hold identical projects (a fork). A
    /// genuine duplicate (the same handler mapped twice to the same route)
    /// gets an ordinal, in source order.
    /// </summary>
    public static IEnumerable<EntryPointRecord> AssignIds(Guid repositoryId, string projectPath, IReadOnlyList<DetectedEntryPoint> detected)
    {
        var groups = detected
            .GroupBy(d => $"{repositoryId:D}\n{projectPath}\n{d.Record.Kind}\n{d.HandlerIdentity}\n{d.Route ?? ""}\n{d.Verb ?? ""}", StringComparer.Ordinal);
        foreach (var group in groups)
        {
            var ordinal = 0;
            foreach (var entry in group.OrderBy(d => d.Record.Handler.FilePath, StringComparer.Ordinal).ThenBy(d => d.Record.Handler.LineStart))
            {
                ordinal++;
                var key = ordinal == 1 ? group.Key : $"{group.Key}\n#{ordinal}";
                yield return entry.Record with { EntryPointId = Hash(key) };
            }
        }
    }

    /// <summary>
    /// Stamps <c>origin</c> and <c>entryClass</c>. Origin: an entry point
    /// found in source is the application's; a web.config registration of a
    /// type no project in the repository declares is a framework or package
    /// type's (the registration may sit in one project and the type in
    /// another, so the whole repository is checked). A lifecycle hook carries
    /// no authDeclared: authentication is a question about requests.
    /// </summary>
    public static EntryPointRecord Classify(EntryPointRecord record, IReadOnlySet<string> repositoryTypes)
    {
        var handler = record.HttpHandler;
        if (handler is { InRepository: false } && repositoryTypes.Contains(handler.TypeName))
        {
            handler = handler with { InRepository = true };
        }

        var classified = record with
        {
            HttpHandler = handler,
            Origin = handler is { InRepository: false } ? EntryPointOrigins.Framework : EntryPointOrigins.Application,
        };
        var entryClass = EntryClasses.For(classified);
        return classified with
        {
            EntryClass = entryClass,
            AuthDeclared = entryClass == EntryClasses.Lifecycle ? null : classified.AuthDeclared,
        };
    }

    public static string Hash(string key) =>
        Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(key)))[..32];

    private static ProjectEntryPoints Empty(InputProject project, string status, string? skipReason, IReadOnlyList<Warning> warnings) => new()
    {
        ProjectId = project.ProjectId,
        ProjectPath = project.RelativePath,
        Status = status,
        SkipReason = skipReason,
        Summary = new ProjectEntryPointSummary(),
        Warnings = warnings,
    };

    private static InventorySummary Summarise(IReadOnlyList<ProjectEntryPoints> projects)
    {
        var entries = projects.SelectMany(p => p.EntryPoints).ToList();
        return new InventorySummary
        {
            ProjectsScanned = projects.Count(p => p.Status == ProjectScanStatuses.Scanned),
            ProjectsSkipped = projects.Count(p => p.Status == ProjectScanStatuses.Skipped),
            ProjectsFailed = projects.Count(p => p.Status == ProjectScanStatuses.Failed),
            EntryPointCount = entries.Count,
            RequestEntryPointCount = entries.Count(e => e.EntryClass == EntryClasses.Request),
            LifecycleHookCount = entries.Count(e => e.EntryClass == EntryClasses.Lifecycle),
            CountByKind = Count(entries.Select(e => e.Kind)),
            CountByOrigin = Count(entries.Select(e => e.Origin)),
            CountByVerb = Count(entries.Where(e => e.Http is not null).Select(e => e.Http!.Verb)),
            NoDeclaredAuthenticationCount = projects.Sum(p => p.Summary.NoDeclaredAuthenticationCount),
            AuthorisationNotAssessedCount = projects.Sum(p => p.Summary.AuthorisationNotAssessedCount),
        };
    }

    private static SortedDictionary<string, int> Count(IEnumerable<string> values)
    {
        var counts = new SortedDictionary<string, int>(StringComparer.Ordinal);
        foreach (var value in values)
        {
            counts[value] = counts.GetValueOrDefault(value) + 1;
        }

        return counts;
    }
}
