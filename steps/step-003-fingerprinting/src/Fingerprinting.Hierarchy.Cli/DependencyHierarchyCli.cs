using System.Globalization;
using System.Text;
using System.Text.Json;
using Fingerprinting.Analysis;
using Fingerprinting.Dependencies;
using Fingerprinting.Dependencies.Cli;
using Fingerprinting.Domain;
using Fingerprinting.Hierarchy;
using Fingerprinting.StepHost;

namespace Fingerprinting.Hierarchy.Cli;

/// <summary>
/// dependency-hierarchy — 37-DEPENDENCY-HIERARCHY.md. Two modes, as the other C# steps: the process-adapter envelope
/// (StepContext on stdin, StepResult on stdout), and a standalone mode for iterating without the engine.
/// </summary>
public static class DependencyHierarchyCli
{
    public const string ArtifactType = "dependency-hierarchy";
    public const string ArtifactVersion = "1.0.0";
    public const string OutputFileName = "dependency-hierarchy.json";

    private const string InventoryType = "solution-project-inventory";
    private const string InventoryRange = "^2.0.0";
    private const string AssessmentType = "dependency-assessment";
    // dependency-assessment before 1.7.1 recorded its 1.6.0 artifact as 1.5.0, and those records remain; both carry
    // every field read here.
    private const string AssessmentRange = "^1.5.0";

    private static readonly JsonSerializerOptions CamelCaseRead = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
    };

    public sealed record Options(bool ComparePublicFeed, double CacheTtlHours, bool LookupOffline, int MaxPackageDepth, int MaxPackages, int LookupConcurrency = 8);

    public static async Task<int> RunAsync(string[] args, TextReader input, TextWriter output, TextWriter error)
    {
        FeedCredentials.Configure();
        if (args.Length > 0) return await RunStandaloneAsync(args, error);
        return await StepEnvelopeRunner.RunAsync(input, output, error, ExecuteAsync);
    }

    // ---------- standalone ----------

    private static async Task<int> RunStandaloneAsync(string[] args, TextWriter error)
    {
        string? repo = null, inventory = null, assessment = null, outDir = null, cachePath = null;
        bool compare = true, offline = false;
        int depth = 12, max = 5000, concurrency = 8;
        for (var i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--repo" when i + 1 < args.Length: repo = args[++i]; break;
                case "--inventory" when i + 1 < args.Length: inventory = args[++i]; break;
                case "--assessment" when i + 1 < args.Length: assessment = args[++i]; break;
                case "--out" when i + 1 < args.Length: outDir = args[++i]; break;
                case "--cache" when i + 1 < args.Length: cachePath = args[++i]; break;
                case "--max-depth" when i + 1 < args.Length: depth = int.Parse(args[++i], CultureInfo.InvariantCulture); break;
                case "--max-packages" when i + 1 < args.Length: max = int.Parse(args[++i], CultureInfo.InvariantCulture); break;
                case "--concurrency" when i + 1 < args.Length: concurrency = int.Parse(args[++i], CultureInfo.InvariantCulture); break;
                case "--no-public-compare": compare = false; break;
                case "--offline": offline = true; break;
            }
        }

        if (repo is null || inventory is null)
        {
            error.WriteLine("Standalone mode requires --repo <root> --inventory <solution-project-inventory.json>; optional --assessment "
                            + "<dependency-assessment.json> --out <dir> --cache <lookup-cache.json> --max-depth <n> --max-packages <n> --concurrency <n> "
                            + "--no-public-compare --offline.");
            return 2;
        }

        try
        {
            var inventoryData = await ReadInventoryAsync(Path.GetFullPath(inventory));
            var assessmentData = assessment is null ? null : await ReadAssessmentAsync(Path.GetFullPath(assessment));
            var cache = new FileLookupCache(Path.GetFullPath(cachePath ?? Path.Combine(DependencyAssessmentCli.CacheRoot, "lookup-cache.json")));
            var options = new Options(compare, 24, offline, depth, max, concurrency);
            using var progress = new StepProgress(outDir is null ? null : Path.GetFullPath(outDir), error);
            var started = DateTimeOffset.UtcNow;
            var artifact = await BuildAsync(Path.GetFullPath(repo), inventoryData, assessmentData,
                path => StandaloneIds.ProjectId(inventoryData.RepositoryId, path), new Dictionary<string, PackageProducer>(), cache, options, progress, WorkLimits.Default);
            cache.Save();
            var path = await WriteArtifactAsync(artifact, Path.GetFullPath(outDir ?? "./hierarchy-out"));
            progress.Finish();
            var s = artifact.Summary;
            error.WriteLine($"Wrote {path} in {(DateTimeOffset.UtcNow - started).TotalSeconds:0.0} s");
            error.WriteLine($"{s.ProjectCount} project(s), {s.PackageCount} package(s) ({s.InternalPackageCount} internal, {s.ExternalPackageCount} external, "
                            + $"{s.TransitivePackageCount} transitive), {s.AssemblyCount} assembly reference(s), {s.EdgeCount} edge(s), {s.RootCount} root(s), "
                            + $"{s.CycleCount} cycle(s), {s.NotCheckedCount} not checked, depth {s.Depth}.");
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
            return StepEnvelopeRunner.Failed("database_url is required — dependency-hierarchy resolves the repository, its projects and the lookup cache from it");
        }

        var inventoryRef = WiredInput(context, InventoryType);
        var assessmentRef = WiredInput(context, AssessmentType);
        if (inventoryRef is null || assessmentRef is null)
        {
            return StepEnvelopeRunner.Failed(
                $"input '{(inventoryRef is null ? InventoryType : AssessmentType)}' was not resolved — phase0-repository-discovery must wire it in the step's inputs mapping");
        }

        foreach (var (reference, range) in new[] { (inventoryRef, InventoryRange), (assessmentRef, AssessmentRange) })
        {
            if (!ArtifactVersions.SatisfiesCaret(reference.ArtifactVersion, range))
            {
                return StepEnvelopeRunner.Failed($"{reference.ArtifactType} {reference.ArtifactVersion} does not satisfy {range}");
            }
        }

        var connectionString = DatabaseUrl.ToNpgsqlConnectionString(context.DatabaseUrl);
        var platform = new PlatformDatabase(connectionString);
        var database = new HierarchyDatabase(connectionString);
        var inventory = await ReadInventoryAsync(ArtifactUri.ToLocalPath(inventoryRef.Uri));
        var assessment = await ReadAssessmentAsync(ArtifactUri.ToLocalPath(assessmentRef.Uri));
        var repositoryRoot = await platform.GetRepositoryLocalPathAsync(inventory.RepositoryId, CancellationToken.None);
        if (repositoryRoot is null)
        {
            return StepEnvelopeRunner.Failed($"repository '{inventory.RepositoryId}' has no matching row in the repositories table");
        }

        var config = context.Config;
        var options = new Options(
            Bool(config, "compare_public_feed", true),
            Number(config, "lookup_cache_ttl_hours", 24),
            Bool(config, "lookup_offline", false),
            (int)Number(config, "max_package_depth", 12),
            (int)Number(config, "max_packages", 5000),
            (int)Number(config, "lookup_concurrency", 8));

        var projectIds = await platform.ResolveProjectIdsAsync(inventory.RepositoryId, CancellationToken.None);
        var producers = await database.GetProducersAsync(inventory.RepositoryId, CancellationToken.None);
        var cache = new PostgresLookupCache(connectionString);
        using var progress = new StepProgress(context.OutputDir, Console.Error);
        var (projectLimit, fileLimit) = StepLimits.Within(context);
        var artifact = await BuildAsync(repositoryRoot, inventory, assessment, path => projectIds.TryGetValue(path, out var id) ? id : null, producers, cache,
            options, progress, WorkLimits.From(projectLimit, fileLimit));

        progress.Phase("write");
        var outputPath = await WriteArtifactAsync(artifact, context.OutputDir);
        var checksum = ArtifactUri.Sha256File(outputPath);
        progress.Phase("database");
        await database.ReplaceAllAsync(artifact, cache, StepEnvelopeRunner.TryParseGuid(context.StepExecutionId), CancellationToken.None);
        progress.Finish();

        var s = artifact.Summary;
        return new StepResult
        {
            ExitStatus = ExitStatuses.Completed,
            ExitMessage = $"Dependency graph of '{artifact.RepositorySlug}': {s.ProjectCount} project(s) from {s.RootCount} root(s), {s.PackageCount} package(s) "
                          + $"({s.InternalPackageCount} internal, {s.ExternalPackageCount} external, {s.TransitivePackageCount} transitive), "
                          + $"{s.AssemblyCount} assembly reference(s), {s.EdgeCount} edge(s), depth {s.Depth}"
                          + (s.CycleCount > 0 ? $", {s.CycleCount} cycle(s)" : "")
                          + (s.NotCheckedCount > 0 ? $"; {s.NotCheckedCount} node(s) not checked, each with its reason" : "")
                          + (progress.NotCheckedItems.Count > 0 ? $"; {progress.NotCheckedItems.Count} project(s) over the time limit (see timing-profile.json)" : "")
                          + ".",
            Metrics = new Dictionary<string, long>
            {
                ["read_count"] = s.ProjectCount,
                ["write_count"] = artifact.Nodes.Count + artifact.Edges.Count,
                ["skip_count"] = s.NotCheckedCount,
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
                    Metadata = new Dictionary<string, object?>
                    {
                        ["generated_at"] = DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ", CultureInfo.InvariantCulture),
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

    public static async Task<DependencyHierarchyArtifact> BuildAsync(
        string repositoryRoot, SolutionProjectInventory inventory, AssessmentSlice? assessment, Func<string, Guid?> resolveProjectId,
        IReadOnlyDictionary<string, PackageProducer> producers, ILookupCache cache, Options options, StepProgress progress, WorkLimits limits)
    {
        var projects = inventory.Projects.Select(p => new HierarchyInputProject(
            p.RelativePath,
            resolveProjectId(p.RelativePath),
            p.Name ?? Path.GetFileNameWithoutExtension(p.RelativePath),
            p.StructuralType,
            p.ParseStatus,
            p.ProjectFormat ?? "unknown",
            p.OutputType,
            p.ProjectSdk,
            p.TargetFrameworksRaw ?? (p.TargetFrameworkRaw is null ? [] : [p.TargetFrameworkRaw]),
            DependencyAssessmentCli.CurrentFramework(p),
            p.PackageManagementStyle ?? "none",
            p.Packages.Where(x => !string.IsNullOrWhiteSpace(x.PackageName))
                .Select(x => new InventoryPackageRef(x.PackageName, x.VersionRaw, x.DeclarationSource ?? "packagereference")).ToList())).ToList();
        var references = inventory.ProjectReferences
            .Select(r => new InventoryReference(r.SourceRelativePath, r.ReferencedRelativePath, r.RawPath ?? r.ReferencedRelativePath ?? "", r.ResolutionStatus))
            .ToList();

        // One cache for the walk and the workers that fill it ahead of the walk (Part B6).
        var shared = new SynchronizedLookupCache(cache);
        var now = DateTimeOffset.UtcNow;
        PackageLookup NewLookup() => new(shared, Path.Combine(DependencyAssessmentCli.CacheRoot, "packages"), TimeSpan.FromHours(options.CacheTtlHours),
            forceRefresh: false, now, options.LookupOffline);
        var workers = options.LookupConcurrency > 1 ? new LookupWorkers(Enumerable.Range(0, options.LookupConcurrency).Select(_ => NewLookup()).ToList()) : null;
        var pipeline = new HierarchyPipeline(NewLookup(), new HierarchyOptions(options.ComparePublicFeed, options.MaxPackageDepth, options.MaxPackages), workers);
        return await pipeline.RunAsync(new HierarchyInput(inventory.RepositoryId, inventory.RepositorySlug, projects, references, assessment, producers),
            repositoryRoot, CancellationToken.None, progress, limits);
    }

    private static async Task<SolutionProjectInventory> ReadInventoryAsync(string path) =>
        JsonSerializer.Deserialize<SolutionProjectInventory>(await File.ReadAllTextAsync(path), EnvelopeJson.Options)
        ?? throw new InvalidOperationException("solution-project-inventory deserialized to null");

    private static async Task<AssessmentSlice> ReadAssessmentAsync(string path) =>
        JsonSerializer.Deserialize<AssessmentSlice>(await File.ReadAllTextAsync(path), CamelCaseRead)
        ?? throw new InvalidOperationException("dependency-assessment deserialized to null");

    private static readonly Lazy<ArtifactSchemaValidator> SchemaValidator = new(() =>
        ArtifactSchemaValidator.Load(Path.Combine(AppContext.BaseDirectory, "schemas", "dependency-hierarchy-1.0.0.schema.json")));

    public static async Task<string> WriteArtifactAsync(DependencyHierarchyArtifact artifact, string outDir)
    {
        var json = DeterministicJson.Serialize(artifact);
        SchemaValidator.Value.Validate(json);
        Directory.CreateDirectory(outDir);
        var outputPath = Path.Combine(outDir, OutputFileName);
        await File.WriteAllTextAsync(outputPath, json, new UTF8Encoding(false));
        return outputPath;
    }
}
