using Fingerprinting.Analysis;
using System.Text.Json;
using Fingerprinting.EntryPoints;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>Step 4 scanner 2.0.0: the seven kinds ported from the
/// find-dotnet-entry-points pattern catalog, the extended message
/// consumers, and the capability manifest.</summary>
public class EntryPointKindsV2Tests
{
    private static readonly Guid RepositoryId = Guid.Parse("11111111-2222-3333-4444-555555555555");

    private static List<EntryPointRecord> Detect(
        Dictionary<string, string> files, string projectPath, IReadOnlyList<(string Path, string Text)>? auxiliary = null,
        IReadOnlyList<string>? packages = null)
    {
        var source = ProjectSource.FromText(projectPath, files, packages, auxiliary);
        var repository = new RepositoryFiles(
            (auxiliary ?? []).Where(f => f.Path.EndsWith(".svc", StringComparison.OrdinalIgnoreCase)).ToList(),
            (auxiliary ?? []).Where(f => ConfigFile.IsConfigFileName(f.Path)).Select(f => ConfigFile.Parse(f.Path, f.Text)).ToList());
        return EntryPointPipeline.Detect(RepositoryId, new InputProject(projectPath, Guid.Empty, null, packages ?? []), source,
            WcfContractIndex.Build([source], repository), repository).EntryPoints.ToList();
    }

    private static EntryPointRecord Single(List<EntryPointRecord> entries, string kind) => Assert.Single(entries, e => e.Kind == kind);

    [Fact]
    public void Windows_services_record_their_hooks_name_and_where_they_are_run()
    {
        var entries = Detect(new()
        {
            ["src/Svc/OrderService.cs"] = """
                using System.ServiceProcess;
                public class OrderService : ServiceBase
                {
                    public OrderService() { ServiceName = "OrderProcessor"; }
                    protected override void OnStart(string[] args) { }
                    protected override void OnStop() { }
                }
                """,
            ["src/Svc/Program.cs"] = "static class Program { static void Main() { ServiceBase.Run(new OrderService()); } }",
        }, "src/Svc/Svc.csproj");

        var service = Single(entries, EntryPointKinds.WindowsService);
        Assert.Equal(("OrderService", "OnStart", "OrderProcessor", 1.0), (service.Handler.Type, service.Handler.Member, service.WindowsService!.ServiceName, service.Confidence));
        Assert.Equal(["OnStart", "OnStop"], service.WindowsService.Hooks);
        Assert.StartsWith("src/Svc/Program.cs:", service.WindowsService.RunAt);
        Assert.Null(service.AuthDeclared);
        // The Main that runs it is not a separate console entry point.
        Assert.DoesNotContain(entries, e => e.Kind == EntryPointKinds.ConsoleMain);
    }

    [Fact]
    public void A_ServiceBase_that_is_not_System_ServiceProcess_is_marked_down()
    {
        var service = Single(Detect(new() { ["src/Svc/Mine.cs"] = "public class Mine : ServiceBase { protected override void OnStart(string[] a) { } }" }, "src/Svc/Svc.csproj"),
            EntryPointKinds.WindowsService);
        Assert.Equal(0.7, service.Confidence);
    }

    [Fact]
    public void Http_handlers_and_modules_come_from_source_ashx_and_web_config()
    {
        const string webConfig = """
            <configuration>
              <system.web>
                <httpModules><add name="Audit" type="Shop.Web.AuditModule, Shop.Web" /></httpModules>
                <authorization><deny users="?" /></authorization>
              </system.web>
              <system.webServer>
                <modules>
                  <remove name="Session" />
                  <add name="Audit" type="Shop.Web.AuditModule, Shop.Web" preCondition="managedHandler" />
                  <add name="Session" type="Microsoft.AspNet.SessionState.SessionStateModuleAsync, Microsoft.AspNet.SessionState.SessionStateModule" />
                </modules>
                <handlers>
                  <add name="Extensionless" path="*." verb="GET,POST" modules="IsapiModule" scriptProcessor="aspnet_isapi.dll" />
                  <add name="Reports" path="reports.axd" verb="GET" type="Shop.Web.ReportHandler, Shop.Web" />
                </handlers>
              </system.webServer>
            </configuration>
            """;
        var entries = Detect(new()
        {
            ["src/Web/AuditModule.cs"] = "namespace Shop.Web { public class AuditModule : IHttpModule { public void Init(HttpApplication app) { } public void Dispose() { } } }",
            ["src/Web/ReportHandler.cs"] = "namespace Shop.Web { public class ReportHandler : IHttpHandler { public void ProcessRequest(HttpContext c) { } public bool IsReusable => true; } }",
            ["src/Web/Thumb.ashx.cs"] = "namespace Shop.Web { public class Thumb : HttpTaskAsyncHandler { public override Task ProcessRequestAsync(HttpContext c) => null; } }",
        }, "src/Web/Web.csproj",
        [
            ("src/Web/Web.config", webConfig),
            ("src/Web/Images/Thumb.ashx", """<%@ WebHandler Language="C#" Class="Shop.Web.Thumb" %>"""),
        ]).Where(e => e.Kind == EntryPointKinds.HttpHandler).ToList();

        var byType = entries.ToDictionary(e => e.Handler.Type);
        Assert.Equal(["AuditModule", "ReportHandler", "SessionStateModuleAsync", "Thumb"], byType.Keys.Order(StringComparer.Ordinal).ToList());

        // Registered twice (classic and integrated): one entry, both places.
        Assert.Equal(("module", "Init", true), (byType["AuditModule"].HttpHandler!.Role, byType["AuditModule"].Handler.Member, byType["AuditModule"].HttpHandler!.InRepository));
        Assert.Null(byType["AuditModule"].AuthDeclared);

        Assert.Equal(("reports.axd", "GET"), (byType["ReportHandler"].HttpHandler!.Path, byType["ReportHandler"].HttpHandler!.Verb));
        Assert.Equal(AuthDeclared.Declared, byType["ReportHandler"].AuthDeclared);

        Assert.Equal(("/Images/Thumb.ashx", "ProcessRequestAsync"), (byType["Thumb"].HttpHandler!.Path, byType["Thumb"].Handler.Member));

        // A package module with no source here, still recorded.
        var session = byType["SessionStateModuleAsync"].HttpHandler!;
        Assert.Equal((false, "Microsoft.AspNet.SessionState.SessionStateModuleAsync"), (session.InRepository, session.TypeName));
        Assert.StartsWith("src/Web/Web.config:", byType["SessionStateModuleAsync"].Handler.FilePath + ":");
    }

    [Fact]
    public void Global_asax_events_are_recorded_with_their_scope()
    {
        var entries = Detect(new()
        {
            ["src/Web/Global.asax.cs"] = """
                public class MvcApplication : System.Web.HttpApplication
                {
                    protected void Application_Start() { }
                    protected void Application_BeginRequest(object sender, EventArgs e) { }
                    protected void Session_Start(object sender, EventArgs e) { }
                    private void Helper() { }
                }
                """,
        }, "src/Web/Web.csproj").Where(e => e.Kind == EntryPointKinds.GlobalAsax).ToList();

        Assert.Equal(["Application_BeginRequest:request", "Application_Start:application", "Session_Start:session"],
            entries.Select(e => $"{e.GlobalAsax!.Event}:{e.GlobalAsax.Scope}").Order(StringComparer.Ordinal).ToList());
    }

    [Fact]
    public void Owin_startup_is_found_by_assembly_attribute_with_middleware_across_partials()
    {
        var entries = Detect(new()
        {
            ["src/Web/Startup.cs"] = """
                [assembly: OwinStartup(typeof(Shop.Web.Startup))]
                namespace Shop.Web {
                public partial class Startup
                {
                    public void Configuration(IAppBuilder app) { ConfigureAuth(app); app.Use<AuditMiddleware>(); }
                } }
                """,
            ["src/Web/App_Start/Startup.Auth.cs"] = """
                namespace Shop.Web {
                public partial class Startup
                {
                    public void ConfigureAuth(IAppBuilder app) { app.UseCookieAuthentication(new CookieAuthenticationOptions()); app.UseOpenIdConnectAuthentication(null); }
                } }
                """,
        }, "src/Web/Web.csproj");

        var owin = Single(entries, EntryPointKinds.OwinStartup);
        Assert.Equal(("Startup", "Configuration", "assembly_attribute"), (owin.Handler.Type, owin.Handler.Member, owin.OwinStartup!.DeclaredBy));
        Assert.Equal(["UseCookieAuthentication", "UseOpenIdConnectAuthentication", "Use<AuditMiddleware>"], owin.OwinStartup.Middleware);
    }

    [Fact]
    public void Owin_startup_by_convention_and_by_app_setting()
    {
        const string startup = "namespace Shop { public class Startup { public void Configuration(IAppBuilder app) { } } }";
        Assert.Equal("convention", Single(Detect(new() { ["src/Web/Startup.cs"] = startup }, "src/Web/Web.csproj"), EntryPointKinds.OwinStartup).OwinStartup!.DeclaredBy);

        var configured = Single(Detect(
            new() { ["src/Web/Boot.cs"] = "namespace Shop { public class Boot { public void Configuration(IAppBuilder app) { } } }" },
            "src/Web/Web.csproj",
            [("src/Web/Web.config", """<configuration><appSettings><add key="owin:appStartup" value="Shop.Boot" /></appSettings></configuration>""")]),
            EntryPointKinds.OwinStartup);
        Assert.Equal(("Boot", "app_setting"), (configured.Handler.Type, configured.OwinStartup!.DeclaredBy));
    }

    [Fact]
    public void Blazor_components_are_routable_per_page_directive()
    {
        var entries = Detect(new(), "src/Admin/Admin.csproj",
        [
            ("src/Admin/Pages/Edit.razor", "@page \"/admin/edit/{Id:int}\"\n@page \"/admin/items/{Id:int}/edit\"\n@attribute [Authorize(Roles = \"Admin\")]\n<h1>Edit</h1>\n"),
            ("src/Admin/Pages/Public.razor", "\n\n@page \"/about\"\n<p>About</p>\n"),
        ]).Where(e => e.Kind == EntryPointKinds.BlazorComponent).ToList();

        Assert.Equal(["/about", "/admin/edit/{Id:int}", "/admin/items/{Id:int}/edit"], entries.Select(e => e.Blazor!.Route).Order(StringComparer.Ordinal).ToList());
        Assert.All(entries.Where(e => e.Handler.Type == "Edit"), e => Assert.Equal(AuthDeclared.Declared, e.AuthDeclared));
        var about = entries.Single(e => e.Handler.Type == "Public");
        Assert.Equal((AuthDeclared.NoneDeclared, 3), (about.AuthDeclared, about.Handler.LineStart));
    }

    [Fact]
    public void Azure_functions_record_the_trigger_and_http_authorization_level()
    {
        var entries = Detect(new()
        {
            ["src/Fn/Orders.cs"] = """
                public static class Orders
                {
                    [FunctionName("GetOrder")]
                    public static Task<IActionResult> Get([HttpTrigger(AuthorizationLevel.Anonymous, "get", Route = "orders/{id}")] HttpRequest req, string id) => null;

                    [FunctionName("Nightly")]
                    public static void Run([TimerTrigger("0 0 2 * * *")] TimerInfo timer) { }
                }
                """,
            ["src/Fn/Queue.cs"] = """
                public class Queue
                {
                    [Function("Drain")]
                    public void Run([QueueTrigger("orders")] string message) { }

                    [Function("Keyed")]
                    public HttpResponseData Keyed([HttpTrigger(AuthorizationLevel.Function, "post")] HttpRequestData req) => null;
                }
                """,
        }, "src/Fn/Fn.csproj", packages: ["Microsoft.Azure.Functions.Worker"]).Where(e => e.Kind == EntryPointKinds.AzureFunction).ToList();

        var byName = entries.ToDictionary(e => e.Function!.FunctionName);
        Assert.Equal(("in_process", "HttpTrigger", "Anonymous", "orders/{id}", AuthDeclared.NoneDeclared),
            (byName["GetOrder"].Function!.Model, byName["GetOrder"].Function!.Trigger, byName["GetOrder"].Function!.AuthorizationLevel, byName["GetOrder"].Function!.Route, byName["GetOrder"].AuthDeclared));
        Assert.Equal(["GET"], byName["GetOrder"].Function!.Methods);
        Assert.Equal(("TimerTrigger", (string?)null), (byName["Nightly"].Function!.Trigger, byName["Nightly"].AuthDeclared));
        Assert.Equal(("isolated", "QueueTrigger"), (byName["Drain"].Function!.Model, byName["Drain"].Function!.Trigger));
        Assert.Equal(AuthDeclared.Declared, byName["Keyed"].AuthDeclared);
    }

    [Fact]
    public void Desktop_apps_replace_console_main_for_winforms_and_wpf()
    {
        var winforms = Single(Detect(new()
        {
            ["src/Desk/Program.cs"] = """
                using System.Windows.Forms;
                static class Program
                {
                    [STAThread]
                    static void Main() { var view = new CatalogView(); view.ShowDialog(); }
                }
                """,
        }, "src/Desk/Desk.csproj"), EntryPointKinds.DesktopApp);
        Assert.Equal(("winforms", "CatalogView", true), (winforms.Desktop!.Framework, winforms.Desktop.MainWindow, winforms.Desktop.StaThread));

        var wpfEntries = Detect(
            new() { ["src/Wpf/App.xaml.cs"] = "using System.Windows; namespace Shop { public partial class App : Application { protected override void OnStartup(StartupEventArgs e) { } } }" },
            "src/Wpf/Wpf.csproj",
            [("src/Wpf/App.xaml", "<Application x:Class=\"Shop.App\" StartupUri=\"MainWindow.xaml\" xmlns=\"http://schemas.microsoft.com/winfx/2006/xaml/presentation\"></Application>")]);
        var wpf = Single(wpfEntries, EntryPointKinds.DesktopApp);
        Assert.Equal(("wpf", "MainWindow.xaml", "App", "OnStartup"), (wpf.Desktop!.Framework, wpf.Desktop.MainWindow, wpf.Handler.Type, wpf.Handler.Member));
    }

    [Fact]
    public void MassTransit_NServiceBus_and_Rebus_consumers_are_recorded_per_message_type()
    {
        var entries = Detect(new()
        {
            ["src/Bus/OrderPlacedConsumer.cs"] = "using MassTransit; public class OrderPlacedConsumer : IConsumer<OrderPlaced> { public Task Consume(ConsumeContext<OrderPlaced> context) => null; }",
            ["src/Bus/Billing.cs"] = """
                using NServiceBus;
                public class Billing : IHandleMessages<OrderPlaced>, IHandleMessages<OrderCancelled>
                {
                    public Task Handle(OrderPlaced message, IMessageHandlerContext context) => null;
                    public Task Handle(OrderCancelled message, IMessageHandlerContext context) => null;
                }
                """,
            ["src/Bus/Shipping.cs"] = "using Rebus.Handlers; public class Shipping : IHandleMessages<OrderPlaced> { public Task Handle(OrderPlaced message) => null; }",
            ["src/Bus/KafkaWorker.cs"] = "public class KafkaWorker { private IConsumer<string, string> _c; public void Run() { _c.Subscribe(\"orders\"); _c.Consume(); } }",
        }, "src/Bus/Bus.csproj").Where(e => e.Kind == EntryPointKinds.MessageConsumer).ToList();

        Assert.Equal(
            ["kafka:orders", "masstransit:OrderPlaced", "nservicebus:OrderCancelled", "nservicebus:OrderPlaced", "rebus:OrderPlaced"],
            entries.Select(e => $"{e.Messaging!.Transport}:{e.Messaging.Sources.Single()}").Order(StringComparer.Ordinal).ToList());
        // A one-argument IConsumer<T> is MassTransit, not Kafka.
        Assert.DoesNotContain(entries, e => e.Handler.Type == "OrderPlacedConsumer" && e.Messaging!.Transport == "kafka");
    }

    // ---------- 2.1.0: origin and entry class ----------

    private const string ModulesConfig = """
        <configuration>
          <system.webServer>
            <modules>
              <add name="Audit" type="Shop.Shared.AuditModule, Shop.Shared" />
              <add name="Session" type="Microsoft.AspNet.SessionState.SessionStateModuleAsync, Microsoft.AspNet.SessionState.SessionStateModule" />
            </modules>
            <handlers>
              <add name="Transfer" path="*." verb="GET" type="System.Web.Handlers.TransferRequestHandler" />
            </handlers>
          </system.webServer>
        </configuration>
        """;

    [Fact]
    public void Registered_framework_and_package_types_are_framework_origin_and_the_rest_application()
    {
        var entries = Detect(
            new() { ["src/Web/Global.asax.cs"] = "public class App : System.Web.HttpApplication { protected void Application_Start() { } }" },
            "src/Web/Web.csproj", [("src/Web/Web.config", ModulesConfig)]);
        var byType = entries.Where(e => e.Kind == EntryPointKinds.HttpHandler).ToDictionary(e => e.Handler.Type);

        Assert.Equal(EntryPointOrigins.Framework, byType["SessionStateModuleAsync"].Origin);
        Assert.Equal(EntryPointOrigins.Framework, byType["TransferRequestHandler"].Origin);
        // Not declared by this project, and no repository-wide set given.
        Assert.Equal(EntryPointOrigins.Framework, byType["AuditModule"].Origin);
        Assert.All(entries.Where(e => e.Kind != EntryPointKinds.HttpHandler), e => Assert.Equal(EntryPointOrigins.Application, e.Origin));
    }

    [Fact]
    public void A_module_registered_in_one_project_and_declared_in_another_is_the_applications()
    {
        var source = ProjectSource.FromText("src/Web/Web.csproj", new Dictionary<string, string>(), null, [("src/Web/Web.config", ModulesConfig)]);
        var repository = new RepositoryFiles([], [ConfigFile.Parse("src/Web/Web.config", ModulesConfig)]);
        var repositoryTypes = new HashSet<string>(StringComparer.Ordinal) { "Shop.Shared.AuditModule" };
        var entries = EntryPointPipeline.Detect(RepositoryId, new InputProject("src/Web/Web.csproj", Guid.Empty, null, []), source,
            WcfContractIndex.Build([source], repository), repository, repositoryTypes).EntryPoints;

        var audit = entries.Single(e => e.Handler.Type == "AuditModule");
        Assert.Equal((EntryPointOrigins.Application, true), (audit.Origin, audit.HttpHandler!.InRepository));
        Assert.Equal(EntryPointOrigins.Framework, entries.Single(e => e.Handler.Type == "SessionStateModuleAsync").Origin);
    }

    [Fact]
    public void Lifecycle_hooks_are_classed_apart_and_never_carry_authentication()
    {
        var project = EntryPointPipeline.Detect(RepositoryId, new InputProject("src/Web/Web.csproj", Guid.Empty, null, []),
            ProjectSource.FromText("src/Web/Web.csproj", new Dictionary<string, string>
            {
                ["src/Web/Global.asax.cs"] = "public class App : System.Web.HttpApplication { protected void Application_Start() { } protected void Application_Error() { } }",
                ["src/Web/Startup.cs"] = "public class Startup { public void Configuration(IAppBuilder app) { } }",
                ["src/Web/OpenController.cs"] = "[Route(\"open\")] public class OpenController : ControllerBase { [HttpGet] public IActionResult Get() => null; }",
                ["src/Web/Handler.cs"] = "public class Ping : IHttpHandler { public void ProcessRequest(HttpContext c) { } }",
                ["src/Web/Module.cs"] = "public class Audit : IHttpModule { public void Init(HttpApplication a) { } }",
            }), WcfContractIndex.Empty);

        var byType = project.EntryPoints.GroupBy(e => e.Handler.Type).ToDictionary(g => g.Key, g => g.ToList());
        Assert.All(byType["App"], e => Assert.Equal(EntryClasses.Lifecycle, e.EntryClass));
        Assert.Equal(EntryClasses.Lifecycle, byType["Startup"].Single().EntryClass);
        Assert.Equal(EntryClasses.Lifecycle, byType["Audit"].Single().EntryClass);
        Assert.Equal(EntryClasses.Request, byType["Ping"].Single().EntryClass);
        Assert.Equal(EntryClasses.Request, byType["OpenController"].Single().EntryClass);
        Assert.All(project.EntryPoints.Where(e => e.EntryClass == EntryClasses.Lifecycle), e => Assert.Null(e.AuthDeclared));

        Assert.Equal((2, 4), (project.Summary.RequestEntryPointCount, project.Summary.LifecycleHookCount));
        // The open controller only; lifecycle hooks never count.
        Assert.Equal(1, project.Summary.NoDeclaredAuthenticationCount);
    }

    [Fact]
    public void The_published_capability_manifest_matches_what_the_scanner_detects()
    {
        var path = Path.Combine(AppContext.BaseDirectory, "schemas", $"entry-point-capabilities-{CapabilityManifest.Version}.json");
        using var manifest = JsonDocument.Parse(File.ReadAllText(path));
        var root = manifest.RootElement;

        Assert.Equal(CapabilityManifest.Version, root.GetProperty("manifestVersion").GetString());
        Assert.Equal(EntryPointPipeline.ScannerVersion, root.GetProperty("scannerVersion").GetString());
        var declared = root.GetProperty("kinds").EnumerateArray().Select(k => k.GetProperty("kind").GetString()!).Order(StringComparer.Ordinal).ToList();
        Assert.Equal(EntryPointKinds.All.Order(StringComparer.Ordinal).ToList(), declared);
        Assert.Equal(AuthDeclared.Scope, root.GetProperty("authDeclaredScope").GetString());
        Assert.NotEmpty(root.GetProperty("notCovered").EnumerateArray());
        Assert.Equal(declared, CapabilityManifest.Stamp().Kinds);

        // The manifest's entry class per kind is the one the scanner stamps.
        foreach (var kind in root.GetProperty("kinds").EnumerateArray().Where(k => k.GetProperty("kind").GetString() != EntryPointKinds.HttpHandler))
        {
            var probe = new EntryPointRecord
            {
                EntryPointId = "", Kind = kind.GetProperty("kind").GetString()!, ProjectPath = "",
                Handler = new HandlerLocation { Type = "T", FilePath = "f", LineStart = 1, LineEnd = 1 }, Confidence = 1,
            };
            Assert.Equal(EntryClasses.For(probe), kind.GetProperty("entryClass").GetString());
        }
    }
}
