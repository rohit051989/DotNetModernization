using System.Globalization;
using System.Text;
using System.Text.Json;
using Fingerprinting.Domain;
using Fingerprinting.Impact;
using Fingerprinting.StepHost;

namespace Fingerprinting.Impact.Cli;

/// <summary>
/// Lifecycle step impact-analysis — 33-IMPACT-ANALYSIS.md. The
/// process-adapter envelope: four required inputs (solution-discovery's projects, step
/// 4's entry points, item-detection's occurrences — the work items and their seeds —
/// and test-coverage-assessment's test mappings), and from the database the engagement's live
/// decisions and the catalog's impact rules. Writes work_item_impacts,
/// impact_summaries and file_impact_rollup, replacing the repository's rows;
/// dependency-and-context-map adds client rows at the end of the next estate run.
/// </summary>
public static class ImpactCli
{
    public const string ArtifactType = "impact-analysis";
    public const string ArtifactVersion = ImpactPipeline.ArtifactVersion;
    public const string OutputFileName = "impact-analysis.json";

    private static readonly (string Type, string Range)[] Inputs =
    [
        ("solution-project-inventory", "^2.0.0"),
        ("entry-point-inventory", "^2.0.0"),
        ("item-occurrences", "^1.0.0"),
        ("test-coverage", "^1.0.0"),
    ];


    public static Task<int> RunAsync(TextReader input, TextWriter output, TextWriter error) =>
        StepEnvelopeRunner.RunAsync(input, output, error, ExecuteAsync);

    private static async Task<StepResult> ExecuteAsync(StepContextEnvelope context)
    {
        if (string.IsNullOrEmpty(context.DatabaseUrl))
        {
            return StepEnvelopeRunner.Failed("database_url is required — impact-analysis reads the engagement's decisions and the catalog's impact rules from it");
        }

        var refs = new Dictionary<string, ArtifactRef>();
        foreach (var (type, range) in Inputs)
        {
            var reference = context.Inputs?.Values.FirstOrDefault(a => a.ArtifactType == type);
            if (reference is null)
            {
                return StepEnvelopeRunner.Failed($"input '{type}' was not resolved — phase0-repository-discovery must wire it in the step's inputs mapping");
            }

            if (!ArtifactVersions.SatisfiesCaret(reference.ArtifactVersion, range))
            {
                return StepEnvelopeRunner.Failed($"{type} {reference.ArtifactVersion} does not satisfy {range}");
            }

            refs[type] = reference;
        }

        var connectionString = DatabaseUrl.ToNpgsqlConnectionString(context.DatabaseUrl);
        var platform = new PlatformDatabase(connectionString);
        var database = new ImpactDatabase(connectionString);
        var inventory = JsonSerializer.Deserialize<SolutionProjectInventory>(await ReadAsync(refs["solution-project-inventory"]), EnvelopeJson.Options)!;
        var repositoryRoot = await platform.GetRepositoryLocalPathAsync(inventory.RepositoryId, CancellationToken.None);
        if (repositoryRoot is null)
        {
            return StepEnvelopeRunner.Failed($"repository '{inventory.RepositoryId}' has no matching row in the repositories table");
        }

        var engagementId = await database.GetEngagementIdAsync(inventory.RepositoryId, CancellationToken.None);
        var workItems = WorkItems(JsonDocument.Parse(await ReadAsync(refs["item-occurrences"])).RootElement);
        var items = await database.GetCatalogAsync(workItems.Select(w => w.ItemId).Distinct().ToList(), CancellationToken.None);
        var decisions = await database.GetDecisionsAsync(engagementId, CancellationToken.None);
        var input = new ImpactInput(
            inventory.RepositoryId, inventory.RepositorySlug, engagementId,
            new ProjectMap(inventory.Projects.ToDictionary(p => p.RelativePath, p => DirectoryOf(p.RelativePath), StringComparer.Ordinal)),
            workItems, items, decisions,
            TestLinks(JsonDocument.Parse(await ReadAsync(refs["test-coverage"])).RootElement),
            EntryPoints(JsonDocument.Parse(await ReadAsync(refs["entry-point-inventory"])).RootElement));

        var artifact = await ImpactPipeline.RunAsync(input, repositoryRoot, CancellationToken.None);
        var outputPath = await WriteArtifactAsync(artifact, context.OutputDir);
        var checksum = ArtifactUri.Sha256File(outputPath);
        await database.ReplaceAllAsync(artifact, StepEnvelopeRunner.TryParseGuid(context.StepExecutionId), CancellationToken.None);

        var s = artifact.Summary;
        return new StepResult
        {
            ExitStatus = ExitStatuses.Completed,
            ExitMessage = $"'{artifact.RepositorySlug}': {s.WorkItems} work item(s); under effective resolutions {s.Changes} change(s) across {s.FilesChanged} distinct file(s) "
                          + $"({s.ByAction.Rewrite} rewrite, {s.ByAction.Update} update, {s.ByAction.Delete} delete), {s.NewFiles} new file(s), {s.FilesToReview} file(s) to review; "
                          + $"{s.Hotspots} hotspot(s), {s.Conflicts} conflict(s). Structural only: client impact is added by the next estate run.",
            Metrics = new Dictionary<string, long>
            {
                ["read_count"] = s.WorkItems,
                ["write_count"] = artifact.WorkItems.Sum(w => w.Resolutions.Sum(r => r.Entries.Count)),
                ["skip_count"] = 0,
                ["commit_count"] = 1,
            },
            Outputs =
            [
                new StepOutput
                {
                    ArtifactType = ArtifactType, ArtifactVersion = ArtifactVersion, Uri = ArtifactUri.FromLocalPath(outputPath), Checksum = checksum,
                    Metadata = new Dictionary<string, object?> { ["generated_at"] = DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ", CultureInfo.InvariantCulture) },
                },
            ],
        };
    }

    /// <summary>item-detection's found items, one work item per (item, project); the
    /// seeds are each occurrence's file and its evidence's source paths.</summary>
    public static IReadOnlyList<WorkItemSeed> WorkItems(JsonElement occurrences)
    {
        var result = new List<WorkItemSeed>();
        foreach (var project in occurrences.GetProperty("projects").EnumerateArray())
        {
            var projectPath = project.GetProperty("projectPath").GetString()!;
            Guid? projectId = project.TryGetProperty("projectId", out var id) && Guid.TryParse(id.GetString(), out var guid) ? guid : null;
            foreach (var item in project.GetProperty("items").EnumerateArray())
            {
                if (item.GetProperty("detectionState").GetString() != "found") continue;
                var seeds = new List<SeedFile>();
                var metadata = new List<string>();
                foreach (var occurrence in item.GetProperty("occurrences").EnumerateArray())
                {
                    var evidence = occurrence.TryGetProperty("evidence", out var e) ? e.EnumerateArray().ToList() : [];
                    metadata.AddRange(evidence.Where(v => Str(v, "field") is not null).Select(v => $"{Str(v, "field")} {Raw(v, "actual")}"));
                    if (occurrence.TryGetProperty("filePath", out var file) && file.ValueKind == JsonValueKind.String)
                    {
                        var signal = evidence.Select(v => Str(v, "signal_name")).FirstOrDefault(n => n is not null);
                        seeds.Add(new SeedFile(file.GetString()!, signal, null));
                    }

                    foreach (var entry in evidence)
                    {
                        if (Str(entry, "source_path") is { } source && !(entry.TryGetProperty("repository_level", out var repo) && repo.ValueKind == JsonValueKind.True))
                        {
                            seeds.Add(new SeedFile(source, Str(entry, "signal_name"), Str(entry, "value")));
                        }
                    }
                }

                // Matched on project metadata only (framework family, output
                // type): the evidence is the project file itself. Every work
                // item has at least its own evidence as impact (Part D).
                if (seeds.Count == 0)
                {
                    seeds.Add(new SeedFile(projectPath, "project metadata", metadata.Count == 0 ? null : string.Join(", ", metadata.Distinct())));
                }

                result.Add(new WorkItemSeed(item.GetProperty("itemId").GetString()!, projectId, projectPath,
                    seeds.DistinctBy(s => s.Path).OrderBy(s => s.Path, StringComparer.Ordinal).ToList()));
            }
        }

        return result;
    }

    public static IReadOnlyList<TestLink> TestLinks(JsonElement coverage) =>
        coverage.GetProperty("mappings").EnumerateArray().Select(m => new TestLink(
            Str(m, "sourceFile")!, Str(m, "productionType")!, Str(m, "testFile")!, Str(m, "testClass")!, Str(m, "method")!,
            m.GetProperty("confidence").GetDecimal())).ToList();

    public static IReadOnlyList<EntryPointRef> EntryPoints(JsonElement inventory) =>
        inventory.GetProperty("projects").EnumerateArray()
            .SelectMany(p => p.GetProperty("entryPoints").EnumerateArray())
            .Select(e =>
            {
                var handler = e.GetProperty("handler");
                return new EntryPointRef(Str(e, "kind")!, Str(handler, "type")!, Str(handler, "namespace"), Str(handler, "member"), Str(handler, "filePath")!);
            })
            .ToList();

    private static string? Str(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() : null;

    private static string Raw(JsonElement element, string name) =>
        !element.TryGetProperty(name, out var value) ? "" : value.ValueKind == JsonValueKind.String ? value.GetString()! : value.GetRawText();

    private static async Task<string> ReadAsync(ArtifactRef reference) => await File.ReadAllTextAsync(ArtifactUri.ToLocalPath(reference.Uri));

    private static string DirectoryOf(string projectPath)
    {
        var index = projectPath.Replace('\\', '/').LastIndexOf('/');
        return index < 0 ? "" : projectPath[..index].Replace('\\', '/');
    }

    private static readonly Lazy<ArtifactSchemaValidator> SchemaValidator = new(() =>
        ArtifactSchemaValidator.Load(Path.Combine(AppContext.BaseDirectory, "schemas", "impact-analysis-2.1.0.schema.json")));

    public static async Task<string> WriteArtifactAsync(ImpactArtifact artifact, string outDir)
    {
        var json = DeterministicJson.Serialize(artifact);
        SchemaValidator.Value.Validate(json);
        Directory.CreateDirectory(outDir);
        var outputPath = Path.Combine(outDir, OutputFileName);
        await File.WriteAllTextAsync(outputPath, json, new UTF8Encoding(false));
        return outputPath;
    }
}
