using Fingerprinting.Domain;
using Fingerprinting.EntryPoints;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>Step 4 as a signal producer (scanner 2.2.0, registry 1.8.0): a WCF
/// service split across projects, as in the WCF sample.</summary>
public class ArchitectureSignalsTests
{
    private const string Contracts = "src/Catalog.Contracts/Catalog.Contracts.csproj";
    private const string Services = "src/Catalog.Services/Catalog.Services.csproj";
    private const string Host = "src/Catalog.Host/Catalog.Host.csproj";
    private const string Web = "src/Web/Web.csproj";

    private static EntryPointRecord Wcf(string operation, string origin = EntryPointOrigins.Application) => new()
    {
        EntryPointId = "ep-" + operation,
        Kind = EntryPointKinds.WcfOperation,
        ProjectPath = Services,
        Origin = origin,
        Handler = new HandlerLocation { Type = "AccountService", Member = operation, FilePath = "src/Catalog.Services/AccountService.cs", LineStart = 10, LineEnd = 12 },
        Confidence = 1.0,
        Wcf = new WcfDetail
        {
            Contract = "IAccountService",
            Operation = operation,
            Endpoints =
            [
                new WcfEndpointDetail { HostKind = "service_host", HostedAt = "src/Catalog.Host/Program.cs:62 via BuildTcpHost", Binding = "netTcpBinding",
                    SecuritySource = "declared", Source = "code", DeclaredAt = "src/Catalog.Host/Program.cs:62" },
                new WcfEndpointDetail { HostKind = "svc", HostedAt = "src/Hosting.Iis/Account.svc:1", Binding = "basicHttpBinding",
                    SecuritySource = "binding_default", Source = "config", DeclaredAt = "src/Hosting.Iis/Web.config:10" },
            ],
        },
    };

    private static ProjectEntryPoints Project(string path, params EntryPointRecord[] entries) => new()
    {
        ProjectId = Guid.NewGuid(),
        ProjectPath = path,
        Status = "SCANNED",
        Summary = new ProjectEntryPointSummary(),
        EntryPoints = entries,
    };

    private static IReadOnlyDictionary<string, IReadOnlyList<Signal>> Build(params ProjectEntryPoints[] projects) =>
        ArchitectureSignals.Build(projects, [Contracts, Services, Host, Web]);

    [Fact]
    public void The_implementing_project_exposes_the_service_and_the_host_project_hosts_it()
    {
        var signals = Build(Project(Services, Wcf("GetAccount"), Wcf("UpdateContactInfo")), Project(Host), Project(Contracts));

        var exposes = Assert.Single(signals[Services], s => s.Name == ArchitectureSignals.ExposesWcfService);
        Assert.Equal(("IAccountService", "src/Catalog.Services/AccountService.cs", 2, "EntryPointInventory"),
            (exposes.Value, exposes.SourcePath, exposes.OccurrenceCount, exposes.Extractor));
        Assert.Equal("AccountService", exposes.Evidence[0].DeclaringType);

        // Hosting is recorded on the implementing project, every host — the
        // .svc folder has no project file and says so.
        Assert.Equal(["IIS .svc in src/Hosting.Iis (no project file)", $"ServiceHost in {Host}"],
            signals[Services].Where(s => s.Name == ArchitectureSignals.WcfServiceHosting).Select(s => s.Value!).Order());

        var hosts = Assert.Single(signals[Host], s => s.Name == ArchitectureSignals.HostsWcfService);
        Assert.Equal(("IAccountService", "src/Catalog.Host/Program.cs", 62, "via BuildTcpHost"),
            (hosts.Value, hosts.SourcePath, hosts.Evidence[0].LineStart, hosts.Evidence[0].Member));

        // The contracts project carries nothing: declaring an interface exposes no service.
        Assert.False(signals.ContainsKey(Contracts));
    }

    [Fact]
    public void Framework_origin_entry_points_expose_nothing_and_http_actions_expose_an_api()
    {
        var action = new EntryPointRecord
        {
            EntryPointId = "ep-http",
            Kind = EntryPointKinds.HttpControllerAction,
            ProjectPath = Web,
            Handler = new HandlerLocation { Type = "OrdersController", Member = "Get", FilePath = "src/Web/OrdersController.cs", LineStart = 5, LineEnd = 5 },
            Confidence = 1.0,
        };
        var signals = Build(Project(Services, Wcf("GetAccount", EntryPointOrigins.Framework)), Project(Web, action));

        Assert.False(signals.ContainsKey(Services));
        Assert.Equal(("EXPOSES_HTTP_API", "OrdersController"), (signals[Web][0].Name, signals[Web][0].Value));
    }
}
