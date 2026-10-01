using System.Text.Json.Serialization;
using Fingerprinting.Domain;

namespace Fingerprinting.EntryPoints;

// The entry-point-inventory@1.0.0 artifact â€” 29-STEPS-004-005-INVENTORIES.md
// Parts B3 and B4. Serialised through DeterministicJson: camelCase keys,
// alphabetical at every level. Nulls are written explicitly (a conventional
// route's null template is information), except the kind-specific blocks on
// an entry point, of which exactly one is present.

public sealed record EntryPointInventoryArtifact
{
    public string ArtifactType { get; init; } = "entry-point-inventory";

    /// <summary>1.1.0: the razor_page kind; WCF endpoints with their
    /// binding and security; web.config authorisation for ASMX and
    /// WebForms. 2.0.0 (breaking): <c>unauthorised</c> becomes
    /// <c>authDeclared</c>, the count becomes <c>noDeclaredAuthenticationCount</c>,
    /// seven kinds are added, and the capability manifest is stamped in.
    /// 2.1.0: <c>origin</c> and <c>entryClass</c> on every entry point, and
    /// counts split by both. Additive.</summary>
    public string ArtifactVersion { get; init; } = "2.1.0";
    public required string ScannerVersion { get; init; }
    public required Guid RepositoryId { get; init; }
    public required string RepositorySlug { get; init; }
    public bool SemanticAnalysisEnabled { get; init; }

    /// <summary>Where each project's skip decision came from:
    /// <c>application-fingerprint</c> (step 3's fingerprintStatus, the normal
    /// case) or <c>solution-project-inventory</c> (step 2's out-of-scope
    /// rule, when no fingerprint was supplied â€” standalone runs only).</summary>
    public required string SkipSource { get; init; }

    /// <summary>What <c>authDeclared</c> can and cannot see â€” see
    /// <see cref="Analysis.AuthDeclared.Scope"/>.</summary>
    public string AuthDeclaredScope { get; init; } = Analysis.AuthDeclared.Scope;

    /// <summary>The entry-point kinds this scan could detect, by manifest
    /// version. A kind not listed was not looked for: its absence from the
    /// results means nothing.</summary>
    public required CapabilitiesStamp Capabilities { get; init; }

    public required InventorySummary Summary { get; init; }
    public required IReadOnlyList<ProjectEntryPoints> Projects { get; init; }
    public IReadOnlyList<Warning> Warnings { get; init; } = [];
}

public sealed record CapabilitiesStamp
{
    public required string ManifestVersion { get; init; }
    public required IReadOnlyList<string> Kinds { get; init; }
}

public sealed record InventorySummary
{
    public int ProjectsScanned { get; init; }
    public int ProjectsSkipped { get; init; }
    public int ProjectsFailed { get; init; }
    public int EntryPointCount { get; init; }

    /// <summary>What downstream steps count, snapshot and test.</summary>
    public int RequestEntryPointCount { get; init; }

    /// <summary>Bootstrap and wiring â€” not places external work enters.</summary>
    public int LifecycleHookCount { get; init; }

    public SortedDictionary<string, int> CountByKind { get; init; } = new(StringComparer.Ordinal);
    public SortedDictionary<string, int> CountByOrigin { get; init; } = new(StringComparer.Ordinal);
    public SortedDictionary<string, int> CountByVerb { get; init; } = new(StringComparer.Ordinal);

    /// <summary>Request entry points with authDeclared none_declared.</summary>
    public int NoDeclaredAuthenticationCount { get; init; }
    public int AuthorisationNotAssessedCount { get; init; }
}

public sealed record ProjectEntryPoints
{
    public required Guid ProjectId { get; init; }
    public required string ProjectPath { get; init; }
    public required string Status { get; init; }
    public string? SkipReason { get; init; }
    public required ProjectEntryPointSummary Summary { get; init; }
    public IReadOnlyList<EntryPointRecord> EntryPoints { get; init; } = [];
    public IReadOnlyList<Warning> Warnings { get; init; } = [];
}

public sealed record ProjectEntryPointSummary
{
    public int RequestEntryPointCount { get; init; }
    public int LifecycleHookCount { get; init; }
    public SortedDictionary<string, int> CountByKind { get; init; } = new(StringComparer.Ordinal);
    public SortedDictionary<string, int> CountByOrigin { get; init; } = new(StringComparer.Ordinal);
    public SortedDictionary<string, int> CountByVerb { get; init; } = new(StringComparer.Ordinal);

    /// <summary>Request entry points with <c>authDeclared: none_declared</c>
    /// â€” review prompts, not findings; see <see cref="AuthDeclared.Scope"/>.
    /// Lifecycle hooks carry no authDeclared, so never count here.</summary>
    public int NoDeclaredAuthenticationCount { get; init; }

    /// <summary>Entry points with <c>authDeclared: not_assessed</c>.</summary>
    public int AuthorisationNotAssessedCount { get; init; }

    /// <summary>Project-wide authorisation written in source â€” a global
    /// <c>AuthorizeFilter</c>, <c>MapControllers().RequireAuthorization()</c>,
    /// a fallback policy â€” each with its location. Already applied to the
    /// entry points it covers.</summary>
    public IReadOnlyList<string> GlobalAuthorisation { get; init; } = [];

    /// <summary>Conventional route tables as written
    /// (<c>MapControllerRoute</c>, <c>routes.MapRoute</c>). Recorded for the
    /// reader; never used to guess a conventional action's template.</summary>
    public IReadOnlyList<string> ConventionalRoutes { get; init; } = [];
}

public sealed record EntryPointRecord
{
    public required string EntryPointId { get; init; }
    public required string Kind { get; init; }
    public required string ProjectPath { get; init; }

    /// <summary><see cref="EntryPointOrigins"/>: application or framework.</summary>
    public string Origin { get; init; } = EntryPointOrigins.Application;

    /// <summary><see cref="EntryClasses"/>: request or lifecycle.</summary>
    public string EntryClass { get; init; } = EntryClasses.Request;

    public required HandlerLocation Handler { get; init; }
    public required double Confidence { get; init; }
    public IReadOnlyList<string> ConfidenceReasons { get; init; } = [];

    /// <summary><c>declared</c>, <c>none_declared</c> or
    /// <c>not_assessed</c> (<see cref="Analysis.AuthDeclared"/>); null
    /// where the question does not apply â€” hosted services, jobs, consumers,
    /// mains, application hooks.</summary>
    public string? AuthDeclared { get; init; }

    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public HttpDetail? Http { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public WcfDetail? Wcf { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public AsmxDetail? Asmx { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public GrpcDetail? Grpc { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public SignalRDetail? SignalR { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public MessagingDetail? Messaging { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public ScheduleDetail? Schedule { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public HostedDetail? Hosted { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public ConsoleDetail? Console { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public WebFormsDetail? WebForms { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public WindowsServiceDetail? WindowsService { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public HttpHandlerDetail? HttpHandler { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public GlobalAsaxDetail? GlobalAsax { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public OwinStartupDetail? OwinStartup { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public BlazorDetail? Blazor { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public FunctionDetail? Function { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public DesktopDetail? Desktop { get; init; }

    /// <summary>The kind-specific block â€” what the entry_points.detail
    /// column stores.</summary>
    public object DetailBlock() =>
        (object?)Http ?? Wcf ?? Asmx ?? Grpc ?? SignalR ?? Messaging ?? Schedule ?? Hosted ?? Console ?? WebForms
        ?? WindowsService ?? HttpHandler ?? GlobalAsax ?? OwinStartup ?? Blazor ?? Function ?? (object?)Desktop
        ?? throw new InvalidOperationException($"entry point {EntryPointId} has no detail block");
}

public sealed record HandlerLocation
{
    /// <summary>The type as written, without namespace.</summary>
    public required string Type { get; init; }
    public string? Namespace { get; init; }

    /// <summary>The member, or null where the type itself is the entry
    /// point (a WebForms page).</summary>
    public string? Member { get; init; }

    public required string FilePath { get; init; }
    public required int LineStart { get; init; }
    public required int LineEnd { get; init; }
}

public sealed record HttpDetail
{
    public required string Verb { get; init; }

    /// <summary>The composed route, no leading slash. Null for
    /// conventional routing (the route table is elsewhere) and wherever
    /// part of the template could not be resolved statically.</summary>
    public string? RouteTemplate { get; init; }

    public required string Routing { get; init; }
    public IReadOnlyList<HttpParameter> Parameters { get; init; } = [];
    public string? ReturnType { get; init; }

    /// <summary>The authorisation attributes and conventions that apply,
    /// as written.</summary>
    public string? Authorisation { get; init; }

    /// <summary>Controller and action names, recorded for every controller
    /// action; for conventional routing they are all there is.</summary>
    public string? Controller { get; init; }
    public string? Action { get; init; }

    /// <summary>Minimal APIs: the template passed to MapGet and siblings,
    /// before any MapGroup prefix, and how the prefix resolved.</summary>
    public string? MappedTemplate { get; init; }
    public GroupPrefix? GroupPrefix { get; init; }

    /// <summary>Minimal APIs: <c>lambda</c> or <c>method_group</c>.</summary>
    public string? HandlerForm { get; init; }

    /// <summary>Razor Pages: the .cshtml carrying the <c>@page</c> directive.</summary>
    public string? PageFile { get; init; }

    /// <summary>Razor Pages: a named handler (<c>OnPostDelete</c> is
    /// <c>Delete</c>, selected by <c>?handler=Delete</c> unless the route
    /// carries <c>{handler}</c>); null for the page's default handler.</summary>
    public string? PageHandler { get; init; }
}

public sealed record HttpParameter
{
    public required string Name { get; init; }
    public string? Type { get; init; }

    /// <summary>route, query, body, header or form from an explicit
    /// <c>[FromRoute]</c>-style attribute; <c>inferred</c> otherwise.</summary>
    public required string Source { get; init; }

    /// <summary>For <c>source: inferred</c>, the binding source the
    /// framework's conventions give syntactically, where they give one.</summary>
    public string? InferredSource { get; init; }
}

public sealed record GroupPrefix
{
    /// <summary><c>resolved</c> or <c>unresolved</c>.</summary>
    public required string Resolution { get; init; }
    public string? Prefix { get; init; }

    /// <summary>For an unresolved prefix, the expression as written.</summary>
    public string? Expression { get; init; }
}

public sealed record WcfDetail
{
    public required string Contract { get; init; }
    public required string Operation { get; init; }
    public string? Implementation { get; init; }
    public bool IsOneWay { get; init; }

    /// <summary>The first host, as 1.0.0 recorded it: <c>svc</c>,
    /// <c>service_host</c> or <c>corewcf</c>, and where. Every host is in
    /// <see cref="Endpoints"/>.</summary>
    public string? HostedBy { get; init; }
    public string? HostFile { get; init; }

    /// <summary><c>[PrincipalPermission]</c> and the like on the
    /// implementation, as written.</summary>
    public string? Authorisation { get; init; }

    /// <summary>Every endpoint serving this contract, across every host,
    /// with its binding and security.</summary>
    public IReadOnlyList<WcfEndpointDetail> Endpoints { get; init; } = [];
}

public sealed record WcfEndpointDetail
{
    /// <summary><c>svc</c>, <c>service_host</c> or <c>corewcf</c>.</summary>
    public required string HostKind { get; init; }
    public required string HostedAt { get; init; }
    public required string Binding { get; init; }
    public string? SecurityMode { get; init; }

    /// <summary>The credential type the security mode uses: the transport
    /// one for Transport / TransportCredentialOnly, the message one for
    /// Message / TransportWithMessageCredential, None for mode None.</summary>
    public string? ClientCredentialType { get; init; }

    /// <summary><c>declared</c>; <c>binding_default</c> when a value left
    /// out was filled from WCF's documented default for the binding;
    /// <c>unresolved</c> when it could not be determined.</summary>
    public required string SecuritySource { get; init; }

    /// <summary>True: the endpoint takes no client credential.</summary>
    public bool? Anonymous { get; init; }

    public string? Address { get; init; }

    /// <summary><c>config</c> or <c>code</c>, and where it is declared.</summary>
    public required string Source { get; init; }
    public required string DeclaredAt { get; init; }

    /// <summary>An <c>if</c> the endpoint is added under, as written.</summary>
    public string? Condition { get; init; }
}

public sealed record AsmxDetail
{
    public required string ServicePath { get; init; }
    public required string Method { get; init; }
    public string? Authorisation { get; init; }
}

public sealed record WebFormsDetail
{
    public required string PagePath { get; init; }
    public required string CodeBehindClass { get; init; }
    public string? Authorisation { get; init; }
}

public sealed record GrpcDetail
{
    public required string Service { get; init; }
    public required string Method { get; init; }
    public string? ProtoPackage { get; init; }
    public string? ProtoFile { get; init; }

    /// <summary><c>/package.Service/Method</c>, where the .proto declares
    /// the service.</summary>
    public string? FullMethod { get; init; }
    public string? Authorisation { get; init; }
}

public sealed record SignalRDetail
{
    public required string Hub { get; init; }
    public required string Method { get; init; }

    /// <summary>From <c>MapHub&lt;THub&gt;("/path")</c> in the project.</summary>
    public string? HubRoute { get; init; }
    public string? Authorisation { get; init; }
}

public sealed record MessagingDetail
{
    /// <summary><c>kafka</c>, <c>msmq</c>, <c>masstransit</c>,
    /// <c>nservicebus</c> or <c>rebus</c>.</summary>
    public required string Transport { get; init; }

    /// <summary>Topics or queue paths written as literals in the class
    /// (Kafka, MSMQ); the message type handled (MassTransit, NServiceBus,
    /// Rebus), which is the effective route.</summary>
    public IReadOnlyList<string> Sources { get; init; } = [];

    /// <summary><c>resolved</c> when at least one literal was found,
    /// <c>unresolved</c> otherwise.</summary>
    public required string SourceResolution { get; init; }

    /// <summary>Set when the consuming class is itself a hosted service.</summary>
    public string? HostedService { get; init; }
}

public sealed record ScheduleDetail
{
    /// <summary><c>quartz</c>, <c>hangfire</c> or <c>threading_timer</c>.</summary>
    public required string Scheduler { get; init; }

    /// <summary>Cron expression, Cron.* call or timer period, as written.</summary>
    public string? Expression { get; init; }
    public string? JobId { get; init; }
}

public sealed record HostedDetail
{
    /// <summary><c>BackgroundService</c> or <c>IHostedService</c>.</summary>
    public required string ServiceBase { get; init; }

    /// <summary>An <c>AddHostedService&lt;T&gt;()</c> for it was found in the project.</summary>
    public bool Registered { get; init; }
}

public sealed record ConsoleDetail
{
    /// <summary><c>main</c> or <c>top_level_statements</c>.</summary>
    public required string Form { get; init; }
    public bool StaThread { get; init; }
}

// ---------- 2.0.0 kinds ----------

public sealed record WindowsServiceDetail
{
    public required string ServiceClass { get; init; }

    /// <summary>The service name assigned in code (<c>ServiceName = "..."</c>), when a literal.</summary>
    public string? ServiceName { get; init; }

    /// <summary>The lifecycle overrides present: OnStart, OnStop, OnPause,
    /// OnContinue, OnShutdown, OnCustomCommand, OnSessionChange, OnPowerEvent.</summary>
    public IReadOnlyList<string> Hooks { get; init; } = [];

    /// <summary>Where <c>ServiceBase.Run</c> starts it, when found.</summary>
    public string? RunAt { get; init; }
}

public sealed record HttpHandlerDetail
{
    /// <summary><c>handler</c> (IHttpHandler, IHttpAsyncHandler,
    /// HttpTaskAsyncHandler, .ashx) or <c>module</c> (IHttpModule), which
    /// sees every request.</summary>
    public required string Role { get; init; }

    /// <summary>The type as registered or declared.</summary>
    public required string TypeName { get; init; }

    /// <summary>The URL path: an .ashx file's, or a registration's
    /// <c>path</c> pattern. Null for a module.</summary>
    public string? Path { get; init; }
    public string? Verb { get; init; }

    /// <summary>Where web.config registers it, and in which section.</summary>
    public string? RegisteredAt { get; init; }
    public string? ConfigSection { get; init; }

    /// <summary>False for a registered type with no source in the
    /// repository â€” a framework or package handler or module.</summary>
    public bool InRepository { get; init; }
    public string? Authorisation { get; init; }
}

public sealed record GlobalAsaxDetail
{
    public required string ApplicationClass { get; init; }

    /// <summary>Application_Start, Application_BeginRequest, Session_Start, ...</summary>
    public required string Event { get; init; }

    /// <summary><c>application</c> (once per app), <c>request</c> (every
    /// request) or <c>session</c>.</summary>
    public required string Scope { get; init; }
}

public sealed record OwinStartupDetail
{
    public required string StartupClass { get; init; }

    /// <summary><c>assembly_attribute</c> ([assembly: OwinStartup]),
    /// <c>app_setting</c> (owin:appStartup) or <c>convention</c> (a class
    /// named Startup with Configuration(IAppBuilder)).</summary>
    public required string DeclaredBy { get; init; }
    public string? DeclaredAt { get; init; }

    /// <summary>The middleware the pipeline registers, in order â€”
    /// <c>app.UseCookieAuthentication</c>, <c>app.Use&lt;T&gt;</c> â€” across
    /// every part of the partial class.</summary>
    public IReadOnlyList<string> Middleware { get; init; } = [];
}

public sealed record BlazorDetail
{
    public required string Route { get; init; }
    public required string ComponentFile { get; init; }

    /// <summary><c>@attribute [Authorize]</c> and friends, as written.</summary>
    public string? Authorisation { get; init; }
}

public sealed record FunctionDetail
{
    public required string FunctionName { get; init; }

    /// <summary><c>in_process</c> ([FunctionName]) or <c>isolated</c> ([Function]).</summary>
    public required string Model { get; init; }

    /// <summary>The trigger attribute on the first triggered parameter â€”
    /// HttpTrigger, TimerTrigger, QueueTrigger, ... â€” which decides what
    /// kind of entry point it is. Null when none is written.</summary>
    public string? Trigger { get; init; }

    /// <summary>The trigger attribute as written.</summary>
    public string? TriggerAttribute { get; init; }

    /// <summary>HttpTrigger: <c>Anonymous</c>, <c>Function</c>, <c>Admin</c>, ...</summary>
    public string? AuthorizationLevel { get; init; }
    public IReadOnlyList<string> Methods { get; init; } = [];
    public string? Route { get; init; }
}

public sealed record DesktopDetail
{
    /// <summary><c>wpf</c> or <c>winforms</c>.</summary>
    public required string Framework { get; init; }

    /// <summary>The main form or window: the form <c>Application.Run</c>
    /// or <c>ShowDialog</c> opens, or App.xaml's <c>StartupUri</c>.</summary>
    public string? MainWindow { get; init; }
    public bool StaThread { get; init; }
}
