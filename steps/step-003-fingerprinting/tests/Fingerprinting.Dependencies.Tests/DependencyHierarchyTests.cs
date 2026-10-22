using Fingerprinting.Dependencies;
using Fingerprinting.Domain;
using Fingerprinting.Hierarchy;
using Fingerprinting.StepHost;
using NuGet.Packaging;
using NuGet.Packaging.Core;
using NuGet.Versioning;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>dependency-hierarchy — 37-DEPENDENCY-HIERARCHY.md. Offline: the client feed is a local folder in the
/// repository and nuget.org is a local folder standing in for it, both built here.</summary>
public sealed class DependencyHierarchyTests : IDisposable
{
    private static readonly Guid RepositoryId = Guid.Parse("22222222-3333-4444-5555-666666666666");
    private readonly string _root = Path.Combine(Path.GetTempPath(), "hierarchy-tests-" + Guid.NewGuid().ToString("N"));
    private readonly string _repo;
    private readonly string _clientFeed;
    private readonly string _publicFeed;
    private readonly List<HierarchyInputProject> _projects = [];
    private readonly List<InventoryReference> _references = [];

    public DependencyHierarchyTests()
    {
        _repo = Path.Combine(_root, "repo");
        _clientFeed = Path.Combine(_repo, "feeds", "internal");
        _publicFeed = Path.Combine(_root, "public");
        Directory.CreateDirectory(_clientFeed);
        Directory.CreateDirectory(_publicFeed);
        File.WriteAllText(Path.Combine(_repo, "NuGet.config"), """
            <?xml version="1.0" encoding="utf-8"?>
            <configuration>
              <packageSources>
                <clear />
                <add key="internal" value="feeds/internal" />
              </packageSources>
            </configuration>
            """);
    }

    public void Dispose()
    {
        try { Directory.Delete(_root, recursive: true); } catch (IOException) { }
    }

    // ---------- fixture builders ----------

    /// <summary>A package with a placeholder file and nuspec dependencies "Id@range", for net48 and net8.0.</summary>
    private void Package(string feed, string id, string version, params string[] dependencies)
    {
        var builder = new PackageBuilder { Id = id, Version = NuGetVersion.Parse(version), Description = id };
        builder.Authors.Add("tests");
        var file = Path.Combine(_root, "content", id, version, "readme.txt");
        Directory.CreateDirectory(Path.GetDirectoryName(file)!);
        File.WriteAllText(file, id);
        builder.Files.Add(new PhysicalPackageFile { SourcePath = file, TargetPath = "content/readme.txt" });
        foreach (var tfm in new[] { "net48", "net8.0" })
        {
            builder.DependencyGroups.Add(new PackageDependencyGroup(NuGet.Frameworks.NuGetFramework.Parse(tfm),
                dependencies.Select(d => d.Split('@')).Select(d => new PackageDependency(d[0], VersionRange.Parse(d[1])))));
        }

        using var output = File.Create(Path.Combine(feed, $"{id}.{version}.nupkg"));
        builder.Save(output);
    }

    /// <summary>A project file at src/<paramref name="name"/>, registered as the inventory would.</summary>
    private void Project(string name, string body = "", string sdk = "Microsoft.NET.Sdk", string framework = "net8.0", string? outputType = null,
        string[]? references = null, (string Id, string Version)[]? packages = null, bool packagesConfig = false)
    {
        var directory = Path.Combine(_repo, "src", name);
        Directory.CreateDirectory(directory);
        var legacy = sdk == "";
        var referenceItems = string.Join("\n", (references ?? []).Select(r => $"    <ProjectReference Include=\"..\\{r}\\{r}.csproj\" />"));
        var packageItems = packagesConfig ? "" : string.Join("\n", (packages ?? []).Select(p => $"    <PackageReference Include=\"{p.Id}\" Version=\"{p.Version}\" />"));
        File.WriteAllText(Path.Combine(directory, $"{name}.csproj"), $"""
            <Project{(legacy ? "" : $" Sdk=\"{sdk}\"")}>
              <PropertyGroup>{(legacy ? $"<TargetFrameworkVersion>v4.8</TargetFrameworkVersion>" : $"<TargetFramework>{framework}</TargetFramework>")}{(outputType is null ? "" : $"<OutputType>{outputType}</OutputType>")}</PropertyGroup>
              <ItemGroup>
            {referenceItems}
            {packageItems}
            {body}
              </ItemGroup>
            </Project>
            """);
        if (packagesConfig)
        {
            File.WriteAllText(Path.Combine(directory, "packages.config"),
                "<packages>\n" + string.Join("\n", (packages ?? []).Select(p => $"  <package id=\"{p.Id}\" version=\"{p.Version}\" targetFramework=\"net48\" />")) + "\n</packages>");
        }

        var path = $"src/{name}/{name}.csproj";
        _projects.Add(new HierarchyInputProject(path, Guid.NewGuid(), name, "csharp_project", "success", legacy ? "legacy_msbuild" : "sdk_style",
            outputType, legacy ? "none" : sdk, [legacy ? "v4.8" : framework], legacy ? "net48" : framework,
            packagesConfig ? "packages_config" : (packages ?? []).Length > 0 ? "packagereference" : "none",
            (packages ?? []).Select(p => new InventoryPackageRef(p.Id, p.Version, packagesConfig ? "packages_config" : "packagereference")).ToList()));
        foreach (var reference in references ?? [])
        {
            _references.Add(new InventoryReference(path, $"src/{reference}/{reference}.csproj", $@"..\{reference}\{reference}.csproj", "resolved"));
        }
    }

    private async Task<DependencyHierarchyArtifact> Run(HierarchyOptions? options = null, IReadOnlyDictionary<string, PackageProducer>? producers = null, bool workers = false)
    {
        var cache = new SynchronizedLookupCache(new MemoryLookupCache());
        PackageLookup NewLookup() => new(cache, Path.Combine(_root, "packages"), TimeSpan.FromHours(24), forceRefresh: false, DateTimeOffset.Parse("2026-10-22T00:00:00Z"));
        var pipeline = new HierarchyPipeline(NewLookup(), options ?? new HierarchyOptions(ComparePublicFeed: true, PublicFeedSource: _publicFeed),
            workers ? new LookupWorkers([NewLookup(), NewLookup(), NewLookup()]) : null);
        return await pipeline.RunAsync(new HierarchyInput(RepositoryId, "fixture", _projects, _references, null,
            producers ?? new Dictionary<string, PackageProducer>()), _repo, CancellationToken.None);
    }

    private static HierarchyNode Node(DependencyHierarchyArtifact artifact, string id) => Assert.Single(artifact.Nodes, n => n.Id == id);

    private static IEnumerable<HierarchyEdge> From(DependencyHierarchyArtifact artifact, string id) => artifact.Edges.Where(e => e.From == id);

    // ---------- a graph, not a tree ----------

    [Fact]
    public async Task A_shared_library_with_several_parents_is_one_node_and_each_edge_is_recorded_once()
    {
        Project("Shared");
        Project("Domain", references: ["Shared"]);
        Project("Web", outputType: "Exe", references: ["Domain", "Shared"]);
        Project("Worker", outputType: "Exe", references: ["Domain", "Shared"]);

        var artifact = await Run();

        Assert.Single(artifact.Nodes, n => n.Id == "project:src/Shared/Shared.csproj");
        Assert.Equal(3, artifact.Edges.Count(e => e.To == "project:src/Shared/Shared.csproj"));
        Assert.Equal(artifact.Edges.Count, artifact.Edges.Select(e => (e.From, e.To, e.Kind)).Distinct().Count());
        Assert.Equal(["project:src/Web/Web.csproj", "project:src/Worker/Worker.csproj"], artifact.Roots);
        Assert.Equal(2, artifact.Summary.Depth);                                    // Web → Domain → Shared
        Assert.All(From(artifact, "project:src/Web/Web.csproj"), e =>
        {
            Assert.Equal(EdgeKinds.ProjectReference, e.Kind);
            Assert.Equal("src/Web/Web.csproj", e.DeclaredAt!.FilePath);
            Assert.NotNull(e.DeclaredAt.Line);
        });
    }

    [Fact]
    public async Task A_package_two_projects_use_at_the_same_version_is_one_node()
    {
        Package(_clientFeed, "Acme.Common", "1.0.0");
        Project("A", packages: [("Acme.Common", "1.0.0")]);
        Project("B", packages: [("Acme.Common", "1.0.0")]);

        var artifact = await Run();

        Assert.Single(artifact.Nodes, n => n.Type == NodeTypes.Package);
        Assert.Equal(2, artifact.Edges.Count(e => e.To == "package:acme.common@1.0.0" && e.Kind == EdgeKinds.PackageReference));
    }

    // ---------- packages ----------

    [Fact]
    public async Task Packages_config_is_read_and_a_package_s_dependencies_come_from_the_feed_at_the_lowest_version_the_range_allows()
    {
        Package(_clientFeed, "Acme.Logging", "2.0.0");
        Package(_clientFeed, "Acme.Logging", "2.1.0");
        Package(_clientFeed, "Acme.Data", "1.0.0", "Acme.Logging@[2.0.0, )");
        Project("Legacy", sdk: "", packages: [("Acme.Data", "1.0.0")], packagesConfig: true);

        var artifact = await Run();

        var declared = Assert.Single(From(artifact, "project:src/Legacy/Legacy.csproj"));
        Assert.Equal((EdgeKinds.PackagesConfig, "package:acme.data@1.0.0"), (declared.Kind, declared.To));
        var dependency = Assert.Single(From(artifact, "package:acme.data@1.0.0"));
        Assert.Equal((EdgeKinds.PackageDependency, "package:acme.logging@2.0.0", Resolutions.FeedMetadata, "[2.0.0, )"),
            (dependency.Kind, dependency.To, dependency.Resolution, dependency.VersionRequested));
        Assert.Equal(["net48"], dependency.Frameworks);
        Assert.True(Node(artifact, "package:acme.logging@2.0.0").Package!.Transitive);
        Assert.False(Node(artifact, "package:acme.data@1.0.0").Package!.Transitive);
        Assert.Equal(Resolutions.FeedMetadata, Node(artifact, "package:acme.data@1.0.0").Package!.DependenciesResolution);
    }

    [Fact]
    public async Task A_restored_assets_file_gives_the_versions_restore_chose()
    {
        Package(_clientFeed, "Acme.Logging", "2.0.0");
        Package(_clientFeed, "Acme.Logging", "2.5.0");
        Package(_clientFeed, "Acme.Data", "1.0.0", "Acme.Logging@[2.0.0, )");
        Project("App", packages: [("Acme.Data", "1.0.0")]);
        var obj = Path.Combine(_repo, "src", "App", "obj");
        Directory.CreateDirectory(obj);
        File.WriteAllText(Path.Combine(obj, "project.assets.json"), """
            { "version": 3, "targets": { "net8.0": {
                "Acme.Data/1.0.0": { "type": "package", "dependencies": { "Acme.Logging": "2.0.0" } },
                "Acme.Logging/2.5.0": { "type": "package" } } } }
            """);

        var artifact = await Run();

        var dependency = Assert.Single(From(artifact, "package:acme.data@1.0.0"));
        Assert.Equal(("package:acme.logging@2.5.0", Resolutions.AssetsFile), (dependency.To, dependency.Resolution));
    }

    [Fact]
    public async Task A_package_only_a_client_feed_has_is_internal_and_one_nuget_org_has_too_is_external()
    {
        Package(_clientFeed, "Acme.Common", "1.0.0");
        Package(_clientFeed, "Newtonsoft.Json", "13.0.3");
        Package(_publicFeed, "Newtonsoft.Json", "13.0.3");
        Project("App", packages: [("Acme.Common", "1.0.0"), ("Newtonsoft.Json", "13.0.3")]);

        var artifact = await Run(workers: true);

        var common = Node(artifact, "package:acme.common@1.0.0").Package!;
        Assert.Equal(PackageOrigins.Internal, common.Origin);
        Assert.Equal("on client feed 'internal', not on nuget.org", common.OriginBasis);
        var json = Node(artifact, "package:newtonsoft.json@13.0.3").Package!;
        Assert.Equal(PackageOrigins.External, json.Origin);
        Assert.Equal((1, 1), (artifact.Summary.InternalPackageCount, artifact.Summary.ExternalPackageCount));
    }

    [Fact]
    public async Task An_internal_package_names_the_repository_that_produces_it_where_estate_consolidation_knows_it()
    {
        Package(_clientFeed, "Acme.Common", "1.0.0");
        Project("App", packages: [("Acme.Common", "1.0.0")]);
        var producer = new PackageProducer { RepositoryId = Guid.NewGuid(), RepositoryName = "acme-common", ProjectPath = "src/Acme.Common/Acme.Common.csproj" };

        var artifact = await Run(producers: new Dictionary<string, PackageProducer> { ["acme.common"] = producer });

        var package = Node(artifact, "package:acme.common@1.0.0").Package!;
        Assert.Equal(PackageOrigins.Internal, package.Origin);
        Assert.Equal(producer, package.Producer);
    }

    [Fact]
    public async Task A_package_no_feed_answers_for_is_not_checked_with_the_reason()
    {
        Project("App", packages: [("Missing.Package", "1.0.0")]);

        var artifact = await Run();

        var node = Node(artifact, "package:missing.package@1.0.0");
        Assert.Equal(NodeStatuses.NotChecked, node.Status);
        Assert.Contains("feed 'internal' lists no version of it", node.NotCheckedReason);
        Assert.Equal(PackageOrigins.Unknown, node.Package!.Origin);
    }

    // ---------- assembly references ----------

    [Fact]
    public async Task Assembly_references_are_dependencies_whether_in_the_repository_the_gac_or_the_framework()
    {
        Directory.CreateDirectory(Path.Combine(_repo, "lib"));
        File.WriteAllText(Path.Combine(_repo, "lib", "Vendor.Charts.dll"), "");
        Project("Legacy", sdk: "", packages: [("Acme.Data", "1.0.0")], packagesConfig: true, body: """
                <Reference Include="System.Web" />
                <Reference Include="Vendor.Licensing, Version=3.1.0.0, Culture=neutral, PublicKeyToken=abc" />
                <Reference Include="Vendor.Charts"><HintPath>..\..\lib\Vendor.Charts.dll</HintPath></Reference>
                <Reference Include="Vendor.Gone"><HintPath>..\..\lib\Vendor.Gone.dll</HintPath></Reference>
                <Reference Include="Acme.Data"><HintPath>..\..\packages\Acme.Data.1.0.0\lib\net48\Acme.Data.dll</HintPath></Reference>
            """);
        Package(_clientFeed, "Acme.Data", "1.0.0");

        var artifact = await Run();

        var assemblies = artifact.Nodes.Where(n => n.Type == NodeTypes.Assembly).ToDictionary(n => n.Name, n => n);
        Assert.Equal(["System.Web", "Vendor.Charts", "Vendor.Gone", "Vendor.Licensing"], assemblies.Keys.Order());   // Acme.Data is the package's
        Assert.Equal(AssemblyLocations.Framework, assemblies["System.Web"].Assembly!.Location);
        Assert.Equal((AssemblyLocations.Gac, "3.1.0.0"), (assemblies["Vendor.Licensing"].Assembly!.Location, assemblies["Vendor.Licensing"].Assembly!.Version));
        Assert.Equal((AssemblyLocations.Repository, "lib/Vendor.Charts.dll", true),
            (assemblies["Vendor.Charts"].Assembly!.Location, assemblies["Vendor.Charts"].Assembly!.Path, assemblies["Vendor.Charts"].Assembly!.Exists));
        Assert.Equal(NodeStatuses.NotChecked, assemblies["Vendor.Gone"].Status);
        Assert.All(From(artifact, "project:src/Legacy/Legacy.csproj").Where(e => e.Kind == EdgeKinds.AssemblyReference), e => Assert.NotNull(e.DeclaredAt!.Line));
    }

    // ---------- guards ----------

    [Fact]
    public async Task A_cycle_is_recorded_once_and_not_followed()
    {
        Package(_clientFeed, "Acme.A", "1.0.0", "Acme.B@[1.0.0, )");
        Package(_clientFeed, "Acme.B", "1.0.0", "Acme.A@[1.0.0, )");
        Project("App", packages: [("Acme.A", "1.0.0")]);

        var artifact = await Run();

        var cycle = Assert.Single(artifact.Cycles);
        Assert.Equal(["package:acme.a@1.0.0", "package:acme.b@1.0.0"], cycle);
        var closing = Assert.Single(artifact.Edges, e => e.ClosesCycle);
        Assert.Equal(("package:acme.b@1.0.0", "package:acme.a@1.0.0"), (closing.From, closing.To));
    }

    [Fact]
    public async Task Dependencies_deeper_than_the_limit_are_not_followed_and_say_so()
    {
        Package(_clientFeed, "Chain.4", "1.0.0");
        Package(_clientFeed, "Chain.3", "1.0.0", "Chain.4@[1.0.0, )");
        Package(_clientFeed, "Chain.2", "1.0.0", "Chain.3@[1.0.0, )");
        Package(_clientFeed, "Chain.1", "1.0.0", "Chain.2@[1.0.0, )");
        Project("App", packages: [("Chain.1", "1.0.0")]);

        var artifact = await Run(new HierarchyOptions(ComparePublicFeed: true, MaxPackageDepth: 2, PublicFeedSource: _publicFeed));

        Assert.DoesNotContain(artifact.Nodes, n => n.Id == "package:chain.4@1.0.0");
        Assert.Contains("deeper than 2 levels", Node(artifact, "package:chain.3@1.0.0").Package!.DependenciesNotCheckedReason);
    }

    [Fact]
    public async Task A_project_reference_to_a_file_that_is_not_there_is_a_node_not_checked()
    {
        Project("App");
        _references.Add(new InventoryReference("src/App/App.csproj", null, @"..\Gone\Gone.csproj", "unresolved"));

        var artifact = await Run();

        var node = Node(artifact, "project:src/Gone/Gone.csproj");
        Assert.Equal((NodeStatuses.NotChecked, "the referenced project file was not found in the repository"), (node.Status, node.NotCheckedReason));
        Assert.DoesNotContain(node.Id, artifact.Roots);
    }

    // ---------- what kind of project ----------

    [Fact]
    public async Task Projects_are_applications_libraries_tests_or_other_each_with_its_reason()
    {
        Project("Api", sdk: "Microsoft.NET.Sdk.Web");
        Project("Lib");
        Project("Lib.Tests", outputType: "Exe", packages: [("Microsoft.NET.Test.Sdk", "17.12.0")]);
        Project("OldWeb", sdk: "", body: "</ItemGroup><PropertyGroup><ProjectTypeGuids>{349c5851-65df-11da-9384-00065b846f21};{fae04ec0-301f-11d3-bf4b-00c04f79efbc}</ProjectTypeGuids></PropertyGroup><ItemGroup>");

        var artifact = await Run(new HierarchyOptions(ComparePublicFeed: false, PublicFeedSource: _publicFeed));

        string Kind(string name) => Node(artifact, $"project:src/{name}/{name}.csproj").Project!.Kind + " | " + Node(artifact, $"project:src/{name}/{name}.csproj").Project!.KindBasis;
        Assert.Equal("application | SDK Microsoft.NET.Sdk.Web", Kind("Api"));
        Assert.Equal("library | OutputType Library", Kind("Lib"));
        Assert.Equal("test | test package Microsoft.NET.Test.Sdk", Kind("Lib.Tests"));
        Assert.Equal("application | the legacy ASP.NET web application project type", Kind("OldWeb"));
    }

    // ---------- the artifact ----------

    [Fact]
    public async Task The_artifact_is_schema_valid_and_two_runs_write_the_same_bytes()
    {
        Package(_clientFeed, "Acme.Logging", "2.0.0");
        Package(_clientFeed, "Acme.Data", "1.0.0", "Acme.Logging@[2.0.0, )");
        Project("Shared", packages: [("Acme.Data", "1.0.0")]);
        Project("Web", outputType: "Exe", references: ["Shared"], packages: [("Acme.Logging", "2.0.0")]);

        var first = DeterministicJson.Serialize(await Run(workers: true));
        var second = DeterministicJson.Serialize(await Run());

        Assert.Equal(first, second);
        ArtifactSchemaValidator.Load(Path.Combine(AppContext.BaseDirectory, "schemas", "dependency-hierarchy-1.0.0.schema.json")).Validate(first);
    }
}
