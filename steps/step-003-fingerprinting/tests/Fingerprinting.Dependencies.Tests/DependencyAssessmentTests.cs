using Fingerprinting.Dependencies;
using Fingerprinting.Domain;
using Fingerprinting.StepHost;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using NuGet.Packaging;
using NuGet.Packaging.Core;
using NuGet.Versioning;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>Step 6, dependency-assessment — 30-DEPENDENCY-ASSESSMENT.md.
/// Offline: feeds are local folders of packages built here, their assemblies
/// compiled with Roslyn, so the API diff runs against real metadata.</summary>
public sealed class DependencyAssessmentTests : IDisposable
{
    private static readonly Guid RepositoryId = Guid.Parse("11111111-2222-3333-4444-555555555555");
    private readonly string _root = Path.Combine(Path.GetTempPath(), "dep-tests-" + Guid.NewGuid().ToString("N"));
    private readonly string _repo;
    private readonly string _clientFeed;
    private readonly string _publicFeed;

    public DependencyAssessmentTests()
    {
        _repo = Path.Combine(_root, "repo");
        _clientFeed = Path.Combine(_repo, "feeds", "artifactory");
        _publicFeed = Path.Combine(_root, "public");
        Directory.CreateDirectory(_clientFeed);
        Directory.CreateDirectory(_publicFeed);
    }

    public void Dispose()
    {
        try { Directory.Delete(_root, recursive: true); } catch (IOException) { }
    }

    // ---------- fixture builders ----------

    private static byte[] Compile(string assemblyName, string code)
    {
        var references = ((string)AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES")!).Split(Path.PathSeparator)
            .Where(p => Path.GetFileName(p) is "System.Runtime.dll" or "System.Private.CoreLib.dll" or "netstandard.dll")
            .Select(p => MetadataReference.CreateFromFile(p));
        var compilation = CSharpCompilation.Create(assemblyName, [CSharpSyntaxTree.ParseText(code)], references,
            new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));
        using var stream = new MemoryStream();
        var result = compilation.Emit(stream);
        Assert.True(result.Success, string.Join("\n", result.Diagnostics));
        return stream.ToArray();
    }

    /// <summary>A nuspec dependency group for <paramref name="tfm"/>: "Id@[1.0.0, )" each.</summary>
    private static void Depend(PackageBuilder builder, string tfm, string[] dependencies)
    {
        if (dependencies.Length == 0) return;
        builder.DependencyGroups.Add(new PackageDependencyGroup(NuGet.Frameworks.NuGetFramework.Parse(tfm),
            dependencies.Select(d => d.Split('@')).Select(d => new PackageDependency(d[0], VersionRange.Parse(d[1])))));
    }

    /// <summary>A package with one assembly under lib/{tfm}/, and any nuspec dependencies ("Id@range").</summary>
    private void Package(string feed, string id, string version, string tfm, string code, params string[] dependencies)
    {
        var dll = Path.Combine(_root, "build", id, version, tfm, id + ".dll");
        Directory.CreateDirectory(Path.GetDirectoryName(dll)!);
        File.WriteAllBytes(dll, Compile(id, code));
        var builder = new PackageBuilder
        {
            Id = id,
            Version = NuGetVersion.Parse(version),
            Description = id,
        };
        builder.Authors.Add("tests");
        builder.Files.Add(new PhysicalPackageFile { SourcePath = dll, TargetPath = $"lib/{tfm}/{id}.dll" });
        Depend(builder, tfm, dependencies);
        using var output = File.Create(Path.Combine(feed, $"{id}.{version}.nupkg"));
        builder.Save(output);
    }

    /// <summary>A package with no lib/ assembly: only the given files
    /// (build/x.props, tools/x.exe, content/x.css, analyzers/...), so its kind
    /// comes from its contents.</summary>
    private void AssetPackage(string feed, string id, string version, params string[] targetPaths) =>
        MetaPackage(feed, id, version, targetPaths, []);

    /// <summary>A package with only the given files and nuspec dependencies
    /// ("Id@range", net8.0 group): a meta-package when the files are build/ props.</summary>
    private void MetaPackage(string feed, string id, string version, string[] targetPaths, string[] dependencies)
    {
        var builder = new PackageBuilder { Id = id, Version = NuGetVersion.Parse(version), Description = id };
        Depend(builder, "net8.0", dependencies);
        builder.Authors.Add("tests");
        foreach (var target in targetPaths)
        {
            var source = Path.Combine(_root, "assets", id, version, target.Replace('/', Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(source)!);
            File.WriteAllText(source, target);
            builder.Files.Add(new PhysicalPackageFile { SourcePath = source, TargetPath = target });
        }

        using var output = File.Create(Path.Combine(feed, $"{id}.{version}.nupkg"));
        builder.Save(output);
    }

    private void Project(string packageReferences, string code) => ProjectAt("App", packageReferences, code);

    private void ProjectAt(string name, string packageReferences, string code, string sdk = "Microsoft.NET.Sdk")
    {
        var directory = Path.Combine(_repo, "src", name);
        Directory.CreateDirectory(directory);
        File.WriteAllText(Path.Combine(directory, $"{name}.csproj"), $"""
            <Project Sdk="{sdk}">
              <PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>
              <ItemGroup>
            {packageReferences}
              </ItemGroup>
            </Project>
            """);
        File.WriteAllText(Path.Combine(directory, "Program.cs"), code);
    }

    private void ClientFeedConfig(string extraSources = "") => File.WriteAllText(Path.Combine(_repo, "NuGet.config"), $"""
        <?xml version="1.0" encoding="utf-8"?>
        <configuration>
          <packageSources>
            <clear />
            <add key="artifactory" value="feeds/artifactory" />
            {extraSources}
          </packageSources>
        </configuration>
        """);

    private Task<DependencyAssessmentArtifact> Run(IReadOnlyList<InputPackage> packages, ILookupCache? cache = null, string? currentFramework = "net8.0") =>
        RunProjects([("src/App/App.csproj", packages)], cache, currentFramework);

    private static readonly SharedFrameworks Shared =
        SharedFrameworks.Load(Path.Combine(AppContext.BaseDirectory, "schemas", "shared-frameworks-1.0.0.json"));

    private async Task<DependencyAssessmentArtifact> RunProjects(IReadOnlyList<(string Path, IReadOnlyList<InputPackage> Packages)> projects, ILookupCache? cache = null, string? currentFramework = "net8.0",
        string? projectSdk = null)
    {
        var lookup = new PackageLookup(cache ?? new MemoryLookupCache(), Path.Combine(_root, "packages"), TimeSpan.FromHours(24), forceRefresh: false,
            DateTimeOffset.Parse("2026-10-02T00:00:00Z"));
        var pipeline = new DependencyPipeline(lookup, new DependencyOptions("net10.0", ComparePublicFeed: true, PublicFeedSource: _publicFeed, SharedFrameworks: Shared));
        var input = new DependencyInput(RepositoryId, "fixture", "application-fingerprint",
            projects.Select(p => new DependencyInputProject(p.Path, Guid.Empty, null, currentFramework, p.Packages, projectSdk)).ToList(), []);
        return await pipeline.RunAsync(input, _repo, CancellationToken.None);
    }

    private static PackageAssessment Package(DependencyAssessmentArtifact artifact, string id) =>
        Assert.Single(artifact.Projects.Single().Packages, p => p.PackageId == id);

    private const string JsonV1 = "namespace Acme.Json { public static class Serializer { public static string Parse(string s) => s; public static string Write(object o) => \"\"; } }";
    private const string JsonV11 = "namespace Acme.Json { public static class Serializer { public static string Write(object o) => \"\"; public static string Read(string s) => s; } }";
    private const string JsonV12 = "namespace Acme.Json { public static class Serializer { public static string Write(object o) => \"\"; public static string Read(string s) => s; public static int V => 12; } }";

    // ---------- feeds (Part B2, B3) ----------

    [Fact]
    public async Task Client_feeds_answer_clear_is_honoured_and_a_public_only_version_is_not_in_client_feed()
    {
        ClientFeedConfig();
        Package(_clientFeed, "Acme.Json", "1.0.0", "net8.0", JsonV1);
        Package(_clientFeed, "Acme.Json", "1.1.0", "net8.0", JsonV11);
        Package(_publicFeed, "Acme.Json", "1.0.0", "net8.0", JsonV1);
        Package(_publicFeed, "Acme.Json", "1.1.0", "net8.0", JsonV11);
        Package(_publicFeed, "Acme.Json", "1.2.0", "net8.0", JsonV12);
        Project("""    <PackageReference Include="Acme.Json" Version="1.0.0" />""",
            "using Acme.Json; class P { static void Main() { var x = Serializer.Parse(\"{}\"); } }");

        var artifact = await Run([new InputPackage("Acme.Json", "1.0.0", "packagereference")]);
        var json = Package(artifact, "Acme.Json");

        // The client feed is the authority: 1.1.0, never the public 1.2.0.
        Assert.Equal((FeedSources.ClientFeed, "artifactory", "1.1.0"), (json.FeedSource, json.FeedName, json.RecommendedVersion));
        Assert.Equal("repo:feeds/artifactory", json.FeedUrl);
        Assert.Equal(("1.2.0", "1.1.0"), (json.NotInClientFeed!.LatestPublicVersion, json.NotInClientFeed.LatestInClientFeed));

        // <clear/> removed the user-level nuget.org and the machine's tooling folder.
        var feeds = artifact.Projects.Single().Feeds;
        Assert.Equal(["artifactory"], feeds.Where(f => f.Role == "client_feed").Select(f => f.Name));
        Assert.DoesNotContain(feeds, f => f.Role == "nuget_org");
    }

    [Fact]
    public async Task With_no_client_feed_nuget_org_is_the_fallback()
    {
        // No NuGet.config in the repository: the user's nuget.org (or the
        // default) answers; the machine's local tooling folder is ignored.
        Package(_publicFeed, "Acme.Json", "1.0.0", "net8.0", JsonV1);
        Project("""    <PackageReference Include="Acme.Json" Version="1.0.0" />""", "class P { }");

        var json = Package(await Run([new InputPackage("Acme.Json", "1.0.0", "packagereference")]), "Acme.Json");
        Assert.Equal((FeedSources.NuGetOrgFallback, "nuget.org", Outcomes.Current), (json.FeedSource, json.FeedName, json.Outcome));
        Assert.Null(json.NotInClientFeed);
    }

    [Fact]
    public async Task With_no_nuget_config_in_the_repository_a_parent_folders_feed_is_the_client_feed()
    {
        // 1.6.0: the repository has no NuGet.config; the folder above it does, as dotnet restore finds it.
        var parentFeed = Path.Combine(_root, "parentfeed");
        Directory.CreateDirectory(parentFeed);
        File.WriteAllText(Path.Combine(_root, "NuGet.config"), """
            <?xml version="1.0" encoding="utf-8"?>
            <configuration>
              <packageSources>
                <add key="team-feed" value="parentfeed" />
              </packageSources>
            </configuration>
            """);
        Package(parentFeed, "Acme.Json", "1.0.0", "net8.0", JsonV1);
        Package(parentFeed, "Acme.Json", "1.1.0", "net8.0", JsonV11);
        Package(_publicFeed, "Acme.Json", "1.2.0", "net8.0", JsonV12);
        Project("""    <PackageReference Include="Acme.Json" Version="1.0.0" />""", "class P { }");

        var artifact = await Run([new InputPackage("Acme.Json", "1.0.0", "packagereference")]);
        var json = Package(artifact, "Acme.Json");
        Assert.Equal((FeedSources.ClientFeed, "team-feed", "1.1.0"), (json.FeedSource, json.FeedName, json.RecommendedVersion));
        var feed = Assert.Single(artifact.Projects.Single().Feeds, f => f.Name == "team-feed");
        Assert.Equal(("client_feed", "parent"), (feed.Role, feed.DeclaredIn));
        Assert.StartsWith("file:", feed.Url);
    }

    [Theory]
    [InlineData(@"C:\work\repo\NuGet.config", "repository")]
    [InlineData(@"C:\work\repo\src\App\nuget.config", "repository")]
    [InlineData(@"C:\work\NuGet.config", "parent")]
    [InlineData(@"C:\NuGet.Config", "parent")]
    [InlineData(@"C:\Users\u\AppData\Roaming\NuGet\NuGet.Config", "user")]
    [InlineData(@"C:\Users\u\AppData\Roaming\NuGet\config\team.config", "user")]
    [InlineData(@"C:\Program Files (x86)\NuGet\Config\Microsoft.VisualStudio.Offline.config", "machine")]
    public void A_config_files_origin_is_where_it_sits(string file, string origin) =>
        Assert.Equal(origin, FeedResolver.Origin(file, @"C:\work\repo\", @"C:\Users\u\AppData\Roaming\NuGet\", @"C:\Program Files (x86)\NuGet\Config\"));

    [Fact]
    public async Task An_unreachable_feed_is_unknown_with_its_reason_never_a_substituted_answer_and_no_credential_survives()
    {
        File.WriteAllText(Path.Combine(_repo, "NuGet.config"), """
            <configuration><packageSources><clear />
              <add key="locked" value="http://svc-user:S3cr3tFeedPw@127.0.0.1:9/v3/index.json?token=QueryT0ken" />
            </packageSources></configuration>
            """);
        Package(_publicFeed, "Acme.Json", "1.0.0", "net8.0", JsonV1);
        Project("""    <PackageReference Include="Acme.Json" Version="1.0.0" />""", "class P { }");

        var artifact = await Run([new InputPackage("Acme.Json", "1.0.0", "packagereference")]);
        var json = Package(artifact, "Acme.Json");
        Assert.Equal(Outcomes.Unknown, json.Outcome);
        Assert.Contains("locked", json.OutcomeReason);
        Assert.Null(json.RecommendedVersion);

        var text = DeterministicJson.Serialize(artifact);
        Assert.DoesNotContain("S3cr3tFeedPw", text);
        Assert.DoesNotContain("QueryT0ken", text);
        Assert.DoesNotContain("svc-user", text);
        Assert.Contains("http://127.0.0.1:9/v3/index.json", text);
    }

    // ---------- outcomes and classification (Part C) ----------

    [Fact]
    public async Task The_api_diff_overrides_semver_in_both_directions()
    {
        ClientFeedConfig();
        // Minor version, but the code calls the removed Serializer.Parse: breaking.
        Package(_clientFeed, "Acme.Json", "1.0.0", "net8.0", JsonV1);
        Package(_clientFeed, "Acme.Json", "1.1.0", "net8.0", JsonV11);
        // Major version, but what changed is not called: safe.
        Package(_clientFeed, "Acme.Util", "1.0.0", "net8.0", "namespace Acme.Util { public static class Text { public static string Trim(string s) => s; public static string Old() => \"\"; } }");
        Package(_clientFeed, "Acme.Util", "2.0.0", "net8.0", "namespace Acme.Util { public static class Text { public static string Trim(string s) => s; } }");
        Project("""
                <PackageReference Include="Acme.Json" Version="1.0.0" />
                <PackageReference Include="Acme.Util" Version="1.0.0" />
            """, """
            using Acme.Json;
            using Acme.Util;
            class P
            {
                static void Main()
                {
                    var a = Serializer.Parse("{}");
                    var b = Text.Trim(a);
                }
            }
            """);

        var artifact = await Run([new InputPackage("Acme.Json", "1.0.0", "packagereference"), new InputPackage("Acme.Util", "1.0.0", "packagereference")]);

        var json = Package(artifact, "Acme.Json");
        Assert.Equal((Outcomes.UpgradeBreaking, ClassificationMethods.ApiDiff, "minor"), (json.Outcome, json.ClassificationMethod, json.SemverChange));
        var member = Assert.Single(json.BreakingMembers);
        Assert.Equal(("member_removed", "Acme.Json.Serializer", "Parse"), (member.Change, member.Type, member.Member));
        var site = Assert.Single(json.CallSites);
        Assert.Equal(("src/App/Program.cs", 7), (site.FilePath, site.LineStart));
        Assert.True(json.Confidence < 1.0);

        var util = Package(artifact, "Acme.Util");
        Assert.Equal((Outcomes.UpgradeSafe, ClassificationMethods.ApiDiff, "major"), (util.Outcome, util.ClassificationMethod, util.SemverChange));
        Assert.Equal(1, util.ApiDiff!.RemovedMembers);

        // Signals (Part D1): breaking at the call site, safe would be at the reference.
        var signals = artifact.Projects.Single().Signals;
        var breaking = Assert.Single(signals, s => s.Name == "PACKAGE_UPGRADE_BREAKING");
        Assert.Equal(("src/App/Program.cs", "API_INVOCATION", "Acme.Json 1.0.0 -> 1.1.0: Acme.Json.Serializer.Parse"), (breaking.SourcePath, breaking.Type, breaking.Value));
        var safe = Assert.Single(signals, s => s.Name == "PACKAGE_UPGRADE_SAFE");
        Assert.Equal(("src/App/App.csproj", "Acme.Util 1.0.0 -> 2.0.0", 5), (safe.SourcePath, safe.Value, safe.Evidence.Single().LineStart));
    }

    [Fact]
    public async Task Source_compatible_changes_do_not_make_an_upgrade_breaking()
    {
        ClientFeedConfig();
        // 2.0.0: Positive gains an optional parameter; the three-argument
        // Check changes type but the code only calls the two-argument one;
        // Ctx drops its override of Build, which Base still declares.
        Package(_clientFeed, "Acme.Guard", "1.0.0", "net8.0", """
            namespace Acme.Guard {
              public static class Guard { public static int Positive(int v, string n) => v; public static void Check(int a, int b) { } public static void Check(int a, int b, int c) { } }
              public class Base { public virtual void Build() { } }
              public class Ctx : Base { public override void Build() { } } }
            """);
        Package(_clientFeed, "Acme.Guard", "2.0.0", "net8.0", """
            namespace Acme.Guard {
              public static class Guard { public static int Positive(int v, string n, string message = null) => v; public static void Check(int a, int b) { } public static void Check(long a, int b, int c) { } }
              public class Base { public virtual void Build() { } }
              public class Ctx : Base { } }
            """);
        Project("""    <PackageReference Include="Acme.Guard" Version="1.0.0" />""", """
            using Acme.Guard;
            class My : Ctx
            {
                public override void Build() { base.Build(); Guard.Positive(1, "x"); Guard.Check(1, 2); }
            }
            """);

        var guard = Package(await Run([new InputPackage("Acme.Guard", "1.0.0", "packagereference")]), "Acme.Guard");

        Assert.Equal((Outcomes.UpgradeSafe, ClassificationMethods.ApiDiff), (guard.Outcome, guard.ClassificationMethod));
        // Only Check(int,int,int) counts as changed; the optional parameter and the override do not.
        Assert.Equal((0, 1), (guard.ApiDiff!.RemovedMembers, guard.ApiDiff.ChangedSignatures));
        Assert.Empty(guard.CallSites);
    }

    [Fact]
    public async Task A_version_held_in_an_msbuild_property_is_resolved_from_the_props_files()
    {
        ClientFeedConfig();
        Package(_clientFeed, "Acme.Json", "1.0.0", "net8.0", JsonV1);
        Package(_clientFeed, "Acme.Json", "1.1.0", "net8.0", JsonV11);
        File.WriteAllText(Path.Combine(_repo, "Directory.Packages.props"),
            "<Project><PropertyGroup><AcmeVersion>1.0.0</AcmeVersion></PropertyGroup></Project>");
        Project("""    <PackageReference Include="Acme.Json" />""", "class P { }");

        var json = Package(await Run([new InputPackage("Acme.Json", "$(AcmeVersion)", "packagereference")]), "Acme.Json");

        Assert.Equal(("1.0.0", Outcomes.UpgradeSafe), (json.CurrentVersion, json.Outcome));
    }

    // ---------- 1.1.0: package kind, call-site certainty, version drift ----------

    [Theory]
    [InlineData("lib/net8.0/A.dll", false, PackageKinds.Runtime)]
    [InlineData("lib/net8.0/_._|build/net8.0/A.props", true, PackageKinds.Build)]
    [InlineData("build/A.props|build/A.Tasks.dll", false, PackageKinds.Build)]
    [InlineData("buildTransitive/A.targets", false, PackageKinds.Build)]
    [InlineData("tools/csc.exe|tools/Microsoft.CodeAnalysis.dll", false, PackageKinds.Tools)]
    [InlineData("analyzers/dotnet/cs/A.Analyzers.dll|build/A.props", false, PackageKinds.Analyzer)]
    [InlineData("content/Scripts/a.js|contentFiles/any/any/a.css", true, PackageKinds.Content)]
    [InlineData("lib/netstandard1.0/_._", true, PackageKinds.Runtime)]
    [InlineData("runtime.json|lib/netstandard1.0/_._", false, PackageKinds.Build)]
    public void Package_kind_comes_from_the_package_contents(string files, bool hasDependencies, string expected) =>
        Assert.Equal(expected, PackageKinds.Classify(files.Split('|'), hasDependencies));

    // ---------- package dependencies and transitive API ----------

    private const string CoreV1 = "namespace Acme.Core.Models { public class Schema { } public class Info { } }";
    private const string CoreV2 = "namespace Acme.Core.Models { public class JsonSchema { } public class Info { } }";
    private const string GenApi = "namespace Acme.Gen { public static class Options { public static void Add() { } } }";

    /// <summary>Acme.Meta (build props only) -> Acme.Gen (assemblies, API
    /// unchanged) -> Acme.Core, which drops Models.Schema at 2.0.0.</summary>
    private void SwaggerLikeFamily()
    {
        Package(_clientFeed, "Acme.Core", "1.0.0", "net8.0", CoreV1);
        Package(_clientFeed, "Acme.Core", "2.0.0", "net8.0", CoreV2);
        Package(_clientFeed, "Acme.Gen", "1.0.0", "net8.0", GenApi, "Acme.Core@[1.0.0, )");
        Package(_clientFeed, "Acme.Gen", "2.0.0", "net8.0", GenApi, "Acme.Core@[2.0.0, )");
        MetaPackage(_clientFeed, "Acme.Meta", "1.0.0", ["build/Acme.Meta.props"], ["Acme.Gen@[1.0.0, )"]);
        MetaPackage(_clientFeed, "Acme.Meta", "2.0.0", ["build/Acme.Meta.props"], ["Acme.Gen@[2.0.0, )"]);
    }

    [Fact]
    public async Task Each_versions_nuspec_dependencies_are_recorded_in_the_lookup_cache()
    {
        ClientFeedConfig();
        SwaggerLikeFamily();
        Project("""    <PackageReference Include="Acme.Gen" Version="1.0.0" />""", "class P { }");
        var cache = new MemoryLookupCache();

        var gen = Package(await Run([new InputPackage("Acme.Gen", "1.0.0", "packagereference")], cache), "Acme.Gen");

        var entry = cache.Get(gen.FeedUrl!, "Acme.Gen")!;
        var group = Assert.Single(entry.Versions.Single(v => v.Version == "2.0.0").Dependencies!);
        Assert.Equal("net8.0", group.Framework);
        var dependency = Assert.Single(group.Packages);
        Assert.Equal(("Acme.Core", "[2.0.0, )"), (dependency.Id, dependency.Range));
    }

    [Fact]
    public async Task A_dependency_whose_major_version_moves_is_diffed_and_a_meta_package_is_diffed_through_what_it_carries()
    {
        ClientFeedConfig();
        SwaggerLikeFamily();
        Project("""
                <PackageReference Include="Acme.Meta" Version="1.0.0" />
                <PackageReference Include="Acme.Gen" Version="1.0.0" />
            """, """
            using Acme.Core.Models;
            class P
            {
                static void Main() { var s = new Schema(); }
            }
            """);

        var artifact = await Run([new InputPackage("Acme.Meta", "1.0.0", "packagereference"), new InputPackage("Acme.Gen", "1.0.0", "packagereference")]);

        // Acme.Gen's own API is unchanged; Acme.Core, which it moves 1 -> 2, drops the Schema the code uses.
        var gen = Package(artifact, "Acme.Gen");
        Assert.Equal((Outcomes.UpgradeBreaking, ClassificationMethods.ApiDiff), (gen.Outcome, gen.ClassificationMethod));
        Assert.Contains(gen.BreakingMembers, m => (m.Change, m.Type) == ("type_removed", "Acme.Core.Models.Schema"));
        Assert.Contains(gen.ConfidenceReasons, r => r.Contains("Acme.Core 1.0.0 -> 2.0.0"));

        // Acme.Meta has no assemblies: its API is Acme.Gen's, and through it Acme.Core's.
        var meta = Package(artifact, "Acme.Meta");
        Assert.Equal((Outcomes.UpgradeBreaking, PackageKinds.Build), (meta.Outcome, meta.PackageKind));
        Assert.Contains(meta.BreakingMembers, m => m.Type == "Acme.Core.Models.Schema");
        Assert.Contains(meta.ConfidenceReasons, r => r.Contains("Acme.Gen 1.0.0 -> 2.0.0") && r.Contains("Acme.Core 1.0.0 -> 2.0.0"));

        // 1.2.0: a build-kind package may be breaking, through an API diff.
        PackageSchema().Validate(DeterministicJson.Serialize(artifact.Projects.Single().Packages));
    }

    /// <summary>dependency-assessment-1.3.0's package definition, as a schema
    /// for an array of packages. The whole artifact is not validated here: the
    /// fixture's "public" feed is a local folder, which the feed enum rightly refuses.</summary>
    private static ArtifactSchemaValidator PackageSchema()
    {
        var schema = System.Text.Json.Nodes.JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "schemas", "dependency-assessment-1.6.0.schema.json")))!;
        var wrapper = new System.Text.Json.Nodes.JsonObject
        {
            ["$schema"] = schema["$schema"]!.DeepClone(),
            ["type"] = "array",
            ["items"] = new System.Text.Json.Nodes.JsonObject { ["$ref"] = "#/$defs/package" },
            ["$defs"] = schema["$defs"]!.DeepClone(),
        };
        var path = Path.Combine(Path.GetTempPath(), $"package-schema-{Guid.NewGuid():N}.json");
        File.WriteAllText(path, wrapper.ToJsonString());
        try { return ArtifactSchemaValidator.Load(path); }
        finally { File.Delete(path); }
    }

    [Fact]
    public async Task A_moved_dependency_the_code_does_not_call_into_leaves_the_upgrade_safe()
    {
        ClientFeedConfig();
        SwaggerLikeFamily();
        Project("""    <PackageReference Include="Acme.Meta" Version="1.0.0" />""",
            "using Acme.Core.Models; class P { static void Main() { var i = new Info(); } }");

        var meta = Package(await Run([new InputPackage("Acme.Meta", "1.0.0", "packagereference")]), "Acme.Meta");
        Assert.Equal((Outcomes.UpgradeSafe, ClassificationMethods.PackageKind), (meta.Outcome, meta.ClassificationMethod));
        Assert.Contains(meta.ConfidenceReasons, r => r.Contains("changes nothing the code calls"));
    }

    [Fact]
    public async Task Build_tools_and_content_packages_are_never_breaking_but_content_majors_are_flagged()
    {
        ClientFeedConfig();
        AssetPackage(_clientFeed, "Acme.Test.Sdk", "17.0.0", "build/Acme.Test.Sdk.props");
        AssetPackage(_clientFeed, "Acme.Test.Sdk", "18.0.0", "build/Acme.Test.Sdk.props");
        AssetPackage(_clientFeed, "Acme.Compilers", "2.0.0", "tools/csc.exe");
        AssetPackage(_clientFeed, "Acme.Compilers", "4.0.0", "tools/csc.exe");
        AssetPackage(_clientFeed, "acme-bootstrap", "4.3.1", "content/Content/bootstrap.css");
        AssetPackage(_clientFeed, "acme-bootstrap", "5.3.8", "content/Content/bootstrap.css");
        AssetPackage(_clientFeed, "acme-jquery", "3.6.0", "content/Scripts/jquery.js");
        AssetPackage(_clientFeed, "acme-jquery", "3.7.1", "content/Scripts/jquery.js");
        Project("""
                <PackageReference Include="Acme.Test.Sdk" Version="17.0.0" />
                <PackageReference Include="Acme.Compilers" Version="2.0.0" />
                <PackageReference Include="acme-bootstrap" Version="4.3.1" />
                <PackageReference Include="acme-jquery" Version="3.6.0" />
            """, "class P { }");

        var artifact = await Run([
            new InputPackage("Acme.Test.Sdk", "17.0.0", "packagereference"), new InputPackage("Acme.Compilers", "2.0.0", "packagereference"),
            new InputPackage("acme-bootstrap", "4.3.1", "packagereference"), new InputPackage("acme-jquery", "3.6.0", "packagereference")]);

        foreach (var (id, kind, contentRisk) in new[] { ("Acme.Test.Sdk", PackageKinds.Build, false), ("Acme.Compilers", PackageKinds.Tools, false),
                     ("acme-bootstrap", PackageKinds.Content, true), ("acme-jquery", PackageKinds.Content, false) })
        {
            var p = Package(artifact, id);
            Assert.Equal((Outcomes.UpgradeSafe, kind, ClassificationMethods.PackageKind, contentRisk, (string?)null),
                (p.Outcome, p.PackageKind, p.ClassificationMethod, p.ContentBreakingPossible, p.BreakingEvidence));
        }

        Assert.Equal(0, artifact.Summary.CountByOutcome.GetValueOrDefault(Outcomes.UpgradeBreaking));
        Assert.Equal(1, artifact.Summary.ContentBreakingPossibleCount);
        Assert.Equal(4, artifact.Projects.Single().Signals.Count(s => s.Name == "PACKAGE_UPGRADE_SAFE"));
    }

    [Fact]
    public async Task A_call_an_unchanged_overload_could_take_is_ambiguous_and_the_package_says_so()
    {
        ClientFeedConfig();
        // 2.0.0 removes Eq(IEquatable<T>, IEquatable<T>); the generic Eq(T, T)
        // is unchanged and takes the same two arguments — the MSTest
        // Assert.AreEqual case. Eq(a, b, message) is removed outright and
        // has no same-arity overload left, so that call is confirmed.
        Package(_clientFeed, "Acme.Assert", "1.0.0", "net8.0", """
            namespace Acme.Assert { public static class Check {
              public static void Eq<T>(System.IEquatable<T> a, System.IEquatable<T> b) { }
              public static void Eq<T>(T a, T b) { }
              public static void Eq(object a, object b, string message) { } } }
            """);
        Package(_clientFeed, "Acme.Assert", "2.0.0", "net8.0", """
            namespace Acme.Assert { public static class Check {
              public static void Eq<T>(T a, T b) { } } }
            """);
        Project("""    <PackageReference Include="Acme.Assert" Version="1.0.0" />""", """
            using Acme.Assert;
            class P
            {
                static void Main()
                {
                    Check.Eq(1, 2);
                }
            }
            """);

        var possible = Package(await Run([new InputPackage("Acme.Assert", "1.0.0", "packagereference")]), "Acme.Assert");

        Assert.Equal((Outcomes.UpgradeBreaking, BreakingEvidence.AmbiguousCallSitesOnly, CallSiteFinder.AmbiguousConfidence),
            (possible.Outcome, possible.BreakingEvidence, possible.Confidence));
        Assert.All(possible.CallSites, s => Assert.Equal(CallSiteCertainty.Ambiguous, s.Certainty));
        Assert.StartsWith("possibly breaking", possible.OutcomeReason);

        // Now a three-argument call too: that one binds to nothing unchanged.
        File.WriteAllText(Path.Combine(_repo, "src", "App", "Program.cs"), """
            using Acme.Assert;
            class P
            {
                static void Main()
                {
                    Check.Eq(1, 2);
                    Check.Eq(1, 2, "why");
                }
            }
            """);
        var confirmed = Package(await Run([new InputPackage("Acme.Assert", "1.0.0", "packagereference")]), "Acme.Assert");
        Assert.Equal((BreakingEvidence.ConfirmedCallSites, CallSiteFinder.Confidence), (confirmed.BreakingEvidence, confirmed.Confidence));
        Assert.Contains(confirmed.CallSites, s => s.LineStart == 7 && s.Certainty == CallSiteCertainty.Confirmed);
        Assert.Contains(confirmed.CallSites, s => s.LineStart == 6 && s.Certainty == CallSiteCertainty.Ambiguous);
    }

    [Fact]
    public async Task One_package_at_two_versions_across_projects_is_version_drift()
    {
        ClientFeedConfig();
        Package(_clientFeed, "Acme.Json", "1.0.0", "net8.0", JsonV1);
        Package(_clientFeed, "Acme.Json", "1.1.0", "net8.0", JsonV11);
        Package(_clientFeed, "Acme.Util", "1.0.0", "net8.0", "namespace Acme.Util { public static class Text { } }");
        ProjectAt("Web", """
                <PackageReference Include="Acme.Json" Version="1.0.0" />
                <PackageReference Include="Acme.Util" Version="1.0.0" />
            """, "class W { }");
        ProjectAt("Api", """
                <PackageReference Include="Acme.Json" Version="1.1.0" />
                <PackageReference Include="Acme.Util" Version="1.0.0" />
            """, "class A { }");

        var artifact = await RunProjects([
            ("src/Web/Web.csproj", [new InputPackage("Acme.Json", "1.0.0", "packagereference"), new InputPackage("Acme.Util", "1.0.0", "packagereference")]),
            ("src/Api/Api.csproj", [new InputPackage("Acme.Json", "1.1.0", "packagereference"), new InputPackage("Acme.Util", "1.0.0", "packagereference")])]);

        Assert.Equal(1, artifact.Summary.VersionDriftCount);
        var all = artifact.Projects.SelectMany(p => p.Packages).ToList();
        Assert.All(all.Where(p => p.PackageId == "Acme.Json"), p => Assert.True(p.VersionDrift));
        Assert.All(all.Where(p => p.PackageId == "Acme.Util"), p => Assert.False(p.VersionDrift));
    }

    [Fact]
    public async Task Recommended_is_the_newest_version_supporting_the_target_not_merely_the_newest()
    {
        ClientFeedConfig();
        Package(_clientFeed, "Acme.Old", "1.0.0", "net45", "namespace Acme.Old { public class A { } }");
        Package(_clientFeed, "Acme.Old", "1.5.0", "netstandard2.0", "namespace Acme.Old { public class A { } }");
        Package(_clientFeed, "Acme.Old", "2.0.0", "net45", "namespace Acme.Old { public class A { } }");
        Package(_clientFeed, "Acme.Legacy", "1.0.0", "net45", "namespace Acme.Legacy { public class A { } }");
        Package(_clientFeed, "Acme.Legacy", "1.1.0", "net45", "namespace Acme.Legacy { public class A { } }");
        Project("""
                <PackageReference Include="Acme.Old" Version="1.0.0" />
                <PackageReference Include="Acme.Legacy" Version="1.0.0" />
            """, "class P { }");

        var artifact = await Run([new InputPackage("Acme.Old", "1.0.0", "packagereference"), new InputPackage("Acme.Legacy", "1.0.0", "packagereference")]);

        var old = Package(artifact, "Acme.Old");
        Assert.Equal(("1.5.0", "2.0.0", Outcomes.UpgradeSafe), (old.RecommendedVersion, old.LatestVersion, old.Outcome));

        var legacy = Package(artifact, "Acme.Legacy");
        Assert.Equal(Outcomes.NoCompatibleVersion, legacy.Outcome);
        Assert.Single(artifact.Projects.Single().Signals, s => s.Name == "PACKAGE_NO_COMPATIBLE_VERSION");
    }

    [Fact]
    public async Task Deprecated_and_vulnerable_are_flags_that_co_occur_with_any_outcome_read_from_the_cache()
    {
        ClientFeedConfig();
        Project("""    <PackageReference Include="Acme.Json" Version="1.0.0" />""",
            "using Acme.Json; class P { static void Main() { var x = Serializer.Parse(\"{}\"); } }");
        Package(_clientFeed, "Acme.Json", "1.0.0", "net8.0", JsonV1);
        Package(_clientFeed, "Acme.Json", "1.1.0", "net8.0", JsonV11);

        // The feed knows nothing of advisories; a cached entry does — and a
        // fresh entry is read instead of the feed (Part B6).
        var cache = new MemoryLookupCache();
        cache.Put(new CacheEntry
        {
            FeedUrl = "repo:feeds/artifactory",
            PackageId = "acme.json",
            FetchedAt = DateTimeOffset.Parse("2026-10-01T23:00:00Z"),
            Versions =
            [
                new CachedVersion { Version = "1.1.0", DependencyFrameworks = ["net8.0"] },
                new CachedVersion
                {
                    Version = "1.0.0",
                    DependencyFrameworks = ["net8.0"],
                    Deprecation = new CachedDeprecation { Reasons = ["Legacy"], AlternateId = "System.Text.Json" },
                    Vulnerabilities = [new CachedVulnerability { Severity = 2, AdvisoryUrl = "https://github.com/advisories/GHSA-fixture" }],
                },
            ],
        });

        var json = Package(await Run([new InputPackage("Acme.Json", "1.0.0", "packagereference")], cache), "Acme.Json");
        Assert.Equal(Outcomes.UpgradeBreaking, json.Outcome);
        Assert.Equal("System.Text.Json", json.Deprecated!.ReplacementId);
        Assert.Equal(("high", true), (json.Vulnerable!.MaxSeverity, json.Vulnerable.ResolvedByUpgrade));
    }

    private static CachedVersion Cached(string version, bool vulnerable = false, CachedDeprecation? deprecation = null) => new()
    {
        Version = version,
        DependencyFrameworks = ["net8.0"],
        Deprecation = deprecation,
        Vulnerabilities = vulnerable ? [new CachedVulnerability { Severity = 2, AdvisoryUrl = "https://github.com/advisories/GHSA-fixture" }] : [],
    };

    private static CacheEntry Entry(string packageId, params CachedVersion[] versions) => new()
    {
        FeedUrl = "repo:feeds/artifactory", PackageId = packageId, FetchedAt = DateTimeOffset.Parse("2026-10-01T23:00:00Z"), Versions = versions,
    };

    /// <summary>1.5.0: no recommended version carries a known advisory. The newest compatible version has one, so the
    /// newest without one is recommended, and the vulnerability names it as the fix.</summary>
    [Fact]
    public async Task A_version_with_a_known_advisory_is_never_recommended()
    {
        ClientFeedConfig();
        Project("""    <PackageReference Include="Acme.Json" Version="1.0.0" />""",
            "using Acme.Json; class P { static void Main() { var x = Serializer.Parse(\"{}\"); } }");
        Package(_clientFeed, "Acme.Json", "1.0.0", "net8.0", JsonV1);
        Package(_clientFeed, "Acme.Json", "1.1.0", "net8.0", JsonV11);
        var cache = new MemoryLookupCache();
        cache.Put(Entry("acme.json", Cached("1.2.0", vulnerable: true), Cached("1.1.0"), Cached("1.0.0", vulnerable: true)));

        var artifact = await Run([new InputPackage("Acme.Json", "1.0.0", "packagereference")], cache);
        var json = Package(artifact, "Acme.Json");
        Assert.Equal("1.1.0", json.RecommendedVersion);
        Assert.Equal("1.1.0", json.Vulnerable!.FixedIn);
        Assert.Equal("Acme.Json 1.0.0: high; fixed in 1.1.0",
            Assert.Single(artifact.Projects.Single().Signals, s => s.Name == "PACKAGE_VULNERABLE").Value);
        PackageSchema().Validate(DeterministicJson.Serialize(artifact.Projects.Single().Packages));
    }

    /// <summary>1.5.0: when every newer version has a known advisory too, nothing is asked for: the package stays at
    /// its version, and the vulnerability says plainly that no fixed release exists yet.</summary>
    [Fact]
    public async Task A_vulnerability_with_no_fixed_release_says_so_instead_of_asking_for_a_vulnerable_version()
    {
        ClientFeedConfig();
        Project("""    <PackageReference Include="Acme.Json" Version="1.0.0" />""",
            "using Acme.Json; class P { static void Main() { var x = Serializer.Parse(\"{}\"); } }");
        Package(_clientFeed, "Acme.Json", "1.0.0", "net8.0", JsonV1);
        Package(_clientFeed, "Acme.Json", "1.1.0", "net8.0", JsonV11);
        var cache = new MemoryLookupCache();
        cache.Put(Entry("acme.json", Cached("1.1.0", vulnerable: true), Cached("1.0.0", vulnerable: true)));

        var artifact = await Run([new InputPackage("Acme.Json", "1.0.0", "packagereference")], cache);
        var json = Package(artifact, "Acme.Json");
        Assert.Equal(Outcomes.Current, json.Outcome);
        Assert.Null(json.Vulnerable!.FixedIn);
        var signals = artifact.Projects.Single().Signals;
        Assert.Equal($"Acme.Json 1.0.0: high; {DependencyPipeline.NoFixedRelease}", Assert.Single(signals, s => s.Name == "PACKAGE_VULNERABLE").Value);
        Assert.DoesNotContain(signals, s => s.Name.StartsWith("PACKAGE_UPGRADE_", StringComparison.Ordinal));
    }

    /// <summary>1.5.0: a retired package's replacement is given a version: its newest release within the
    /// publisher's range that is stable, not deprecated, free of known advisories and supports the target.</summary>
    [Fact]
    public async Task A_replacement_names_its_newest_compatible_release_without_a_known_advisory()
    {
        ClientFeedConfig();
        Project("""    <PackageReference Include="Acme.Json" Version="1.0.0" />""",
            "using Acme.Json; class P { static void Main() { var x = Serializer.Parse(\"{}\"); } }");
        Package(_clientFeed, "Acme.Json", "1.0.0", "net8.0", JsonV1);
        var retired = new CachedDeprecation { Reasons = ["Other"], AlternateId = "Acme.Json.Next", AlternateRange = "[*, )" };
        var cache = new MemoryLookupCache();
        cache.Put(Entry("acme.json", Cached("1.0.0", deprecation: retired)));
        cache.Put(Entry("acme.json.next", Cached("4.0.0-beta.1"), Cached("3.0.0", vulnerable: true),
            Cached("2.5.0", deprecation: new CachedDeprecation { Reasons = ["CriticalBugs"] }), Cached("2.1.0"), Cached("2.0.0")));

        var artifact = await Run([new InputPackage("Acme.Json", "1.0.0", "packagereference")], cache);
        var json = Package(artifact, "Acme.Json");
        Assert.Equal("2.1.0", json.Deprecated!.ReplacementVersion);
        Assert.Equal("Acme.Json 1.0.0: package deprecated (Other); replacement Acme.Json.Next 2.1.0",
            Assert.Single(artifact.Projects.Single().Signals, s => s.Name == "PACKAGE_DEPRECATED").Value);
        PackageSchema().Validate(DeterministicJson.Serialize(artifact.Projects.Single().Packages));
    }

    /// <summary>1.4.3: an engine run may take a release published after an experiment's lookups were frozen. A
    /// version newer than every version the answers know is an upgrade (current), reported as newer than the
    /// lookups; never no-compatible-version, which would raise a replacement work item.</summary>
    [Fact]
    public async Task A_version_newer_than_the_lookup_answers_counts_as_upgraded()
    {
        ClientFeedConfig();
        Project("""    <PackageReference Include="Acme.Json" Version="1.2.0" />""",
            "using Acme.Json; class P { static void Main() { var x = Serializer.Write(1); } }");
        var cache = new MemoryLookupCache();
        cache.Put(new CacheEntry
        {
            FeedUrl = "repo:feeds/artifactory", PackageId = "acme.json", FetchedAt = DateTimeOffset.Parse("2026-10-01T23:00:00Z"),
            Versions = [new CachedVersion { Version = "1.1.0", DependencyFrameworks = ["net8.0"] },
                        new CachedVersion { Version = "1.0.0", DependencyFrameworks = ["net8.0"] }],
        });

        var artifact = await Run([new InputPackage("Acme.Json", "1.2.0", "packagereference")], cache);
        var json = Package(artifact, "Acme.Json");
        Assert.Equal(Outcomes.Current, json.Outcome);
        Assert.StartsWith(DependencyPipeline.NewerThanLookups, json.OutcomeReason);
        Assert.Contains("recommended 1.1.0", json.OutcomeReason);
        Assert.DoesNotContain(artifact.Projects.Single().Signals, s => s.Name.StartsWith("PACKAGE_", StringComparison.Ordinal));
    }

    // 1.5.0: the replacement is not on the fixture's feed, so no release of it is named.
    private const string NoReplacementRelease = "no release of it supports the target without a known advisory";

    /// <summary>1.3.0 (Part C3): NuGet deprecates versions. A deprecated release of a maintained package — a newer
    /// version is not deprecated, and the reason is not Legacy — is an upgrade; a Legacy package, or one whose newer
    /// versions are all deprecated too, is retired and needs replacing. The signal's value says which.</summary>
    [Theory]
    [InlineData("CriticalBugs", "System.Text.Json", false, "version", "Acme.Json 1.0.0: version deprecated (CriticalBugs); 1.1.0 is not")]
    [InlineData("Other", null, false, "version", "Acme.Json 1.0.0: version deprecated (Other); 1.1.0 is not")]
    [InlineData("Legacy", null, false, "version", "Acme.Json 1.0.0: version deprecated (Legacy); 1.1.0 is not")]
    [InlineData("Legacy", "Acme.Json", false, "version", "Acme.Json 1.0.0: version deprecated (Legacy); 1.1.0 is not")]
    [InlineData("Legacy", "System.Text.Json", false, "package", "Acme.Json 1.0.0: package deprecated (Legacy); replacement System.Text.Json; " + NoReplacementRelease)]
    [InlineData("CriticalBugs", "System.Text.Json", true, "package", "Acme.Json 1.0.0: package deprecated (CriticalBugs); replacement System.Text.Json; " + NoReplacementRelease)]
    [InlineData("Other", null, true, "package", "Acme.Json 1.0.0: package deprecated (Other); no suggested replacement")]
    public async Task A_deprecated_version_of_a_maintained_package_is_told_apart_from_a_retired_package(
        string reason, string? alternate, bool newerDeprecatedToo, string scope, string signalValue)
    {
        ClientFeedConfig();
        Project("""    <PackageReference Include="Acme.Json" Version="1.0.0" />""",
            "using Acme.Json; class P { static void Main() { var x = Serializer.Parse(\"{}\"); } }");
        Package(_clientFeed, "Acme.Json", "1.0.0", "net8.0", JsonV1);
        Package(_clientFeed, "Acme.Json", "1.1.0", "net8.0", JsonV11);
        var deprecation = new CachedDeprecation { Reasons = [reason], AlternateId = alternate };
        var cache = new MemoryLookupCache();
        cache.Put(new CacheEntry
        {
            FeedUrl = "repo:feeds/artifactory",
            PackageId = "acme.json",
            FetchedAt = DateTimeOffset.Parse("2026-10-01T23:00:00Z"),
            Versions =
            [
                new CachedVersion { Version = "1.1.0", DependencyFrameworks = ["net8.0"], Deprecation = newerDeprecatedToo ? deprecation : null },
                new CachedVersion { Version = "1.0.0", DependencyFrameworks = ["net8.0"], Deprecation = deprecation },
            ],
        });

        var artifact = await Run([new InputPackage("Acme.Json", "1.0.0", "packagereference")], cache);
        var json = Package(artifact, "Acme.Json");
        Assert.Equal("1.6.0", artifact.ArtifactVersion);
        Assert.Equal(scope, json.Deprecated!.Scope);
        Assert.Equal(scope == "version" ? "1.1.0" : null, json.Deprecated.NewestNotDeprecated);
        Assert.Equal(signalValue, Assert.Single(artifact.Projects.Single().Signals, s => s.Name == "PACKAGE_DEPRECATED").Value);
        PackageSchema().Validate(DeterministicJson.Serialize(artifact.Projects.Single().Packages));
    }

    /// <summary>1.4.0: a package the target's shared framework provides is a removal, decided before any feed
    /// lookup. Microsoft.AspNetCore.App's packages are a Web project's; Microsoft.NETCore.App's are every project's.</summary>
    [Fact]
    public async Task A_package_the_target_framework_provides_is_a_removal_not_an_upgrade()
    {
        ClientFeedConfig();
        ProjectAt("App", """    <PackageReference Include="Microsoft.AspNetCore.Server.Kestrel" Version="2.3.9" />""", "class P {}", "Microsoft.NET.Sdk.Web");
        var artifact = await RunProjects([("src/App/App.csproj", [new InputPackage("Microsoft.AspNetCore.Server.Kestrel", "2.3.9", "packagereference")])],
            projectSdk: "Microsoft.NET.Sdk.Web");
        var kestrel = Package(artifact, "Microsoft.AspNetCore.Server.Kestrel");
        Assert.Equal(Outcomes.FrameworkProvided, kestrel.Outcome);
        Assert.Null(kestrel.RecommendedVersion);
        Assert.Contains("Microsoft.AspNetCore.App", kestrel.OutcomeReason);
        Assert.Equal("Microsoft.AspNetCore.Server.Kestrel 2.3.9: provided by Microsoft.AspNetCore.App net10.0",
            Assert.Single(artifact.Projects.Single().Signals, s => s.Name == "PACKAGE_PROVIDED_BY_FRAMEWORK").Value);
        Assert.DoesNotContain(artifact.Projects.Single().Signals, s => s.Name == "PACKAGE_UPGRADE_SAFE");
        PackageSchema().Validate(DeterministicJson.Serialize(artifact.Projects.Single().Packages));
    }

    [Fact]
    public async Task An_aspnetcore_package_in_a_plain_library_is_not_provided_but_a_runtime_one_is()
    {
        ClientFeedConfig();
        Project("""
                <PackageReference Include="Microsoft.AspNetCore.Server.Kestrel" Version="2.3.9" />
                <PackageReference Include="System.Text.Json" Version="8.0.6" />
            """, "class P {}");
        var artifact = await Run([new InputPackage("Microsoft.AspNetCore.Server.Kestrel", "2.3.9", "packagereference"),
                                  new InputPackage("System.Text.Json", "8.0.6", "packagereference")]);
        Assert.NotEqual(Outcomes.FrameworkProvided, Package(artifact, "Microsoft.AspNetCore.Server.Kestrel").Outcome);
        Assert.Equal(Outcomes.FrameworkProvided, Package(artifact, "System.Text.Json").Outcome);
    }

    /// <summary>1.4.0: TARGET_FRAMEWORK_BELOW_ENGAGEMENT_TARGET for a modern .NET project below the target, at the line
    /// declaring its framework; none for one already on it.</summary>
    [Fact]
    public async Task A_project_below_the_engagement_target_framework_emits_the_retarget_signal()
    {
        ClientFeedConfig();
        Project("", "class P {}");
        var below = await Run([], currentFramework: "net8.0");
        var signal = Assert.Single(below.Projects.Single().Signals, s => s.Name == "TARGET_FRAMEWORK_BELOW_ENGAGEMENT_TARGET");
        Assert.Equal(("net8.0 -> net10.0", "src/App/App.csproj", 2), (signal.Value, signal.SourcePath, signal.Evidence.Single().LineStart));
        var onTarget = await Run([], currentFramework: "net10.0");
        Assert.DoesNotContain(onTarget.Projects.Single().Signals, s => s.Name == "TARGET_FRAMEWORK_BELOW_ENGAGEMENT_TARGET");
        var framework = await Run([], currentFramework: "net48");
        Assert.DoesNotContain(framework.Projects.Single().Signals, s => s.Name == "TARGET_FRAMEWORK_BELOW_ENGAGEMENT_TARGET");
    }

    [Fact]
    public async Task Two_runs_against_the_same_cache_produce_identical_artifacts()
    {
        ClientFeedConfig();
        Package(_clientFeed, "Acme.Json", "1.0.0", "net8.0", JsonV1);
        Package(_clientFeed, "Acme.Json", "1.1.0", "net8.0", JsonV11);
        Package(_publicFeed, "Acme.Json", "1.2.0", "net8.0", JsonV12);
        Project("""    <PackageReference Include="Acme.Json" Version="1.0.0" />""",
            "using Acme.Json; class P { static void Main() { var x = Serializer.Parse(\"{}\"); } }");
        var cache = new MemoryLookupCache();
        var packages = new[] { new InputPackage("Acme.Json", "1.0.0", "packagereference") };

        var first = DeterministicJson.Serialize(await Run(packages, cache));
        // A package published after the first run is not seen: the cache decides.
        Package(_clientFeed, "Acme.Json", "1.3.0", "net8.0", JsonV12);
        var second = DeterministicJson.Serialize(await Run(packages, cache));
        Assert.Equal(first, second);
        Assert.DoesNotContain("2026-10-0", first);
    }

    [Fact]
    public void Feed_urls_are_normalised_before_storage()
    {
        Assert.Equal("https://pkgs.example.com/nuget/v3/index.json",
            FeedResolver.NormaliseUrl("https://u:p@PKGS.example.com/nuget/v3/index.json?api-key=x#frag", @"C:\repo\"));
        Assert.True(FeedResolver.IsNuGetOrg("https://api.nuget.org/v3/index.json"));
    }
}
