using System.Security.Cryptography;
using System.Text;
using Fingerprinting.Analysis;
using Fingerprinting.Domain;

namespace Fingerprinting.Outbound;

/// <summary>One project as the pipeline receives it: step 2's path and
/// packages, the database id, step 3's verdict on whether to scan it, and
/// step 3's UNC path literals for it.</summary>
public sealed record OutboundInputProject(
    string RelativePath, Guid ProjectId, string? SkipReason, IReadOnlyList<string> Packages, IReadOnlyList<UncLiteral> UncLiterals)
{
    /// <summary>Step 2's output type and SDK (1.3.0): whether the project is a host.</summary>
    public string? OutputType { get; init; }
    public string? ProjectSdk { get; init; }
}

public sealed record OutboundInput(
    Guid RepositoryId,
    string RepositorySlug,
    string SkipSource,
    IReadOnlyList<OutboundInputProject> Projects,
    IReadOnlyList<Warning> Warnings)
{
    /// <summary>Step 2's resolved references, source → referenced (1.3.0).</summary>
    public IReadOnlyList<(string Source, string Referenced)> ProjectReferences { get; init; } = [];

    /// <summary>The engagement's SetParameters globs (1.3.0); empty means the defaults.</summary>
    public IReadOnlyList<string> DeployParameterGlobs { get; init; } = [];

    /// <summary>Step 4's entry points (1.3.0), for <see cref="BackendReach"/>.</summary>
    public IReadOnlyList<InboundEntryPoint> EntryPoints { get; init; } = [];

    /// <summary>1.4.0: the engagement's target framework, and the WCF client
    /// support matrix the SOAP runtime verdicts come from (<see cref="RuntimeVerdicts"/>).</summary>
    public string? TargetFramework { get; init; }
    public WcfClientSupport? WcfClientSupport { get; init; }

    /// <summary>1.5.0: the WCF client platform matrix the SOAP platform verdicts come from.</summary>
    public WcfClientSupport? WcfClientPlatform { get; init; }
}

/// <summary>
/// Builds the outbound-invocation-inventory@1.0.0 artifact for one
/// repository — 29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md Part C. Deterministic per
/// step 3's rules: every collection sorted, ids derived, nothing time- or
/// machine-dependent.
/// </summary>
public sealed class OutboundPipeline
{
    /// <summary>Matches the outbound-invocation-inventory step registration version. 1.5.1: the WCF client
    /// matrices 1.1.0 (the wildcard rule; reviewer decisions); artifact 1.5.0 unchanged. 1.6.0: a SOAP client built by
    /// a custom helper from options-bound configuration (WCFClientHelper.CreateClient&lt;T&gt;(name)) — call sites followed
    /// up through generic callers, binding, mode, credential and address read per environment; artifact unchanged.
    /// 1.7.0 (release 5): each project's own files only (a nested project's are its own); one repository index
    /// shared by every project instead of a walk of the repository per project, and call sites found from an index
    /// of invocations instead of a walk of the project per call site; projects in parallel, bounded, each within a
    /// time limit, and each file within its own, over which it is recorded NOT_CHECKED with the reason; every
    /// unresolved operation names its reason; progress, a timing profile, and finished projects kept so a rerun
    /// continues from there. Artifact unchanged.
    /// 1.7.1: the WCF client platform matrix 1.2.1, wording only; no verdict changed. Artifact unchanged.</summary>
    public const string ScannerVersion = "1.7.1";

    /// <summary>Projects loaded and analysed at once: bounded, leaving a core for the rest of the machine.</summary>
    public static int Parallelism { get; } = Math.Clamp(Environment.ProcessorCount - 1, 1, 8);

    public async Task<OutboundInventoryArtifact> RunAsync(
        OutboundInput input, string repositoryRoot, CancellationToken cancellationToken, StepProgress? progress = null,
        WorkLimits? limits = null, ProjectCheckpoints? checkpoints = null)
    {
        progress ??= StepProgress.Silent();
        limits ??= WorkLimits.Default;
        checkpoints ??= ProjectCheckpoints.None;
        var results = new List<ProjectInvocations>();
        var loadedByPath = new System.Collections.Concurrent.ConcurrentDictionary<string, (OutboundInputProject Input, ProjectSource Source)>(StringComparer.Ordinal);
        var failedByPath = new System.Collections.Concurrent.ConcurrentDictionary<string, ProjectInvocations>(StringComparer.Ordinal);

        // Each project is read and parsed once — however many solutions include it — in parallel, each within its own
        // time limit (release 5).
        progress.Phase("load", input.Projects.Count);
        await Parallel.ForEachAsync(input.Projects, new ParallelOptions { MaxDegreeOfParallelism = Parallelism, CancellationToken = cancellationToken },
            async (project, ct) =>
        {
            using var item = progress.Item(project.RelativePath);
            if (project.SkipReason is not null)
            {
                failedByPath[project.RelativePath] = Empty(project, ProjectScanStatuses.Skipped, project.SkipReason, []);
                return;
            }

            var directory = Path.GetDirectoryName(Path.Combine(repositoryRoot, project.RelativePath.Replace('/', Path.DirectorySeparatorChar)))!;
            if (!Directory.Exists(directory))
            {
                failedByPath[project.RelativePath] = Empty(project, ProjectScanStatuses.Failed, null,
                [
                    new Warning
                    {
                        Code = WarningCodes.ProjectDirectoryNotFound,
                        Message = $"Project directory not found on disk: {project.RelativePath}",
                        Severity = WarningSeverities.Warning,
                    },
                ]);
                return;
            }

            if (checkpoints.Skipped(project.RelativePath, out var skipped))
            {
                // Not retried: an earlier, interrupted run recorded it, or was stuck on it (release 5).
                progress.RecordNotChecked(project.RelativePath, "project", skipped);
                failedByPath[project.RelativePath] = Empty(project, ProjectScanStatuses.Failed, null,
                    [new Warning { Code = WarningCodes.NotChecked, Message = skipped, Severity = WarningSeverities.Warning }]);
                return;
            }

            // Generated files are loaded (flagged) so a service reference's
            // Reference.cs can supply a binding; nothing else reads them.
            using var limit = CancellationTokenSource.CreateLinkedTokenSource(ct);
            limit.CancelAfter(limits.ProjectLoad);
            try
            {
                var source = await ProjectSource.LoadAsync(
                    repositoryRoot, project.RelativePath, project.Packages, NoAuxiliaryFiles.Instance, limit.Token, includeGenerated: true,
                    fileTimed: (path, took) => progress.Timed(path, "file", took), fileLimit: limits.File);
                foreach (var (path, reason) in source.NotChecked)
                {
                    progress.RecordNotChecked(path, "file", reason);
                }

                loadedByPath[project.RelativePath] = (project, source);
            }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested)
            {
                var reason = $"not checked: loading the project took longer than {limits.ProjectLoad.TotalSeconds:0} s";
                progress.RecordNotChecked(project.RelativePath, "project", reason);
                checkpoints.MarkNotChecked(project.RelativePath, reason);
                failedByPath[project.RelativePath] = Empty(project, ProjectScanStatuses.Failed, null,
                    [new Warning { Code = WarningCodes.NotChecked, Message = reason, Severity = WarningSeverities.Warning }]);
            }
        });

        results.AddRange(failedByPath.Values);
        var loaded = loadedByPath.Values.OrderBy(l => l.Input.RelativePath, StringComparer.Ordinal).ToList();

        progress.Phase("configuration");

        var projectPaths = input.Projects.Select(p => p.RelativePath).ToList();
        var deployFiles = DeployParameterFiles.Discover(repositoryRoot, input.DeployParameterGlobs, projectPaths, cancellationToken);
        var config = RepositoryConfig.Build(repositoryRoot, cancellationToken)
            .WithDeployParameters(deployFiles, ReadDeclarations(repositoryRoot, deployFiles));
        config = config.WithHosts(ResolveHosts(input.Projects, input.ProjectReferences, config));
        results.AddRange(Detect(input.RepositoryId, loaded, config, input.EntryPoints,
            new SoapMatrices(input.TargetFramework, input.WcfClientSupport, input.WcfClientPlatform), progress, limits, checkpoints));
        results = results.OrderBy(r => r.ProjectPath, StringComparer.Ordinal).ToList();

        var warnings = input.Warnings.ToList();
        warnings.AddRange(deployFiles.Where(f => f.ProjectPath is null).Select(f => new Warning
        {
            Code = WarningCodes.ProjectDirectoryNotFound,
            Message = $"SetParameters file '{f.RelativePath}' is not under, or in a folder named after, any project; its parameters are not applied.",
            Severity = WarningSeverities.Warning,
        }));

        return new OutboundInventoryArtifact
        {
            ScannerVersion = ScannerVersion,
            RepositoryId = input.RepositoryId,
            RepositorySlug = input.RepositorySlug,
            SemanticAnalysisEnabled = false,
            SkipSource = input.SkipSource,
            WcfClientSupport = input.WcfClientSupport is { } matrix && input.TargetFramework is { } target
                ? new WcfClientSupportStamp
                {
                    MatrixVersion = matrix.MatrixVersion, Target = target, Sha256 = matrix.Sha256, UnconfirmedEntries = matrix.UnconfirmedCount,
                    PlatformMatrixVersion = input.WcfClientPlatform?.MatrixVersion, PlatformSha256 = input.WcfClientPlatform?.Sha256,
                }
                : null,
            Summary = Summarise(results),
            Projects = results,
            Warnings = warnings.OrderBy(w => w.Message, StringComparer.Ordinal).ToList(),
        };
    }

    /// <summary>Each SetParameters file's project directory's parameters.xml, by directory.</summary>
    private static IReadOnlyDictionary<string, string> ReadDeclarations(string repositoryRoot, IReadOnlyList<DeployParameterFile> files)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var project in files.Select(f => f.ProjectPath).OfType<string>().Distinct(StringComparer.Ordinal))
        {
            var directory = project.Contains('/') ? project[..project.LastIndexOf('/')] : "";
            var absolute = Path.Combine(repositoryRoot, directory.Replace('/', Path.DirectorySeparatorChar));
            var declarations = Directory.Exists(absolute)
                ? Directory.EnumerateFiles(absolute).FirstOrDefault(f => Path.GetFileName(f).Equals("parameters.xml", StringComparison.OrdinalIgnoreCase))
                : null;
            if (declarations is not null)
            {
                result[directory] = File.ReadAllText(declarations);
            }
        }

        return result;
    }

    /// <summary>
    /// A class library's hosts (1.3.0): the executable and web projects that
    /// reference it, directly or through other libraries. Only a project that
    /// is not itself a host and has no configuration file of its own gets
    /// hosts — in .NET, App.config and web.config belong to the process.
    /// </summary>
    public static IReadOnlyDictionary<string, IReadOnlyList<HostRef>> ResolveHosts(
        IReadOnlyList<OutboundInputProject> projects, IReadOnlyList<(string Source, string Referenced)> references, RepositoryConfig config)
    {
        static string DirectoryOf(string path) => path.Contains('/') ? path[..path.LastIndexOf('/')] : "";
        // An executable, a web SDK project, or a project with a web.config
        // (a classic ASP.NET or WCF web host).
        bool IsHost(OutboundInputProject p) =>
            p.OutputType is "Exe" or "WinExe" or "AppContainerExe"
            || (p.ProjectSdk ?? "").Contains(".Web", StringComparison.OrdinalIgnoreCase)
            || HasWebConfig(config, DirectoryOf(p.RelativePath));

        var byPath = projects.ToDictionary(p => p.RelativePath, StringComparer.Ordinal);
        var referencedBy = references.GroupBy(r => r.Referenced, StringComparer.Ordinal)
            .ToDictionary(g => g.Key, g => g.Select(r => r.Source).Distinct(StringComparer.Ordinal).ToList(), StringComparer.Ordinal);

        var result = new Dictionary<string, IReadOnlyList<HostRef>>(StringComparer.OrdinalIgnoreCase);
        foreach (var project in projects)
        {
            var directory = DirectoryOf(project.RelativePath);
            if (IsHost(project) || config.ConfigDirectories.Contains(directory))
            {
                continue;
            }

            var hosts = new SortedSet<string>(StringComparer.Ordinal);
            var seen = new HashSet<string>(StringComparer.Ordinal) { project.RelativePath };
            var pending = new Queue<string>([project.RelativePath]);
            while (pending.Count > 0)
            {
                foreach (var source in referencedBy.GetValueOrDefault(pending.Dequeue()) ?? [])
                {
                    if (!seen.Add(source))
                    {
                        continue;
                    }

                    if (byPath.TryGetValue(source, out var referencing) && IsHost(referencing))
                    {
                        hosts.Add(source);
                    }
                    else
                    {
                        pending.Enqueue(source);   // a library in between: keep walking up
                    }
                }
            }

            if (hosts.Count > 0)
            {
                result[directory] = hosts.Select(h => new HostRef(h, DirectoryOf(h))).ToList();
            }
        }

        return result;
    }

    private static bool HasWebConfig(RepositoryConfig config, string directory) =>
        config.Entries.Any(e => e.Directory.Equals(directory, StringComparison.OrdinalIgnoreCase) && e.File.EndsWith("eb.config", StringComparison.OrdinalIgnoreCase))
        || config.ClientEndpoints.Any(e => e.Directory.Equals(directory, StringComparison.OrdinalIgnoreCase) && e.File.EndsWith("eb.config", StringComparison.OrdinalIgnoreCase));

    /// <summary>Detection over already-loaded projects — the entry point tests use.</summary>
    public static IReadOnlyList<ProjectInvocations> Detect(
        Guid repositoryId, IReadOnlyList<(OutboundInputProject Input, ProjectSource Source)> loaded, RepositoryConfig config,
        IReadOnlyList<InboundEntryPoint>? entryPoints = null, SoapMatrices? soapMatrices = null, StepProgress? progress = null,
        WorkLimits? limits = null, ProjectCheckpoints? checkpoints = null)
    {
        progress ??= StepProgress.Silent();
        limits ??= WorkLimits.Default;
        checkpoints ??= ProjectCheckpoints.None;
        var sources = loaded.Select(l => l.Source).ToList();
        progress.Phase("index");
        var symbols = SymbolIndex.Build(sources);
        var index = new RepositoryIndex(sources);
        var claimed = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var contexts = loaded.Select(l => (l.Input, Context: new DetectionContext
        {
            Project = l.Source,
            Resolver = new ValueResolver(l.Source, symbols, config),
            Symbols = symbols,
            Config = config,
            Repository = sources,
            UncLiterals = l.Input.UncLiterals,
            ClaimedEndpoints = claimed,
            Index = index,
        })).ToList();
        var references = DatabaseDetector.IndexReferences(contexts.Select(c => c.Context));

        // SOAP clients in code first, for every project: a library's client
        // claims its host's endpoint entry before the host looks for entries
        // nothing claimed (1.3.0).
        // Each project's SOAP passes within its time limit too (release 5): a project over it is not checked, and
        // the others carry on. A project an earlier, interrupted run did not finish because it hit a wall is not retried (ProjectCheckpoints.Skipped).
        progress.Phase("soap clients", contexts.Count);
        var soap = new Dictionary<string, List<Detected>>(StringComparer.Ordinal);
        var configOnly = new Dictionary<string, List<Detected>>(StringComparer.Ordinal);
        var stopped = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var c in contexts)
        {
            using var item = progress.Item(c.Input.RelativePath);
            if (checkpoints.Skipped(c.Input.RelativePath, out var skipped))
            {
                soap[c.Input.RelativePath] = [];
                stopped[c.Input.RelativePath] = skipped;
                continue;
            }

            using var limit = new CancellationTokenSource(limits.ProjectLoad);
            c.Context.Cancellation = limit.Token;
            try
            {
                soap[c.Input.RelativePath] = SoapClientDetector.Detect(c.Context).ToList();
            }
            catch (OperationCanceledException)
            {
                soap[c.Input.RelativePath] = [];
                stopped[c.Input.RelativePath] = $"not checked: analysing the project's SOAP clients took longer than {limits.ProjectLoad.TotalSeconds:0} s";
            }
        }

        // Configuration-only endpoints claim entries too, in project order: kept in order, as before.
        foreach (var c in contexts)
        {
            if (stopped.ContainsKey(c.Input.RelativePath))
            {
                configOnly[c.Input.RelativePath] = [];
                continue;
            }

            using var limit = new CancellationTokenSource(limits.ProjectLoad);
            c.Context.Cancellation = limit.Token;
            try
            {
                configOnly[c.Input.RelativePath] = SoapClientDetector.DetectConfigOnly(c.Context).ToList();
            }
            catch (OperationCanceledException)
            {
                configOnly[c.Input.RelativePath] = [];
                stopped[c.Input.RelativePath] = $"not checked: analysing the project's configured endpoints took longer than {limits.ProjectLoad.TotalSeconds:0} s";
            }
        }

        // The rest, per project, in parallel; each project within its own time limit, and saved as it completes so a
        // rerun continues from there (release 5).
        progress.Phase("detect", contexts.Count);
        var detectedByPath = new System.Collections.Concurrent.ConcurrentDictionary<string, ProjectInvocations>(StringComparer.Ordinal);
        Parallel.ForEach(contexts, new ParallelOptions { MaxDegreeOfParallelism = Parallelism }, c =>
        {
            using var item = progress.Item(c.Input.RelativePath);
            if (checkpoints.TryGet<ProjectInvocations>(c.Input.RelativePath, out var saved) && saved is not null)
            {
                detectedByPath[c.Input.RelativePath] = saved;
                return;
            }

            if (stopped.TryGetValue(c.Input.RelativePath, out var why))
            {
                progress.RecordNotChecked(c.Input.RelativePath, "project", why);
                var notChecked = Empty(c.Input, ProjectScanStatuses.Failed, null,
                    [new Warning { Code = WarningCodes.NotChecked, Message = why, Severity = WarningSeverities.Warning }]);
                checkpoints.Save(c.Input.RelativePath, notChecked);
                detectedByPath[c.Input.RelativePath] = notChecked;
                return;
            }

            using var limit = new CancellationTokenSource(limits.ProjectLoad);
            c.Context.Cancellation = limit.Token;
            ProjectInvocations result;
            try
            {
                result = DetectProject(repositoryId, c.Input, c.Context, soap[c.Input.RelativePath], configOnly[c.Input.RelativePath], references, soapMatrices);
            }
            catch (OperationCanceledException)
            {
                var reason = $"not checked: analysing the project took longer than {limits.ProjectLoad.TotalSeconds:0} s";
                progress.RecordNotChecked(c.Input.RelativePath, "project", reason);
                checkpoints.MarkNotChecked(c.Input.RelativePath, reason);
                result = Empty(c.Input, ProjectScanStatuses.Failed, null,
                    [new Warning { Code = WarningCodes.NotChecked, Message = reason, Severity = WarningSeverities.Warning }]);
            }

            checkpoints.Save(c.Input.RelativePath, result);
            detectedByPath[c.Input.RelativePath] = result;
        });
        var results = contexts.Select(c => detectedByPath[c.Input.RelativePath]).ToList();
        // Each project's SetParameters parameters (1.3.0). A URL's value is
        // kept only where a used invocation's binding cites the parameter —
        // the URL then names an endpoint the platform uses — normalised as
        // the binding holds it; a path is kept; nothing else ever is.
        var allInvocations = results.SelectMany(r => r.Invocations).Where(i => i.Usage == Usages.Used).ToList();
        var cited = allInvocations.SelectMany(i => i.EnvironmentBindings)
            .Where(b => b.DeployParameter is not null)
            .GroupBy(b => (b.SourceFile, b.DeployParameter!))
            .ToDictionary(g => g.Key, g => g.First());
        var deployByProject = config.DeployParameters.Where(d => d.ProjectPath is not null)
            .Select(d => d.Kind == "url" && cited.TryGetValue((d.SourceFile, d.Name), out var binding)
                ? d with { Value = Endpoints.Display(new Endpoint { Scheme = binding.Scheme, Host = binding.Host, Port = binding.Port, Path = binding.Path, Resolution = binding.Resolution }) }
                : d)
            .GroupBy(d => d.ProjectPath!, StringComparer.Ordinal)
            .ToDictionary(g => g.Key, g => g.OrderBy(d => d.SourceFile, StringComparer.Ordinal).ThenBy(d => d.Line).ThenBy(d => d.Name, StringComparer.Ordinal).ToList(),
                StringComparer.Ordinal);

        progress.Phase("backend reach");
        var reach = BackendReach.Build(sources, allInvocations, entryPoints ?? []);
        return results.Select(r => r with
        {
            DeployParameters = deployByProject.GetValueOrDefault(r.ProjectPath) ?? [],
            EntryPointBackend = reach.GetValueOrDefault(r.ProjectPath) ?? [],
        }).ToList();
    }

    /// <summary>One project's detection, after the SOAP passes that claim endpoint entries (which run in order).</summary>
    private static ProjectInvocations DetectProject(
        Guid repositoryId, OutboundInputProject project, DetectionContext context, IReadOnlyList<Detected> soap,
        IReadOnlyList<Detected> configOnly, ILookup<string, ConnectionReference> references, SoapMatrices? soapMatrices)
    {
        var detected = new List<Detected>();
        detected.AddRange(soap);
        detected.AddRange(configOnly);
        detected.AddRange(HttpClientDetector.Detect(context));
        detected.AddRange(GrpcClientDetector.Detect(context));
        detected.AddRange(DatabaseDetector.Detect(context, references));
        detected.AddRange(MessagingDetector.Detect(context));
        detected.AddRange(CacheDetector.Detect(context));
        detected.AddRange(SecretStoreDetector.Detect(context));
        detected.AddRange(FileShareDetector.Detect(context));
        detected.AddRange(SmtpDetector.Detect(context));
        detected.AddRange(LdapDetector.Detect(context));

        var invocations = Finish(repositoryId, project.RelativePath, detected, soapMatrices);
        var used = invocations.Where(i => i.Usage == Usages.Used).ToList();
        var warnings = new List<Warning>();
        if (context.Project.Truncated)
        {
            warnings.Add(new Warning
            {
                Code = WarningCodes.SourceFileCapExceeded,
                Message = $"More than {SourceFileScanner.MaxFilesPerProject} C# files; the rest were not read.",
                Severity = WarningSeverities.Warning,
            });
        }

        foreach (var (path, reason) in context.Project.NotChecked)
        {
            warnings.Add(new Warning { Code = WarningCodes.NotChecked, Message = $"{path}: {reason}", Severity = WarningSeverities.Warning });
        }

        return new ProjectInvocations
        {
            ProjectId = project.ProjectId,
            ProjectPath = project.RelativePath,
            Status = ProjectScanStatuses.Scanned,
            Summary = SummariseProject(invocations),
            Invocations = invocations,
            Warnings = warnings,
        };
    }

    /// <summary>
    /// Stamps project path, verdict and id, merges duplicates and sorts —
    /// incompatible first (Part D: the list someone will act on), unused last. The id is
    /// sha256 over repository, project, mechanism, normalised endpoint and
    /// the detector's identity (the SOAP contract, the connection-string
    /// name), truncated to 32 hex digits: stable across rescans. The same
    /// dependency reached from several call sites is one invocation with
    /// every call site.
    /// </summary>
    public static IReadOnlyList<Invocation> Finish(Guid repositoryId, string projectPath, IReadOnlyList<Detected> detected, SoapMatrices? soap = null)
    {
        var merged = detected
            .Select(d => (Key: $"{repositoryId:D}\n{projectPath}\n{d.Record.Mechanism}\n{Endpoints.Key(d.Record.Endpoint)}\n{d.Identity}", d.Record))
            .GroupBy(x => x.Key, StringComparer.Ordinal)
            .Select(g => Merge(Hash(g.Key), projectPath, g.Select(x => x.Record).ToList(), soap))
            .ToList();

        return merged
            .OrderBy(i => i.Usage == Usages.Used ? 0 : 1)
            .ThenBy(i => Verdicts.Rank(i.LinuxCompatibility.Verdict))
            .ThenBy(i => i.Mechanism, StringComparer.Ordinal)
            .ThenBy(i => Endpoints.Display(i.Endpoint), StringComparer.Ordinal)
            .ThenBy(i => i.InvocationId, StringComparer.Ordinal)
            .ToList();
    }

    private static Invocation Merge(string id, string projectPath, IReadOnlyList<Invocation> records, SoapMatrices? soap)
    {
        var ordered = records
            .OrderBy(r => r.CallSites.FirstOrDefault()?.FilePath ?? "", StringComparer.Ordinal)
            .ThenBy(r => r.CallSites.FirstOrDefault()?.LineStart ?? 0)
            .ToList();
        var first = ordered[0];
        var merged = first with
        {
            InvocationId = id,
            ProjectPath = projectPath,
            EnvironmentBindings = ordered.SelectMany(r => r.EnvironmentBindings)
                .DistinctBy(b => (b.Environment, b.SourceFile, b.KeyPath))
                .OrderBy(b => b.Environment == "default" ? 0 : 1).ThenBy(b => b.Environment, StringComparer.Ordinal)
                .ThenBy(b => b.SourceFile, StringComparer.Ordinal).ThenBy(b => b.KeyPath, StringComparer.Ordinal)
                .ToList(),
            Credentials = ordered.SelectMany(r => r.Credentials)
                .DistinctBy(c => (c.Kind, c.KeyPath, c.SourceFile))
                .OrderBy(c => c.Kind, StringComparer.Ordinal).ThenBy(c => c.KeyPath ?? "", StringComparer.Ordinal)
                .ThenBy(c => c.DeclaredAt ?? "", StringComparer.Ordinal)
                .ToList(),
            CallSites = ordered.SelectMany(r => r.CallSites)
                .DistinctBy(c => (c.FilePath, c.LineStart))
                .OrderBy(c => c.FilePath, StringComparer.Ordinal).ThenBy(c => c.LineStart)
                .ToList(),
            Operations = ordered.SelectMany(r => r.Operations)
                .DistinctBy(o => (o.CallSite.FilePath, o.CallSite.LineStart, o.Operation, o.Verb, o.Path, o.Resolution))
                .OrderBy(o => o.CallSite.FilePath, StringComparer.Ordinal).ThenBy(o => o.CallSite.LineStart)
                .ThenBy(o => o.Operation ?? o.Path ?? "", StringComparer.Ordinal).ThenBy(o => o.Verb ?? "", StringComparer.Ordinal)
                .ToList(),
            Confidence = ordered.Max(r => r.Confidence),
            ConfidenceReasons = ordered.SelectMany(r => r.ConfidenceReasons).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToList(),
            // Several call sites under different conditions: none applies to all.
            Soap = first.Soap is null ? null
                : ordered.Select(r => r.Soap?.Condition).Distinct().Count() == 1 ? first.Soap : first.Soap with { Condition = null },
        };

        // A credential makes the declaration: declared wins across call sites.
        if (ordered.Any(r => r.AuthDeclared == AuthDeclared.Declared))
        {
            merged = merged with { AuthDeclared = AuthDeclared.Declared };
        }

        // Used anywhere is used.
        merged = merged with { Usage = ordered.Any(r => r.Usage == Usages.Used) ? Usages.Used : Usages.Unused };

        // Call sites are where the dependency is invoked (1.3.0): each
        // followed operation's site. Where the client is created
        // (`using (var service = new XClient())`) is kept apart, when it differs.
        var invokedAt = merged.Operations.Where(o => o.Resolution != Resolutions.Unresolved).Select(o => o.CallSite)
            .DistinctBy(c => (c.FilePath, c.LineStart))
            .OrderBy(c => c.FilePath, StringComparer.Ordinal).ThenBy(c => c.LineStart)
            .ToList();
        if (invokedAt.Count > 0 && !invokedAt.Select(c => (c.FilePath, c.LineStart)).SequenceEqual(merged.CallSites.Select(c => (c.FilePath, c.LineStart))))
        {
            merged = merged with { ConstructionSites = merged.CallSites, CallSites = invokedAt };
        }

        // Both SOAP verdicts, from the two matrices: platform (Linux) and runtime (the target's WCF client).
        return RuntimeVerdicts.Apply(LinuxVerdicts.Apply(merged, soap), soap?.Runtime, soap?.Target);
    }

    public static string Hash(string key) =>
        Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(key)))[..32];

    private static ProjectInvocations Empty(OutboundInputProject project, string status, string? skipReason, IReadOnlyList<Warning> warnings) => new()
    {
        ProjectId = project.ProjectId,
        ProjectPath = project.RelativePath,
        Status = status,
        SkipReason = skipReason,
        Summary = new ProjectOutboundSummary(),
        Warnings = warnings,
    };

    /// <summary>A project's summary from its invocations.</summary>
    public static ProjectOutboundSummary SummariseProject(IReadOnlyList<Invocation> invocations)
    {
        var used = invocations.Where(i => i.Usage == Usages.Used).ToList();
        return new ProjectOutboundSummary
        {
            UnusedCount = invocations.Count - used.Count,
            CountByMechanism = Count(used.Select(i => i.Mechanism)),
            CountByVerdict = Count(used.Select(i => i.LinuxCompatibility.Verdict)),
            Incompatible = used
                .Where(i => i.LinuxCompatibility.Verdict == Verdicts.Incompatible)
                .Select(i => new IncompatibleInvocation
                {
                    InvocationId = i.InvocationId,
                    Mechanism = i.Mechanism,
                    Endpoint = Endpoints.Display(i.Endpoint),
                    Reasons = i.LinuxCompatibility.Reasons,
                })
                .ToList(),
        };
    }

    /// <summary>The artifact's summary from its projects.</summary>
    public static OutboundSummary Summarise(IReadOnlyList<ProjectInvocations> projects)
    {
        var invocations = projects.SelectMany(p => p.Invocations).ToList();
        var used = invocations.Where(i => i.Usage == Usages.Used).ToList();
        return new OutboundSummary
        {
            ProjectsScanned = projects.Count(p => p.Status == ProjectScanStatuses.Scanned),
            ProjectsSkipped = projects.Count(p => p.Status == ProjectScanStatuses.Skipped),
            ProjectsFailed = projects.Count(p => p.Status == ProjectScanStatuses.Failed),
            InvocationCount = invocations.Count,
            UnusedCount = invocations.Count - used.Count,
            CountByMechanism = Count(used.Select(i => i.Mechanism)),
            CountByVerdict = Count(used.Select(i => i.LinuxCompatibility.Verdict)),
            CountByRuntimeVerdict = Count(used.Select(i => i.RuntimeCompatibility?.Verdict).OfType<string>()),
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
