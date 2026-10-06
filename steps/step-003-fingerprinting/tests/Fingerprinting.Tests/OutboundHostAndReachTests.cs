using Fingerprinting.Analysis;
using Fingerprinting.Outbound;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>Step 5, 1.3.0 — 29-STEPS-004-005-INVENTORIES.md Part C9: a class
/// library's configuration through its hosts, Web Deploy SetParameters,
/// invocation call sites, and which backend calls each entry point reaches.
/// The fixture is the WCF sample's FundsTransfer slice.</summary>
public class OutboundHostAndReachTests
{
    private static readonly Guid RepositoryId = Guid.Parse("11111111-2222-3333-4444-555555555555");

    private const string Library = "src/Catalog.Services/Catalog.Services.csproj";
    private const string Host = "src/Catalog.Host/Catalog.Host.csproj";
    private const string SecondHost = "src/Batch.Host/Batch.Host.csproj";

    private const string Reference = """
        namespace WcfCatalog.Services.FundsTransferWS
        {
            [System.ServiceModel.ServiceContractAttribute(ConfigurationName="FundsTransferWS.FundsTransferWSSoap")]
            public interface FundsTransferWSSoap
            {
                [System.ServiceModel.OperationContractAttribute] string PlaceRealTimeFTOrder(string request);
                [System.ServiceModel.OperationContractAttribute] RTFTInquiryResponse RealTimeFTInquiry(string orderId);
            }

            [System.CodeDom.Compiler.GeneratedCodeAttribute("System.ServiceModel", "4.0.0.0")]
            public partial class FundsTransferWSSoapClient : System.ServiceModel.ClientBase<FundsTransferWSSoap>, FundsTransferWSSoap
            {
                public FundsTransferWSSoapClient() { }
                public string PlaceRealTimeFTOrder(string request) => base.Channel.PlaceRealTimeFTOrder(request);
                public RTFTInquiryResponse RealTimeFTInquiry(string orderId) => base.Channel.RealTimeFTInquiry(orderId);
            }
        }
        """;

    // Line numbers matter: the assertions name them.
    private const string Service = """
        using WcfCatalog.Services.FundsTransferWS;
        public class FundsTransferService
        {
            private readonly TransferQueue transferQueue = new TransferQueue();
            public string PlaceFundsTransfer(Item item)
            {
                if (item.IsPracticeAccount)
                {
                    return transferQueue.PlacePracticeFTOrder(item);
                }
                else
                {
                    using (FundsTransferWSSoapClient service = new FundsTransferWSSoapClient())
                    {
                        return service.PlaceRealTimeFTOrder(Log(item));
                    }
                }
            }
            public void ProcessTransferQueue(List<Item> items)
            {
                for (int i = 0; i < items.Count; i++)
                {
                    Send(items[i]);
                }
            }
            private void Send(Item item)
            {
                using (FundsTransferWSSoapClient service = new FundsTransferWSSoapClient())
                {
                    service.PlaceRealTimeFTOrder(item.ToString());
                }
            }
            public Status GetFundsTransferStatus(string orderId)
            {
                var practice = transferQueue.GetPracticeFTOrder(orderId);
                if (practice != null)
                {
                    return practice;
                }
                using (FundsTransferWSSoapClient service = new FundsTransferWSSoapClient())
                {
                    return Map(service.RealTimeFTInquiry(orderId));
                }
            }
            public List<Item> GetTransferHistory() => transferQueue.GetTransferHistory();
            private string Log(Item item) => item.ToString();
            private Status Map(RTFTInquiryResponse r) => null;
        }
        """;

    private const string HostConfig = """
        <configuration>
          <system.serviceModel>
            <client>
              <endpoint address="http://localhost:8090/FundsTransferWS.asmx" binding="basicHttpBinding"
                        contract="FundsTransferWS.FundsTransferWSSoap" name="FundsTransferWSSoap" />
            </client>
          </system.serviceModel>
        </configuration>
        """;

    private const string Declarations = """
        <parameters>
          <parameter name="FundsTransferWSURL" defaultValue="http://localhost:8090/FundsTransferWS.asmx">
            <parameterEntry kind="XmlFile" scope="x" match="/configuration/system.serviceModel/client/endpoint[@name='FundsTransferWSSoap']/@address" />
          </parameter>
          <parameter name="LogDirectory">
            <parameterEntry kind="XmlFile" scope="x" match="/configuration/appSettings/add[@key='LogDirectory']/@value" />
          </parameter>
        </parameters>
        """;

    private static string SetParam(string url) => $"""
        <parameters>
          <setParameter name="FundsTransferWSURL" value="{url}" />
          <setParameter name="LogDirectory" value="G:\Logs\WcfCatalog\FundsTransfer\" />
          <setParameter name="FundsTransferUserId" value="BATCHSVC" />
        </parameters>
        """;

    private static readonly IReadOnlyList<(string, string)> SetParamFiles =
    [
        ("CustomFiles/Catalog.Host/SetParamFiles/DEV/SetParam.xml", SetParam("http://appsrv0341/FundsTransferWS/FundsTransferWS.asmx")),
        ("CustomFiles/Catalog.Host/SetParamFiles/PROD/SetParam.xml", SetParam("http://ftmt.corp.example.com/FundsTransferWS/FundsTransferWS.asmx")),
    ];

    private static readonly IReadOnlyList<InboundEntryPoint> EntryPoints =
    [
        new("ep-place", Library, "wcf_operation", "FundsTransferService", "PlaceFundsTransfer", "src/Catalog.Services/FundsTransferService.cs", 5),
        new("ep-process", Library, "wcf_operation", "FundsTransferService", "ProcessTransferQueue", "src/Catalog.Services/FundsTransferService.cs", 19),
        new("ep-status", Library, "wcf_operation", "FundsTransferService", "GetFundsTransferStatus", "src/Catalog.Services/FundsTransferService.cs", 33),
        new("ep-history", Library, "wcf_operation", "FundsTransferService", "GetTransferHistory", "src/Catalog.Services/FundsTransferService.cs", 45),
    ];

    private const string TransferQueueWithDatabase = """
        public class TransferQueue
        {
            public string PlacePracticeFTOrder(Item item) => "P";
            public Status GetPracticeFTOrder(string id) => null;
            public List<Item> GetTransferHistory() { using (var c = new SqlConnection(ConfigurationManager.ConnectionStrings["Transfers"].ConnectionString)) { return null; } }
        }
        """;

    private static IReadOnlyList<ProjectInvocations> Run(
        bool withDeclarations = true, bool secondHost = false, string? transferQueue = null)
    {
        var projects = new List<(OutboundInputProject, ProjectSource)>
        {
            (new OutboundInputProject(Library, Guid.NewGuid(), null, [], []) { OutputType = "Library", ProjectSdk = "Microsoft.NET.Sdk" },
                ProjectSource.FromText(Library, new Dictionary<string, string>
                {
                    ["src/Catalog.Services/Service References/FundsTransferWS/Reference.cs"] = Reference,
                    ["src/Catalog.Services/FundsTransferService.cs"] = Service,
                    ["src/Catalog.Services/TransferQueue.cs"] = transferQueue ?? "public class TransferQueue { public string PlacePracticeFTOrder(Item i) => \"P\"; public Status GetPracticeFTOrder(string id) => null; public List<Item> GetTransferHistory() => null; }",
                })),
            (new OutboundInputProject(Host, Guid.NewGuid(), null, [], []) { OutputType = "Exe", ProjectSdk = "Microsoft.NET.Sdk" },
                ProjectSource.FromText(Host, new Dictionary<string, string> { ["src/Catalog.Host/Program.cs"] = "class Program { static void Main() { } }" })),
        };
        var configFiles = new List<(string, string)> { ("src/Catalog.Host/App.config", HostConfig) };
        var references = new List<(string, string)> { (Host, Library) };
        if (secondHost)
        {
            projects.Add((new OutboundInputProject(SecondHost, Guid.NewGuid(), null, [], []) { OutputType = "Exe" },
                ProjectSource.FromText(SecondHost, new Dictionary<string, string> { ["src/Batch.Host/Program.cs"] = "class Program { static void Main() { } }" })));
            configFiles.Add(("src/Batch.Host/App.config", HostConfig.Replace("http://localhost:8090/FundsTransferWS.asmx", "https://ftmt-batch.corp.example.com/FundsTransferWS.asmx")));
            references.Add((SecondHost, Library));
        }

        var paths = projects.Select(p => p.Item1.RelativePath).ToList();
        var config = RepositoryConfig.FromText(configFiles)
            .WithDeployParameters(DeployParameterFiles.FromText(SetParamFiles, paths),
                withDeclarations ? new Dictionary<string, string> { ["src/Catalog.Host"] = Declarations } : new Dictionary<string, string>());
        config = config.WithHosts(OutboundPipeline.ResolveHosts(projects.Select(p => p.Item1).ToList(), references, config));
        return OutboundPipeline.Detect(RepositoryId, projects, config, EntryPoints);
    }

    // ---------- 1. configuration through the host ----------

    [Fact]
    public void A_library_client_takes_its_hosts_configuration_and_is_one_invocation()
    {
        var projects = Run();
        var library = projects.Single(p => p.ProjectPath == Library);
        var client = Assert.Single(library.Invocations, i => i.Mechanism == Mechanisms.SoapClient);

        Assert.Equal(("FundsTransferWSSoap", "basicHttpBinding", "config"), (client.Soap!.Contract, client.Soap.Binding, client.Soap.BindingSource));
        Assert.Equal(("localhost", 8090, Resolutions.Resolved), (client.Endpoint.Host, client.Endpoint.Port, client.Endpoint.Resolution));
        Assert.Contains(client.ConfidenceReasons, r => r.Contains("src/Catalog.Host/Catalog.Host.csproj"));
        var defaultBinding = Assert.Single(client.EnvironmentBindings, b => b.Environment == "default");
        Assert.Equal((Host, "src/Catalog.Host/App.config"), (defaultBinding.HostProject, defaultBinding.SourceFile));

        // The host no longer reports the entry as configured but never constructed.
        Assert.DoesNotContain(projects.Single(p => p.ProjectPath == Host).Invocations, i => i.Mechanism == Mechanisms.SoapClient);
    }

    [Fact]
    public void A_library_referenced_by_two_hosts_gets_one_binding_per_host()
    {
        var client = Run(secondHost: true).Single(p => p.ProjectPath == Library).Invocations.Single(i => i.Mechanism == Mechanisms.SoapClient);
        var defaults = client.EnvironmentBindings.Where(b => b.Environment == "default").Select(b => (b.HostProject, b.Host)).Order().ToList();
        Assert.Equal([(SecondHost, "ftmt-batch.corp.example.com"), (Host, "localhost")], defaults);
    }

    // ---------- 2. SetParameters ----------

    [Fact]
    public void Every_SetParam_environment_is_a_binding_linked_by_parameters_xml()
    {
        var client = Run().Single(p => p.ProjectPath == Library).Invocations.Single(i => i.Mechanism == Mechanisms.SoapClient);
        var dev = Assert.Single(client.EnvironmentBindings, b => b.Environment == "DEV");
        var prod = Assert.Single(client.EnvironmentBindings, b => b.Environment == "PROD");

        Assert.Equal(("appsrv0341", "/FundsTransferWS/FundsTransferWS.asmx"), (dev.Host, dev.Path));
        Assert.Equal("ftmt.corp.example.com", prod.Host);
        Assert.All([dev, prod], b => Assert.Equal(("FundsTransferWSURL", "parameters_xml", 1.0, Host),
            (b.DeployParameter, b.LinkMethod, b.LinkConfidence, b.HostProject)));
        Assert.Equal("CustomFiles/Catalog.Host/SetParamFiles/PROD/SetParam.xml", prod.SourceFile);
    }

    [Fact]
    public void Without_parameters_xml_the_name_and_path_link_at_lower_confidence()
    {
        var client = Run(withDeclarations: false).Single(p => p.ProjectPath == Library).Invocations.Single(i => i.Mechanism == Mechanisms.SoapClient);
        var prod = Assert.Single(client.EnvironmentBindings, b => b.Environment == "PROD");
        // FundsTransferWSURL ~ FundsTransferWSSoap, and FundsTransferWS.asmx is the path's last segment.
        Assert.Equal(("name_and_path", 0.8), (prod.LinkMethod, prod.LinkConfidence));
    }

    [Fact]
    public void SetParam_values_are_kept_only_for_linked_urls_and_paths()
    {
        var host = Run().Single(p => p.ProjectPath == Host);
        var prod = host.DeployParameters.Where(p => p.Environment == "PROD").ToDictionary(p => p.Name);
        // Normalised as the binding holds it: scheme, host, port, path.
        Assert.Equal("http://ftmt.corp.example.com:80/FundsTransferWS/FundsTransferWS.asmx", prod["FundsTransferWSURL"].Value);
        Assert.Equal(@"G:\Logs\WcfCatalog\FundsTransfer\", prod["LogDirectory"].Value);
        Assert.Equal(("other", null), (prod["FundsTransferUserId"].Kind, prod["FundsTransferUserId"].Value));
        Assert.Equal(("client_endpoint", "FundsTransferWSSoap"), (prod["FundsTransferWSURL"].LinkedKind, prod["FundsTransferWSURL"].LinkedName));
    }

    [Fact]
    public void An_unqualified_host_makes_its_environment_require_change()
    {
        var client = Run().Single(p => p.ProjectPath == Library).Invocations.Single(i => i.Mechanism == Mechanisms.SoapClient);
        var dev = Assert.Single(client.EnvironmentBindings, b => b.Environment == "DEV");
        Assert.Equal(Verdicts.RequiresChange, dev.LinuxVerdict);
        Assert.Contains(dev.LinuxReasons, r => r.Contains("unqualified hostname 'appsrv0341'"));
        Assert.Equal(Verdicts.Compatible, client.EnvironmentBindings.Single(b => b.Environment == "PROD").LinuxVerdict);
        Assert.Equal(Verdicts.RequiresChange, client.LinuxCompatibility.Verdict);
    }

    // ---------- 3. call sites are invocations ----------

    [Fact]
    public void Call_sites_are_where_operations_are_invoked_and_construction_is_kept_apart()
    {
        var client = Run().Single(p => p.ProjectPath == Library).Invocations.Single(i => i.Mechanism == Mechanisms.SoapClient);
        Assert.Equal([15, 30, 42], client.CallSites.Select(c => c.LineStart));
        Assert.Equal([13, 28, 40], client.ConstructionSites.Select(c => c.LineStart));
        Assert.Equal(["PlaceRealTimeFTOrder", "PlaceRealTimeFTOrder", "RealTimeFTInquiry"], client.Operations.Select(o => o.Operation));
    }

    // ---------- 4. entry point → backend calls ----------

    [Fact]
    public void Each_entry_point_records_the_backend_calls_it_reaches_with_depth_condition_and_loop()
    {
        var reach = Run().Single(p => p.ProjectPath == Library).EntryPointBackend.ToDictionary(e => e.EntryPointId);

        var place = Assert.Single(reach["ep-place"].Calls);
        Assert.Equal((BackendReach.Yes, "PlaceRealTimeFTOrder", 15, 0, true, false),
            (reach["ep-place"].Status, place.Operation, place.CallSite.LineStart, place.Depth, place.Conditional, place.InLoop));
        Assert.Contains("else of if (item.IsPracticeAccount)", place.Context);

        // Through a method of the same class, inside the loop.
        var process = Assert.Single(reach["ep-process"].Calls);
        Assert.Equal((1, true, 30), (process.Depth, process.InLoop, process.CallSite.LineStart));
        Assert.Equal(["ProcessTransferQueue", "Send"], process.Via);

        // After an early return for practice accounts: conditional.
        var status = Assert.Single(reach["ep-status"].Calls);
        Assert.Equal(("RealTimeFTInquiry", true, false), (status.Operation, status.Conditional, status.InLoop));
        Assert.Contains(status.Context, c => c.StartsWith("after early return: if (practice != null)"));

        // A call to nothing that reaches a backend: No, never guessed.
        Assert.Equal(BackendReach.No, reach["ep-history"].Status);
    }

    [Fact]
    public void A_path_through_another_class_that_makes_backend_calls_is_unresolved_not_followed()
    {
        var reach = Run(transferQueue: TransferQueueWithDatabase).Single(p => p.ProjectPath == Library).EntryPointBackend.ToDictionary(e => e.EntryPointId);
        Assert.Equal(BackendReach.Unresolved, reach["ep-history"].Status);
        Assert.Contains(reach["ep-history"].Unresolved, u => u.Reason.StartsWith("TransferQueue.GetTransferHistory: another class"));
        // Its own backend call is still found, with the unfollowed path beside it.
        Assert.Equal(BackendReach.Yes, reach["ep-status"].Status);
        Assert.NotEmpty(reach["ep-status"].Unresolved);
    }
}
