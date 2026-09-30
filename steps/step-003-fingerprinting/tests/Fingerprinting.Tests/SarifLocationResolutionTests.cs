using System.Runtime.CompilerServices;
using Fingerprinting.Cli;
using Fingerprinting.Domain;
using Fingerprinting.Extractors;
using Fingerprinting.StepHost;
using Xunit;
using Xunit.Abstractions;

namespace Fingerprinting.Tests;

/// <summary>
/// Mechanical proof of 25-STANDARDS-AND-VIEWPOINTS.md Part A3's addendum:
/// a SARIF <c>physicalLocation</c> must resolve to a FILE on disk — never a
/// directory, never a missing path. A folder-presence signal (e.g.
/// SERVICES_FOLDER) must never produce one at all.
/// </summary>
public sealed class SarifLocationResolutionTests
{
    private readonly ITestOutputHelper _output;

    public SarifLocationResolutionTests(ITestOutputHelper output)
    {
        _output = output;
    }

    [Fact]
    public async Task FolderEvidenceSignal_NeverGetsAPhysicalLocation()
    {
        using var fixture = new TempProjectFixture();
        Directory.CreateDirectory(Path.Combine(fixture.ProjectDirectory, "Controllers"));
        await File.WriteAllTextAsync(
            Path.Combine(fixture.ProjectDirectory, "Global.asax"),
            """<%@ Application Inherits="WebApplication.Global" %>""");

        var registry = SignalRegistry.LoadLatest(SchemasDir());
        var pipeline = new FingerprintPipeline(registry, [new FileIndicatorExtractor()]);
        var inventory = new SolutionProjectInventory
        {
            RepositoryId = Guid.NewGuid(),
            RepositorySlug = "folder-evidence-test",
            Projects = [new InventoryProject { RelativePath = "Test.csproj", ParseStatus = "success", StructuralType = "csharp_project" }],
        };

        var artifact = await pipeline.RunAsync(inventory, fixture.RepositoryRoot, _ => Guid.NewGuid(), CancellationToken.None);
        var sarif = SarifBuilder.Build(artifact, registry);

        var results = sarif.Runs.SelectMany(r => r.Results).ToList();
        var folderResult = Assert.Single(results, r => r.RuleId == "CONTROLLERS_FOLDER");
        var fileResult = Assert.Single(results, r => r.RuleId == "GLOBAL_ASAX_FILE");

        Assert.Null(folderResult.Locations);
        Assert.Equal("Controllers", folderResult.Properties?["folderPath"]);

        Assert.NotNull(fileResult.Locations);
        Assert.NotEmpty(fileResult.Locations!);

        AssertAllLocationsResolveToRealFiles(sarif, fixture.RepositoryRoot);
    }

    [Fact]
    public async Task PathWithASpace_IsPercentEncoded_AndStillResolves()
    {
        using var fixture = new TempProjectFixture();
        var generated = Path.Combine(fixture.ProjectDirectory, "Connected Services", "Ledger");
        Directory.CreateDirectory(generated);
        await File.WriteAllTextAsync(Path.Combine(generated, "Program.cs"), "class P { }");

        var registry = SignalRegistry.LoadLatest(SchemasDir());
        var pipeline = new FingerprintPipeline(registry, [new FileIndicatorExtractor()]);
        var inventory = new SolutionProjectInventory
        {
            RepositoryId = Guid.NewGuid(),
            RepositorySlug = "spaced-path-test",
            Projects = [new InventoryProject { RelativePath = "Test.csproj", ParseStatus = "success", StructuralType = "csharp_project" }],
        };

        var artifact = await pipeline.RunAsync(inventory, fixture.RepositoryRoot, _ => Guid.NewGuid(), CancellationToken.None);
        var sarif = SarifBuilder.Build(artifact, registry);

        var uri = sarif.Runs.SelectMany(r => r.Results).Single(r => r.RuleId == "PROGRAM_CS_FILE")
            .Locations!.Single().PhysicalLocation.ArtifactLocation.Uri;
        Assert.Equal("Connected%20Services/Ledger/Program.cs", uri);
        AssertAllLocationsResolveToRealFiles(sarif, fixture.RepositoryRoot);
    }

    /// <summary>Runs the real pipeline (all six extractors) against the
    /// eShopOnWeb sample application on this machine and asserts every
    /// physicalLocation in the resulting SARIF resolves to a real file.
    /// Skips (does not fail) when the sample app is not checked out at the
    /// conventional sibling location — see <see cref="FindEShopOnWebRepoRoot"/>
    /// — since it is not part of this git repository and every CI or
    /// contributor machine will not have it.</summary>
    [Fact]
    public async Task EShopOnWeb_EveryPhysicalLocationResolvesToARealFile()
    {
        var repoRoot = FindEShopOnWebRepoRoot();
        if (repoRoot is null)
        {
            _output.WriteLine(
                "Skipped: eShopOnWeb sample app not found. Set ESHOPONWEB_SAMPLE_REPO or check it out at " +
                "<repo-root>/../sampleapps/eShopOnWeb (the convention this platform's own registered sample " +
                "repositories use).");
            return;
        }

        var inventoryPath = Path.Combine(FingerprintingTestsDir(), "..", "..", "tests", "fixtures", "sample-input", "solution-project-inventory.json");
        var inventoryJson = await File.ReadAllTextAsync(Path.GetFullPath(inventoryPath));
        var inventory = System.Text.Json.JsonSerializer.Deserialize<SolutionProjectInventory>(inventoryJson, EnvelopeJson.Options)
            ?? throw new InvalidOperationException("inventory deserialized to null");

        var registry = SignalRegistry.LoadLatest(SchemasDir());
        var pipeline = new FingerprintPipeline(registry, [
            new FileIndicatorExtractor(),
            new FrameworkReferenceExtractor(),
            new AttributeExtractor(),
            new InheritanceExtractor(),
            new EntryPointExtractor(),
            new ConfigurationExtractor(),
        ]);

        var artifact = await pipeline.RunAsync(inventory, repoRoot, _ => Guid.NewGuid(), CancellationToken.None);
        var sarif = SarifBuilder.Build(artifact, registry);

        // Report per Part A3's ask: how many signals point at a file, a
        // folder, or carry no navigable source path at all — independent of
        // the SARIF projection, straight off the native artifact.
        var allSignals = artifact.Projects.SelectMany(p => p.Signals).ToList();
        var byKind = allSignals.GroupBy(s => s.EvidenceKind).ToDictionary(g => g.Key ?? "NULL", g => g.Count());
        var fileCount = byKind.GetValueOrDefault(SignalEvidenceKinds.File);
        var folderCount = byKind.GetValueOrDefault(SignalEvidenceKinds.Folder);
        var noneCount = byKind.GetValueOrDefault(SignalEvidenceKinds.None);
        _output.WriteLine($"eShopOnWeb signals by evidence kind: FILE={fileCount}, FOLDER={folderCount}, NONE={noneCount}, total={allSignals.Count}");

        var resultCount = sarif.Runs.Sum(r => r.Results.Count);
        var withLocations = sarif.Runs.SelectMany(r => r.Results).Count(r => r.Locations is { Count: > 0 });
        _output.WriteLine($"SARIF results: {resultCount} total, {withLocations} with a physicalLocation, {resultCount - withLocations} without.");

        // Every FILE-kind signal's sourcePath must genuinely be a file, and
        // every FOLDER-kind signal's sourcePath must genuinely be a folder —
        // the registry's evidence_kind audit checked against ground truth,
        // not just an assumption about what each extractor is supposed to do.
        foreach (var signal in allSignals.Where(s => s.SourcePath is not null))
        {
            var resolved = Path.Combine(repoRoot, signal.SourcePath!.Replace('/', Path.DirectorySeparatorChar));
            switch (signal.EvidenceKind)
            {
                case SignalEvidenceKinds.File:
                    Assert.True(File.Exists(resolved), $"{signal.Name}: sourcePath '{signal.SourcePath}' is registered evidence_kind FILE but no such file exists.");
                    break;
                case SignalEvidenceKinds.Folder:
                    Assert.True(Directory.Exists(resolved), $"{signal.Name}: sourcePath '{signal.SourcePath}' is registered evidence_kind FOLDER but no such directory exists.");
                    break;
            }
        }

        AssertAllLocationsResolveToRealFiles(sarif, repoRoot);
    }

    /// <summary>The one assertion Part A3 asked for: every physicalLocation
    /// resolves to a FILE on disk, never a directory, never a missing
    /// path.</summary>
    private static void AssertAllLocationsResolveToRealFiles(SarifLog sarif, string repoRoot)
    {
        foreach (var run in sarif.Runs)
        {
            foreach (var result in run.Results)
            {
                foreach (var location in result.Locations ?? [])
                {
                    var artifactLocation = location.PhysicalLocation.ArtifactLocation;
                    Assert.Equal("REPOROOT", artifactLocation.UriBaseId);
                    Assert.NotNull(artifactLocation.Uri);

                    // Decode as a viewer would: the URI is percent-encoded per segment.
                    var relative = Uri.UnescapeDataString(artifactLocation.Uri!);
                    var resolved = Path.Combine(repoRoot, relative.Replace('/', Path.DirectorySeparatorChar));
                    Assert.True(File.Exists(resolved), $"{result.RuleId}: location '{artifactLocation.Uri}' does not resolve to a file.");
                    Assert.False(Directory.Exists(resolved) && !File.Exists(resolved), $"{result.RuleId}: location '{artifactLocation.Uri}' resolves to a directory, not a file.");
                }
            }
        }
    }

    /// <summary>Sibling-directory convention this platform's own registered
    /// sample repositories use: <c>sampleapps/&lt;name&gt;</c> next to the
    /// <c>code/</c> git repository, not inside it (eShopOnWeb is a real
    /// third-party application, not something this repo vendors). Override
    /// with the ESHOPONWEB_SAMPLE_REPO environment variable if checked out
    /// elsewhere.</summary>
    private static string? FindEShopOnWebRepoRoot()
    {
        var overridePath = Environment.GetEnvironmentVariable("ESHOPONWEB_SAMPLE_REPO");
        if (!string.IsNullOrEmpty(overridePath) && Directory.Exists(overridePath))
        {
            return overridePath;
        }

        var dir = new DirectoryInfo(FingerprintingTestsDir());
        while (dir is not null && !Directory.Exists(Path.Combine(dir.FullName, ".git")))
        {
            dir = dir.Parent;
        }

        if (dir is null)
        {
            return null;
        }

        var candidate = Path.Combine(dir.Parent?.FullName ?? "", "sampleapps", "eShopOnWeb");
        return Directory.Exists(candidate) ? candidate : null;
    }

    private static string SchemasDir() => Path.Combine(AppContext.BaseDirectory, "schemas");

    private static string FingerprintingTestsDir([CallerFilePath] string sourceFile = "") =>
        Path.GetDirectoryName(sourceFile)!;

    private sealed class TempProjectFixture : IDisposable
    {
        public string RepositoryRoot { get; }
        public string ProjectDirectory { get; }

        public TempProjectFixture()
        {
            RepositoryRoot = Directory.CreateTempSubdirectory("fingerprinting-sarif-location-test-").FullName;
            ProjectDirectory = RepositoryRoot;
        }

        public void Dispose()
        {
            try
            {
                Directory.Delete(RepositoryRoot, recursive: true);
            }
            catch (IOException)
            {
                // Best-effort cleanup; a lingering temp dir is not a test failure.
            }
        }
    }
}
