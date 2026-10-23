using System.Globalization;
using System.Text;
using System.Text.Json;
using Fingerprinting.Analysis;
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
    public const string OutputFileName = "impact-analysis.json";

    private static readonly (string Type, string Range)[] Inputs =
    [
        ("solution-project-inventory", "^2.0.0"),
        ("entry-point-inventory", "^2.0.0"),
        ("item-occurrences", "^1.0.0"),
        ("test-coverage", "^1.0.0"),
        ("outbound-invocation-inventory", "^1.3.0"),
    ];


    public static async Task<int> RunAsync(string[] args, TextReader input, TextWriter output, TextWriter error)
    {
        if (args.Length > 0) return await RunStandaloneAsync(args, error);
        return await StepEnvelopeRunner.RunAsync(input, output, error, ExecuteAsync);
    }

    // ---------- standalone ----------

    /// <summary>
    /// Runs the pipeline without the engine or the database, from files: the
    /// four upstream artifacts, the catalog's impact rules and the decisions.
    /// Used to calibrate the rules against a hand analysis
    /// (backend/app/impact/calibration.py). Writes the artifact only.
    ///
    /// --catalog is {"items": [{"itemId", "name", "resolutions": [{"id", "name",
    /// "isDefault", "consumerImpact", "rules": [...]}]}]}; --decisions is
    /// {"item-id": "resolution-id"}.
    /// </summary>
    private static async Task<int> RunStandaloneAsync(string[] args, TextWriter error)
    {
        var options = new Dictionary<string, string>(StringComparer.Ordinal);
        for (var i = 0; i + 1 < args.Length; i += 2) options[args[i]] = args[i + 1];
        string[] required = ["--repo", "--inventory", "--occurrences", "--entry-points", "--test-coverage", "--outbound", "--catalog", "--decisions", "--out"];
        var missing = required.Where(r => !options.ContainsKey(r)).ToList();
        if (missing.Count > 0)
        {
            error.WriteLine($"Standalone mode requires {string.Join(" ", required.Select(r => r + " <path>"))}; missing {string.Join(", ", missing)}.");
            return 2;
        }

        try
        {
            var inventory = JsonSerializer.Deserialize<SolutionProjectInventory>(await File.ReadAllTextAsync(options["--inventory"]), EnvelopeJson.Options)!;
            var workItems = WorkItems(JsonDocument.Parse(await File.ReadAllTextAsync(options["--occurrences"])).RootElement);
            var catalog = JsonDocument.Parse(await File.ReadAllTextAsync(options["--catalog"])).RootElement;
            var items = catalog.GetProperty("items").EnumerateArray().Select(item => new CatalogItemInfo(
                    Str(item, "itemId")!, Str(item, "name")!,
                    item.GetProperty("resolutions").EnumerateArray().Select(r => new ResolutionInfo(
                        Str(r, "id")!, Str(r, "name")!, r.GetProperty("isDefault").GetBoolean(), Str(r, "consumerImpact")!,
                        JsonSerializer.Deserialize<List<ImpactRule>>(r.GetProperty("rules").GetRawText()) ?? [])).ToList()))
                .ToDictionary(i => i.ItemId, StringComparer.Ordinal);
            var decisions = JsonSerializer.Deserialize<Dictionary<string, string>>(await File.ReadAllTextAsync(options["--decisions"])) ?? [];
            var input = new ImpactInput(
                inventory.RepositoryId, inventory.RepositorySlug, "standalone",
                new ProjectMap(inventory.Projects.ToDictionary(p => p.RelativePath, p => DirectoryOf(p.RelativePath), StringComparer.Ordinal)),
                workItems, items, decisions,
                TestLinks(JsonDocument.Parse(await File.ReadAllTextAsync(options["--test-coverage"])).RootElement),
                EntryPoints(JsonDocument.Parse(await File.ReadAllTextAsync(options["--entry-points"])).RootElement),
                HostLinks(JsonDocument.Parse(await File.ReadAllTextAsync(options["--entry-points"])).RootElement),
                DeployFiles(JsonDocument.Parse(await File.ReadAllTextAsync(options["--outbound"])).RootElement));
            var artifact = await ImpactPipeline.RunAsync(input, Path.GetFullPath(options["--repo"]), CancellationToken.None);
            var path = await WriteArtifactAsync(artifact, Path.GetFullPath(options["--out"]));
            error.WriteLine($"Wrote {path}");
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
            EntryPoints(JsonDocument.Parse(await ReadAsync(refs["entry-point-inventory"])).RootElement),
            HostLinks(JsonDocument.Parse(await ReadAsync(refs["entry-point-inventory"])).RootElement),
            DeployFiles(JsonDocument.Parse(await ReadAsync(refs["outbound-invocation-inventory"])).RootElement));

        // release 5: progress and a timing profile.
        using var progress = new StepProgress(context.OutputDir, Console.Error);
        var artifact = await ImpactPipeline.RunAsync(input, repositoryRoot, CancellationToken.None, progress);
        progress.Phase("write");
        var outputPath = await WriteArtifactAsync(artifact, context.OutputDir);
        var checksum = ArtifactUri.Sha256File(outputPath);
        progress.Phase("database");
        await database.ReplaceAllAsync(artifact, StepEnvelopeRunner.TryParseGuid(context.StepExecutionId), CancellationToken.None);
        progress.Finish();

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
                    ArtifactType = ArtifactType, ArtifactVersion = ArtifactUri.DeclaredVersion(outputPath), Uri = ArtifactUri.FromLocalPath(outputPath), Checksum = checksum,
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
                var packages = new List<string>();
                foreach (var occurrence in item.GetProperty("occurrences").EnumerateArray())
                {
                    var evidence = occurrence.TryGetProperty("evidence", out var e) ? e.EnumerateArray().ToList() : [];
                    // A package work item names its packages: "Foo 1.0.0 -> 2.0.0", "Foo 1.0.0: ...".
                    var firstSignal = evidence.Select(v => Str(v, "signal_name")).FirstOrDefault(n => n is not null);
                    foreach (var (signal, value) in evidence.Select(v => (Str(v, "signal_name"), Str(v, "value"))).Append((firstSignal, Str(occurrence, "value"))))
                    {
                        if (signal is not null && signal.StartsWith("PACKAGE_", StringComparison.Ordinal) && value?.Split(' ', 2)[0] is { Length: > 0 } package)
                        {
                            packages.Add(package);
                        }
                    }

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
                    seeds.DistinctBy(s => s.Path).OrderBy(s => s.Path, StringComparer.Ordinal).ToList(),
                    packages.Distinct(StringComparer.OrdinalIgnoreCase).Order(StringComparer.OrdinalIgnoreCase).ToList()));
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

    /// <summary>entry-point-inventory's HOSTS_WCF_SERVICE signals: the project
    /// constructing the ServiceHost or holding the .svc, and the contract.</summary>
    public static IReadOnlyList<HostLink> HostLinks(JsonElement inventory) =>
        inventory.GetProperty("projects").EnumerateArray()
            .SelectMany(p => (p.TryGetProperty("signals", out var s) ? s.EnumerateArray() : Enumerable.Empty<JsonElement>())
                .Where(signal => Str(signal, "name") == "HOSTS_WCF_SERVICE" && Str(signal, "value") is not null)
                .Select(signal => new HostLink(Str(p, "projectPath")!, Str(signal, "value")!)))
            .Distinct()
            .ToList();

    /// <summary>outbound-invocation-inventory's deploy parameters (1.3.0): each
    /// SetParam / SetParameters file found for a project, with its environment.</summary>
    public static IReadOnlyList<DeployFile> DeployFiles(JsonElement outbound) =>
        outbound.GetProperty("projects").EnumerateArray()
            .SelectMany(p => (p.TryGetProperty("deployParameters", out var d) ? d.EnumerateArray() : Enumerable.Empty<JsonElement>())
                .Select(parameter => new DeployFile(Str(parameter, "projectPath") ?? Str(p, "projectPath")!, Str(parameter, "sourceFile")!,
                    Str(parameter, "environment")!)))
            .Distinct()
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
