using System.Text.Json.Serialization;
using Fingerprinting.Domain;

namespace Fingerprinting.Outbound;

// The outbound-invocation-inventory@1.0.0 artifact — 29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES-
// INVENTORIES.md Parts C7 and C8. Serialised through DeterministicJson.
// Secrets never enter these records (Part C5): endpoints are normalised
// before they are built, connection strings contribute host, port, provider
// and authentication kind only, and credentials are recorded by key path.

public static class Mechanisms
{
    public const string HttpClient = "http_client";
    public const string SoapClient = "soap_client";
    public const string GrpcClient = "grpc_client";
    public const string Database = "database";
    public const string MessageProducer = "message_producer";
    public const string MessageConsumer = "message_consumer";
    public const string Cache = "cache";
    public const string SecretStore = "secret_store";
    public const string FileShare = "file_share";
    public const string Smtp = "smtp";
    public const string Ldap = "ldap";

    public static readonly IReadOnlyList<string> All =
        [HttpClient, SoapClient, GrpcClient, Database, MessageProducer, MessageConsumer, Cache, SecretStore, FileShare, Smtp, Ldap];
}

public static class Verdicts
{
    public const string Incompatible = "incompatible";
    public const string RequiresChange = "requires_change";
    public const string Unknown = "unknown";
    public const string Compatible = "compatible";

    /// <summary>Worst first — the order a list someone will act on is sorted in.</summary>
    public static int Rank(string verdict) => verdict switch
    {
        Incompatible => 0,
        RequiresChange => 1,
        Unknown => 2,
        _ => 3,
    };
}

/// <summary>Whether an invocation is a dependency at all. An unused client
/// — declared, but constructed nowhere and configured nowhere — makes no
/// outbound call: it stays in the inventory, is left out of verdict counts,
/// and step 10's endpoint register does not treat it as a dependency.</summary>
public static class Usages
{
    public const string Used = "used";
    public const string Unused = "unused";
}

public static class Resolutions
{
    public const string Resolved = "resolved";
    public const string Partial = "partial";
    public const string Unresolved = "unresolved";
}

public sealed record OutboundInventoryArtifact
{
    public string ArtifactType { get; init; } = "outbound-invocation-inventory";
    public string ArtifactVersion { get; init; } = "1.5.0";
    public required string ScannerVersion { get; init; }
    public required Guid RepositoryId { get; init; }
    public required string RepositorySlug { get; init; }
    public bool SemanticAnalysisEnabled { get; init; }
    public required string SkipSource { get; init; }

    /// <summary>What <c>authDeclared</c> means for an outbound call.</summary>
    public string AuthDeclaredScope { get; init; } =
        "authDeclared on an outbound invocation reports whether the client presents credentials, as declared in source and " +
        "config: a WCF client credential type, a connection string's authentication, an API key, token or certificate. " +
        "Credentials added outside the code (a sidecar, a gateway, a delegating handler registered elsewhere) are not visible " +
        "to static analysis, so none_declared and not_assessed are prompts to review, not findings.";

    /// <summary>1.4.0: the WCF client support matrix the runtime verdicts
    /// were given from, and for which target; null when none was loaded.</summary>
    public WcfClientSupportStamp? WcfClientSupport { get; init; }

    public required OutboundSummary Summary { get; init; }
    public required IReadOnlyList<ProjectInvocations> Projects { get; init; }
    public IReadOnlyList<Warning> Warnings { get; init; } = [];
}

public sealed record WcfClientSupportStamp
{
    public required string MatrixVersion { get; init; }

    /// <summary>1.5.0: the platform matrix's version and sha256.</summary>
    public string? PlatformMatrixVersion { get; init; }
    public string? PlatformSha256 { get; init; }
    public required string Target { get; init; }

    /// <summary>sha256 of the matrix file as read.</summary>
    public required string Sha256 { get; init; }

    /// <summary>Entries not yet confirmed by a person: a report resting on one is a draft.</summary>
    public required int UnconfirmedEntries { get; init; }
}

public sealed record OutboundSummary
{
    public int ProjectsScanned { get; init; }
    public int ProjectsSkipped { get; init; }
    public int ProjectsFailed { get; init; }
    public int InvocationCount { get; init; }

    /// <summary>Invocations with <c>usage: unused</c> — counted here, and
    /// nowhere else.</summary>
    public int UnusedCount { get; init; }

    /// <summary>Used invocations only.</summary>
    public SortedDictionary<string, int> CountByMechanism { get; init; } = new(StringComparer.Ordinal);

    /// <summary>Used invocations only: an unused client has no verdict worth counting.</summary>
    public SortedDictionary<string, int> CountByVerdict { get; init; } = new(StringComparer.Ordinal);

    /// <summary>1.4.0: used SOAP clients, by runtime verdict.</summary>
    public SortedDictionary<string, int> CountByRuntimeVerdict { get; init; } = new(StringComparer.Ordinal);
}

public sealed record ProjectInvocations
{
    public required Guid ProjectId { get; init; }
    public required string ProjectPath { get; init; }
    public required string Status { get; init; }
    public string? SkipReason { get; init; }
    public required ProjectOutboundSummary Summary { get; init; }
    public IReadOnlyList<Invocation> Invocations { get; init; } = [];

    /// <summary>1.3.0: every SetParameters parameter of this project, linked
    /// or not. A value only where <see cref="Fingerprinting.Analysis.DeployParameterFiles.MayStore"/> allows.</summary>
    public IReadOnlyList<DeployParameterRecord> DeployParameters { get; init; } = [];

    /// <summary>1.3.0: per step 4 entry point of this project, the outbound
    /// call sites it reaches — see <see cref="BackendReach"/>.</summary>
    public IReadOnlyList<EntryPointBackend> EntryPointBackend { get; init; } = [];
    public IReadOnlyList<Warning> Warnings { get; init; } = [];
}

/// <summary>One SetParameters parameter (1.3.0). <see cref="Value"/> is set
/// only for a path, or a URL that links to an endpoint some invocation uses;
/// every other parameter — a password, a connection string, a user id — is
/// recorded as present, with its name and kind only.</summary>
public sealed record DeployParameterRecord
{
    public string? ProjectPath { get; init; }
    public required string SourceFile { get; init; }
    public required string Environment { get; init; }
    public required string Name { get; init; }

    /// <summary><c>url</c>, <c>path</c>, <c>connection_string</c>, <c>sensitive</c> or <c>other</c>.</summary>
    public required string Kind { get; init; }
    public required int Line { get; init; }
    public string? Value { get; init; }

    /// <summary>What it replaces: <c>client_endpoint</c>, <c>app_setting</c>,
    /// <c>connection_string</c> or <c>xpath</c>, and that thing's name.</summary>
    public string? LinkedKind { get; init; }
    public string? LinkedName { get; init; }

    /// <summary><c>parameters_xml</c> or <c>name_and_path</c>.</summary>
    public string? LinkMethod { get; init; }
    public double? LinkConfidence { get; init; }
    public string? LinkNote { get; init; }
}

/// <summary>What one inbound entry point reaches (1.3.0).
/// <see cref="Status"/>: <c>yes</c> (an outbound call site is reached),
/// <c>no</c> (none, and no path left unfollowed), <c>unresolved</c> (none
/// found, but a path through another class or deeper was not followed).</summary>
public sealed record EntryPointBackend
{
    public required string EntryPointId { get; init; }
    public required string Status { get; init; }
    public IReadOnlyList<BackendCall> Calls { get; init; } = [];
    public IReadOnlyList<UnfollowedPath> Unresolved { get; init; } = [];
}

public sealed record BackendCall
{
    public required string InvocationId { get; init; }
    public required string Mechanism { get; init; }

    /// <summary>The operation as step 5 records it (<c>PlaceRealTimeFTOrder</c>,
    /// <c>GET /api/orders</c>); null for a mechanism without operations.</summary>
    public string? Operation { get; init; }
    public required CallSite CallSite { get; init; }

    /// <summary>0: in the entry point's own method; n: through n methods of the same class.</summary>
    public required int Depth { get; init; }

    /// <summary>The methods walked, entry point first.</summary>
    public IReadOnlyList<string> Via { get; init; } = [];
    public required bool Conditional { get; init; }
    public required bool InLoop { get; init; }

    /// <summary>The conditions and loops around it, as written in code
    /// (<c>else of if (item.IsPracticeAccount)</c>) — syntax, not interpretation.</summary>
    public IReadOnlyList<string> Context { get; init; } = [];
}

public sealed record UnfollowedPath
{
    public required string Reason { get; init; }
    public required CallSite CallSite { get; init; }
}

public sealed record ProjectOutboundSummary
{
    public int UnusedCount { get; init; }

    /// <summary>Used invocations only, as are the verdict counts and the incompatible list.</summary>
    public SortedDictionary<string, int> CountByMechanism { get; init; } = new(StringComparer.Ordinal);
    public SortedDictionary<string, int> CountByVerdict { get; init; } = new(StringComparer.Ordinal);

    /// <summary>Part C8: the incompatible invocations, listed explicitly —
    /// the list someone will act on.</summary>
    public IReadOnlyList<IncompatibleInvocation> Incompatible { get; init; } = [];
}

public sealed record IncompatibleInvocation
{
    public required string InvocationId { get; init; }
    public required string Mechanism { get; init; }
    public required string Endpoint { get; init; }
    public IReadOnlyList<string> Reasons { get; init; } = [];
}

public sealed record Invocation
{
    public required string InvocationId { get; init; }
    public required string Mechanism { get; init; }
    public required string ProjectPath { get; init; }
    public required Endpoint Endpoint { get; init; }

    /// <summary><c>used</c> or <c>unused</c> — see <see cref="Usages"/>.</summary>
    public string Usage { get; init; } = Usages.Used;

    /// <summary>One logical endpoint's value per environment file (Part C4):
    /// <c>appsettings.DEV.json</c> and <c>appsettings.PROD.json</c> pointing
    /// at different hosts is one invocation with two bindings.</summary>
    public IReadOnlyList<EnvironmentBinding> EnvironmentBindings { get; init; } = [];

    /// <summary><c>declared</c> (the client presents a credential),
    /// <c>none_declared</c> (declared as presenting none — a WCF credential
    /// type of None) or <c>not_assessed</c>; see
    /// <see cref="OutboundInventoryArtifact.AuthDeclaredScope"/>.</summary>
    public string? AuthDeclared { get; init; }

    /// <summary>Credentials the client is configured with — kind and key
    /// path only, never a value (Part C5).</summary>
    public IReadOnlyList<CredentialReference> Credentials { get; init; } = [];

    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public SoapDetail? Soap { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public HttpDetail? Http { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public GrpcDetail? Grpc { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public DatabaseDetail? Database { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public MessagingDetail? Messaging { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public ProviderDetail? Cache { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public ProviderDetail? SecretStore { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public FileShareDetail? FileShare { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public SmtpDetail? Smtp { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public LdapDetail? Ldap { get; init; }

    /// <summary>Where the dependency is invoked (1.3.0): each resolved
    /// operation's call site when there are any; otherwise where the client is
    /// created or configured.</summary>
    public IReadOnlyList<CallSite> CallSites { get; init; } = [];

    /// <summary>1.3.0: where the client is created — <c>new XClient()</c>,
    /// <c>new ChannelFactory&lt;T&gt;</c> — when that differs from where it is invoked.</summary>
    public IReadOnlyList<CallSite> ConstructionSites { get; init; } = [];

    /// <summary>What the client invokes, each with its own call site
    /// (1.2.0): SOAP and gRPC operations, HTTP verb and path. Empty for the
    /// other mechanisms. See <see cref="OperationTracer"/>.</summary>
    public IReadOnlyList<InvokedOperation> Operations { get; init; } = [];
    public required LinuxCompatibility LinuxCompatibility { get; init; }

    /// <summary>1.4.0, SOAP only: see <see cref="RuntimeVerdicts"/>.</summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public RuntimeCompatibility? RuntimeCompatibility { get; init; }
    public required double Confidence { get; init; }
    public IReadOnlyList<string> ConfidenceReasons { get; init; } = [];

    public object DetailBlock() =>
        (object?)Soap ?? Http ?? Grpc ?? Database ?? Messaging ?? Cache ?? SecretStore ?? FileShare ?? Smtp ?? (object?)Ldap
        ?? throw new InvalidOperationException($"invocation {InvocationId} has no detail block");
}

/// <summary>Part C3: scheme, host, port, path — and nothing else. Userinfo,
/// query and fragment are removed before one of these is built.</summary>
public sealed record Endpoint
{
    public string? Scheme { get; init; }

    /// <summary>Lowercased.</summary>
    public string? Host { get; init; }
    public int? Port { get; init; }
    public string? Path { get; init; }

    /// <summary><c>resolved</c>, <c>partial</c> (built from literal fragments
    /// and values this step could not resolve) or <c>unresolved</c>.</summary>
    public required string Resolution { get; init; }

    /// <summary>For an unresolved endpoint: the placeholder, environment
    /// variable or configuration key it waits on — <c>${SERVICE_URL}</c>,
    /// <c>env:SERVICE_URL</c>, <c>config:Services:Account:Url</c>. Never guessed.</summary>
    public string? Placeholder { get; init; }

    /// <summary>For a partial endpoint: the literal fragments, sanitised.</summary>
    public IReadOnlyList<string> Fragments { get; init; } = [];

    /// <summary>Which file and key the endpoint came from, when configuration.</summary>
    public ConfigSource? Source { get; init; }
}

public sealed record ConfigSource
{
    public required string SourceFile { get; init; }
    public required string KeyPath { get; init; }
}

public sealed record EnvironmentBinding
{
    /// <summary><c>default</c> for appsettings.json / web.config, else the
    /// environment the file is named for (appsettings.Docker.json → Docker,
    /// Web.Release.config → Release).</summary>
    public required string Environment { get; init; }
    public required string SourceFile { get; init; }
    public required string KeyPath { get; init; }
    public string? Scheme { get; init; }
    public string? Host { get; init; }
    public int? Port { get; init; }
    public string? Path { get; init; }
    public required string Resolution { get; init; }
    public string? Placeholder { get; init; }

    /// <summary>A database binding's authentication kind, or a Kafka
    /// binding's SASL mechanism — the fact its verdict can differ on.</summary>
    public string? Authentication { get; init; }

    /// <summary>This environment's own verdict. The invocation's verdict is
    /// the worst of these; an OpenShift target environment
    /// (appsettings.DEV.json) already on SQL authentication is
    /// compatible even where a legacy Windows environment is not.</summary>
    public string? LinuxVerdict { get; init; }

    public IReadOnlyList<string> LinuxReasons { get; init; } = [];

    /// <summary>1.3.0: for a class library, the host project whose
    /// configuration this is; null for the project's own.</summary>
    public string? HostProject { get; init; }

    /// <summary>1.3.0: the SetParameters parameter that sets this value, and
    /// how it was linked (<c>parameters_xml</c> exact, <c>name_and_path</c> lower).</summary>
    public string? DeployParameter { get; init; }
    public string? LinkMethod { get; init; }
    public double? LinkConfidence { get; init; }

    /// <summary>1.4.0, SOAP only: this environment's own effective security —
    /// binding, mode and the credential type that mode uses, declared or
    /// else the binding's default. Two environment files can configure one
    /// endpoint differently.</summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public EnvironmentSoapSecurity? Soap { get; init; }

    /// <summary>1.4.0, SOAP only: does the target .NET's WCF client support
    /// this binding, mode and credential type — <see cref="RuntimeVerdicts"/>,
    /// from the WCF client support matrix. The Linux verdict above is the
    /// platform question; this is the runtime one.</summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public string? RuntimeVerdict { get; init; }

    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public IReadOnlyList<string>? RuntimeReasons { get; init; }

    /// <summary>The matrix entry the runtime verdict rests on; null when none matched.</summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public string? RuntimeMatrixEntry { get; init; }

    /// <summary>1.5.0, SOAP only: the WCF client platform matrix entry the
    /// Linux verdict rests on; null when none matched.</summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public string? PlatformMatrixEntry { get; init; }
}

/// <summary>1.5.0: what a SOAP client's two verdicts are given from — the
/// engagement's target framework, the runtime matrix (wcf-client-support) and
/// the platform matrix (wcf-client-platform). Null matrices give
/// <c>unknown</c>, never a rule from code.</summary>
public sealed record SoapMatrices(string? Target, WcfClientSupport? Runtime, WcfClientSupport? Platform);

public sealed record EnvironmentSoapSecurity
{
    public required string Binding { get; init; }
    public string? SecurityMode { get; init; }
    public string? ClientCredentialType { get; init; }

    /// <summary><c>declared</c>, <c>binding_default</c> or <c>unresolved</c>.</summary>
    public required string SecuritySource { get; init; }
}

/// <summary>1.4.0: the runtime verdict of a SOAP client — the worst of its
/// environment bindings' — for the engagement's target framework, from
/// matrix version <see cref="MatrixVersion"/>.</summary>
public sealed record RuntimeCompatibility
{
    public required string Target { get; init; }
    public required string MatrixVersion { get; init; }
    public required string Verdict { get; init; }
    public IReadOnlyList<string> Reasons { get; init; } = [];
}

/// <summary>Runtime verdict values, worst first.</summary>
public static class RuntimeVerdictValues
{
    public const string Unsupported = "unsupported";
    public const string Unknown = "unknown";
    public const string SupportedWithCaveat = "supported_with_caveat";
    public const string Supported = "supported";

    public static int Rank(string verdict) => verdict switch
    {
        Unsupported => 0,
        Unknown => 1,
        SupportedWithCaveat => 2,
        _ => 3,
    };
}

public sealed record CredentialReference
{
    /// <summary><c>certificate</c>, <c>password</c>, <c>api_key</c>,
    /// <c>token</c>, <c>client_secret</c> or <c>windows</c>.</summary>
    public required string Kind { get; init; }
    public string? KeyPath { get; init; }
    public string? SourceFile { get; init; }

    /// <summary>Where in code it is attached, when code.</summary>
    public string? DeclaredAt { get; init; }
}

public sealed record CallSite
{
    public required string FilePath { get; init; }
    public required int LineStart { get; init; }
    public required int LineEnd { get; init; }
}

/// <summary>One operation a client invokes, where (1.2.0).</summary>
public sealed record InvokedOperation
{
    /// <summary>SOAP: the method called on the proxy or channel, as called.
    /// gRPC: the RPC (a generated <c>…Async</c> method's name without the suffix).
    /// Null for HTTP and when unresolved.</summary>
    public string? Operation { get; init; }

    /// <summary>HTTP: GET, POST, PUT, PATCH, DELETE; null when not readable.</summary>
    public string? Verb { get; init; }

    /// <summary>HTTP: the request path with any base-address path
    /// prefixed; a part this step could not read is <c>{…}</c>.</summary>
    public string? Path { get; init; }

    /// <summary>The member invoked, as written; null when unresolved.</summary>
    public string? Member { get; init; }

    /// <summary><c>resolved</c>, <c>partial</c> (an HTTP path with unread
    /// parts, or a verb that could not be read) or <c>unresolved</c>.</summary>
    public required string Resolution { get; init; }

    /// <summary>Why it is unresolved, or how it was found when indirect.</summary>
    public string? Reason { get; init; }

    public required CallSite CallSite { get; init; }
}

public sealed record LinuxCompatibility
{
    public required string Verdict { get; init; }
    public IReadOnlyList<string> Reasons { get; init; } = [];
}

public sealed record SoapDetail
{
    public required string Contract { get; init; }
    public required string Binding { get; init; }
    public string? SecurityMode { get; init; }
    public string? ClientCredentialType { get; init; }

    /// <summary><c>declared</c>, <c>binding_default</c> or <c>unresolved</c> —
    /// as step 4 records for services.</summary>
    public required string SecuritySource { get; init; }

    /// <summary>Where the binding came from, in Part C2's order of
    /// preference: <c>config</c>, <c>code</c> or <c>generated_reference</c>.</summary>
    public required string BindingSource { get; init; }

    /// <summary><c>hand_written</c> (ChannelFactory, a hand-written
    /// ClientBase) or <c>generated</c> (a service reference proxy) — a
    /// generated proxy is regenerated during migration, not rewritten.</summary>
    public required string ClientSource { get; init; }

    /// <summary><c>ChannelFactory</c>, <c>DuplexChannelFactory</c>, or the ClientBase class.</summary>
    public required string ClientType { get; init; }
    public string? EndpointName { get; init; }

    /// <summary>An <c>if</c> the client is created under, as written.</summary>
    public string? Condition { get; init; }

    /// <summary>The helper the client is built in, when it is built through
    /// one (<c>CreateTcpFactory</c>), and where that helper constructs it —
    /// the call site is where the helper is called.</summary>
    public string? Via { get; init; }
}

public sealed record HttpDetail
{
    /// <summary><c>HttpClient</c>, <c>IHttpClientFactory</c>, <c>WebClient</c>,
    /// <c>WebRequest</c> or <c>RestSharp</c>.</summary>
    public required string Library { get; init; }
    public string? ClientName { get; init; }
    public string? TypedClient { get; init; }
}

public sealed record GrpcDetail
{
    public string? Contract { get; init; }
}

public sealed record DatabaseDetail
{
    /// <summary>The connection string's name — never its value.</summary>
    public string? Name { get; init; }
    public string? Provider { get; init; }

    /// <summary><c>integrated</c>, <c>credentials</c> or <c>unknown</c>.</summary>
    public required string Authentication { get; init; }
    public bool LocalDb { get; init; }
}

public sealed record MessagingDetail
{
    /// <summary><c>kafka</c> or <c>msmq</c>.</summary>
    public required string Transport { get; init; }
    public IReadOnlyList<string> Topics { get; init; } = [];

    /// <summary>Kafka: the SASL mechanism where code or configuration states
    /// it — <c>gssapi</c>, <c>plain</c>, <c>scram</c>, <c>oauthbearer</c> —
    /// <c>none</c> where the client is built in code with no SASL at all, and
    /// <c>unknown</c> only where it cannot be determined (Part C6). MSMQ: <c>windows</c>.</summary>
    public required string Authentication { get; init; }

    /// <summary>Where the mechanism was read: a code location or a config file and key.</summary>
    public string? AuthenticationSource { get; init; }
}

public sealed record ProviderDetail
{
    /// <summary><c>redis</c>; <c>vault</c> or <c>azure_key_vault</c>.</summary>
    public required string Provider { get; init; }
}

public sealed record FileShareDetail
{
    /// <summary>The share, <c>\\server\share</c> — no deeper path.</summary>
    public required string Share { get; init; }
}

public sealed record SmtpDetail
{
    public bool UsesDefaultCredentials { get; init; }
}

public sealed record LdapDetail
{
    /// <summary><c>System.DirectoryServices</c>,
    /// <c>System.DirectoryServices.AccountManagement</c> or
    /// <c>System.DirectoryServices.Protocols</c>.</summary>
    public required string Api { get; init; }
}
