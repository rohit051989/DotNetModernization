using System.Text.Json.Nodes;
using Fingerprinting.Analysis;
using Fingerprinting.Domain;
using Fingerprinting.EntryPoints;
using Fingerprinting.StepHost;
using Microsoft.CodeAnalysis.CSharp;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>Step 4's framework delta signals (scanner 2.3.0, registry 1.10.0):
/// eShopOnWeb's shape — a test project referencing Web (implicit Program) and
/// PublicApi (explicit public partial Program), naming Program.</summary>
public class FrameworkDeltaSignalsTests
{
    private const string Web = "src/Web/Web.csproj";
    private const string Api = "src/PublicApi/PublicApi.csproj";
    private const string Tests = "tests/ApiTests/ApiTests.csproj";
    private const string Lib = "src/Core/Core.csproj";

    private const string TopLevel = "var app = WebApplication.Create(args);\napp.Run();\n";
    private const string UsesProgram = "public class T { static WebApplicationFactory<Program> f = new(); }";

    private static ProjectSource Source(string project, params (string Name, string Code)[] files)
    {
        var directory = project[..project.LastIndexOf('/')];
        return new ProjectSource
        {
            ProjectPath = project,
            ProjectDirectory = directory,
            Files = files.Select(f => new ParsedFile($"{directory}/{f.Name}", CSharpSyntaxTree.ParseText(f.Code).GetCompilationUnitRoot())).ToList(),
            PackageNames = [],
            Truncated = false,
            AuxiliaryFiles = [],
        };
    }

    private const string WebSdk = "Microsoft.NET.Sdk.Web";
    private const string Sdk = "Microsoft.NET.Sdk";

    private static IReadOnlyDictionary<string, IReadOnlyList<Fingerprinting.Domain.Signal>> Build(string webProgram, string testCode, string webSdk = WebSdk) =>
        FrameworkDeltaSignals.Build(
        [
            (Web, webSdk, Source(Web, ("Program.cs", webProgram))),
            (Api, WebSdk, Source(Api, ("Program.cs", TopLevel + "public partial class Program { }\n"))),
            (Lib, Sdk, Source(Lib, ("Order.cs", "public class Order { }"))),
            (Tests, Sdk, Source(Tests, ("ProgramTest.cs", testCode))),
        ],
        [(Tests, Api), (Tests, Lib), (Lib, Web)]);   // Web is reached transitively, through Core

    [Fact]
    public void A_project_naming_Program_with_two_public_programs_on_net10_carries_the_signal_with_the_file_to_fix()
    {
        var signals = Build(TopLevel, UsesProgram);

        var signal = Assert.Single(signals[Tests]);
        Assert.Equal((FrameworkDeltaSignals.AmbiguousTopLevelProgramOnNet10, "src/Web/Program.cs", "tests/ApiTests/ProgramTest.cs", "EntryPointInventory"),
            (signal.Name, signal.Value, signal.SourcePath, signal.Extractor));
        Assert.Equal((1, "Program"), (signal.Evidence.Single().LineStart, signal.Evidence.Single().Member));
        Assert.False(signals.ContainsKey(Web));
        Assert.False(signals.ContainsKey(Api));

        // The artifact carries it, so it must be a valid signal by the artifact's own schema.
        SignalSchema().Validate(DeterministicJson.Serialize(signals[Tests]));
    }

    /// <summary>entry-point-inventory-2.2.0's signal definition, as a schema for an array of signals.</summary>
    private static ArtifactSchemaValidator SignalSchema()
    {
        var schema = JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "schemas", "entry-point-inventory-2.2.0.schema.json")))!;
        var wrapper = new JsonObject
        {
            ["$schema"] = schema["$schema"]!.DeepClone(),
            ["type"] = "array",
            ["items"] = new JsonObject { ["$ref"] = "#/$defs/signal" },
            ["$defs"] = schema["$defs"]!.DeepClone(),
        };
        var path = Path.Combine(Path.GetTempPath(), $"signal-schema-{Guid.NewGuid():N}.json");
        File.WriteAllText(path, wrapper.ToJsonString());
        try { return ArtifactSchemaValidator.Load(path); }
        finally { File.Delete(path); }
    }

    [Fact]
    public void Nothing_when_the_implicit_program_is_pinned_internal_not_a_web_project_or_never_named()
    {
        // The fix itself: an explicit internal declaration keeps Program internal on net10.0.
        Assert.Empty(Build(TopLevel + "internal partial class Program { }\n", UsesProgram));
        // Only the ASP.NET Core generator makes Program public.
        Assert.Empty(Build(TopLevel, UsesProgram, webSdk: Sdk));
        // CS0433 needs a use: referencing both projects alone compiles.
        Assert.Empty(Build(TopLevel, "public class T { }"));
    }

    [Fact]
    public void Already_ambiguous_on_the_source_framework_is_not_a_delta()
    {
        var signals = Build(TopLevel + "public partial class Program { }\n", UsesProgram);
        Assert.Empty(signals);
    }
}
