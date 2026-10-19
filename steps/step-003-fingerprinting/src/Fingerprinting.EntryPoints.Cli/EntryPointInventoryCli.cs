using System.Globalization;
using System.Text;
using System.Text.Json;
using Fingerprinting.Analysis;
using Fingerprinting.Domain;
using Fingerprinting.StepHost;

namespace Fingerprinting.EntryPoints.Cli;

/// <summary>
/// Lifecycle step 4, entry-point-inventory — 29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md
/// Part B. Two modes, as step 3: the process-adapter envelope (StepContext on
/// stdin, StepResult on stdout), and a standalone mode for iterating without
/// the engine.
/// </summary>
public static class EntryPointInventoryCli
{
    public const string ArtifactType = "entry-point-inventory";
    public const string ArtifactVersion = "2.2.0";
    public const string OutputFileName = "entry-point-inventory.json";

    private const string InventoryType = "solution-project-inventory";
    private const string InventoryRange = "^2.0.0";
    private const string FingerprintType = "application-fingerprint";
    private const string FingerprintRange = "^1.2.0";

    private static readonly JsonSerializerOptions CamelCaseRead = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
    };

    public static async Task<int> RunAsync(string[] args, TextReader input, TextWriter output, TextWriter error)
    {
        if (TryParseStandaloneArgs(args, out var repo, out var inventory, out var fingerprint, out var outDir))
        {
            return await RunStandaloneAsync(repo, inventory, fingerprint, outDir, error);
        }

        return await StepEnvelopeRunner.RunAsync(input, output, error, ExecuteAsync);
    }

    // ---------- standalone ----------

    private static bool TryParseStandaloneArgs(
        string[] args, out string repo, out string inventory, out string? fingerprint, out string outDir)
    {
        repo = inventory = outDir = "";
        fingerprint = null;
        string? r = null, i = null, f = null, o = null;
        for (var index = 0; index < args.Length; index++)
        {
            switch (args[index])
            {
                case "--repo" when index + 1 < args.Length: r = args[++index]; break;
                case "--inventory" when index + 1 < args.Length: i = args[++index]; break;
                case "--fingerprint" when index + 1 < args.Length: f = args[++index]; break;
                case "--out" when index + 1 < args.Length: o = args[++index]; break;
            }
        }

        if (r is null && i is null && f is null && o is null)
        {
            return false;
        }

        if (r is null || i is null)
        {
            throw new ArgumentException(
                "Standalone mode requires --repo <repository-root> and --inventory <solution-project-inventory.json>; " +
                "--fingerprint <application-fingerprint.json> and --out <dir> are optional.");
        }

        repo = Path.GetFullPath(r);
        inventory = Path.GetFullPath(i);
        fingerprint = f is null ? null : Path.GetFullPath(f);
        outDir = Path.GetFullPath(o ?? "./entry-point-out");
        return true;
    }

    private static async Task<int> RunStandaloneAsync(string repoPath, string inventoryPath, string? fingerprintPath, string outDir, TextWriter error)
    {
        try
        {
            var inventory = await ReadInventoryAsync(inventoryPath);
            var fingerprint = fingerprintPath is null ? null : await ReadFingerprintAsync(fingerprintPath);

            // No database: ids come from the fingerprint (which carries the
            // real projects.id values), else are derived from the path.
            var fingerprintIds = fingerprint?.Projects.ToDictionary(p => p.ProjectPath, p => p.ProjectId, StringComparer.Ordinal);
            var input = BuildInput(inventory, fingerprint, path =>
                fingerprintIds is null ? StandaloneIds.ProjectId(inventory.RepositoryId, path)
                : fingerprintIds.TryGetValue(path, out var id) ? id : null);

            using var progress = new StepProgress(outDir, error);
            var artifact = await new EntryPointPipeline().RunAsync(input, repoPath, CancellationToken.None, progress);
            progress.Finish();
            var outputPath = await WriteArtifactAsync(artifact, outDir);
            error.WriteLine($"Wrote {outputPath}");
            error.WriteLine($"{artifact.Summary.EntryPointCount} entry point(s), {artifact.Summary.NoDeclaredAuthenticationCount} with no declared authentication.");
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
                "database_url is required — step 4 resolves the repository's local_path and project ids from it");
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
        var input = BuildInput(inventory, fingerprint, path => projectIds.TryGetValue(path, out var id) ? id : null);

        // rbc-release-5: progress and a timing profile; each project's load within its own time limit.
        using var progress = new StepProgress(context.OutputDir, Console.Error);
        var (projectLimit, fileLimit) = StepLimits.Within(context);
        var artifact = await new EntryPointPipeline().RunAsync(input, repositoryRoot, CancellationToken.None, progress,
            WorkLimits.From(projectLimit, fileLimit));
        progress.Phase("write");
        var outputPath = await WriteArtifactAsync(artifact, context.OutputDir);
        var checksum = ArtifactUri.Sha256File(outputPath);

        await new EntryPointDatabase(connectionString).ReplaceAllAsync(
            artifact, StepEnvelopeRunner.TryParseGuid(context.StepExecutionId), CancellationToken.None);

        var generatedAt = DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ", CultureInfo.InvariantCulture);
        var summary = artifact.Summary;
        progress.Finish();
        return new StepResult
        {
            ExitStatus = ExitStatuses.Completed,
            ExitMessage = $"Inventoried {summary.RequestEntryPointCount} request entry point(s) and {summary.LifecycleHookCount} lifecycle hook(s) " +
                          $"across {summary.ProjectsScanned} project(s) " +
                          $"in '{artifact.RepositorySlug}' ({summary.ProjectsSkipped} skipped, {summary.ProjectsFailed} failed); " +
                          $"{summary.NoDeclaredAuthenticationCount} with no declared authentication." +
                          (progress.NotCheckedItems.Count > 0 ? $" {progress.NotCheckedItems.Count} item(s) not checked (see timing-profile.json)." : ""),
            Metrics = new Dictionary<string, long>
            {
                ["read_count"] = inventory.Projects.Count,
                ["write_count"] = summary.EntryPointCount,
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
                    // input yields an identical checksum — same as step 3.
                    Metadata = new Dictionary<string, object?> { ["generated_at"] = generatedAt },
                },
            ],
        };
    }

    /// <summary>The input of <paramref name="artifactType"/> the engine
    /// resolved from the job definition's <c>inputs</c> mapping.</summary>
    private static ArtifactRef? WiredInput(StepContextEnvelope context, string artifactType) =>
        context.Inputs?.Values.FirstOrDefault(a => a.ArtifactType == artifactType);

    // ---------- shared ----------

    /// <summary>Joins step 2's project list with step 3's verdict. A project
    /// step 3 skipped is skipped here too; one step 3 never saw (dropped for
    /// having no projects row) is skipped with that reason.</summary>
    public static InventoryInput BuildInput(
        SolutionProjectInventory inventory, ApplicationFingerprintSlice? fingerprint, Func<string, Guid?> resolveProjectId)
    {
        var warnings = new List<Warning>();
        var statusByPath = fingerprint?.Projects.ToDictionary(p => p.ProjectPath, p => p.FingerprintStatus, StringComparer.Ordinal);
        var projects = new List<InputProject>();

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

            string? skipReason;
            if (statusByPath is not null)
            {
                skipReason = !statusByPath.TryGetValue(project.RelativePath, out var status)
                    ? "not fingerprinted by step 3"
                    : status switch
                    {
                        FingerprintStatuses.Skipped => "skipped by step 3 (out of scope)",
                        FingerprintStatuses.Failed => "step 3 could not read the project directory",
                        _ => null,
                    };
            }
            else
            {
                skipReason = project.ParseStatus == "out_of_scope" || OutOfScopeStructuralTypes.Values.Contains(project.StructuralType)
                    ? "out of scope per step 2 (parse_status / structural_type)"
                    : null;
            }

            projects.Add(new InputProject(project.RelativePath, projectId.Value, skipReason, project.Packages.Select(p => p.PackageName).ToList())
            {
                ProjectSdk = project.ProjectSdk,
            });
        }

        return new InventoryInput(
            inventory.RepositoryId,
            inventory.RepositorySlug,
            fingerprint is null ? InventoryType : FingerprintType,
            projects,
            warnings)
        {
            ProjectReferences = inventory.ProjectReferences
                .Where(r => r.ReferencedRelativePath is not null && r.ResolutionStatus is null or "resolved")
                .Select(r => (r.SourceRelativePath, r.ReferencedRelativePath!))
                .ToList(),
        };
    }

    private static async Task<SolutionProjectInventory> ReadInventoryAsync(string path) =>
        JsonSerializer.Deserialize<SolutionProjectInventory>(await File.ReadAllTextAsync(path), EnvelopeJson.Options)
        ?? throw new InvalidOperationException("solution-project-inventory deserialized to null");

    private static async Task<ApplicationFingerprintSlice> ReadFingerprintAsync(string path) =>
        JsonSerializer.Deserialize<ApplicationFingerprintSlice>(await File.ReadAllTextAsync(path), CamelCaseRead)
        ?? throw new InvalidOperationException("application-fingerprint deserialized to null");

    private static readonly Lazy<ArtifactSchemaValidator> SchemaValidator = new(() =>
        ArtifactSchemaValidator.Load(Path.Combine(AppContext.BaseDirectory, "schemas", "entry-point-inventory-2.2.0.schema.json")));

    /// <summary>Serialises deterministically, validates against the schema —
    /// a failure is a step failure — and writes.</summary>
    private static async Task<string> WriteArtifactAsync(EntryPointInventoryArtifact artifact, string outDir)
    {
        var json = DeterministicJson.Serialize(artifact);
        SchemaValidator.Value.Validate(json);
        Directory.CreateDirectory(outDir);
        var outputPath = Path.Combine(outDir, OutputFileName);
        await File.WriteAllTextAsync(outputPath, json, new UTF8Encoding(false));
        return outputPath;
    }
}
