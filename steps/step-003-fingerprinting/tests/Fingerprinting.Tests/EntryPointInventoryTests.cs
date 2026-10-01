using Fingerprinting.Analysis;
using Fingerprinting.Domain;
using Fingerprinting.EntryPoints;
using Fingerprinting.EntryPoints.Cli;
using Fingerprinting.StepHost;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>Step 4, entry-point-inventory â€” the acceptance criteria in
/// 29-STEPS-004-005-INVENTORIES.md, one or more tests each.</summary>
public class EntryPointInventoryTests
{
    private static readonly Guid RepositoryId = Guid.Parse("11111111-2222-3333-4444-555555555555");

    /// <summary><paramref name="auxiliary"/> holds the non-C# files: .svc,
    /// .proto, .cshtml, web.config and app.config. The .svc and config files
    /// also form the repository-wide set the WCF host index reads.</summary>
    private static List<EntryPointRecord> Detect(
        Dictionary<string, string> files, string projectPath = "src/Api/Api.csproj",
        IReadOnlyList<string>? packages = null, IReadOnlyList<(string, string)>? auxiliary = null)
    {
        var source = ProjectSource.FromText(projectPath, files, packages, auxiliary);
        var repository = Repository(auxiliary);
        var project = new InputProject(projectPath, Guid.Empty, null, packages ?? []);
        return EntryPointPipeline.Detect(RepositoryId, project, source, WcfContractIndex.Build([source], repository), repository)
            .EntryPoints.ToList();
    }

    private static RepositoryFiles Repository(IReadOnlyList<(string Path, string Text)>? files) => new(
        (files ?? []).Where(f => f.Path.EndsWith(".svc", StringComparison.OrdinalIgnoreCase)).ToList(),
        (files ?? []).Where(f => ConfigFile.IsConfigFileName(f.Path)).Select(f => ConfigFile.Parse(f.Path, f.Text)).ToList());

    private static List<EntryPointRecord> Http(Dictionary<string, string> files) =>
        Detect(files).Where(e => e.Http is not null).ToList();

    // ---------- B2: controller route composition ----------

    [Fact]
    public void Controller_route_composes_with_the_verb_template_and_resolves_controller()
    {
        var entries = Http(new()
        {
            ["src/Api/AccountsController.cs"] = """
                [ApiController]
                [Route("api/[controller]")]
                public class AccountsController : ControllerBase
                {
                    [HttpGet("{id}")]
                    [Authorize(Policy = "AccountRead")]
                    public ActionResult<AccountDto> GetById(int id) => null;
                }
                """,
        });

        var entry = Assert.Single(entries);
        Assert.Equal("GET", entry.Http!.Verb);
        Assert.Equal("api/accounts/{id}", entry.Http.RouteTemplate);
        Assert.Equal(HttpRouting.Attribute, entry.Http.Routing);
        Assert.Equal("ActionResult<AccountDto>", entry.Http.ReturnType);
        Assert.Equal("[Authorize(Policy = \"AccountRead\")]", entry.Http.Authorisation);
        Assert.Equal(AuthDeclared.Declared, entry.AuthDeclared);
        var parameter = Assert.Single(entry.Http.Parameters);
        Assert.Equal(("id", "int", "inferred", "route"), (parameter.Name, parameter.Type, parameter.Source, parameter.InferredSource));
        Assert.Equal(("AccountsController", "GetById"), (entry.Handler.Type, entry.Handler.Member));
        Assert.True(entry.Confidence < 1.0);
        Assert.Contains(entry.ConfidenceReasons, r => r.Contains("[controller]"));
    }

    [Fact]
    public void Action_and_area_tokens_resolve_and_a_missing_area_is_left_unresolved()
    {
        var entries = Http(new()
        {
            ["src/Api/ReportsController.cs"] = """
                [Area("Admin")]
                [Route("[area]/[controller]/[action]")]
                public class ReportsController : Controller
                {
                    [HttpGet] public IActionResult Monthly() => null;
                }

                [Route("[area]/[controller]")]
                public class OrphanController : Controller
                {
                    [HttpGet] public IActionResult Index() => null;
                }
                """,
        });

        var reports = entries.Single(e => e.Handler.Type == "ReportsController");
        Assert.Equal("Admin/reports/Monthly", reports.Http!.RouteTemplate);

        var orphan = entries.Single(e => e.Handler.Type == "OrphanController");
        Assert.Equal("[area]/orphan", orphan.Http!.RouteTemplate);
        Assert.Equal(0.5, orphan.Confidence);
        Assert.Contains(orphan.ConfidenceReasons, r => r.Contains("[area] has no [Area] attribute"));
    }

    [Fact]
    public void An_action_template_starting_with_a_slash_replaces_rather_than_appends()
    {
        var entries = Http(new()
        {
            ["src/Api/HealthController.cs"] = """
                [Route("api/health")]
                public class HealthController : ControllerBase
                {
                    [HttpGet("/status")] public IActionResult Status() => null;
                    [HttpGet("~/ping")] public IActionResult Ping() => null;
                    [HttpGet("deep")] public IActionResult Deep() => null;
                }
                """,
        });

        Assert.Equal(["api/health/deep", "ping", "status"], entries.Select(e => e.Http!.RouteTemplate).Order().ToList());
    }

    [Fact]
    public void Multiple_route_and_verb_attributes_produce_one_entry_each()
    {
        var entries = Http(new()
        {
            ["src/Api/ItemsController.cs"] = """
                [Route("api/items")]
                [Route("api/v2/items")]
                public class ItemsController : ControllerBase
                {
                    [HttpGet("{id}")]
                    [HttpHead("{id}")]
                    public IActionResult Get(int id) => null;
                }
                """,
        });

        Assert.Equal(4, entries.Count);
        Assert.Equal(
            ["GET api/items/{id}", "GET api/v2/items/{id}", "HEAD api/items/{id}", "HEAD api/v2/items/{id}"],
            entries.Select(e => $"{e.Http!.Verb} {e.Http.RouteTemplate}").Order().ToList());
        Assert.Equal(4, entries.Select(e => e.EntryPointId).Distinct().Count());
    }

    [Fact]
    public void Conventional_routing_records_a_null_template_with_controller_and_action()
    {
        var entries = Detect(new()
        {
            ["src/Web/Controllers/CatalogController.cs"] = """
                public class CatalogController : Controller
                {
                    public ActionResult Index(int pageSize = 10) => View();
                    [HttpPost] public ActionResult Edit(CatalogItem item) => View();
                    private void Helper() { }
                    [NonAction] public void NotAnAction() { }
                }
                """,
            ["src/Web/App_Start/RouteConfig.cs"] = """
                public static class RouteConfig
                {
                    public static void RegisterRoutes(RouteCollection routes) =>
                        routes.MapRoute(name: "Default", url: "{controller}/{action}/{id}");
                }
                """,
        }, "src/Web/Web.csproj");

        var project = EntryPointPipeline.Detect(RepositoryId, new InputProject("src/Web/Web.csproj", Guid.Empty, null, []),
            ProjectSource.FromText("src/Web/Web.csproj", new Dictionary<string, string>
            {
                ["src/Web/App_Start/RouteConfig.cs"] = "class C { void M(RouteCollection routes) => routes.MapRoute(name: \"Default\", url: \"{controller}/{action}/{id}\"); }",
            }), WcfContractIndex.Empty);
        Assert.Contains(project.Summary.ConventionalRoutes, r => r.StartsWith("MapRoute Default: {controller}/{action}/{id}", StringComparison.Ordinal));

        Assert.Equal(2, entries.Count(e => e.Kind == EntryPointKinds.HttpControllerAction));
        Assert.All(entries.Where(e => e.Http is not null), e =>
        {
            Assert.Equal(HttpRouting.Conventional, e.Http!.Routing);
            Assert.Null(e.Http.RouteTemplate);
            Assert.Equal("catalog", e.Http.Controller);
        });
        Assert.Equal(["ANY Index", "POST Edit"], entries.Where(e => e.Http is not null).Select(e => $"{e.Http!.Verb} {e.Http.Action}").Order().ToList());
    }

    [Fact]
    public void No_verb_attribute_on_an_ApiController_is_ANY_at_0_7()
    {
        var entry = Assert.Single(Http(new()
        {
            ["src/Api/FilesController.cs"] = """
                [ApiController, Route("api/files")]
                public class FilesController : ControllerBase
                {
                    public IActionResult Index([FromQuery] string filter, Upload body) => null;
                }
                """,
        }));

        Assert.Equal("ANY", entry.Http!.Verb);
        Assert.Equal(0.7, entry.Confidence);
        Assert.Equal(("filter", "query", null), (entry.Http.Parameters[0].Name, entry.Http.Parameters[0].Source, entry.Http.Parameters[0].InferredSource));
        Assert.Equal(("body", "inferred", "body"), (entry.Http.Parameters[1].Name, entry.Http.Parameters[1].Source, entry.Http.Parameters[1].InferredSource));
    }

    [Fact]
    public void Controller_base_and_route_are_followed_through_an_in_project_base_class()
    {
        var entry = Assert.Single(Http(new()
        {
            ["src/Api/BaseApiController.cs"] = """
                [Route("api/[controller]/[action]")]
                [ApiController]
                public abstract class BaseApiController : ControllerBase { }
                """,
            ["src/Api/OrdersController.cs"] = """
                public class OrdersController : BaseApiController
                {
                    [HttpGet] public IActionResult Recent() => null;
                }
                """,
        }));

        Assert.Equal("api/orders/Recent", entry.Http!.RouteTemplate);
        Assert.Contains(entry.ConfidenceReasons, r => r.Contains("through in-project class BaseApiController"));
    }

    [Fact]
    public void Ardalis_endpoints_are_controller_actions_at_reduced_confidence()
    {
        var entry = Assert.Single(Http(new()
        {
            ["src/Api/AuthenticateEndpoint.cs"] = """
                public class AuthenticateEndpoint : EndpointBaseAsync.WithRequest<AuthenticateRequest>.WithActionResult<AuthenticateResponse>
                {
                    [HttpPost("api/authenticate")]
                    public override async Task<ActionResult<AuthenticateResponse>> HandleAsync(AuthenticateRequest request, CancellationToken cancellationToken = default) => null;
                }
                """,
        }));

        Assert.Equal(("POST", "api/authenticate"), (entry.Http!.Verb, entry.Http.RouteTemplate));
        Assert.Equal(0.9, entry.Confidence);
        Assert.DoesNotContain(entry.Http.Parameters, p => p.Name == "cancellationToken");
    }

    // ---------- B2: minimal APIs ----------

    [Fact]
    public void Minimal_APIs_compose_static_MapGroup_prefixes()
    {
        var entries = Http(new()
        {
            ["src/Api/Program.cs"] = """
                var app = builder.Build();
                var api = app.MapGroup("/api").RequireAuthorization();
                var todos = api.MapGroup("todos");
                todos.MapGet("/{id}", (int id) => id);
                app.MapGroup("/v2").MapPost("orders", (Order order) => order).AllowAnonymous();
                app.MapGet("/", () => "ok");
                """,
        });

        var byRoute = entries.ToDictionary(e => $"{e.Http!.Verb} {e.Http.RouteTemplate}");
        var todo = byRoute["GET api/todos/{id}"];
        Assert.Equal(("resolved", "api/todos"), (todo.Http!.GroupPrefix!.Resolution, todo.Http.GroupPrefix.Prefix));
        Assert.Equal("/{id}", todo.Http.MappedTemplate);
        Assert.Equal(".RequireAuthorization()", todo.Http.Authorisation);
        Assert.Equal(AuthDeclared.Declared, todo.AuthDeclared);
        Assert.Equal("route", todo.Http.Parameters.Single().InferredSource);

        Assert.Equal(AuthDeclared.NoneDeclared, byRoute["POST v2/orders"].AuthDeclared);
        Assert.Equal(AuthDeclared.NoneDeclared, byRoute["GET "].AuthDeclared);
        Assert.All(entries, e => Assert.Equal(HttpRouting.MinimalApi, e.Http!.Routing));
        Assert.All(entries, e => Assert.Equal(("Program", "<top-level statements>"), (e.Handler.Type, e.Handler.Member)));
    }

    [Fact]
    public void A_prefix_held_in_a_variable_or_passed_in_is_recorded_unresolved()
    {
        var entries = Http(new()
        {
            ["src/Api/Endpoints.cs"] = """
                public static class Endpoints
                {
                    public static void Map(WebApplication app, string prefix)
                    {
                        app.MapGroup(prefix).MapGet("items", () => 1);
                    }

                    public static void MapUsers(this RouteGroupBuilder group) => group.MapGet("users", GetUsers);

                    private static IResult GetUsers(int page) => null;
                }
                """,
        });

        var items = entries.Single(e => e.Http!.MappedTemplate == "items");
        Assert.Null(items.Http!.RouteTemplate);
        Assert.Equal(("unresolved", "prefix"), (items.Http.GroupPrefix!.Resolution, items.Http.GroupPrefix.Expression));
        Assert.Contains(items.ConfidenceReasons, r => r.Contains("not statically resolvable"));

        var users = entries.Single(e => e.Http!.MappedTemplate == "users");
        Assert.Null(users.Http!.RouteTemplate);
        Assert.Equal("unresolved", users.Http.GroupPrefix!.Resolution);
        Assert.Equal(("method_group", "GetUsers"), (users.Http.HandlerForm, users.Handler.Member));
        Assert.Equal("query", users.Http.Parameters.Single().InferredSource);
    }

    [Fact]
    public void MapMethods_produces_one_entry_per_verb()
    {
        var entries = Http(new() { ["src/Api/Program.cs"] = """app.MapMethods("/sync", new[] { "PUT", "PATCH" }, () => 1);""" });
        Assert.Equal(["PATCH", "PUT"], entries.Select(e => e.Http!.Verb).Order().ToList());
    }

    // ---------- B1: the other kinds ----------

    [Fact]
    public void WCF_operations_are_recorded_against_the_hosted_implementation()
    {
        var files = new Dictionary<string, string>
        {
            ["src/Svc/ICatalogService.cs"] = """
                namespace Shop.Wcf {
                [ServiceContract]
                public interface ICatalogService
                {
                    [OperationContract] Item Find(int id);
                    [OperationContract(IsOneWay = true)] void Touch(int id);
                } }
                """,
            ["src/Svc/CatalogService.svc.cs"] = """
                namespace Shop.Wcf {
                public class CatalogService : ICatalogService
                {
                    [PrincipalPermission(SecurityAction.Demand, Role = "Staff")]
                    public Item Find(int id) => null;
                    public void Touch(int id) { }
                } }
                """,
            ["src/Svc/CatalogServiceMock.cs"] = "namespace Shop.Wcf { public class CatalogServiceMock : ICatalogService { public Item Find(int id) => null; public void Touch(int id) { } } }",
            ["src/Svc/CatalogServiceClient.cs"] = "namespace Shop.Wcf { public class CatalogServiceClient : System.ServiceModel.ClientBase<ICatalogService>, ICatalogService { } }",
        };
        var entries = Detect(files, "src/Svc/Svc.csproj",
            auxiliary: [("src/Svc/CatalogService.svc", """<%@ ServiceHost Service="Shop.Wcf.CatalogService" %>""")]);

        Assert.Equal(2, entries.Count);
        Assert.All(entries, e => Assert.Equal(("CatalogService", "svc", 1.0), (e.Wcf!.Implementation, e.Wcf.HostedBy, e.Confidence)));
        var find = entries.Single(e => e.Wcf!.Operation == "Find");
        Assert.Equal("src/Svc/CatalogService.svc.cs", find.Handler.FilePath);
        Assert.StartsWith("[PrincipalPermission(", find.Wcf!.Authorisation);
        Assert.True(entries.Single(e => e.Wcf!.Operation == "Touch").Wcf!.IsOneWay);
        // [PrincipalPermission] authorises Find; nothing declares Touch's
        // endpoints, so it stays not assessed.
        Assert.Equal(AuthDeclared.Declared, find.AuthDeclared);
        Assert.Equal(AuthDeclared.NotAssessed, entries.Single(e => e.Wcf!.Operation == "Touch").AuthDeclared);
    }

    // ---------- WCF security from config and code ----------

    private const string CatalogContract = """
        namespace Shop.Contracts {
        [ServiceContract] public interface ICatalog { [OperationContract] int Count(); } }
        """;

    private const string CatalogService = "namespace Shop.Services { using Shop.Contracts; public class Catalog : ICatalog { public int Count() => 0; } }";

    [Fact]
    public void A_svc_host_takes_binding_and_security_from_its_web_config()
    {
        const string webConfig = """
            <configuration>
              <system.serviceModel>
                <services>
                  <service name="Shop.Services.Catalog">
                    <endpoint address="" binding="wsHttpBinding" bindingConfiguration="secure" contract="Shop.Contracts.ICatalog" />
                    <endpoint address="mex" binding="mexHttpsBinding" contract="IMetadataExchange" />
                    <endpoint address="open" binding="basicHttpBinding" contract="Shop.Contracts.ICatalog" />
                  </service>
                </services>
                <bindings>
                  <wsHttpBinding>
                    <binding name="secure"><security mode="TransportWithMessageCredential"><message clientCredentialType="Certificate" /></security></binding>
                  </wsHttpBinding>
                </bindings>
              </system.serviceModel>
            </configuration>
            """;
        var entry = Assert.Single(Detect(
            new() { ["src/Svc/ICatalog.cs"] = CatalogContract, ["src/Svc/Catalog.cs"] = CatalogService },
            "src/Svc/Svc.csproj",
            auxiliary: [("iis/Catalog.svc", """<%@ ServiceHost Service="Shop.Services.Catalog" %>"""), ("iis/Web.config", webConfig)]));

        Assert.Equal("svc", entry.Wcf!.HostedBy);
        var byAddress = entry.Wcf.Endpoints.ToDictionary(e => e.Address!);
        Assert.Equal(2, byAddress.Count);
        Assert.Equal(("wsHttpBinding", "TransportWithMessageCredential", "Certificate", "declared", false),
            (byAddress[""].Binding, byAddress[""].SecurityMode, byAddress[""].ClientCredentialType, byAddress[""].SecuritySource, byAddress[""].Anonymous!.Value));
        // basicHttpBinding with nothing declared: WCF's default, security None.
        Assert.Equal(("None", "binding_default", true), (byAddress["open"].SecurityMode, byAddress["open"].SecuritySource, byAddress["open"].Anonymous!.Value));
        Assert.StartsWith("iis/Web.config:", byAddress["open"].DeclaredAt);
        // Reachable anonymously through one endpoint: unauthorised.
        Assert.Equal(AuthDeclared.NoneDeclared, entry.AuthDeclared);
    }

    [Fact]
    public void A_generic_ServiceHost_helper_is_bound_at_each_call_site()
    {
        const string host = """
            namespace Shop.Host {
            using Shop.Contracts; using Shop.Services;
            class Program
            {
                static void Main(Settings settings)
                {
                    Build<Catalog, ICatalog>("Catalog", 8101, requireClientCertificate: true);
                    if (settings.EnableHttp)
                    {
                        BuildHttps<Catalog, ICatalog>("Catalog", 8443);
                    }
                }

                static ServiceHost Build<TService, TContract>(string name, int port, bool requireClientCertificate)
                {
                    var baseAddress = new Uri($"net.tcp://localhost:{port}/{name}");
                    var host = new ServiceHost(typeof(TService), baseAddress);
                    var binding = new NetTcpBinding(SecurityMode.Transport)
                    {
                        Security = { Transport = { ClientCredentialType = requireClientCertificate ? TcpClientCredentialType.Certificate : TcpClientCredentialType.None } }
                    };
                    host.AddServiceEndpoint(typeof(TContract), binding, baseAddress);
                    return host;
                }

                static ServiceHost BuildHttps<TService, TContract>(string name, int port)
                {
                    var host = new ServiceHost(typeof(TService));
                    var binding = new BasicHttpBinding(BasicHttpSecurityMode.Transport);
                    binding.Security.Transport.ClientCredentialType = HttpClientCredentialType.None;
                    host.AddServiceEndpoint(typeof(TContract), binding, $"https://localhost:{port}/{name}");
                    return host;
                }
            } }
            """;
        var entry = Assert.Single(Detect(
            new() { ["src/Svc/ICatalog.cs"] = CatalogContract, ["src/Svc/Catalog.cs"] = CatalogService, ["src/Svc/Program.cs"] = host },
            "src/Svc/Svc.csproj"));

        var endpoints = entry.Wcf!.Endpoints;
        Assert.Equal(2, endpoints.Count);
        var tcp = endpoints.Single(e => e.Binding == "netTcpBinding");
        Assert.Equal(("service_host", "Transport", "Certificate", "declared", false, "net.tcp://localhost:{port}/Catalog", null),
            (tcp.HostKind, tcp.SecurityMode, tcp.ClientCredentialType, tcp.SecuritySource, tcp.Anonymous!.Value, tcp.Address, tcp.Condition));
        Assert.Contains("via Build", tcp.HostedAt);
        var https = endpoints.Single(e => e.Binding == "basicHttpBinding");
        Assert.Equal(("Transport", "None", true, "settings.EnableHttp"), (https.SecurityMode, https.ClientCredentialType, https.Anonymous!.Value, https.Condition));
        Assert.Equal(AuthDeclared.NoneDeclared, entry.AuthDeclared);
    }

    [Fact]
    public void CoreWCF_endpoints_are_read_from_the_service_builder()
    {
        var entry = Assert.Single(Detect(new()
        {
            ["src/Svc/ICatalog.cs"] = CatalogContract,
            ["src/Svc/Catalog.cs"] = CatalogService,
            ["src/Svc/Program.cs"] = """
                app.UseServiceModel(builder =>
                {
                    builder.AddService<Catalog>();
                    builder.AddServiceEndpoint<Catalog, ICatalog>(new NetTcpBinding(), "/catalog");
                });
                """,
        }, "src/Svc/Svc.csproj", ["CoreWCF.NetTcp"]));

        var endpoint = Assert.Single(entry.Wcf!.Endpoints);
        Assert.Equal(("corewcf", "netTcpBinding", "Transport", "Windows", "binding_default", false),
            (endpoint.HostKind, endpoint.Binding, endpoint.SecurityMode, endpoint.ClientCredentialType, endpoint.SecuritySource, endpoint.Anonymous!.Value));
        Assert.Equal(AuthDeclared.Declared, entry.AuthDeclared);
    }

    [Fact]
    public void Web_config_authorisation_turns_WebForms_and_ASMX_into_answers_and_leaves_the_rest_not_assessed()
    {
        const string root = """
            <configuration>
              <system.web><authorization><allow users="*" /></authorization></system.web>
              <location path="Admin"><system.web><authorization><deny users="?" /></authorization></system.web></location>
            </configuration>
            """;
        var entries = Detect(new()
        {
            ["src/Web/Default.aspx.cs"] = "public partial class _Default : System.Web.UI.Page { }",
            ["src/Web/Admin/Users.aspx.cs"] = "public partial class Users : System.Web.UI.Page { }",
            ["src/Web/Upload.asmx.cs"] = "public class Upload : WebService { [WebMethod] public void Image() { } }",
        }, "src/Web/Web.csproj", auxiliary: [("src/Web/Web.config", root)]);

        var byType = entries.ToDictionary(e => e.Handler.Type);
        Assert.Equal(AuthDeclared.NoneDeclared, byType["_Default"].AuthDeclared);
        Assert.Equal(AuthDeclared.Declared, byType["Users"].AuthDeclared);
        Assert.Contains("deny users=\"?\"", byType["Users"].WebForms!.Authorisation);
        Assert.Equal(AuthDeclared.NoneDeclared, byType["Upload"].AuthDeclared);

        var bare = Detect(new() { ["src/Web/Default.aspx.cs"] = "public partial class _Default : System.Web.UI.Page { }" }, "src/Web/Web.csproj");
        Assert.Equal(AuthDeclared.NotAssessed, Assert.Single(bare).AuthDeclared);
    }

    // ---------- razor_page ----------

    [Fact]
    public void Razor_pages_record_each_handler_with_its_route_and_authorisation()
    {
        var entries = Detect(new()
        {
            ["src/Web/Pages/Basket/Index.cshtml.cs"] = """
                public class IndexModel : PageModel
                {
                    public Task OnGet() => null;
                    public Task<IActionResult> OnPostAsync(IEnumerable<BasketItemViewModel> items) => null;
                    public Task<IActionResult> OnPostUpdate(int id) => null;
                    public void Helper() { }
                }
                """,
            ["src/Web/Pages/Basket/Checkout.cshtml.cs"] = "[Authorize] public class CheckoutModel : PageModel { public void OnPost() { } }",
            ["src/Web/Areas/Identity/Pages/Account/Login.cshtml.cs"] = "[AllowAnonymous] public class LoginModel : PageModel { public void OnGet() { } }",
            ["src/Web/Program.cs"] = "builder.Services.AddRazorPages(options => { options.Conventions.AuthorizePage(\"/Admin/Edit\"); });",
        }, "src/Web/Web.csproj", auxiliary:
        [
            ("src/Web/Pages/Basket/Index.cshtml", "@page \"{handler?}\"\n@model IndexModel\n"),
            // CRLF, with a BOM, as Visual Studio writes them.
            ("src/Web/Pages/Basket/Checkout.cshtml", "﻿@page\r\n@model CheckoutModel\r\n"),
            ("src/Web/Areas/Identity/Pages/Account/Login.cshtml", "@page\n@model LoginModel\n"),
            ("src/Web/Pages/Admin/Edit.cshtml", "@page \"{id:int}\"\n<h1>No model</h1>\n"),
            ("src/Web/Pages/Error.cshtml", "@page \"/oops\"\n"),
        ]).Where(e => e.Kind == EntryPointKinds.RazorPage).ToList();

        string Key(EntryPointRecord e) => $"{e.Http!.Verb} {e.Http.RouteTemplate}{(e.Http.PageHandler is null ? "" : "?handler=" + e.Http.PageHandler)}";
        var byKey = entries.ToDictionary(Key);
        Assert.Equal(
            ["GET Admin/Edit/{id:int}", "GET Basket/Checkout", "GET Basket/{handler?}", "GET Identity/Account/Login", "GET oops",
             "POST Basket/Checkout", "POST Basket/{handler?}", "POST Basket/{handler?}?handler=Update"],
            byKey.Keys.Order(StringComparer.Ordinal).ToList());

        Assert.Equal(("IndexModel", "OnPostUpdate"), (byKey["POST Basket/{handler?}?handler=Update"].Handler.Type, byKey["POST Basket/{handler?}?handler=Update"].Handler.Member));
        Assert.Equal(AuthDeclared.NoneDeclared, byKey["POST Basket/{handler?}"].AuthDeclared);
        Assert.Equal(AuthDeclared.Declared, byKey["POST Basket/Checkout"].AuthDeclared);
        // Renders on GET without an OnGet handler.
        Assert.Null(byKey["GET Basket/Checkout"].Handler.Member);
        Assert.Equal(AuthDeclared.NoneDeclared, byKey["GET Identity/Account/Login"].AuthDeclared);
        // No PageModel, but a convention authorises it.
        Assert.Equal(AuthDeclared.Declared, byKey["GET Admin/Edit/{id:int}"].AuthDeclared);
        Assert.StartsWith("AuthorizePage(", byKey["GET Admin/Edit/{id:int}"].Http!.Authorisation);
        Assert.All(entries, e => Assert.Equal(HttpRouting.RazorPage, e.Http!.Routing));
    }

    [Fact]
    public void A_contract_only_proxies_implement_is_not_an_entry_point()
    {
        var entries = Detect(new()
        {
            ["src/Client/IRemote.cs"] = "[ServiceContract] public interface IRemote { [OperationContract] void Call(); }",
            ["src/Client/RemoteClient.cs"] = "public class RemoteClient : ClientBase<IRemote>, IRemote { public void Call() { } }",
        }, "src/Client/Client.csproj");

        Assert.DoesNotContain(entries, e => e.Kind == EntryPointKinds.WcfOperation);
    }

    [Fact]
    public void gRPC_overrides_carry_the_proto_full_method_name()
    {
        var entry = Assert.Single(Detect(new()
        {
            ["src/Billing/Services/BillingService.cs"] = """
                public class BillingService : Billing.BillingBase
                {
                    public override Task<InvoiceReply> GetInvoice(InvoiceRequest request, ServerCallContext context) => null;
                    public Task Helper() => null;
                }
                """,
        }, "src/Billing/Billing.csproj", ["Grpc.AspNetCore"],
            [("src/Billing/Protos/billing.proto", "syntax = \"proto3\";\npackage billing;\nservice Billing {\n rpc GetInvoice (InvoiceRequest) returns (InvoiceReply);\n}\n")]));

        Assert.Equal(EntryPointKinds.GrpcServiceMethod, entry.Kind);
        Assert.Equal("/billing.Billing/GetInvoice", entry.Grpc!.FullMethod);
        Assert.Equal(1.0, entry.Confidence);
        Assert.Equal(AuthDeclared.NoneDeclared, entry.AuthDeclared);
    }

    [Fact]
    public void SignalR_hub_methods_hosted_services_consumers_jobs_webforms_and_asmx_are_each_detected()
    {
        var entries = Detect(new()
        {
            ["src/App/ChatHub.cs"] = """
                [Authorize]
                public class ChatHub : Hub
                {
                    public Task Send(string message) => null;
                    public override Task OnConnectedAsync() => null;
                }
                """,
            ["src/App/Program.cs"] = """
                app.MapHub<ChatHub>("/chat");
                builder.Services.AddHostedService<OrderWorker>();
                RecurringJob.AddOrUpdate<ReportJob>("nightly-report", j => j.Run(), Cron.Daily());
                """,
            ["src/App/OrderWorker.cs"] = """
                public class OrderWorker : BackgroundService
                {
                    private readonly IConsumer<string, string> _consumer;
                    protected override Task ExecuteAsync(CancellationToken stoppingToken)
                    {
                        _consumer.Subscribe("orders");
                        var result = _consumer.Consume(stoppingToken);
                        return Task.CompletedTask;
                    }
                }
                """,
            ["src/App/QueueReader.cs"] = """
                public class QueueReader
                {
                    public void Read() { var q = new MessageQueue(@".\private$\orders"); q.Receive(); }
                }
                """,
            ["src/App/CleanupJob.cs"] = "public class CleanupJob : IJob { public Task Execute(IJobExecutionContext context) => null; }",
            ["src/App/Heartbeat.cs"] = """
                using System.Threading;
                public class Heartbeat : IHostedService
                {
                    private Timer _timer;
                    public Task StartAsync(CancellationToken ct) { _timer = new Timer(Beat, null, TimeSpan.Zero, TimeSpan.FromMinutes(5)); return null; }
                    public Task StopAsync(CancellationToken ct) => null;
                    private void Beat(object state) { }
                }
                """,
            ["src/App/Catalog/List.aspx.cs"] = "public partial class List : System.Web.UI.Page { protected void Page_Load(object s, EventArgs e) { } }",
            ["src/App/Upload.asmx.cs"] = "public class Upload : WebService { [WebMethod] public void Image() { } }",
        }, "src/App/App.csproj");

        var kinds = entries.GroupBy(e => e.Kind).ToDictionary(g => g.Key, g => g.ToList());

        var hub = Assert.Single(kinds[EntryPointKinds.SignalRHubMethod]);
        Assert.Equal(("chat", "Send", AuthDeclared.Declared), (hub.SignalR!.HubRoute, hub.SignalR.Method, hub.AuthDeclared));

        Assert.Equal(["Heartbeat", "OrderWorker"], kinds[EntryPointKinds.HostedService].Select(e => e.Handler.Type).Order().ToList());
        Assert.True(kinds[EntryPointKinds.HostedService].Single(e => e.Handler.Type == "OrderWorker").Hosted!.Registered);

        var consumers = kinds[EntryPointKinds.MessageConsumer];
        var kafka = consumers.Single(e => e.Messaging!.Transport == "kafka");
        Assert.Equal(["orders"], kafka.Messaging!.Sources);
        Assert.Equal("OrderWorker", kafka.Messaging.HostedService);
        Assert.Equal(@".\private$\orders", consumers.Single(e => e.Messaging!.Transport == "msmq").Messaging!.Sources.Single());

        var jobs = kinds[EntryPointKinds.ScheduledJob].ToDictionary(e => e.Schedule!.Scheduler);
        Assert.Equal("CleanupJob", jobs["quartz"].Handler.Type);
        Assert.Equal(("nightly-report", "Cron.Daily()", "ReportJob", "Run"),
            (jobs["hangfire"].Schedule!.JobId, jobs["hangfire"].Schedule!.Expression, jobs["hangfire"].Handler.Type, jobs["hangfire"].Handler.Member));
        Assert.Equal(("Beat", "TimeSpan.FromMinutes(5)"), (jobs["threading_timer"].Handler.Member, jobs["threading_timer"].Schedule!.Expression));

        Assert.Equal("/Catalog/List.aspx", Assert.Single(kinds[EntryPointKinds.WebFormsPage]).WebForms!.PagePath);
        Assert.Equal("/Upload.asmx", Assert.Single(kinds[EntryPointKinds.AsmxWebMethod]).Asmx!.ServicePath);

        // Top-level statements are present, but the project has other entry points.
        Assert.False(kinds.ContainsKey(EntryPointKinds.ConsoleMain));
    }

    [Fact]
    public void Console_main_is_recorded_only_for_a_project_with_no_other_entry_points()
    {
        var entry = Assert.Single(Detect(new()
        {
            ["src/Tool/Program.cs"] = "static class Program { [STAThread] static void Main(string[] args) { } }",
        }, "src/Tool/Tool.csproj"));
        Assert.Equal((EntryPointKinds.ConsoleMain, "main", true), (entry.Kind, entry.Console!.Form, entry.Console.StaThread));

        var topLevel = Assert.Single(Detect(new() { ["src/Tool/Program.cs"] = "Console.WriteLine(1);\nreturn 0;" }, "src/Tool/Tool.csproj"));
        Assert.Equal(("top_level_statements", 1, 2), (topLevel.Console!.Form, topLevel.Handler.LineStart, topLevel.Handler.LineEnd));
    }

    // ---------- B3: ids and authorisation ----------

    private const string StableSource = """
        [Route("api/[controller]")]
        public class PingController : ControllerBase
        {
            [HttpGet] public IActionResult Get() => null;
            [HttpGet("{id}")] public IActionResult Get(int id) => null;
        }
        """;

    [Fact]
    public void EntryPointId_is_derived_and_stable_across_rescans_and_moved_code()
    {
        var first = Detect(new() { ["src/Api/PingController.cs"] = StableSource });
        var again = Detect(new() { ["src/Api/PingController.cs"] = StableSource });
        var moved = Detect(new() { ["src/Api/PingController.cs"] = "// a comment\n\n\nusing System;\n" + StableSource });

        Assert.Equal(2, first.Select(e => e.EntryPointId).Distinct().Count());
        Assert.All(first, e => Assert.Matches("^[0-9a-f]{32}$", e.EntryPointId));
        Assert.Equal(first.Select(e => e.EntryPointId), again.Select(e => e.EntryPointId));
        Assert.Equal(first.Select(e => e.EntryPointId), moved.Select(e => e.EntryPointId));
        Assert.NotEqual(first.Select(e => e.Handler.LineStart), moved.Select(e => e.Handler.LineStart));
    }

    [Fact]
    public void Authorisation_is_recorded_as_written_and_AllowAnonymous_wins()
    {
        var entries = Http(new()
        {
            ["src/Api/UserController.cs"] = """
                [Authorize]
                [Route("user")]
                public class UserController : ControllerBase
                {
                    [HttpGet] public IActionResult Me() => null;
                    [HttpPost("logout"), AllowAnonymous] public IActionResult Logout() => null;
                }

                [Route("open")]
                public class OpenController : ControllerBase
                {
                    [HttpGet] public IActionResult Get() => null;
                }
                """,
        });

        Assert.Equal(("[Authorize]", AuthDeclared.Declared), (entries.Single(e => e.Http!.RouteTemplate == "user").Http!.Authorisation, entries.Single(e => e.Http!.RouteTemplate == "user").AuthDeclared));
        Assert.Equal(("[Authorize] + [AllowAnonymous]", AuthDeclared.NoneDeclared), (entries.Single(e => e.Http!.RouteTemplate == "user/logout").Http!.Authorisation, entries.Single(e => e.Http!.RouteTemplate == "user/logout").AuthDeclared));
        Assert.Equal(((string?)null, AuthDeclared.NoneDeclared), (entries.Single(e => e.Http!.RouteTemplate == "open").Http!.Authorisation, entries.Single(e => e.Http!.RouteTemplate == "open").AuthDeclared));

        var project = EntryPointPipeline.Detect(RepositoryId, new InputProject("src/Api/Api.csproj", Guid.Empty, null, []),
            ProjectSource.FromText("src/Api/Api.csproj", new Dictionary<string, string> { ["src/Api/UserController.cs"] = """
                [Authorize] [Route("user")] public class UserController : ControllerBase { [HttpGet] public IActionResult Me() => null; [HttpPost("logout"), AllowAnonymous] public IActionResult Logout() => null; }
                [Route("open")] public class OpenController : ControllerBase { [HttpGet] public IActionResult Get() => null; }
                """ }), WcfContractIndex.Empty);
        Assert.Equal(2, project.Summary.NoDeclaredAuthenticationCount);
    }

    [Fact]
    public void A_global_filter_written_in_source_authorises_controller_actions()
    {
        var entry = Assert.Single(Http(new()
        {
            ["src/Api/Program.cs"] = "builder.Services.AddControllers(o => o.Filters.Add(new AuthorizeFilter()));\napp.MapControllers();",
            ["src/Api/OpenController.cs"] = """[Route("open")] public class OpenController : ControllerBase { [HttpGet] public IActionResult Get() => null; }""",
        }));

        Assert.Equal(AuthDeclared.Declared, entry.AuthDeclared);
        Assert.Equal("global AuthorizeFilter at src/Api/Program.cs:1 (global)", entry.Http!.Authorisation);
    }

    // ---------- B4: artifact ----------

    [Fact]
    public async Task Artifact_is_deterministic_and_valid_against_its_schema()
    {
        var root = Path.Combine(Path.GetTempPath(), "ep-inventory-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path.Combine(root, "src", "Api"));
        try
        {
            await File.WriteAllTextAsync(Path.Combine(root, "src", "Api", "Api.csproj"), "<Project Sdk=\"Microsoft.NET.Sdk.Web\" />");
            await File.WriteAllTextAsync(Path.Combine(root, "src", "Api", "PingController.cs"), StableSource);
            await File.WriteAllTextAsync(Path.Combine(root, "src", "Api", "Program.cs"), "app.MapGroup(\"/v1\").MapGet(\"ping\", () => 1);");

            var inventory = new SolutionProjectInventory
            {
                RepositoryId = RepositoryId,
                RepositorySlug = "sample",
                Projects =
                [
                    new InventoryProject { RelativePath = "src/Api/Api.csproj", ParseStatus = "success", StructuralType = "csharp_project" },
                    new InventoryProject { RelativePath = "docker-compose.dcproj", ParseStatus = "success", StructuralType = "docker_compose_project" },
                ],
            };
            var fingerprint = new ApplicationFingerprintSlice
            {
                RepositoryId = RepositoryId,
                Projects =
                [
                    new FingerprintedProject { ProjectId = Guid.NewGuid(), ProjectPath = "src/Api/Api.csproj", FingerprintStatus = FingerprintStatuses.Partial },
                    new FingerprintedProject { ProjectId = Guid.NewGuid(), ProjectPath = "docker-compose.dcproj", FingerprintStatus = FingerprintStatuses.Skipped },
                ],
            };
            var ids = fingerprint.Projects.ToDictionary(p => p.ProjectPath, p => (Guid?)p.ProjectId);
            var input = EntryPointInventoryCli.BuildInput(inventory, fingerprint, path => ids[path]);

            var one = DeterministicJson.Serialize(await new EntryPointPipeline().RunAsync(input, root, CancellationToken.None));
            var two = DeterministicJson.Serialize(await new EntryPointPipeline().RunAsync(input, root, CancellationToken.None));
            Assert.Equal(one, two);
            Assert.DoesNotContain("\r", one);
            Assert.DoesNotContain(root.Replace('\\', '/'), one.Replace("\\\\", "/"));

            ArtifactSchemaValidator.Load(Path.Combine(AppContext.BaseDirectory, "schemas", "entry-point-inventory-2.1.0.schema.json")).Validate(one);

            var artifact = System.Text.Json.JsonDocument.Parse(one).RootElement;
            Assert.Equal("application-fingerprint", artifact.GetProperty("skipSource").GetString());
            var skipped = artifact.GetProperty("projects").EnumerateArray().Single(p => p.GetProperty("projectPath").GetString() == "docker-compose.dcproj");
            Assert.Equal(("SKIPPED", "skipped by step 3 (out of scope)"), (skipped.GetProperty("status").GetString(), skipped.GetProperty("skipReason").GetString()));
            Assert.Equal(3, artifact.GetProperty("summary").GetProperty("entryPointCount").GetInt32());
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Theory]
    [InlineData("1.2.0", "^1.2.0", true)]
    [InlineData("1.3.1", "^1.2.0", true)]
    [InlineData("1.1.0", "^1.2.0", false)]
    [InlineData("2.0.0", "^1.2.0", false)]
    [InlineData("2.0.0", "^2.0.0", true)]
    public void Caret_ranges_match_the_engine(string version, string range, bool expected) =>
        Assert.Equal(expected, ArtifactVersions.SatisfiesCaret(version, range));
}
