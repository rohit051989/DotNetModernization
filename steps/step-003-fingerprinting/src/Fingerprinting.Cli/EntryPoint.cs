using System.Globalization;
using System.Text;
using System.Text.Json;
using Fingerprinting.Analysis;
using Fingerprinting.Domain;
using Fingerprinting.Extractors;

namespace Fingerprinting.Cli;

/// <summary>
/// Orchestration entry point, deliberately separate from <c>Program.cs</c> so
/// the ordering-sensitive bootstrap (MSBuildLocator, the stdout guard) stays
/// a two-line <c>Main</c> and everything testable lives here.
/// </summary>
public static class EntryPoint
{
    public static async Task<int> RunAsync(string[] args, TextReader input, TextWriter output, TextWriter error)
    {
        if (TryParseStandaloneArgs(args, out var repoPath, out var inventoryPath, out var outDir))
        {
            return await RunStandaloneAsync(repoPath, inventoryPath, outDir, error);
        }

        return await RunEnvelopeAsync(input, output, error);
    }

    /// <summary>Developer-convenience mode (11-STEP-CONTRACT.md / Part B):
    /// takes a repository path and step 2's inventory file directly, writes
    /// the artifact to a folder, and never touches stdin/stdout/the
    /// database. Useful for iterating on extractors without the engine.</summary>
    private static bool TryParseStandaloneArgs(
        string[] args, out string repoPath, out string inventoryPath, out string outDir)
    {
        repoPath = "";
        inventoryPath = "";
        outDir = "";

        string? repo = null, inventory = null, output = null;
        for (var i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--repo" when i + 1 < args.Length:
                    repo = args[++i];
                    break;
                case "--inventory" when i + 1 < args.Length:
                    inventory = args[++i];
                    break;
                case "--out" when i + 1 < args.Length:
                    output = args[++i];
                    break;
            }
        }

        if (repo is null && inventory is null && output is null)
        {
            return false;
        }

        if (repo is null || inventory is null)
        {
            throw new ArgumentException(
                "Standalone mode requires both --repo <repository-root> and --inventory <solution-project-inventory.json>.");
        }

        repoPath = Path.GetFullPath(repo);
        inventoryPath = Path.GetFullPath(inventory);
        outDir = Path.GetFullPath(output ?? "./fingerprint-out");
        return true;
    }

    private static async Task<int> RunStandaloneAsync(string repoPath, string inventoryPath, string outDir, TextWriter error)
    {
        try
        {
            var inventoryJson = await File.ReadAllTextAsync(inventoryPath);
            var inventory = JsonSerializer.Deserialize<SolutionProjectInventory>(inventoryJson, EnvelopeJson.Options)
                ?? throw new InvalidOperationException("inventory deserialized to null");

            var registry = SignalRegistry.LoadLatest(SchemasDir());
            var pipeline = new FingerprintPipeline(registry, Extractors());

            // No database in standalone mode — every project gets a
            // deterministic, stable-across-reruns id derived from its path
            // rather than a real projects.id.
            using var progress = new StepProgress(outDir, error);
            var artifact = await pipeline.RunAsync(
                inventory, repoPath, relativePath => StandaloneIds.ProjectId(inventory.RepositoryId, relativePath), CancellationToken.None,
                progress: progress);
            progress.Finish();

            var artifactJson = DeterministicJson.Serialize(artifact);
            ArtifactSchemaValidator.Load(SchemaPath()).Validate(artifactJson);

            Directory.CreateDirectory(outDir);
            var outputPath = Path.Combine(outDir, "application-fingerprint.json");
            await File.WriteAllTextAsync(outputPath, artifactJson, new UTF8Encoding(false));

            var sarifJson = BuildAndValidateSarif(artifact, registry, repoRootUri: null);
            var sarifPath = Path.Combine(outDir, "application-fingerprint.sarif");
            await File.WriteAllTextAsync(sarifPath, sarifJson, new UTF8Encoding(false));

            var localSarifJson = BuildAndValidateSarif(artifact, registry, repoRootUri: ToRepoRootFileUri(repoPath));
            var localSarifPath = Path.Combine(outDir, "application-fingerprint.local.sarif");
            await File.WriteAllTextAsync(localSarifPath, localSarifJson, new UTF8Encoding(false));

            error.WriteLine($"Wrote {outputPath}");
            error.WriteLine($"Wrote {sarifPath}");
            error.WriteLine($"Wrote {localSarifPath} (local viewing only — not a declared output)");
            return 0;
        }
        catch (Exception ex)
        {
            error.WriteLine($"Fatal: {ex}");
            return 1;
        }
    }

    private static Task<int> RunEnvelopeAsync(TextReader input, TextWriter output, TextWriter error) =>
        StepEnvelopeRunner.RunAsync(input, output, error, ExecuteAsync);

    private static async Task<StepResult> ExecuteAsync(StepContextEnvelope context)
    {
        if (context.Inputs is null || !context.Inputs.TryGetValue("solution-project-inventory", out var inventoryRef))
        {
            // The engine resolves `inputs` before invoking a step per its
            // `consumes` declaration; this only fires if invoked standalone
            // without the expected envelope, or the job's flow entry is
            // missing an `inputs:` mapping.
            return Failed("input 'solution-project-inventory' was not resolved");
        }

        SolutionProjectInventory inventory;
        try
        {
            var inventoryPath = ArtifactUri.ToLocalPath(inventoryRef.Uri);
            var inventoryJson = await File.ReadAllTextAsync(inventoryPath);
            inventory = JsonSerializer.Deserialize<SolutionProjectInventory>(inventoryJson, EnvelopeJson.Options)
                ?? throw new InvalidOperationException("deserialized to null");
        }
        catch (Exception ex)
        {
            return Failed($"could not read solution-project-inventory artifact: {ex.Message}");
        }

        if (string.IsNullOrEmpty(context.DatabaseUrl))
        {
            // Unlike step 2, step 3 has no other source for the repository's
            // local_path or for project ids (the artifact carries neither) —
            // database_url is not optional here.
            return Failed("database_url is required — step 3 resolves the repository's local_path and project ids from it");
        }

        var connectionString = DatabaseUrl.ToNpgsqlConnectionString(context.DatabaseUrl);
        var platform = new PlatformDatabase(connectionString);
        var db = new FingerprintDatabase(connectionString);

        var repositoryRoot = await platform.GetRepositoryLocalPathAsync(inventory.RepositoryId, CancellationToken.None);
        if (repositoryRoot is null)
        {
            return Failed($"repository '{inventory.RepositoryId}' has no matching row in the repositories table");
        }

        var projectIds = await platform.ResolveProjectIdsAsync(inventory.RepositoryId, CancellationToken.None);

        var registry = SignalRegistry.LoadLatest(SchemasDir());
        var pipeline = new FingerprintPipeline(registry, Extractors());

        // release 5: progress and a timing profile; each project within its own time limit; what is finished kept,
        // so a rerun continues from the last completed project.
        using var progress = new StepProgress(context.OutputDir, Console.Error);
        var (projectLimit, fileLimit) = StepLimits.Within(context);
        var limits = WorkLimits.From(projectLimit, fileLimit);
        var globs = await platform.GetDeployParameterGlobsAsync(inventory.RepositoryId, CancellationToken.None);
        var checkpoints = ProjectCheckpoints.Open(StepLimits.CheckpointDirectory(context), ProjectCheckpoints.Key(
            "application-fingerprint", FingerprintPipeline.ScannerVersion, registry.RegistryVersion, inventoryRef.Checksum,
            string.Join(",", globs), limits.ProjectLoad.TotalSeconds.ToString(CultureInfo.InvariantCulture)));
        checkpoints.Watch(progress);
        var artifact = await pipeline.RunAsync(
            inventory,
            repositoryRoot,
            relativePath => projectIds.TryGetValue(relativePath, out var id) ? id : null,
            CancellationToken.None,
            globs,
            progress,
            limits,
            checkpoints);
        progress.Phase("write");

        var artifactJson = DeterministicJson.Serialize(artifact);
        ArtifactSchemaValidator.Load(SchemaPath()).Validate(artifactJson);

        Directory.CreateDirectory(context.OutputDir);
        var outputPath = Path.Combine(context.OutputDir, "application-fingerprint.json");
        await File.WriteAllTextAsync(outputPath, artifactJson, new UTF8Encoding(false));
        var checksum = ArtifactUri.Sha256File(outputPath);

        var sarifJson = BuildAndValidateSarif(artifact, registry, repoRootUri: null);
        var sarifPath = Path.Combine(context.OutputDir, "application-fingerprint.sarif");
        await File.WriteAllTextAsync(sarifPath, sarifJson, new UTF8Encoding(false));
        var sarifChecksum = ArtifactUri.Sha256File(sarifPath);

        // Local-viewing convenience only (Part A3's uriBaseId addendum): the
        // registered file above deliberately leaves originalUriBaseIds.REPOROOT.uri
        // unset so no absolute machine path enters its checksum. This sibling
        // fills that in with this machine's real repository path so the VS Code
        // SARIF viewer can resolve source locations — never declared as a step
        // output, never checksummed, and gitignored.
        var localSarifJson = BuildAndValidateSarif(artifact, registry, repoRootUri: ToRepoRootFileUri(repositoryRoot));
        var localSarifPath = Path.Combine(context.OutputDir, "application-fingerprint.local.sarif");
        await File.WriteAllTextAsync(localSarifPath, localSarifJson, new UTF8Encoding(false));

        progress.Phase("database");
        var stepExecutionId = TryParseGuid(context.StepExecutionId);
        await db.ReplaceAllAsync(inventory.RepositoryId, artifact, stepExecutionId, CancellationToken.None);
        var resumed = checkpoints.Reused;
        checkpoints.Complete();
        progress.Finish();

        // generated_at deliberately excluded from the artifact file itself —
        // Part A3 — so unchanged input yields an identical checksum. Carried
        // in the output's metadata instead, same as steps 1 and 2.
        var generatedAt = DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ", CultureInfo.InvariantCulture);

        return new StepResult
        {
            ExitStatus = ExitStatuses.Completed,
            ExitMessage = $"Fingerprinted {artifact.Summary.ProjectsEligible} project(s) in '{artifact.RepositorySlug}' " +
                          $"({artifact.Summary.ProjectsPartial} partial, {artifact.Summary.ProjectsFailed} failed, " +
                          $"{artifact.Summary.ProjectsSkipped} skipped)."
                          + (resumed > 0 ? $" {resumed} project(s) carried over from the interrupted run." : "")
                          + (progress.NotCheckedItems.Count > 0 ? $" {progress.NotCheckedItems.Count} item(s) not checked (see timing-profile.json)." : ""),
            Metrics = new Dictionary<string, long>
            {
                ["read_count"] = inventory.Projects.Count,
                ["write_count"] = artifact.Projects.Count,
                ["skip_count"] = artifact.Summary.ProjectsSkipped,
                ["commit_count"] = 1,
            },
            Outputs =
            [
                new StepOutput
                {
                    // 1.2.0: the API_INVOCATION and LITERAL signal types,
                    // evidence.matchedValue and populated repositorySignals
                    // (Part D "Signal types") — additive over 1.1.0, so a
                    // ^1.0.0 consumes range still accepts it.
                    ArtifactType = "application-fingerprint",
                    ArtifactVersion = ArtifactUri.DeclaredVersion(outputPath),
                    Uri = ArtifactUri.FromLocalPath(outputPath),
                    Checksum = checksum,
                    Metadata = new Dictionary<string, object?> { ["generated_at"] = generatedAt },
                },
                new StepOutput
                {
                    // Additive per Part A3 — the native artifact above stays
                    // the primary output; this is the same evidence
                    // re-projected into the OASIS-standard interchange
                    // format so it opens in any SARIF viewer.
                    ArtifactType = "fingerprint-sarif",
                    ArtifactVersion = ArtifactUri.DeclaredVersion(sarifPath),
                    Uri = ArtifactUri.FromLocalPath(sarifPath),
                    Checksum = sarifChecksum,
                    Metadata = new Dictionary<string, object?> { ["generated_at"] = generatedAt },
                },
            ],
        };
    }

    private static StepResult Failed(string message) => StepEnvelopeRunner.Failed(message);

    private static Guid? TryParseGuid(string? value) => StepEnvelopeRunner.TryParseGuid(value);

    /// <summary>Every registered extractor, in the order they run — order is
    /// otherwise immaterial since FingerprintPipeline sorts signals centrally
    /// after collection (21-APPLICATION-FINGERPRINTING.md Part B rule 2).</summary>
    private static IReadOnlyList<IFingerprintExtractor> Extractors() =>
    [
        new FileIndicatorExtractor(),
        new FrameworkReferenceExtractor(),
        new AttributeExtractor(),
        new InheritanceExtractor(),
        new EntryPointExtractor(),
        new ConfigurationExtractor(),
        new ApiUsageExtractor(),
        new PathLiteralExtractor(),
        new IisHostingExtractor(),
        new FileLoggerProviderExtractor(),
    ];

    private static string SchemasDir() => Path.Combine(AppContext.BaseDirectory, "schemas");

    private static string SchemaPath() =>
        Path.Combine(AppContext.BaseDirectory, "schemas", "application-fingerprint-1.2.0.schema.json");

    // The canonical file (Microsoft's Sarif.Sdk NuGet package ships the
    // exact OASIS-published copy) declares itself "$schema": draft-04 and
    // "id" rather than "$id" — JsonSchema.Net (this project's validator,
    // draft 2020-12-first) has no draft-04 dialect registered and fails to
    // even load it. The two lines were rewritten to "$schema": 2020-12 /
    // "$id" so it loads; every constraint keyword the schema actually uses
    // (type, required, properties, enum, additionalProperties, $ref,
    // definitions, minItems, uniqueItems, format) means the same thing under
    // both drafts — confirmed no draft-04-only construct (a boolean
    // exclusiveMinimum/Maximum) appears anywhere in it — so this changes
    // which parser accepts the file, not what it validates.
    private static string SarifSchemaPath() =>
        Path.Combine(AppContext.BaseDirectory, "schemas", "sarif-schema-2.1.0.json");

    // Loaded once per process: Json.Schema.Net registers a schema globally by
    // its "$id" and throws on a second registration of the same one, and
    // BuildAndValidateSarif now runs twice per invocation (registered file,
    // then the local-viewing sibling below).
    private static readonly Lazy<ArtifactSchemaValidator> SarifSchemaValidator =
        new(() => ArtifactSchemaValidator.Load(SarifSchemaPath()));

    /// <summary>Builds the SARIF re-projection of an already-computed
    /// artifact, validates it against the published SARIF 2.1.0 schema —
    /// "a validation failure is a step failure" (Part A3) — and returns the
    /// serialized, ready-to-write text. <paramref name="repoRootUri"/> is
    /// null for the registered, checksummed file; pass the repository's
    /// absolute file URI to build the local-viewing sibling instead.</summary>
    private static string BuildAndValidateSarif(ApplicationFingerprintArtifact artifact, SignalRegistry registry, string? repoRootUri)
    {
        var sarif = SarifBuilder.Build(artifact, registry, repoRootUri);
        var sarifJson = DeterministicJson.SerializeOmitNulls(sarif);
        SarifSchemaValidator.Value.Validate(sarifJson);
        return sarifJson;
    }

    /// <summary>Absolute <c>file://</c> URI for a repository root, with a
    /// trailing slash so SARIF's relative <c>artifactLocation.uri</c> values
    /// resolve against it as a directory rather than replacing its last
    /// segment (RFC 3986 base-URI resolution). Used only for the local-only
    /// <c>.local.sarif</c> sibling — the registered file never embeds an
    /// absolute machine path.</summary>
    private static string ToRepoRootFileUri(string repoRoot)
    {
        var full = Path.GetFullPath(repoRoot);
        if (!full.EndsWith(Path.DirectorySeparatorChar))
        {
            full += Path.DirectorySeparatorChar;
        }

        return new Uri(full).AbsoluteUri;
    }
}
