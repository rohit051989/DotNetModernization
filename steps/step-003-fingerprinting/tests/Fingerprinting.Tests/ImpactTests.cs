using System.Text.Json;
using Fingerprinting.Domain;
using Fingerprinting.Impact;
using Fingerprinting.Impact.Cli;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>impact-analysis — 33-IMPACT-ANALYSIS.md: which resolutions are
/// computed (C), the default rule (D), traversal primitives and filters (E),
/// one action per file, certainty, traversal paths and creates (F), actions
/// as what happens to the file, the three figures, hotspots and conflicts
/// (G), and determinism.</summary>
public sealed class ImpactTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "impact-tests-" + Guid.NewGuid().ToString("N"));

    public ImpactTests()
    {
        Write("src/Contracts/IOrderService.cs", """
            using System.ServiceModel;
            namespace Shop.Contracts
            {
                [ServiceContract]
                public interface IOrderService
                {
                    [OperationContract] OrderSummary GetOrder(int id);
                    [OperationContract] void PlaceOrder(PlaceOrderRequest request);
                }
            }
            """);
        Write("src/Contracts/IHealth.cs", "namespace Shop.Contracts { public interface IHealth { bool Ping(); } }");
        Write("src/Contracts/OrderSummary.cs", "using System.Runtime.Serialization; namespace Shop.Contracts { [DataContract] public class OrderSummary { [DataMember] public int Id { get; set; } } }");
        Write("src/Contracts/PlaceOrderRequest.cs", "using System.Runtime.Serialization; namespace Shop.Contracts { [DataContract] public class PlaceOrderRequest { } }");
        Write("src/Services/OrderService.cs", """
            using Shop.Contracts;
            namespace Shop.Services
            {
                public class OrderService : IOrderService, IHealth
                {
                    public OrderSummary GetOrder(int id) => new OrderSummary();
                    public void PlaceOrder(PlaceOrderRequest request) { }
                    public bool Ping() => true;
                }
            }
            """);
        Write("src/Services/Services.csproj", "<Project Sdk=\"Microsoft.NET.Sdk\" />");
        Write("src/Web/Order.svc", "<%@ ServiceHost Language=\"C#\" Service=\"Shop.Services.OrderService, Shop.Services\" %>");
        Write("src/Web/Web.config", """
            <configuration>
              <system.serviceModel>
                <services>
                  <service name="Shop.Services.OrderService" />
                </services>
              </system.serviceModel>
            </configuration>
            """);
        Write("tests/OrderServiceTests.cs", "namespace Shop.Tests { public class OrderServiceTests { } }");
    }

    public void Dispose()
    {
        try { Directory.Delete(_root, recursive: true); } catch (IOException) { }
    }

    private void Write(string relative, string text)
    {
        var path = Path.Combine(_root, relative.Replace('/', Path.DirectorySeparatorChar));
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, text);
    }

    private static IReadOnlyList<ImpactRule> Rules(string json) => JsonSerializer.Deserialize<List<ImpactRule>>(json)!;

    private const string RestRules = """
        [
          {"id": "impl", "from": "seed", "select": "self", "action": "rewrite", "reason": "Implementation becomes controller logic"},
          {"id": "contracts", "from": "impl", "traverse": "implemented_interfaces", "filter": {"has_attribute": "ServiceContract"}, "action": "delete"},
          {"id": "data-contracts", "from": "contracts", "traverse": "signature_types", "filter": {"has_attribute": "DataContract"}, "action": "update"},
          {"id": "svc", "from": "impl", "traverse": "convention_files", "kind": "svc", "action": "delete"},
          {"id": "service-config", "from": "impl", "traverse": "config_elements", "path": "system.serviceModel/services", "action": "update",
           "reason": "Remove the <service> registration"},
          {"id": "tests", "from": ["impl", "contracts"], "traverse": "referencing_tests", "action": "update"},
          {"id": "controllers", "create": "REST controller per service contract", "for_each": "contracts",
           "proposed_path": "{project.dir}/Controllers/{type.base_name}Controller.cs", "action": "create"},
          {"id": "clients", "traverse": "client_call_sites", "action": "rewrite"}
        ]
        """;

    private const string CoreWcfRules = """
        [
          {"id": "impl", "from": "seed", "select": "self", "action": "update"},
          {"id": "contracts", "from": "impl", "traverse": "implemented_interfaces", "filter": {"has_attribute": "ServiceContract"}, "action": "update"},
          {"id": "data-contracts", "from": "contracts", "traverse": "signature_types", "filter": {"has_attribute": "DataContract"}, "action": "review"},
          {"id": "svc", "from": "impl", "traverse": "convention_files", "kind": "svc", "action": "delete"}
        ]
        """;

    private ImpactInput Input(IReadOnlyDictionary<string, string> decisions, IReadOnlyList<ResolutionInfo>? resolutions = null, IReadOnlyList<WorkItemSeed>? workItems = null) => new(
        Guid.Parse("11111111-1111-1111-1111-111111111111"), "shop", "eng",
        new ProjectMap(new Dictionary<string, string> { ["src/Services/Services.csproj"] = "src/Services" }),
        workItems ?? [new WorkItemSeed("wcf-service", null, "src/Services/Services.csproj", [new SeedFile("src/Services/OrderService.cs", "EXPOSES_WCF_SERVICE", "IOrderService")])],
        new Dictionary<string, CatalogItemInfo>
        {
            ["wcf-service"] = new("wcf-service", "WCF service", resolutions ??
            [
                new ResolutionInfo("corewcf", "CoreWCF", true, "none", Rules(CoreWcfRules)),
                new ResolutionInfo("rest", "REST rewrite", false, "high", Rules(RestRules)),
                new ResolutionInfo("windows", "Remain Windows-hosted", false, "none", []),
            ]),
        },
        decisions,
        [new TestLink("src/Services/OrderService.cs", "Shop.Services.OrderService", "tests/OrderServiceTests.cs", "OrderServiceTests", "type_reference", 0.9m)],
        []);

    private Task<ImpactArtifact> Run(ImpactInput input) => ImpactPipeline.RunAsync(input, _root, CancellationToken.None);

    private static ResolutionImpact Resolution(ImpactArtifact artifact, string id) =>
        Assert.Single(artifact.WorkItems).Resolutions.Single(r => r.ResolutionId == id);

    private static ImpactEntry Entry(ResolutionImpact resolution, string path) =>
        resolution.Entries.Single(e => (e.FilePath ?? e.ProposedPath) == path);

    // ---------- Part C: which resolutions are computed ----------

    [Fact]
    public async Task NoDecision_ComputesTheDefaultOnly_OthersPending()
    {
        var work = Assert.Single((await Run(Input(new Dictionary<string, string>()))).WorkItems);
        var only = Assert.Single(work.Resolutions);
        Assert.Equal("corewcf", only.ResolutionId);
        Assert.Equal(["default"], only.Roles);
        Assert.True(only.Effective);
        Assert.Null(only.DecisionResolutionId);
        Assert.Equal(["rest", "windows"], work.PendingResolutions.Select(p => p.ResolutionId));
    }

    [Fact]
    public async Task Decision_ComputesTheChosenAndTheDefault_ChosenIsEffective()
    {
        var work = Assert.Single((await Run(Input(new Dictionary<string, string> { ["wcf-service"] = "rest" }))).WorkItems);
        Assert.Equal(["corewcf", "rest"], work.Resolutions.Select(r => r.ResolutionId));
        Assert.False(work.Resolutions[0].Effective);
        Assert.Equal(["chosen"], work.Resolutions[1].Roles);
        Assert.Equal("rest", work.EffectiveResolutionId);
        Assert.All(work.Resolutions, r => Assert.Equal("rest", r.DecisionResolutionId));
        Assert.Equal(["windows"], work.PendingResolutions.Select(p => p.ResolutionId));
    }

    [Fact]
    public async Task ChoosingTheDefault_ComputesItOnce_WithBothRoles()
    {
        var work = Assert.Single((await Run(Input(new Dictionary<string, string> { ["wcf-service"] = "corewcf" }))).WorkItems);
        Assert.Equal(["default", "chosen"], Assert.Single(work.Resolutions).Roles);
    }

    [Fact]
    public async Task NoDefault_TheLowestConsumerImpactIsPresumptive()
    {
        var input = Input(new Dictionary<string, string>(),
        [
            new ResolutionInfo("b-high", "High", false, "high", []),
            new ResolutionInfo("a-low", "Low", false, "low", []),
        ]);
        var only = Assert.Single(Assert.Single((await Run(input)).WorkItems).Resolutions);
        Assert.Equal("a-low", only.ResolutionId);
        Assert.Equal(["presumptive"], only.Roles);
    }

    // ---------- Part D: the default rule ----------

    [Fact]
    public async Task NoRules_TheDefaultRule_ImpactsTheEvidenceFiles()
    {
        var input = Input(new Dictionary<string, string> { ["wcf-service"] = "windows" });
        var windows = Resolution(await Run(input), "windows");
        Assert.Equal("default", windows.RulesSource);
        var entry = Assert.Single(windows.Entries);
        Assert.Equal(("src/Services/OrderService.cs", Actions.Update), (entry.FilePath, entry.Action));
        Assert.Equal("evidence", Assert.Single(entry.Reasons).RuleId);
    }

    // ---------- Parts E and F: the REST rewrite against CoreWCF ----------

    [Fact]
    public async Task RestRewrite_TraversesContractsDataContractsConventionConfigTestsAndCreates()
    {
        var rest = Resolution(await Run(Input(new Dictionary<string, string> { ["wcf-service"] = "rest" })), "rest");

        Assert.Equal(Actions.Rewrite, Entry(rest, "src/Services/OrderService.cs").Action);
        Assert.Equal(Actions.Delete, Entry(rest, "src/Contracts/IOrderService.cs").Action);
        Assert.DoesNotContain(rest.Entries, e => e.FilePath == "src/Contracts/IHealth.cs");   // filtered: no [ServiceContract]
        Assert.Equal(Actions.Update, Entry(rest, "src/Contracts/OrderSummary.cs").Action);
        Assert.Equal(Actions.Update, Entry(rest, "src/Contracts/PlaceOrderRequest.cs").Action);
        Assert.Equal(Actions.Delete, Entry(rest, "src/Web/Order.svc").Action);
        var config = Entry(rest, "src/Web/Web.config");
        Assert.Equal(Actions.Update, config.Action);   // an element goes; the file stays
        Assert.Equal(["element <service> at system.serviceModel/services, line 4"], config.Details);
        Assert.Equal(Actions.Update, Entry(rest, "tests/OrderServiceTests.cs").Action);

        var create = Entry(rest, "src/Services/Controllers/OrderServiceController.cs");
        Assert.Null(create.FilePath);
        Assert.Equal(Actions.Create, create.Action);
        Assert.Contains("IOrderService", create.Description);

        Assert.Equal(["clients"], rest.DeferredRules);   // dependency-and-context-map's
        Assert.Equal(new ActionCounts { Rewrite = 1, Delete = 2, Update = 4, Create = 1 }, rest.Counts);
        Assert.Equal((7, 1, 0), (rest.Changed, rest.Created, rest.ToReview));
    }

    [Fact]
    public async Task EveryEntry_HasATraversalPathBackToTheSeed()
    {
        var rest = Resolution(await Run(Input(new Dictionary<string, string> { ["wcf-service"] = "rest" })), "rest");
        Assert.All(rest.Entries, e => Assert.All(e.TraversalPaths, p => Assert.EndsWith("evidence src/Services/OrderService.cs (EXPOSES_WCF_SERVICE IOrderService)", p)));
        Assert.Equal(
            "OrderSummary used in IOrderService.GetOrder ← IOrderService implemented by OrderService ← evidence src/Services/OrderService.cs (EXPOSES_WCF_SERVICE IOrderService)",
            Assert.Single(Entry(rest, "src/Contracts/OrderSummary.cs").TraversalPaths));
    }

    [Fact]
    public async Task SeveralRulesOnOneFile_StrongestActionKept_EveryReasonRecorded()
    {
        var merged = Rules("""
            [
              {"id": "a-review", "from": "seed", "select": "self", "action": "review", "reason": "check it"},
              {"id": "b-delete", "from": "seed", "select": "self", "action": "delete", "reason": "remove it"},
              {"id": "c-update", "from": "seed", "select": "self", "action": "update", "reason": "edit it"}
            ]
            """);
        var input = Input(new Dictionary<string, string>(), [new ResolutionInfo("only", "Only", true, "none", merged)]);
        var entry = Assert.Single(Resolution(await Run(input), "only").Entries);
        Assert.Equal(Actions.Delete, entry.Action);
        Assert.Equal(["a-review", "b-delete", "c-update"], entry.Reasons.Select(r => r.RuleId));
    }

    [Fact]
    public async Task AmbiguousTypeResolution_IsPossible()
    {
        Write("src/Other/OrderSummary.cs", "namespace Other { [System.Runtime.Serialization.DataContract] public class OrderSummary { } }");
        var rest = Resolution(await Run(Input(new Dictionary<string, string> { ["wcf-service"] = "rest" })), "rest");
        // The contract imports Shop.Contracts only, and declares in it: the visible one is unique, so confirmed.
        Assert.Equal(Certainties.Confirmed, Entry(rest, "src/Contracts/OrderSummary.cs").Certainty);

        Write("src/Contracts/IOrderService.cs", """
            [System.ServiceModel.ServiceContract] public interface IOrderService { OrderSummary GetOrder(int id); }
            """);
        rest = Resolution(await Run(Input(new Dictionary<string, string> { ["wcf-service"] = "rest" })), "rest");
        Assert.Equal(Certainties.Possible, Entry(rest, "src/Other/OrderSummary.cs").Certainty);
    }

    [Fact]
    public async Task Reflection_IsAKnownLimit_NotClaimedImpact()
    {
        Write("src/Services/OrderService.cs", """
            using Shop.Contracts;
            namespace Shop.Services
            {
                public class OrderService : IOrderService
                {
                    public OrderSummary GetOrder(int id) => (OrderSummary)System.Activator.CreateInstance(System.Type.GetType("Shop.Contracts.OrderSummary"));
                    public void PlaceOrder(PlaceOrderRequest request) { }
                }
            }
            """);
        var core = Resolution(await Run(Input(new Dictionary<string, string>())), "corewcf");
        Assert.Contains(core.KnownLimits, l => l.StartsWith("Reflection in src/Services/OrderService.cs", StringComparison.Ordinal));
    }

    [Fact]
    public async Task TwoRuns_ProduceIdenticalArtifacts()
    {
        var input = Input(new Dictionary<string, string> { ["wcf-service"] = "rest" });
        Assert.Equal(DeterministicJson.Serialize(await Run(input)), DeterministicJson.Serialize(await Run(input)));
    }

    // ---------- Part F: an action describes what happens to the file ----------

    [Fact]
    public async Task DeletingAConfigElement_UpdatesTheFile_NamingTheElement()
    {
        var rules = Rules("""
            [{"id": "cfg", "from": "seed", "traverse": "config_elements", "path": "system.serviceModel/services", "action": "delete"}]
            """);
        var input = Input(new Dictionary<string, string>(), [new ResolutionInfo("only", "Only", true, "none", rules)]);
        var entry = Assert.Single(Resolution(await Run(input), "only").Entries);
        Assert.Equal(("src/Web/Web.config", Actions.Update), (entry.FilePath, entry.Action));
        Assert.Equal(["element <service> at system.serviceModel/services, line 4"], entry.Details);
        Assert.Equal(Actions.Delete, Assert.Single(entry.Reasons).Action);   // what the rule asked, kept in the reason
    }

    [Fact]
    public async Task DeletingATypeWhoseFileDeclaresOthers_UpdatesTheFile()
    {
        Write("src/Contracts/IOrderService.cs", """
            using System.ServiceModel;
            namespace Shop.Contracts
            {
                [ServiceContract] public interface IOrderService { OrderSummary GetOrder(int id); }
                public enum OrderState { Open, Closed }
            }
            """);
        var rest = Resolution(await Run(Input(new Dictionary<string, string> { ["wcf-service"] = "rest" })), "rest");
        var contract = Entry(rest, "src/Contracts/IOrderService.cs");
        Assert.Equal(Actions.Update, contract.Action);
        Assert.Equal(["removes IOrderService; the file also declares OrderState"], contract.Details);
        Assert.Equal(Actions.Delete, Entry(rest, "src/Web/Order.svc").Action);   // a whole file still goes
    }

    [Fact]
    public async Task AConfigFileEditedByTwoWorkItems_IsNotAConflict()
    {
        var input = Input(new Dictionary<string, string> { ["wcf-service"] = "rest" });
        input = input with
        {
            WorkItems = [.. input.WorkItems, new WorkItemSeed("t-config-key", null, "src/Services/Services.csproj", [new SeedFile("src/Web/Web.config", "SENSITIVE_CONFIG_KEY", null)])],
            Items = new Dictionary<string, CatalogItemInfo>(input.Items)
            {
                ["t-config-key"] = new("t-config-key", "Sensitive config key", [new ResolutionInfo("t-config-key-secret", "Move to a secret", true, "low", [])]),
            },
        };
        var config = (await Run(input)).Rollup.Single(f => f.FileKey == "src/Web/Web.config");
        Assert.Equal([("t-config-key", Actions.Update), ("wcf-service", Actions.Update)], config.WorkItems.Select(i => (i.ItemId, i.Action)));
        Assert.Empty(config.Conflicts);
    }

    [Fact]
    public async Task CopiesOfACodebase_EachWorkItemReachesItsOwnCopy()
    {
        foreach (var copy in new[] { "legacy", "modern" })
        {
            Write($"{copy}/Svc/IOrderService.cs", "namespace Shop { [System.ServiceModel.ServiceContract] public interface IOrderService { } }");
            Write($"{copy}/Svc/OrderService.cs", "namespace Shop { public class OrderService : IOrderService { } }");
            Write($"{copy}/Svc/Order.svc", "<%@ ServiceHost Service=\"Shop.OrderService\" %>");
            Write($"{copy}/Svc/Web.config", "<configuration><system.serviceModel><services><service name=\"Shop.OrderService\" /></services></system.serviceModel></configuration>");
        }

        var rules = Rules("""
            [
              {"id": "impl", "from": "seed", "select": "self", "action": "rewrite"},
              {"id": "contracts", "from": "impl", "traverse": "implemented_interfaces", "action": "delete"},
              {"id": "svc", "from": "impl", "traverse": "convention_files", "kind": "svc", "action": "delete"},
              {"id": "config", "from": "impl", "traverse": "config_elements", "path": "system.serviceModel/services", "action": "update"}
            ]
            """);
        var input = Input(new Dictionary<string, string>(), [new ResolutionInfo("only", "Only", true, "none", rules)],
            [new WorkItemSeed("wcf-service", null, "modern/Svc/Svc.csproj", [new SeedFile("modern/Svc/OrderService.cs", null, null)])]);
        var only = Resolution(await Run(input), "only");
        Assert.Equal(["modern/Svc/IOrderService.cs", "modern/Svc/Order.svc", "modern/Svc/OrderService.cs", "modern/Svc/Web.config"],
            only.Entries.Select(e => e.FilePath));
        Assert.All(only.Entries, e => Assert.Equal(Certainties.Confirmed, e.Certainty));
    }

    [Fact]
    public async Task APartialClassAcrossTwoFiles_IsOneCopy()
    {
        Write("web/Default.aspx", "<%@ Page Language=\"C#\" Inherits=\"Shop.Web.Default\" %>");
        Write("web/Default.aspx.cs", "namespace Shop.Web { public partial class Default { } }");
        Write("web/Default.aspx.designer.cs", "namespace Shop.Web { public partial class Default { } }");
        var rules = Rules("""
            [
              {"id": "code-behind", "from": "seed", "select": "self", "action": "rewrite"},
              {"id": "markup", "from": "code-behind", "traverse": "convention_files", "kind": "webforms_markup", "action": "delete"}
            ]
            """);
        var input = Input(new Dictionary<string, string>(), [new ResolutionInfo("only", "Only", true, "none", rules)],
            [new WorkItemSeed("wcf-service", null, "web/Web.csproj", [new SeedFile("web/Default.aspx.cs", null, null)])]);
        var markup = Entry(Resolution(await Run(input), "only"), "web/Default.aspx");
        Assert.Equal((Actions.Delete, Certainties.Confirmed), (markup.Action, markup.Certainty));
    }

    private const string HostRules = """
        [
          {"id": "host", "from": "seed", "select": "self", "filter": {"extension": ".cs"}, "action": "rewrite"},
          {"id": "svc-activation", "from": "seed", "select": "self", "filter": {"extension": ".svc"}, "action": "delete"},
          {"id": "host-entry-point", "create": "ASP.NET Core host entry point", "for_each": "svc-activation",
           "proposed_path": "{project.dir}/Program.cs", "action": "create"}
        ]
        """;

    private ImpactInput HostInput(string project, params string[] seeds) =>
        Input(new Dictionary<string, string>(), [new ResolutionInfo("web-host", "ASP.NET Core web host", true, "low", Rules(HostRules))],
            [new WorkItemSeed("wcf-service", null, project, seeds.Select(s => new SeedFile(s, null, null)).ToList())]) with
        {
            Projects = new ProjectMap(new Dictionary<string, string> { [project] = project[..project.LastIndexOf('/')] }),
        };

    [Fact]
    public async Task AnIisHostedService_DeletesItsSvcAndCreatesTheHost_NeverRewritesTheSvc()
    {
        var host = Resolution(await Run(HostInput("src/Web/Web.csproj", "src/Web/Order.svc")), "web-host");
        Assert.Equal([("src/Web/Order.svc", Actions.Delete), ("src/Web/Program.cs", Actions.Create)],
            host.Entries.Select(e => (e.FilePath ?? e.ProposedPath, e.Action)));
    }

    [Fact]
    public async Task ASelfHostedService_RewritesItsProgram_CreatesNothing()
    {
        Write("src/Host/Program.cs", "class Program { static void Main() { } }");
        var host = Resolution(await Run(HostInput("src/Host/Host.csproj", "src/Host/Program.cs")), "web-host");
        Assert.Equal([("src/Host/Program.cs", Actions.Rewrite)], host.Entries.Select(e => (e.FilePath, e.Action)));
    }

    [Fact]
    public async Task AProposedFileThatAlreadyExists_IsUpdated_NotCreated()
    {
        Write("src/Web/Program.cs", "class Program { }");
        var host = Resolution(await Run(HostInput("src/Web/Web.csproj", "src/Web/Order.svc")), "web-host");
        var program = Entry(host, "src/Web/Program.cs");
        Assert.Equal((Actions.Update, "src/Web/Program.cs"), (program.Action, program.FilePath));
        Assert.Contains("already exists", Assert.Single(program.Details));
    }

    [Fact]
    public async Task TwoWorkItemsDeletingOneSvc_Agree()
    {
        var input = HostInput("src/Web/Web.csproj", "src/Web/Order.svc");
        input = input with
        {
            WorkItems = [.. input.WorkItems, new WorkItemSeed("t-other", null, "src/Web/Web.csproj", [new SeedFile("src/Web/Order.svc", null, null)])],
            Items = new Dictionary<string, CatalogItemInfo>(input.Items)
            {
                ["t-other"] = new("t-other", "Other", [new ResolutionInfo("t-other-r", "R", true, "low", Rules(
                    """[{"id": "svc", "from": "seed", "select": "self", "action": "delete"}]"""))]),
            },
        };
        var svc = (await Run(input)).Rollup.Single(f => f.FileKey == "src/Web/Order.svc");
        Assert.Equal(2, svc.WorkItems.Count);
        Assert.Empty(svc.Conflicts);
        Assert.Equal(["svc-activation"], svc.WorkItems.Single(i => i.ItemId == "wcf-service").RuleIds);
    }

    [Fact]
    public async Task Review_IsCountedApart_NeverAsAChange()
    {
        var core = Resolution(await Run(Input(new Dictionary<string, string>())), "corewcf");
        // impl and contract updated, .svc deleted; the two data contracts only to review.
        Assert.Equal((3, 0, 2), (core.Changed, core.Created, core.ToReview));
    }

    [Fact]
    public async Task RepositorySummary_Reconciles()
    {
        var artifact = await Run(Input(new Dictionary<string, string> { ["wcf-service"] = "rest" }));
        var s = artifact.Summary;
        Assert.Equal(s.Changes, s.ByAction.Rewrite + s.ByAction.Update + s.ByAction.Delete);
        Assert.Equal((7, 7, 1, 0), (s.Changes, s.FilesChanged, s.NewFiles, s.FilesToReview));
    }

    // ---------- Work items from item-detection's occurrences ----------

    [Fact]
    public void WorkItems_SeedFromOccurrenceFilesAndEvidence_ProjectMetadataSeedsTheProjectFile()
    {
        var occurrences = JsonDocument.Parse("""
            {"projects": [{"projectPath": "src/Svc/Svc.csproj", "projectId": null, "items": [
              {"itemId": "wcf-service", "detectionState": "found", "occurrences": [
                {"filePath": "src/Svc/OrderService.cs", "evidence": [{"signal_name": "EXPOSES_WCF_SERVICE", "source_path": "src/Svc/OrderService.cs", "value": "IOrderService"}]},
                {"filePath": null, "evidence": [{"signal_name": "SVC_FILE", "source_path": "src/Web/Order.svc"}, {"signal_name": "X", "source_path": "x", "repository_level": true}]}]},
              {"itemId": "fx47-class-library", "detectionState": "found", "occurrences": [
                {"filePath": null, "evidence": [{"field": "frameworkFamily", "actual": "net-framework"}, {"field": "outputType", "actual": "Library"}]}]},
              {"itemId": "absent", "detectionState": "checked_absent", "occurrences": []}]}]}
            """).RootElement;
        var items = ImpactCli.WorkItems(occurrences);
        Assert.Equal(["wcf-service", "fx47-class-library"], items.Select(w => w.ItemId));
        Assert.Equal(["src/Svc/OrderService.cs", "src/Web/Order.svc"], items[0].Seeds.Select(s => s.Path));
        var metadata = Assert.Single(items[1].Seeds);
        Assert.Equal(("src/Svc/Svc.csproj", "project metadata", "frameworkFamily net-framework, outputType Library"), (metadata.Path, metadata.Signal, metadata.Value));
    }

    // ---------- Part G: hotspots and conflicts ----------

    private static (string, RollupWorkItem) On(string file, string item, string action, string source = "structural") =>
        (file, new RollupWorkItem { ItemId = item, ProjectPath = "p.csproj", ResolutionId = item + "-r", Action = action, Source = source, RuleIds = ["rule"] });

    [Fact]
    public void ThreeWorkItemsOnAFile_IsAHotspot_TwoIsNot()
    {
        var rollup = ImpactPipeline.Rollup([On("a.cs", "x", "update"), On("a.cs", "y", "rewrite"), On("a.cs", "z", "update", "client"), On("b.cs", "x", "update"), On("b.cs", "y", "update")]);
        Assert.True(rollup.Single(f => f.FileKey == "a.cs").Hotspot);
        Assert.False(rollup.Single(f => f.FileKey == "b.cs").Hotspot);
        Assert.Empty(rollup.SelectMany(f => f.Conflicts));   // rewrite with update, update with update: ordering only
    }

    [Fact]
    public void DeleteWithChange_AndCreateAtOnePath_AreConflicts_NamingBothWorkItems()
    {
        var rollup = ImpactPipeline.Rollup([On("a.cs", "x", "delete"), On("a.cs", "y", "update"), On("create:n.cs", "x", "create"), On("create:n.cs", "y", "create"), On("d.cs", "x", "delete"), On("d.cs", "y", "delete")]);
        var deleted = Assert.Single(rollup.Single(f => f.FileKey == "a.cs").Conflicts);
        Assert.Equal(("delete_with_change", "x", "y"), (deleted.Kind, deleted.First.ItemId, deleted.Second.ItemId));
        Assert.Equal("create_same_path", Assert.Single(rollup.Single(f => f.FileKey == "create:n.cs").Conflicts).Kind);
        Assert.Empty(rollup.Single(f => f.FileKey == "d.cs").Conflicts);   // delete with delete agrees
    }

    [Fact]
    public async Task Rollup_UsesEffectiveResolutionsOnly()
    {
        var artifact = await Run(Input(new Dictionary<string, string> { ["wcf-service"] = "rest" }));
        var impl = artifact.Rollup.Single(f => f.FileKey == "src/Services/OrderService.cs");
        Assert.Equal("rest", Assert.Single(impl.WorkItems).ResolutionId);
        Assert.Contains(artifact.Rollup, f => f.FileKey == "create:src/Services/Controllers/OrderServiceController.cs");
    }
}
