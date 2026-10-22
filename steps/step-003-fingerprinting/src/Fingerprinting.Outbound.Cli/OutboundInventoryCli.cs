using System.Globalization;
using System.Text;
using System.Text.Json;
using Fingerprinting.Analysis;
using Fingerprinting.Domain;
using Fingerprinting.StepHost;

namespace Fingerprinting.Outbound.Cli;

/// <summary>
/// Lifecycle step 5, outbound-invocation-inventory — 29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md
/// Part C. Two modes, as steps 3 and 4: the process-adapter envelope
/// (StepContext on stdin, StepResult on stdout), and a standalone mode for
/// iterating without the engine.
/// </summary>
public static class OutboundInventoryCli
{
    public const string ArtifactType = "outbound-invocation-inventory";
    public const string ArtifactVersion = "1.5.0";
    public const string OutputFileName = "outbound-invocation-inventory.json";

    private const string InventoryType = "solution-project-inventory";
    private const string InventoryRange = "^2.0.0";
    private const string FingerprintType = "application-fingerprint";
    private const string FingerprintRange = "^1.2.0";
    private const string EntryPointsType = "entry-point-inventory";
    private const string EntryPointsRange = "^2.0.0";
    private const string UncSignal = "UNC_PATH_LITERAL";

    private static readonly JsonSerializerOptions CamelCaseRead = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
    };

    public static async Task<int> RunAsync(string[] args, TextReader input, TextWriter output, TextWriter error)
    {
        if (TryParseStandaloneArgs(args, out var repo, out var inventory, out var fingerprint, out var outDir, out var entryPoints, out var globs))
        {
            return await RunStandaloneAsync(repo, inventory, fingerprint, outDir, entryPoints, globs, error);
        }

        return await StepEnvelopeRunner.RunAsync(input, output, error, ExecuteAsync);
    }

    // ---------- standalone ----------

    private static bool TryParseStandaloneArgs(
        string[] args, out string repo, out string inventory, out string fingerprint, out string outDir, out string? entryPoints,
        out IReadOnlyList<string> globs)
    {
        repo = inventory = fingerprint = outDir = "";
        entryPoints = null;
        globs = [];
        string? r = null, i = null, f = null, o = null;
        for (var index = 0; index < args.Length; index++)
        {
            switch (args[index])
            {
                case "--repo" when index + 1 < args.Length: r = args[++index]; break;
                case "--inventory" when index + 1 < args.Length: i = args[++index]; break;
                case "--fingerprint" when index + 1 < args.Length: f = args[++index]; break;
                case "--out" when index + 1 < args.Length: o = args[++index]; break;
                // 1.3.0, both optional: step 4's artifact, and SetParameters globs (comma-separated).
                case "--entry-points" when index + 1 < args.Length: entryPoints = Path.GetFullPath(args[++index]); break;
                // 1.4.0, optional: the target framework the SOAP runtime verdicts are for.
                case "--target" when index + 1 < args.Length: Target = args[++index]; break;
                // release 5, optional: a checkpoint folder, so a rerun continues from the last completed project.
                case "--checkpoints" when index + 1 < args.Length: Checkpoints = Path.GetFullPath(args[++index]); break;
                case "--deploy-globs" when index + 1 < args.Length:
                    globs = args[++index].Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
                    break;
            }
        }

        if (r is null && i is null && f is null && o is null)
        {
            return false;
        }

        // Both inputs are required here too: step 3's skip verdicts and UNC
        // literals are part of the input, not an optional refinement.
        if (r is null || i is null || f is null)
        {
            throw new ArgumentException(
                "Standalone mode requires --repo <repository-root>, --inventory <solution-project-inventory.json> and " +
                "--fingerprint <application-fingerprint.json>; --out <dir> is optional.");
        }

        repo = Path.GetFullPath(r);
        inventory = Path.GetFullPath(i);
        fingerprint = Path.GetFullPath(f);
        outDir = Path.GetFullPath(o ?? "./outbound-out");
        return true;
    }

    /// <summary>Standalone mode's --target (1.4.0).</summary>
    private static string? Target;

    /// <summary>Standalone mode's --checkpoints (release 5).</summary>
    private static string? Checkpoints;

    /// <summary>The WCF client support matrix (1.4.0), published beside the schemas.</summary>
    public const string WcfClientSupportFile = "wcf-client-support-1.1.0.json";

    /// <summary>The WCF client platform matrix (1.5.0), published beside it. 1.2.1: wording only, no verdict changed.</summary>
    public const string WcfClientPlatformFile = "wcf-client-platform-1.2.1.json";

    private static WcfClientSupport LoadWcfClientSupport() =>
        WcfClientSupport.Load(Path.Combine(AppContext.BaseDirectory, "schemas", WcfClientSupportFile));

    private static WcfClientSupport LoadWcfClientPlatform() =>
        WcfClientSupport.Load(Path.Combine(AppContext.BaseDirectory, "schemas", WcfClientPlatformFile));

    private static async Task<int> RunStandaloneAsync(
        string repoPath, string inventoryPath, string fingerprintPath, string outDir, string? entryPointsPath, IReadOnlyList<string> globs, TextWriter error)
    {
        try
        {
            var inventory = await ReadInventoryAsync(inventoryPath);
            var fingerprint = await ReadFingerprintAsync(fingerprintPath);

            // No database: ids come from the fingerprint, which carries the
            // real projects.id values.
            var fingerprintIds = fingerprint.Projects.ToDictionary(p => p.ProjectPath, p => p.ProjectId, StringComparer.Ordinal);
            var input = BuildInput(inventory, fingerprint, path => fingerprintIds.TryGetValue(path, out var id) ? id : null) with
            {
                DeployParameterGlobs = globs,
                EntryPoints = entryPointsPath is null ? [] : await ReadEntryPointsAsync(entryPointsPath),
                TargetFramework = Target,
                WcfClientSupport = LoadWcfClientSupport(),
                WcfClientPlatform = LoadWcfClientPlatform(),
            };

            using var progress = new StepProgress(outDir, error);
            var checkpoints = ProjectCheckpoints.Open(Checkpoints, ProjectCheckpoints.Key(
                ArtifactType, OutboundPipeline.ScannerVersion, ArtifactUri.Sha256File(inventoryPath), ArtifactUri.Sha256File(fingerprintPath),
                entryPointsPath is null ? null : ArtifactUri.Sha256File(entryPointsPath), Target, string.Join(",", globs)));
            checkpoints.Watch(progress);
            var artifact = await new OutboundPipeline().RunAsync(input, repoPath, CancellationToken.None, progress, WorkLimits.Default, checkpoints);
            progress.Phase("write");
            artifact = Conform(artifact, progress);
            var outputPath = await WriteArtifactAsync(artifact, outDir);
            if (checkpoints.Reused > 0)
            {
                error.WriteLine($"Resumed: {checkpoints.Reused} project(s) taken from the unfinished run before.");
            }

            checkpoints.Complete();
            progress.Finish();
            error.WriteLine($"Wrote {outputPath}");
            error.WriteLine($"{artifact.Summary.InvocationCount} invocation(s): " +
                            string.Join(", ", artifact.Summary.CountByVerdict.Select(kv => $"{kv.Value} {kv.Key}")));
            return 0;
        }
        catch (Exception ex)
        {
            error.WriteLine($"Fatal: {ex}");
            return 1;
        }
    }

    // ---------- envelope ----------

    private static async Task<StepResult> ExecuteAsync(StepContextEnvelope context)
    {
        if (string.IsNullOrEmpty(context.DatabaseUrl))
        {
            return StepEnvelopeRunner.Failed(
                "database_url is required — step 5 resolves the repository's local_path and project ids from it");
        }

        var connectionString = DatabaseUrl.ToNpgsqlConnectionString(context.DatabaseUrl);
        var platform = new PlatformDatabase(connectionString);

        // Both inputs are required and wired by the job definition; the
        // engine refuses to invoke the step without them. There is no other
        // source: a second input path would drift from this one, and would
        // keep working silently if the wiring broke.
        var inventoryRef = WiredInput(context, InventoryType);
        var fingerprintRef = WiredInput(context, FingerprintType);
        if (inventoryRef is null || fingerprintRef is null)
        {
            return StepEnvelopeRunner.Failed(
                $"input '{(inventoryRef is null ? InventoryType : FingerprintType)}' was not resolved — " +
                "phase0-repository-discovery must wire it in the step's inputs mapping");
        }

        foreach (var (reference, range) in new[] { (inventoryRef, InventoryRange), (fingerprintRef, FingerprintRange) })
        {
            if (!ArtifactVersions.SatisfiesCaret(reference.ArtifactVersion, range))
            {
                return StepEnvelopeRunner.Failed($"{reference.ArtifactType} {reference.ArtifactVersion} does not satisfy {range}");
            }
        }

        var inventory = await ReadInventoryAsync(ArtifactUri.ToLocalPath(inventoryRef.Uri));
        var fingerprint = await ReadFingerprintAsync(ArtifactUri.ToLocalPath(fingerprintRef.Uri));

        var repositoryRoot = await platform.GetRepositoryLocalPathAsync(inventory.RepositoryId, CancellationToken.None);
        if (repositoryRoot is null)
        {
            return StepEnvelopeRunner.Failed($"repository '{inventory.RepositoryId}' has no matching row in the repositories table");
        }

        var projectIds = await platform.ResolveProjectIdsAsync(inventory.RepositoryId, CancellationToken.None);

        // 1.3.0: step 4's entry points, for which backend calls each reaches.
        // Optional: without them the reach is simply not computed, and said so.
        var entryPointsRef = WiredInput(context, EntryPointsType);
        IReadOnlyList<InboundEntryPoint> entryPoints = [];
        if (entryPointsRef is not null)
        {
            if (!ArtifactVersions.SatisfiesCaret(entryPointsRef.ArtifactVersion, EntryPointsRange))
            {
                return StepEnvelopeRunner.Failed($"{entryPointsRef.ArtifactType} {entryPointsRef.ArtifactVersion} does not satisfy {EntryPointsRange}");
            }

            entryPoints = await ReadEntryPointsAsync(ArtifactUri.ToLocalPath(entryPointsRef.Uri));
        }

        var input = BuildInput(inventory, fingerprint, path => projectIds.TryGetValue(path, out var id) ? id : null) with
        {
            DeployParameterGlobs = await platform.GetDeployParameterGlobsAsync(inventory.RepositoryId, CancellationToken.None),
            EntryPoints = entryPoints,
            // 1.4.0: the SOAP runtime verdicts are for the engagement's target.
            TargetFramework = await platform.GetTargetFrameworkAsync(inventory.RepositoryId, CancellationToken.None),
            WcfClientSupport = LoadWcfClientSupport(),
            WcfClientPlatform = LoadWcfClientPlatform(),
        };
        if (entryPointsRef is null)
        {
            input = input with
            {
                Warnings =
                [
                    .. input.Warnings,
                    new Warning
                    {
                        Code = WarningCodes.ProjectDirectoryNotFound,
                        Message = "entry-point-inventory was not wired: which backend calls each entry point reaches is not computed.",
                        Severity = WarningSeverities.Warning,
                    },
                ],
            };
        }

        // release 5: progress and a timing profile throughout; each project's load and analysis within its own
        // limit; and what is finished kept, so a rerun after a time limit, a stall or a crash continues from there.
        using var progress = new StepProgress(context.OutputDir, Console.Error);
        var (projectLimit, fileLimit) = StepLimits.Within(context);
        var limits = WorkLimits.From(projectLimit, fileLimit);
        var checkpoints = ProjectCheckpoints.Open(StepLimits.CheckpointDirectory(context), ProjectCheckpoints.Key(
            ArtifactType, OutboundPipeline.ScannerVersion, inventoryRef.Checksum, fingerprintRef.Checksum, entryPointsRef?.Checksum,
            input.TargetFramework, input.WcfClientSupport?.Sha256, input.WcfClientPlatform?.Sha256, string.Join(",", input.DeployParameterGlobs),
            limits.ProjectLoad.TotalSeconds.ToString(CultureInfo.InvariantCulture)));
        checkpoints.Watch(progress);
        var artifact = await new OutboundPipeline().RunAsync(input, repositoryRoot, CancellationToken.None, progress, limits, checkpoints);
        progress.Phase("write");
        artifact = Conform(artifact, progress);
        var outputPath = await WriteArtifactAsync(artifact, context.OutputDir);
        var checksum = ArtifactUri.Sha256File(outputPath);

        progress.Phase("database");
        await new OutboundDatabase(connectionString).ReplaceAllAsync(
            artifact, StepEnvelopeRunner.TryParseGuid(context.StepExecutionId), CancellationToken.None);
        var resumed = checkpoints.Reused;
        checkpoints.Complete();
        progress.Finish();

        var generatedAt = DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ", CultureInfo.InvariantCulture);
        var summary = artifact.Summary;
        return new StepResult
        {
            ExitStatus = ExitStatuses.Completed,
            ExitMessage = $"Inventoried {summary.InvocationCount} outbound invocation(s) across {summary.ProjectsScanned} project(s) " +
                          $"in '{artifact.RepositorySlug}' ({summary.ProjectsSkipped} skipped, {summary.ProjectsFailed} failed); " +
                          $"{summary.CountByVerdict.GetValueOrDefault(Verdicts.Incompatible)} incompatible with Linux" +
                          (summary.UnusedCount > 0 ? $"; {summary.UnusedCount} unused client(s) not counted." : ".") +
                          (resumed > 0 ? $" Resumed: {resumed} project(s) taken from the unfinished run before." : "") +
                          (progress.NotCheckedItems.Count > 0 ? $" {progress.NotCheckedItems.Count} item(s) not checked within their time limit (see the warnings)." : ""),
            Metrics = new Dictionary<string, long>
            {
                ["read_count"] = inventory.Projects.Count,
                ["write_count"] = summary.InvocationCount,
                ["skip_count"] = summary.ProjectsSkipped,
                ["commit_count"] = 1,
            },
            Outputs =
            [
                new StepOutput
                {
                    ArtifactType = ArtifactType,
                    ArtifactVersion = ArtifactVersion,
                    Uri = ArtifactUri.FromLocalPath(outputPath),
                    Checksum = checksum,
                    // generated_at is kept out of the file itself so unchanged
                    // input yields an identical checksum — same as steps 3 and 4.
                    Metadata = new Dictionary<string, object?> { ["generated_at"] = generatedAt },
                },
            ],
        };
    }

    private static ArtifactRef? WiredInput(StepContextEnvelope context, string artifactType) =>
        context.Inputs?.Values.FirstOrDefault(a => a.ArtifactType == artifactType);

    // ---------- shared ----------

    /// <summary>Joins step 2's project list with step 3's verdict and UNC
    /// literals. A project step 3 skipped is skipped here too.</summary>
    public static OutboundInput BuildInput(
        SolutionProjectInventory inventory, ApplicationFingerprintSlice fingerprint, Func<string, Guid?> resolveProjectId)
    {
        var warnings = new List<Warning>();
        var byPath = fingerprint.Projects.ToDictionary(p => p.ProjectPath, StringComparer.Ordinal);
        var projects = new List<OutboundInputProject>();

        foreach (var project in inventory.Projects)
        {
            var projectId = resolveProjectId(project.RelativePath);
            if (projectId is null)
            {
                warnings.Add(new Warning
                {
                    Code = WarningCodes.ProjectDirectoryNotFound,
                    Message = $"'{project.RelativePath}' has no matching row in the projects table — dropped from this inventory.",
                    Severity = WarningSeverities.Warning,
                });
                continue;
            }

            byPath.TryGetValue(project.RelativePath, out var fingerprinted);
            var skipReason = fingerprinted is null
                ? "not fingerprinted by step 3"
                : fingerprinted.FingerprintStatus switch
                {
                    FingerprintStatuses.Skipped => "skipped by step 3 (out of scope)",
                    FingerprintStatuses.Failed => "step 3 could not read the project directory",
                    _ => null,
                };

            var unc = (fingerprinted?.Signals ?? [])
                .Where(s => s.Name == UncSignal)
                .SelectMany(s => s.Evidence.Count == 0
                    ? [new UncLiteral(s.SourcePath ?? "", null, null, s.Value ?? "")]
                    : s.Evidence.Select(e => new UncLiteral(s.SourcePath ?? "", e.LineStart, e.LineEnd, e.MatchedValue ?? s.Value ?? "")))
                .Where(u => u.MatchedValue.Length > 0)
                .ToList();

            projects.Add(new OutboundInputProject(project.RelativePath, projectId.Value, skipReason, project.Packages.Select(p => p.PackageName).ToList(), unc)
            {
                OutputType = project.OutputType,
                ProjectSdk = project.ProjectSdk,
            });
        }

        return new OutboundInput(inventory.RepositoryId, inventory.RepositorySlug, FingerprintType, projects, warnings)
        {
            ProjectReferences = inventory.ProjectReferences
                .Where(r => r.ReferencedRelativePath is not null && r.ResolutionStatus is null or "resolved")
                .Select(r => (r.SourceRelativePath, r.ReferencedRelativePath!))
                .ToList(),
        };
    }

    // ---------- step 4's entry points (1.3.0) ----------

    private sealed record EntryPointSlice(IReadOnlyList<EntryPointSliceProject> Projects);

    private sealed record EntryPointSliceProject(string ProjectPath, IReadOnlyList<EntryPointSliceRecord>? EntryPoints);

    private sealed record EntryPointSliceRecord(string EntryPointId, string Kind, EntryPointSliceHandler Handler);

    private sealed record EntryPointSliceHandler(string Type, string? Member, string FilePath, int LineStart);

    private static async Task<IReadOnlyList<InboundEntryPoint>> ReadEntryPointsAsync(string path)
    {
        var slice = JsonSerializer.Deserialize<EntryPointSlice>(await File.ReadAllTextAsync(path), CamelCaseRead)
                    ?? throw new InvalidOperationException("entry-point-inventory deserialized to null");
        return slice.Projects
            .SelectMany(p => (p.EntryPoints ?? []).Select(e => new InboundEntryPoint(
                e.EntryPointId, p.ProjectPath, e.Kind, e.Handler.Type, e.Handler.Member, e.Handler.FilePath, e.Handler.LineStart)))
            .ToList();
    }

    private static async Task<SolutionProjectInventory> ReadInventoryAsync(string path) =>
        JsonSerializer.Deserialize<SolutionProjectInventory>(await File.ReadAllTextAsync(path), EnvelopeJson.Options)
        ?? throw new InvalidOperationException("solution-project-inventory deserialized to null");

    private static async Task<ApplicationFingerprintSlice> ReadFingerprintAsync(string path) =>
        JsonSerializer.Deserialize<ApplicationFingerprintSlice>(await File.ReadAllTextAsync(path), CamelCaseRead)
        ?? throw new InvalidOperationException("application-fingerprint deserialized to null");

    private static readonly Lazy<ArtifactSchemaValidator> SchemaValidator = new(() =>
        ArtifactSchemaValidator.Load(Path.Combine(AppContext.BaseDirectory, "schemas", "outbound-invocation-inventory-1.5.0.schema.json")));

    /// <summary>
    /// release 5: one record that does not conform never costs the rest. When the artifact has a problem (a schema
    /// error, or a required field left empty), each record is checked on its own: every invocation that does not
    /// conform is left out and recorded NOT_CHECKED on its project, naming the record and the problem, and the rest is
    /// written. A problem no single invocation explains is left for <see cref="WriteArtifactAsync"/> to fail on.
    /// </summary>
    public static OutboundInventoryArtifact Conform(OutboundInventoryArtifact artifact, StepProgress? progress = null)
    {
        if (SchemaValidator.Value.Problems(DeterministicJson.Serialize(artifact)).Count == 0)
        {
            return artifact;
        }

        var projects = new List<ProjectInvocations>();
        foreach (var project in artifact.Projects)
        {
            if (Problems(artifact, project).Count == 0)
            {
                projects.Add(project);
                continue;
            }

            var kept = new List<Invocation>();
            var warnings = project.Warnings.ToList();
            foreach (var invocation in project.Invocations)
            {
                var problems = Problems(artifact, project with { Invocations = [invocation], Summary = OutboundPipeline.SummariseProject([invocation]) });
                if (problems.Count == 0)
                {
                    kept.Add(invocation);
                    continue;
                }

                // The problem at its deepest location — the field itself, not the records around it — and not one of
                // the schema's alternative shapes the record was never meant to have (a oneOf branch's const).
                var problem = problems.OrderByDescending(p => p.IndexOf(": ", StringComparison.Ordinal))
                    .ThenBy(p => p.Contains(": const", StringComparison.Ordinal) ? 1 : 0).First();
                var record = $"{invocation.Mechanism} invocation {invocation.InvocationId}";
                var reason = $"not checked: {record} did not conform to the artifact schema ({problem}); left out, the rest is written";
                warnings.Add(new Warning { Code = WarningCodes.NotChecked, Message = reason, Severity = WarningSeverities.Warning });
                progress?.RecordNotChecked($"{project.ProjectPath}#{invocation.InvocationId}", "record", reason);
            }

            projects.Add(project with
            {
                Invocations = kept,
                Summary = OutboundPipeline.SummariseProject(kept),
                Warnings = warnings.OrderBy(w => w.Message, StringComparer.Ordinal).ToList(),
            });
        }

        return artifact with { Projects = projects, Summary = OutboundPipeline.Summarise(projects) };
    }

    /// <summary>Every problem with the artifact as it would be written: schema errors and empty required fields.</summary>
    public static IReadOnlyList<string> Problems(OutboundInventoryArtifact artifact) =>
        SchemaValidator.Value.Problems(DeterministicJson.Serialize(artifact));

    private static IReadOnlyList<string> Problems(OutboundInventoryArtifact artifact, ProjectInvocations project) =>
        SchemaValidator.Value.Problems(DeterministicJson.Serialize(artifact with { Projects = [project], Summary = OutboundPipeline.Summarise([project]) }));

    /// <summary>Serialises deterministically, validates against the schema —
    /// a failure is a step failure — and writes. Problems in single records are dealt with first (<see cref="Conform"/>);
    /// the artifact written always conforms.</summary>
    public static async Task<string> WriteArtifactAsync(OutboundInventoryArtifact artifact, string outDir)
    {
        var json = DeterministicJson.Serialize(artifact);
        SchemaValidator.Value.Validate(json);
        if (SchemaValidator.Value.Problems(json) is [_, ..] empty)
        {
            throw new ArtifactSchemaValidationException(empty);
        }

        Directory.CreateDirectory(outDir);
        var outputPath = Path.Combine(outDir, OutputFileName);
        await File.WriteAllTextAsync(outputPath, json, new UTF8Encoding(false));
        return outputPath;
    }
}
