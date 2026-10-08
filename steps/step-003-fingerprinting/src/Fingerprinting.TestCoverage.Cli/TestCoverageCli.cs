using System.Diagnostics;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Fingerprinting.Domain;
using Fingerprinting.StepHost;
using Fingerprinting.TestCoverage;

namespace Fingerprinting.TestCoverage.Cli;

/// <summary>
/// Lifecycle step 8, test-coverage-assessment, phase 1 —
/// 32-STEP-008-TEST-COVERAGE.md. Two modes, as steps 3 to 6: the
/// process-adapter envelope (StepContext on stdin, StepResult on stdout), and
/// a standalone mode for iterating without the engine (no database, no cache).
///
/// <b>Cache (Part I).</b> Coverage only changes when code changes. A run at a
/// commit this step has already computed, with the same inputs and
/// configuration, reuses that result instead of recomputing it — unless the
/// working tree has uncommitted changes to files that matter (source,
/// projects, coverage reports, pipelines), checked with
/// <c>git --no-optional-locks status</c> so the repository's index is never
/// written. A repository without git history has no commit to key on and is
/// always computed.
/// </summary>
public static class TestCoverageCli
{
    public const string ArtifactType = "test-coverage";
    public const string ArtifactVersion = TestCoveragePipeline.ArtifactVersion;
    public const string StepVersion = "1.0.0";
    public const string OutputFileName = "test-coverage.json";

    private const string InventoryType = "solution-project-inventory";
    private const string InventoryRange = "^2.0.0";
    private const string FingerprintType = "application-fingerprint";
    private const string FingerprintRange = "^1.2.0";

    /// <summary>Step 3's test signals (Part B1) — the same set the platform's
    /// project-role computation reads (backend/app/items/roles.py).</summary>
    private static readonly HashSet<string> TestSignalNames = new(
        ["FACT_ATTRIBUTE", "TEST_ATTRIBUTE", "TEST_METHOD_ATTRIBUTE", "TEST_FIXTURE_ATTRIBUTE", "XUNIT_PACKAGE", "NUNIT_PACKAGE", "MSTEST_PACKAGE"],
        StringComparer.Ordinal);

    private static readonly JsonSerializerOptions CamelCaseRead = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase, PropertyNameCaseInsensitive = true };

    public static async Task<int> RunAsync(string[] args, TextReader input, TextWriter output, TextWriter error)
    {
        if (args.Length > 0) return await RunStandaloneAsync(args, error);
        return await StepEnvelopeRunner.RunAsync(input, output, error, ExecuteAsync);
    }

    // ---------- standalone ----------

    private static async Task<int> RunStandaloneAsync(string[] args, TextWriter error)
    {
        string? repo = null, inventory = null, fingerprint = null, outDir = null;
        var locations = new List<string>();
        for (var i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--repo" when i + 1 < args.Length: repo = args[++i]; break;
                case "--inventory" when i + 1 < args.Length: inventory = args[++i]; break;
                case "--fingerprint" when i + 1 < args.Length: fingerprint = args[++i]; break;
                case "--out" when i + 1 < args.Length: outDir = args[++i]; break;
                case "--coverage-location" when i + 1 < args.Length: locations.Add(args[++i]); break;
            }
        }

        if (repo is null || inventory is null || fingerprint is null)
        {
            error.WriteLine("Standalone mode requires --repo <root> --inventory <solution-project-inventory.json> --fingerprint <application-fingerprint.json>; "
                            + "optional --out <dir> and --coverage-location <dir> (repeatable).");
            return 2;
        }

        try
        {
            var inventoryData = await ReadAsync<SolutionProjectInventory>(Path.GetFullPath(inventory), EnvelopeJson.Options);
            var fingerprintData = await ReadAsync<FingerprintWithSignals>(Path.GetFullPath(fingerprint), CamelCaseRead);
            var testInput = BuildInput(inventoryData, fingerprintData, null, locations);
            var artifact = await TestCoveragePipeline.RunAsync(testInput, Path.GetFullPath(repo), CancellationToken.None);
            var path = await WriteArtifactAsync(artifact, Path.GetFullPath(outDir ?? "./test-coverage-out"));
            error.WriteLine($"Wrote {path}");
            error.WriteLine(Summary(artifact));
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
            return StepEnvelopeRunner.Failed("database_url is required — step 8 resolves the repository, its commit and the cache from it");
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
        var database = new TestCoverageDatabase(connectionString);
        var inventory = await ReadAsync<SolutionProjectInventory>(ArtifactUri.ToLocalPath(inventoryRef.Uri), EnvelopeJson.Options);
        var fingerprint = await ReadAsync<FingerprintWithSignals>(ArtifactUri.ToLocalPath(fingerprintRef.Uri), CamelCaseRead);

        var repositoryRoot = await platform.GetRepositoryLocalPathAsync(inventory.RepositoryId, CancellationToken.None);
        if (repositoryRoot is null)
        {
            return StepEnvelopeRunner.Failed($"repository '{inventory.RepositoryId}' has no matching row in the repositories table");
        }

        var commit = await database.GetCommitShaAsync(inventory.RepositoryId, CancellationToken.None);
        var locations = Strings(context.Config, "coverage_report_locations");
        var testInput = BuildInput(inventory, fingerprint, commit, locations);
        var cacheKey = CacheKey(testInput);

        // Part I: reuse, or compute.
        string cacheState;
        string? cacheNote = null;
        TestCoverageArtifact? artifact = null;
        Guid? reusedFrom = null;
        if (commit is null)
        {
            cacheState = "no_commit";
            cacheNote = "the repository has no git history: no commit to key a cache on, so the result is always computed";
        }
        else if (UncommittedChanges(repositoryRoot) is { } changes)
        {
            cacheState = "uncommitted_changes";
            cacheNote = changes;
        }
        else
        {
            var cached = await database.FindCachedAsync(inventory.RepositoryId, commit, cacheKey, CancellationToken.None);
            if (cached is not null)
            {
                artifact = JsonSerializer.Deserialize<TestCoverageArtifact>(cached.Value.Result, DeterministicJson.Options)
                           ?? throw new InvalidOperationException("cached test-coverage result deserialized to null");
                reusedFrom = cached.Value.ScanId;
                cacheState = "reused";
                cacheNote = $"commit {commit[..Math.Min(12, commit.Length)]} computed before with the same inputs: mapping, buckets and coverage reused";
            }
            else
            {
                cacheState = "computed";
            }
        }

        artifact ??= await TestCoveragePipeline.RunAsync(testInput, repositoryRoot, CancellationToken.None);
        var outputPath = await WriteArtifactAsync(artifact, context.OutputDir);
        var checksum = ArtifactUri.Sha256File(outputPath);
        var projectIds = await platform.ResolveProjectIdsAsync(inventory.RepositoryId, CancellationToken.None);
        await database.ReplaceAllAsync(artifact, projectIds, cacheKey, cacheState, cacheNote, reusedFrom, checksum,
            StepEnvelopeRunner.TryParseGuid(context.StepExecutionId), CancellationToken.None);

        return new StepResult
        {
            ExitStatus = ExitStatuses.Completed,
            ExitMessage = $"{Summary(artifact)} Cache: {cacheState}{(cacheNote is null ? "" : $" ({cacheNote})")}.",
            Metrics = new Dictionary<string, long>
            {
                ["read_count"] = artifact.Summary.SourceFiles + artifact.Summary.TestClasses,
                ["write_count"] = artifact.SourceFiles.Count + artifact.TestClasses.Count + artifact.Mappings.Count + 2,
                ["skip_count"] = cacheState == "reused" ? artifact.Summary.SourceFiles : 0,
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
                        ["cache_state"] = cacheState,
                        ["commit_sha"] = commit,
                    },
                },
            ],
        };
    }

    public static string Summary(TestCoverageArtifact artifact)
    {
        var s = artifact.Summary;
        var ci = artifact.CiMaturity;
        return $"'{artifact.RepositorySlug}': {s.TestProjects} test project(s), {s.TestClasses} test class(es) ("
               + string.Join(", ", new (int Count, string Type)[]
                   {
                       (s.TestClassesByType.Unit, TestTypes.Unit), (s.TestClassesByType.Integration, TestTypes.Integration),
                       (s.TestClassesByType.Functional, TestTypes.Functional), (s.TestClassesByType.Smoke, TestTypes.Smoke),
                       (s.TestClassesByType.Unclassified, TestTypes.Unclassified),
                   }.Where(t => t.Count > 0).Select(t => $"{t.Count} {t.Type}"))
               + $"); {s.SourceFiles} source file(s): {s.SourceFilesByBucket.HasTests} {Buckets.HasTests}, "
               + $"{s.SourceFilesByBucket.MissingTests} {Buckets.MissingTests}, {s.SourceFilesByBucket.NoTestableLogic} {Buckets.NoTestableLogic}"
               + $"; {s.CoverageReports} coverage report(s), {s.SourceFilesMeasured} file(s) measured; CI: "
               + (ci.HasPipeline ? $"pipeline, tests {(ci.RunsTests ? "run" : "not run")}, coverage {(ci.CollectsCoverage ? "collected" : "not collected")}" : "no pipeline") + ".";
    }

    private static TestCoverageInput BuildInput(SolutionProjectInventory inventory, FingerprintWithSignals fingerprint, string? commit, IReadOnlyList<string> locations)
    {
        var signals = fingerprint.Projects.ToDictionary(
            p => p.ProjectPath, p => p.Signals.Select(s => s.Name).Where(TestSignalNames.Contains).Distinct().Order(StringComparer.Ordinal).ToList(), StringComparer.Ordinal);
        var projects = inventory.Projects
            .Select(p => new InputProject(p.RelativePath,
                p.Packages.Select(pk => pk.PackageName).Where(n => !string.IsNullOrWhiteSpace(n)).Distinct().Order(StringComparer.OrdinalIgnoreCase).ToList(),
                signals.GetValueOrDefault(p.RelativePath) ?? []))
            .ToList();
        return new TestCoverageInput(inventory.RepositoryId, inventory.RepositorySlug, commit, projects, locations, []);
    }

    /// <summary>What the result depends on besides the commit: this step's
    /// version, every project's path, packages and test signals, and the
    /// configured report locations.</summary>
    public static string CacheKey(TestCoverageInput input)
    {
        var text = new StringBuilder($"test-coverage {StepVersion} {ArtifactVersion}\n");
        foreach (var project in input.Projects.OrderBy(p => p.ProjectPath, StringComparer.Ordinal))
        {
            text.Append(project.ProjectPath).Append('|').AppendJoin(',', project.Packages).Append('|').AppendJoin(',', project.TestSignals).Append('\n');
        }

        text.Append("locations:").AppendJoin(',', input.CoverageLocations.Order(StringComparer.Ordinal));
        return Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text.ToString())));
    }

    /// <summary>A description of uncommitted changes to files that affect the
    /// result, or null when there are none. Read-only: `--no-optional-locks`
    /// keeps git from refreshing (writing) the index.</summary>
    private static string? UncommittedChanges(string repositoryRoot)
    {
        try
        {
            var start = new ProcessStartInfo("git", ["--no-optional-locks", "-C", repositoryRoot, "status", "--porcelain", "--untracked-files=all"])
            {
                RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false,
            };
            using var process = Process.Start(start)!;
            var output = process.StandardOutput.ReadToEnd();
            process.WaitForExit(30_000);
            if (process.ExitCode != 0) return "git status failed: the working tree could not be checked, so the cache is not trusted";
            var relevant = output.Split('\n', StringSplitOptions.RemoveEmptyEntries)
                .Select(l => l.Length > 3 ? l[3..].Trim().Trim('"') : "")
                .Where(Matters).ToList();
            return relevant.Count == 0 ? null : $"{relevant.Count} uncommitted change(s) to source, projects, coverage reports or pipelines (e.g. {relevant[0]}): computed, not reused";
        }
        catch (Exception ex) when (ex is System.ComponentModel.Win32Exception or InvalidOperationException)
        {
            return "git is not available: the working tree could not be checked, so the cache is not trusted";
        }
    }

    private static bool Matters(string path)
    {
        var lower = path.ToLowerInvariant();
        return lower.EndsWith(".cs", StringComparison.Ordinal) || lower.EndsWith(".csproj", StringComparison.Ordinal)
               || lower.EndsWith(".sln", StringComparison.Ordinal) || lower.EndsWith(".props", StringComparison.Ordinal)
               || lower.EndsWith(".targets", StringComparison.Ordinal) || lower.EndsWith("app.config", StringComparison.Ordinal)
               || (Path.GetFileName(lower).StartsWith("appsettings", StringComparison.Ordinal) && lower.EndsWith(".json", StringComparison.Ordinal))
               || CoverageReports.IsCandidate(path) || CiMaturityScanner.SystemOf(path) is not null;
    }

    private static ArtifactRef? WiredInput(StepContextEnvelope context, string artifactType) =>
        context.Inputs?.Values.FirstOrDefault(a => a.ArtifactType == artifactType);

    private static IReadOnlyList<string> Strings(JsonElement? config, string name) =>
        config is { ValueKind: JsonValueKind.Object } c && c.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.Array
            ? v.EnumerateArray().Where(e => e.ValueKind == JsonValueKind.String).Select(e => e.GetString()!).ToList()
            : [];

    private static async Task<T> ReadAsync<T>(string path, JsonSerializerOptions options) =>
        JsonSerializer.Deserialize<T>(await File.ReadAllTextAsync(path), options)
        ?? throw new InvalidOperationException($"{Path.GetFileName(path)} deserialized to null");

    private static readonly Lazy<ArtifactSchemaValidator> SchemaValidator = new(() =>
        ArtifactSchemaValidator.Load(Path.Combine(AppContext.BaseDirectory, "schemas", "test-coverage-1.0.0.schema.json")));

    public static async Task<string> WriteArtifactAsync(TestCoverageArtifact artifact, string outDir)
    {
        var json = DeterministicJson.Serialize(artifact);
        SchemaValidator.Value.Validate(json);
        Directory.CreateDirectory(outDir);
        var outputPath = Path.Combine(outDir, OutputFileName);
        await File.WriteAllTextAsync(outputPath, json, new UTF8Encoding(false));
        return outputPath;
    }
}

/// <summary>The application-fingerprint fields step 8 reads: each project's
/// signal names (Part B1).</summary>
public sealed record FingerprintWithSignals
{
    public required IReadOnlyList<FingerprintProjectSignals> Projects { get; init; }
}

public sealed record FingerprintProjectSignals
{
    public required string ProjectPath { get; init; }
    public IReadOnlyList<FingerprintSignalName> Signals { get; init; } = [];
}

public sealed record FingerprintSignalName
{
    public required string Name { get; init; }
}
