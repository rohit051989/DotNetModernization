using System.Globalization;
using System.Text;
using System.Text.Json;
using Fingerprinting.Analysis;
using Fingerprinting.Dependencies;
using Fingerprinting.Domain;
using Fingerprinting.StepHost;

namespace Fingerprinting.Dependencies.Cli;

/// <summary>
/// Lifecycle step 6, dependency-assessment — 30-DEPENDENCY-ASSESSMENT.md.
/// Two modes, as steps 3 to 5: the process-adapter envelope (StepContext on
/// stdin, StepResult on stdout), and a standalone mode for iterating without
/// the engine.
/// </summary>
public static class DependencyAssessmentCli
{
    public const string ArtifactType = "dependency-assessment";
    public const string OutputFileName = "dependency-assessment.json";

    private const string InventoryType = "solution-project-inventory";
    private const string InventoryRange = "^2.0.0";
    private const string FingerprintType = "application-fingerprint";
    private const string FingerprintRange = "^1.2.0";

    /// <summary>Outside every repository (Part B5): packages are downloaded
    /// and extracted here, scratch restores run here.</summary>
    public static readonly string CacheRoot = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ModernizationPlatform", "dependency-cache");

    private static readonly JsonSerializerOptions CamelCaseRead = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
    };

    public sealed record Options(
        string TargetFramework, bool ComparePublicFeed, double CacheTtlHours, bool ForceRefresh, bool IncludeTransitive, bool ExplainChanges,
        bool LookupOffline = false);

    public static async Task<int> RunAsync(string[] args, TextReader input, TextWriter output, TextWriter error)
    {
        FeedCredentials.Configure();
        if (args.Length > 0) return await RunStandaloneAsync(args, error);
        return await StepEnvelopeRunner.RunAsync(input, output, error, ExecuteAsync);
    }

    // ---------- standalone ----------

    private static async Task<int> RunStandaloneAsync(string[] args, TextWriter error)
    {
        string? repo = null, inventory = null, fingerprint = null, outDir = null, cachePath = null, target = "net10.0";
        bool force = false, transitive = false, compare = true;
        for (var i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--repo" when i + 1 < args.Length: repo = args[++i]; break;
                case "--inventory" when i + 1 < args.Length: inventory = args[++i]; break;
                case "--fingerprint" when i + 1 < args.Length: fingerprint = args[++i]; break;
                case "--out" when i + 1 < args.Length: outDir = args[++i]; break;
                case "--cache" when i + 1 < args.Length: cachePath = args[++i]; break;
                case "--target" when i + 1 < args.Length: target = args[++i]; break;
                case "--force-refresh": force = true; break;
                case "--include-transitive": transitive = true; break;
                case "--no-public-compare": compare = false; break;
            }
        }

        if (repo is null || inventory is null || fingerprint is null)
        {
            error.WriteLine("Standalone mode requires --repo <root> --inventory <solution-project-inventory.json> --fingerprint <application-fingerprint.json>; "
                            + "optional --out <dir> --cache <lookup-cache.json> --target <tfm> --force-refresh --include-transitive --no-public-compare.");
            return 2;
        }

        try
        {
            var inventoryData = await ReadInventoryAsync(Path.GetFullPath(inventory));
            var fingerprintData = await ReadFingerprintAsync(Path.GetFullPath(fingerprint));
            var ids = fingerprintData.Projects.ToDictionary(p => p.ProjectPath, p => p.ProjectId, StringComparer.Ordinal);
            var cache = new FileLookupCache(Path.GetFullPath(cachePath ?? Path.Combine(CacheRoot, "lookup-cache.json")));
            var options = new Options(target, compare, 24, force, transitive, false);

            var (artifact, lookup) = await AssessAsync(Path.GetFullPath(repo), inventoryData, fingerprintData,
                path => ids.TryGetValue(path, out var id) ? id : StandaloneIds.ProjectId(inventoryData.RepositoryId, path), cache, options);
            cache.Save();
            var path = await WriteArtifactAsync(artifact, Path.GetFullPath(outDir ?? "./dependency-out"));
            error.WriteLine($"Wrote {path}");
            error.WriteLine($"{artifact.Summary.PackageCount} package(s): " + string.Join(", ", artifact.Summary.CountByOutcome.Select(kv => $"{kv.Value} {kv.Key}")));
            if (lookup.SnapshotTimes.Count > 0) error.WriteLine($"Lookup cache snapshot: {lookup.SnapshotTimes.Min():O}");
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
            return StepEnvelopeRunner.Failed("database_url is required — step 6 resolves the repository, the engagement's target framework and the lookup cache from it");
        }

        // Both inputs are required and wired by the job definition; there is no other source.
        var inventoryRef = WiredInput(context, InventoryType);
        var fingerprintRef = WiredInput(context, FingerprintType);
        if (inventoryRef is null || fingerprintRef is null)
        {
            return StepEnvelopeRunner.Failed(
                $"input '{(inventoryRef is null ? InventoryType : FingerprintType)}' was not resolved — phase0-repository-discovery must wire it in the step's inputs mapping");
        }

        foreach (var (reference, range) in new[] { (inventoryRef, InventoryRange), (fingerprintRef, FingerprintRange) })
        {
            if (!ArtifactVersions.SatisfiesCaret(reference.ArtifactVersion, range))
            {
                return StepEnvelopeRunner.Failed($"{reference.ArtifactType} {reference.ArtifactVersion} does not satisfy {range}");
            }
        }

        var connectionString = DatabaseUrl.ToNpgsqlConnectionString(context.DatabaseUrl);
        var platform = new PlatformDatabase(connectionString);
        var database = new DependencyDatabase(connectionString);
        var inventory = await ReadInventoryAsync(ArtifactUri.ToLocalPath(inventoryRef.Uri));
        var fingerprint = await ReadFingerprintAsync(ArtifactUri.ToLocalPath(fingerprintRef.Uri));

        var repositoryRoot = await platform.GetRepositoryLocalPathAsync(inventory.RepositoryId, CancellationToken.None);
        if (repositoryRoot is null)
        {
            return StepEnvelopeRunner.Failed($"repository '{inventory.RepositoryId}' has no matching row in the repositories table");
        }

        // Part C1: the engagement's target framework.
        var target = await database.GetTargetFrameworkAsync(inventory.RepositoryId, CancellationToken.None);
        if (target is null)
        {
            return StepEnvelopeRunner.Failed("the repository's engagement has no target_framework");
        }

        var config = context.Config;
        var options = new Options(
            target,
            Bool(config, "compare_public_feed", true),
            Number(config, "lookup_cache_ttl_hours", 24),
            Bool(config, "force_refresh", false),
            Bool(config, "include_transitive", false),
            Bool(config, "enable_change_explanation", false),
            Bool(config, "lookup_offline", false));

        var projectIds = await platform.ResolveProjectIdsAsync(inventory.RepositoryId, CancellationToken.None);
        var cache = new PostgresLookupCache(connectionString);

        // release 5: progress and a timing profile; each project within its own limit; and what is finished kept,
        // so a rerun after a time limit, a stall or a crash continues from there.
        using var progress = new StepProgress(context.OutputDir, Console.Error);
        var (projectLimit, fileLimit) = StepLimits.Within(context);
        var limits = WorkLimits.From(projectLimit, fileLimit);
        var checkpoints = ProjectCheckpoints.Open(StepLimits.CheckpointDirectory(context), ProjectCheckpoints.Key(
            ArtifactType, DependencyPipeline.ScannerVersion, inventoryRef.Checksum, fingerprintRef.Checksum, target,
            options.ToString(), limits.ProjectLoad.TotalSeconds.ToString(CultureInfo.InvariantCulture)));
        checkpoints.Watch(progress);
        var (artifact, lookup) = await AssessAsync(repositoryRoot, inventory, fingerprint, path => projectIds.TryGetValue(path, out var id) ? id : null, cache, options,
            progress, limits, checkpoints);

        progress.Phase("write");
        var outputPath = await WriteArtifactAsync(artifact, context.OutputDir);
        var checksum = ArtifactUri.Sha256File(outputPath);
        progress.Phase("database");
        await database.ReplaceAllAsync(artifact, cache, StepEnvelopeRunner.TryParseGuid(context.StepExecutionId), CancellationToken.None);
        var resumed = checkpoints.Reused;
        checkpoints.Complete();
        progress.Finish();

        var now = DateTimeOffset.UtcNow;
        var snapshot = lookup.SnapshotTimes.Count > 0 ? lookup.SnapshotTimes.Min() : now;
        var summary = artifact.Summary;
        return new StepResult
        {
            ExitStatus = ExitStatuses.Completed,
            ExitMessage = $"Assessed {summary.PackageCount} direct package(s) across {summary.ProjectsScanned} project(s) in '{artifact.RepositorySlug}' for {artifact.TargetFramework}: "
                          + string.Join(", ", summary.CountByOutcome.Select(kv => $"{kv.Value} {kv.Key}"))
                          + $"; {summary.DeprecatedCount} deprecated, {summary.VulnerableCount} vulnerable, {summary.NotInClientFeedCount} not in client feed."
                          + (resumed > 0 ? $" {resumed} project(s) carried over from the interrupted run." : "")
                          + (progress.NotCheckedItems.Count > 0 ? $" {progress.NotCheckedItems.Count} item(s) not checked (see timing-profile.json)." : ""),
            Metrics = new Dictionary<string, long>
            {
                ["read_count"] = summary.PackageCount,
                ["write_count"] = artifact.Projects.Sum(p => p.Packages.Count + p.Signals.Count),
                ["skip_count"] = summary.ProjectsSkipped,
                ["commit_count"] = 1,
            },
            Outputs =
            [
                new StepOutput
                {
                    ArtifactType = ArtifactType,
                    // The version the written artifact declares (1.7.1): a second constant here had drifted to 1.5.0.
                    ArtifactVersion = ArtifactUri.DeclaredVersion(outputPath),
                    Uri = ArtifactUri.FromLocalPath(outputPath),
                    Checksum = checksum,
                    // Volatile fields, kept out of the file so the checksum is
                    // deterministic against the cache (Part B6): when the
                    // answer was true, and when the file was written.
                    Metadata = new Dictionary<string, object?>
                    {
                        ["generated_at"] = now.ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ", CultureInfo.InvariantCulture),
                        ["lookup_cache_snapshot_at"] = snapshot.UtcDateTime.ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ", CultureInfo.InvariantCulture),
                        ["lookup_cache_ttl_hours"] = options.CacheTtlHours,
                        ["force_refresh"] = options.ForceRefresh,
                        ["lookup_offline"] = options.LookupOffline,
                    },
                },
            ],
        };
    }

    private static ArtifactRef? WiredInput(StepContextEnvelope context, string artifactType) =>
        context.Inputs?.Values.FirstOrDefault(a => a.ArtifactType == artifactType);

    private static bool Bool(JsonElement? config, string name, bool fallback) =>
        config is { ValueKind: JsonValueKind.Object } c && c.TryGetProperty(name, out var v)
            ? v.ValueKind switch
            {
                JsonValueKind.True => true,
                JsonValueKind.False => false,
                JsonValueKind.String => bool.TryParse(v.GetString(), out var b) ? b : fallback,
                _ => fallback,
            }
            : fallback;

    private static double Number(JsonElement? config, string name, double fallback) =>
        config is { ValueKind: JsonValueKind.Object } c && c.TryGetProperty(name, out var v)
            ? v.ValueKind == JsonValueKind.Number ? v.GetDouble() : double.TryParse(v.GetString(), CultureInfo.InvariantCulture, out var d) ? d : fallback
            : fallback;

    // ---------- shared ----------

    public static async Task<(DependencyAssessmentArtifact, PackageLookup)> AssessAsync(
        string repositoryRoot, SolutionProjectInventory inventory, ApplicationFingerprintSlice fingerprint, Func<string, Guid?> resolveProjectId,
        ILookupCache cache, Options options, StepProgress? progress = null, WorkLimits? limits = null, ProjectCheckpoints? checkpoints = null)
    {
        var warnings = new List<Warning>();
        if (options.ExplainChanges)
        {
            warnings.Add(new Warning
            {
                Code = "CHANGE_EXPLANATION_NOT_BUILT",
                Message = "enable_change_explanation is set, but the advisory explanation (Part E) is not built yet; nothing was sent and no summary was produced.",
                Severity = WarningSeverities.Info,
            });
        }

        var status = fingerprint.Projects.ToDictionary(p => p.ProjectPath, p => p.FingerprintStatus, StringComparer.Ordinal);
        var projects = new List<DependencyInputProject>();
        foreach (var project in inventory.Projects)
        {
            var id = resolveProjectId(project.RelativePath);
            if (id is null)
            {
                warnings.Add(new Warning { Code = WarningCodes.ProjectDirectoryNotFound, Message = $"'{project.RelativePath}' has no matching row in the projects table — dropped.", Severity = WarningSeverities.Warning });
                continue;
            }

            var skip = !status.TryGetValue(project.RelativePath, out var s)
                ? "not fingerprinted by step 3"
                : s switch
                {
                    FingerprintStatuses.Skipped => "skipped by step 3 (out of scope)",
                    FingerprintStatuses.Failed => "step 3 could not read the project directory",
                    _ => null,
                };
            projects.Add(new DependencyInputProject(project.RelativePath, id.Value, skip, CurrentFramework(project),
                project.Packages.Where(p => !string.IsNullOrWhiteSpace(p.PackageName))
                    .Select(p => new InputPackage(p.PackageName, p.VersionRaw, p.DeclarationSource ?? "packagereference")).ToList(),
                project.ProjectSdk));
        }

        var now = DateTimeOffset.UtcNow;
        var lookup = new PackageLookup(cache, Path.Combine(CacheRoot, "packages"), TimeSpan.FromHours(options.CacheTtlHours), options.ForceRefresh, now,
            options.LookupOffline);
        var transitive = options.IncludeTransitive
            ? new TransitiveResolver(Path.Combine(Path.GetTempPath(), "modernization-platform", "dependency-scratch"), Path.Combine(CacheRoot, "restore-packages"), TimeSpan.FromMinutes(5))
            : null;
        var shared = SharedFrameworks.Load(Path.Combine(AppContext.BaseDirectory, "schemas", "shared-frameworks-1.0.0.json"));
        var pipeline = new DependencyPipeline(lookup, new DependencyOptions(options.TargetFramework, options.ComparePublicFeed, options.IncludeTransitive,
            SharedFrameworks: shared), transitive);
        var artifact = await pipeline.RunAsync(new DependencyInput(inventory.RepositoryId, inventory.RepositorySlug, FingerprintType, projects, warnings), repositoryRoot, CancellationToken.None,
            progress, limits, checkpoints);
        return (artifact, lookup);
    }

    /// <summary>What the project builds for today: its TargetFramework(s), or
    /// for a .NET Framework project, family and version (4.7.2 → net472).</summary>
    public static string? CurrentFramework(InventoryProject project)
    {
        if (project.TargetFrameworksRaw is { Count: > 0 } frameworks) return frameworks[0];
        if (!string.IsNullOrWhiteSpace(project.TargetFrameworkRaw) && !project.TargetFrameworkRaw.StartsWith('v')) return project.TargetFrameworkRaw;
        if (project.FrameworkFamily == "net-framework" && project.FrameworkVersion is { } version)
        {
            return "net" + version.Replace(".", "");
        }

        return project.TargetFrameworkRaw;
    }

    private static async Task<SolutionProjectInventory> ReadInventoryAsync(string path) =>
        JsonSerializer.Deserialize<SolutionProjectInventory>(await File.ReadAllTextAsync(path), EnvelopeJson.Options)
        ?? throw new InvalidOperationException("solution-project-inventory deserialized to null");

    private static async Task<ApplicationFingerprintSlice> ReadFingerprintAsync(string path) =>
        JsonSerializer.Deserialize<ApplicationFingerprintSlice>(await File.ReadAllTextAsync(path), CamelCaseRead)
        ?? throw new InvalidOperationException("application-fingerprint deserialized to null");

    private static readonly Lazy<ArtifactSchemaValidator> SchemaValidator = new(() =>
        ArtifactSchemaValidator.Load(Path.Combine(AppContext.BaseDirectory, "schemas", "dependency-assessment-1.6.0.schema.json")));

    public static async Task<string> WriteArtifactAsync(DependencyAssessmentArtifact artifact, string outDir)
    {
        var json = DeterministicJson.Serialize(artifact);
        SchemaValidator.Value.Validate(json);
        Directory.CreateDirectory(outDir);
        var outputPath = Path.Combine(outDir, OutputFileName);
        await File.WriteAllTextAsync(outputPath, json, new UTF8Encoding(false));
        return outputPath;
    }
}
