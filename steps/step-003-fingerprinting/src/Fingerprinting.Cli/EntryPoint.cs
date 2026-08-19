using System.Globalization;
using System.Text;
using System.Text.Json;
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

            var registry = SignalRegistry.Load(RegistryPath());
            var pipeline = new FingerprintPipeline(registry, Extractors());

            // No database in standalone mode — every project gets a
            // deterministic, stable-across-reruns id derived from its path
            // rather than a real projects.id.
            var artifact = await pipeline.RunAsync(
                inventory, repoPath, relativePath => DeterministicProjectId(inventory.RepositoryId, relativePath), CancellationToken.None);

            var artifactJson = DeterministicJson.Serialize(artifact);
            ArtifactSchemaValidator.Load(SchemaPath()).Validate(artifactJson);

            Directory.CreateDirectory(outDir);
            var outputPath = Path.Combine(outDir, "application-fingerprint.json");
            await File.WriteAllTextAsync(outputPath, artifactJson, new UTF8Encoding(false));

            error.WriteLine($"Wrote {outputPath}");
            return 0;
        }
        catch (Exception ex)
        {
            error.WriteLine($"Fatal: {ex}");
            return 1;
        }
    }

    private static async Task<int> RunEnvelopeAsync(TextReader input, TextWriter output, TextWriter error)
    {
        StepContextEnvelope context;
        try
        {
            // lstrip a BOM: PowerShell's `Get-Content | ...exe` (the documented
            // standalone invocation) can inject one — same guard as step 2.
            var raw = (await input.ReadToEndAsync()).TrimStart('﻿');
            context = JsonSerializer.Deserialize<StepContextEnvelope>(raw, EnvelopeJson.Options)
                ?? throw new InvalidOperationException("StepContext deserialized to null");
        }
        catch (Exception ex)
        {
            // Nothing to build a StepResult against — the process adapter's
            // fallback path (non-zero exit, stderr tail) applies here.
            error.WriteLine($"Fatal: could not parse StepContext from stdin: {ex}");
            return 1;
        }

        StepResult result;
        try
        {
            result = await ExecuteAsync(context);
        }
        catch (Exception ex)
        {
            result = new StepResult { ExitStatus = ExitStatuses.Failed, ExitMessage = $"{ex.GetType().Name}: {ex.Message}" };
        }

        output.Write(JsonSerializer.Serialize(result, EnvelopeJson.Options));
        return 0;
    }

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

        var db = new FingerprintDatabase(DatabaseUrl.ToNpgsqlConnectionString(context.DatabaseUrl));

        var repositoryRoot = await db.GetRepositoryLocalPathAsync(inventory.RepositoryId, CancellationToken.None);
        if (repositoryRoot is null)
        {
            return Failed($"repository '{inventory.RepositoryId}' has no matching row in the repositories table");
        }

        var projectIds = await db.ResolveProjectIdsAsync(inventory.RepositoryId, CancellationToken.None);

        var registry = SignalRegistry.Load(RegistryPath());
        var pipeline = new FingerprintPipeline(registry, Extractors());

        var artifact = await pipeline.RunAsync(
            inventory,
            repositoryRoot,
            relativePath => projectIds.TryGetValue(relativePath, out var id) ? id : null,
            CancellationToken.None);

        var artifactJson = DeterministicJson.Serialize(artifact);
        ArtifactSchemaValidator.Load(SchemaPath()).Validate(artifactJson);

        Directory.CreateDirectory(context.OutputDir);
        var outputPath = Path.Combine(context.OutputDir, "application-fingerprint.json");
        await File.WriteAllTextAsync(outputPath, artifactJson, new UTF8Encoding(false));
        var checksum = ArtifactUri.Sha256File(outputPath);

        var stepExecutionId = TryParseGuid(context.StepExecutionId);
        await db.ReplaceAllAsync(inventory.RepositoryId, artifact, stepExecutionId, CancellationToken.None);

        // generated_at deliberately excluded from the artifact file itself —
        // Part A3 — so unchanged input yields an identical checksum. Carried
        // in the output's metadata instead, same as steps 1 and 2.
        var generatedAt = DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ", CultureInfo.InvariantCulture);

        return new StepResult
        {
            ExitStatus = ExitStatuses.Completed,
            ExitMessage = $"Fingerprinted {artifact.Summary.ProjectsEligible} project(s) in '{artifact.RepositorySlug}' " +
                          $"({artifact.Summary.ProjectsPartial} partial, {artifact.Summary.ProjectsFailed} failed, " +
                          $"{artifact.Summary.ProjectsSkipped} skipped).",
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
                    ArtifactType = "application-fingerprint",
                    ArtifactVersion = "1.0.0",
                    Uri = ArtifactUri.FromLocalPath(outputPath),
                    Checksum = checksum,
                    Metadata = new Dictionary<string, object?> { ["generated_at"] = generatedAt },
                },
            ],
        };
    }

    private static StepResult Failed(string message) => new() { ExitStatus = ExitStatuses.Failed, ExitMessage = message };

    private static Guid? TryParseGuid(string? value) => Guid.TryParse(value, out var guid) ? guid : null;

    /// <summary>A stable id derived from (repository, relative path) for runs
    /// with no database — deterministic across reruns, unlike
    /// <see cref="Guid.NewGuid"/>, which the checksum determinism requirement
    /// (Part B rule 2) rules out.</summary>
    private static Guid DeterministicProjectId(Guid repositoryId, string relativePath)
    {
        var bytes = Encoding.UTF8.GetBytes($"{repositoryId:D}|{relativePath}");
        var hash = System.Security.Cryptography.SHA256.HashData(bytes);
        return new Guid(hash[..16]);
    }

    /// <summary>Every registered extractor, in the order they run — order is
    /// otherwise immaterial since FingerprintPipeline sorts signals centrally
    /// after collection (21-STEP-003-FINGERPRINTING.md Part B rule 2).</summary>
    private static IReadOnlyList<IFingerprintExtractor> Extractors() =>
    [
        new FileIndicatorExtractor(),
        new FrameworkReferenceExtractor(),
        new AttributeExtractor(),
        new InheritanceExtractor(),
        new EntryPointExtractor(),
        new ConfigurationExtractor(),
    ];

    private static string RegistryPath() => Path.Combine(AppContext.BaseDirectory, "schemas", "signal-registry-1.1.0.json");

    private static string SchemaPath() =>
        Path.Combine(AppContext.BaseDirectory, "schemas", "application-fingerprint-1.0.0.schema.json");
}
