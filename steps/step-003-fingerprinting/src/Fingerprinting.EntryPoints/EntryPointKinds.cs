namespace Fingerprinting.EntryPoints;

/// <summary>The entry point kinds — 29-STEPS-004-005-INVENTORIES.md Part B1,
/// razor_page (1.1.0), and seven more (2.0.0) ported from the
/// find-dotnet-entry-points pattern catalog. Published, with a version, in
/// schemas/entry-point-capabilities-*.json.</summary>
public static class EntryPointKinds
{
    public const string HttpControllerAction = "http_controller_action";
    public const string HttpMinimalApi = "http_minimal_api";
    public const string WcfOperation = "wcf_operation";
    public const string AsmxWebMethod = "asmx_web_method";
    public const string GrpcServiceMethod = "grpc_service_method";
    public const string SignalRHubMethod = "signalr_hub_method";
    public const string MessageConsumer = "message_consumer";
    public const string HostedService = "hosted_service";
    public const string ScheduledJob = "scheduled_job";
    public const string ConsoleMain = "console_main";
    public const string WebFormsPage = "webforms_page";
    public const string RazorPage = "razor_page";

    // 2.0.0 — the classic .NET Framework four first.
    public const string WindowsService = "windows_service";
    public const string HttpHandler = "http_handler";
    public const string GlobalAsax = "global_asax";
    public const string OwinStartup = "owin_startup";
    public const string BlazorComponent = "blazor_component";
    public const string AzureFunction = "azure_function";
    public const string DesktopApp = "desktop_app";

    public static readonly IReadOnlyList<string> All =
    [
        HttpControllerAction, HttpMinimalApi, RazorPage, WcfOperation, AsmxWebMethod, GrpcServiceMethod,
        SignalRHubMethod, MessageConsumer, HostedService, ScheduledJob, ConsoleMain, WebFormsPage,
        WindowsService, HttpHandler, GlobalAsax, OwinStartup, BlazorComponent, AzureFunction, DesktopApp,
    ];

    public static bool IsHttp(string kind) => kind is HttpControllerAction or HttpMinimalApi or RazorPage;
}

/// <summary>
/// Whether authentication is declared for an entry point — as written in
/// source or config. Deliberately not "authorised / unauthorised": gateway,
/// reverse-proxy and header-based authentication (an API gateway such as
/// Apigee, an access manager such as ISAM injecting identity headers) sit
/// outside the code and are invisible to static analysis. So
/// <see cref="NoneDeclared"/> is a prompt to review how the entry point is
/// protected, not a finding that it is open.
/// </summary>
public static class AuthDeclared
{
    /// <summary>An attribute, convention, config rule or WCF client
    /// credential requires the caller to authenticate.</summary>
    public const string Declared = "declared";

    /// <summary>Nothing in source or config declares authentication, or
    /// something declares it waived (<c>[AllowAnonymous]</c>, a WCF endpoint
    /// taking no client credential, an anonymous Azure Function).</summary>
    public const string NoneDeclared = "none_declared";

    /// <summary>Where authentication would be declared — web.config, WCF
    /// endpoints — says nothing this step can read.</summary>
    public const string NotAssessed = "not_assessed";

    /// <summary>The note every artifact and view carries with these values.</summary>
    public const string Scope =
        "auth_declared reports authentication as declared in source and config only. Gateway, reverse-proxy and " +
        "header-based authentication (an API gateway, an access manager injecting identity headers) are not visible " +
        "to static analysis, so none_declared is a prompt to review how the entry point is protected, not a security finding.";

    public static string From(AuthorisationState state) => state.NoneDeclared ? NoneDeclared : Declared;

    /// <summary>From a three-state answer: true = none declared, false =
    /// declared, null = not assessed.</summary>
    public static string From(bool? noneDeclared) => noneDeclared switch
    {
        true => NoneDeclared,
        false => Declared,
        null => NotAssessed,
    };
}

/// <summary>
/// Where an entry point's code comes from. <see cref="Framework"/> is a
/// framework or package type the application only registers — an HTTP
/// module from Application Insights, session state, Autofac. It stays in the
/// inventory (an IHttpModule registration matters for the move to
/// middleware), but it migrates through its package's own path rather than
/// being rewritten. Decided by whether the repository declares the type, not
/// by a list of vendor prefixes: a name list goes stale, the source does not.
/// </summary>
public static class EntryPointOrigins
{
    public const string Application = "application";
    public const string Framework = "framework";
}

/// <summary>
/// Whether external work enters here (<see cref="Request"/>) or the
/// application starts and wires itself up here (<see cref="Lifecycle"/>).
/// Downstream steps count, snapshot and test request entry points only —
/// risk scoring (step 8), contract snapshots (step 14), test generation
/// (step 15) — so bootstrap code neither inflates risk nor becomes a test
/// target. Only request entry points carry <c>authDeclared</c>.
/// </summary>
public static class EntryClasses
{
    public const string Request = "request";
    public const string Lifecycle = "lifecycle";

    /// <summary>
    /// Request: a caller, message or trigger enters and is handled —
    /// HTTP actions, minimal APIs, Razor Pages, WCF, ASMX, gRPC, SignalR,
    /// WebForms pages, Blazor routes, Azure Functions (every trigger),
    /// message consumers, scheduled jobs, HTTP handlers.
    /// Lifecycle: the process or pipeline starts or wires itself —
    /// Global.asax events, OWIN startup, HTTP modules (they hook pipeline
    /// events at Init), hosted and Windows services, console and desktop
    /// mains.
    /// </summary>
    public static string For(EntryPointRecord record) => record.Kind switch
    {
        EntryPointKinds.GlobalAsax or EntryPointKinds.OwinStartup or EntryPointKinds.HostedService
            or EntryPointKinds.WindowsService or EntryPointKinds.ConsoleMain or EntryPointKinds.DesktopApp => Lifecycle,
        EntryPointKinds.HttpHandler when record.HttpHandler?.Role == "module" => Lifecycle,
        _ => Request,
    };
}

/// <summary>The capability manifest this scanner implements —
/// schemas/entry-point-capabilities-{Version}.json lists the same kinds with
/// how each is detected, plus what is not covered. A test holds the two
/// together; bump both when a kind is added.</summary>
public static class CapabilityManifest
{
    public const string Version = "1.1.0";

    public static CapabilitiesStamp Stamp() => new()
    {
        ManifestVersion = Version,
        Kinds = EntryPointKinds.All.Order(StringComparer.Ordinal).ToList(),
    };
}

public static class HttpRouting
{
    public const string Attribute = "attribute";
    public const string Conventional = "conventional";
    public const string MinimalApi = "minimal_api";
    public const string RazorPage = "razor_page";
}

public static class ParameterSources
{
    public const string Route = "route";
    public const string Query = "query";
    public const string Body = "body";
    public const string Header = "header";
    public const string Form = "form";
    public const string Inferred = "inferred";
}

public static class ProjectScanStatuses
{
    public const string Scanned = "SCANNED";
    public const string Skipped = "SKIPPED";
    public const string Failed = "FAILED";
}
