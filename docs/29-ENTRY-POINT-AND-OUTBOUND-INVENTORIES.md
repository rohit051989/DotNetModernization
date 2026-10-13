# 29 — Entry-Point and Outbound-Invocation Inventories (`entry-point-inventory`, `outbound-invocation-inventory`)

Lifecycle steps `entry-point-inventory` and `outbound-invocation-inventory`. Owner: **P**. Job: `phase0-repository-discovery`, after
`application-fingerprinting`. Implemented in **C# / .NET**, invoked via the `process` adapter.

`application-fingerprinting` detects **presence** — "this project has controllers". These steps produce
**inventories** — "`GET /api/accounts/{id}` is handled by
`AccountsController.GetById`", and "this project calls `wsse0.saifg.rbc.com` over
NetTcp". Different shape, different consumers.

| | `entry-point-inventory` — inbound | `outbound-invocation-inventory` — outbound |
|---|---|---|
| Question | What can call this application? | What does this application call? |
| Viewpoint | FUNCTIONAL | CONTEXT |
| Feeds | `contract-snapshot`, `characterization-test-generation`, `risk-scoring-tier-assignment` | Endpoint register (`dependency-and-context-map`), `risk-scoring-tier-assignment`, decisions |

---

## Part A — Shared decisions

### A1. Extend the `application-fingerprinting` solution

Both steps are new projects in `steps/step-003-fingerprinting/`, sharing
`Fingerprinting.Analysis` for project loading and Roslyn parsing, and the Cli
infrastructure for the envelope.

This reuses what `application-fingerprinting` already solved: `MSBuildLocator` registered before any MSBuild
type loads, stdout carrying only the StepResult, deterministic JSON with sorted keys and
`\n` line endings, generated-code exclusion, SARIF-safe path encoding, and the secrets
rules. Rebuilding any of that is risk with no benefit.

Each step still has its own registration, its own published binary, its own artifact
and its own tables. Sharing a library is not sharing a contract.

### A2. Syntax analysis, with honest confidence

Semantic analysis stays off, per `application-fingerprinting`'s Part A4. Route templates, type names and
member names are recorded **as written in source**. Where a value cannot be confirmed
syntactically — a base class that might be user-defined, a route token needing
resolution — confidence is below 1.0 and the reason is recorded.

### A3. Consumes

```yaml
consumes:
  - artifact_type: solution-project-inventory
    version_range: "^2.0.0"
  - artifact_type: application-fingerprint
    version_range: "^1.2.0"
```

`solution-discovery` supplies the project list and paths. `application-fingerprinting` supplies which projects are
out-of-scope, so these steps skip what `application-fingerprinting` skipped. Neither re-derives project
structure.

### A4. Secrets

Both steps inherit docs/21 Part G. `outbound-invocation-inventory` carries the most risk, since outbound
configuration is where credentials live. Specific rules in Part C5.

---

## Part B — `entry-point-inventory`

### B1. Entry point kinds

| Kind | Detected from |
|---|---|
| `http_controller_action` | Actions on controllers — `ControllerBase`, `Controller`, `ApiController` subclasses, or `[ApiController]` |
| `http_minimal_api` | `MapGet`, `MapPost`, `MapPut`, `MapDelete`, `MapPatch`, `MapMethods` |
| `wcf_operation` | `[OperationContract]` members on `[ServiceContract]` interfaces, with the implementing class where found |
| `asmx_web_method` | `[WebMethod]` members in `.asmx.cs` |
| `grpc_service_method` | Overrides on classes deriving from a generated `*Base` gRPC type |
| `signalr_hub_method` | Public methods on `Hub` subclasses |
| `message_consumer` | Kafka `IConsumer<,>` usage, MSMQ `MessageQueue.Receive`, `IHostedService` consuming a queue |
| `hosted_service` | `BackgroundService` and `IHostedService` implementations |
| `scheduled_job` | Quartz `IJob`, Hangfire recurring jobs, `System.Threading.Timer` in a hosted service |
| `console_main` | `Main` or top-level statements, for projects with no other entry points |
| `webforms_page` | `.aspx` code-behind classes deriving from `Page` |

A project may have many kinds. A web API with a background worker records both.

### B2. HTTP route composition

The route is the thing contract snapshot needs, so compose it rather than recording
fragments.

```
controller [Route("api/[controller]")]   +   action [HttpGet("{id}")]
= api/accounts/{id}                          GET
```

Rules:

- `[controller]` resolves to the class name minus a `Controller` suffix, lowercased per
  the default convention. `[action]` resolves to the method name. `[area]` from
  `[Area]`
- an action-level template beginning with `/` or `~/` **replaces** the controller
  template rather than appending
- multiple `[Route]` or verb attributes produce one entry each
- a controller with no attribute routing falls back to **conventional routing**. Record
  `routing: conventional` with the controller and action, and a null template, since the
  route table is defined elsewhere. Do not guess
- minimal APIs: compose `MapGroup` prefixes with the mapped template where they are
  statically resolvable. A prefix held in a variable is recorded as unresolved
- an action with no verb attribute on an `[ApiController]` records verb `ANY` with
  confidence 0.7

### B3. Entry point record

```json
{
  "entryPointId": "sha256 of project + kind + handler + route + verb, truncated",
  "kind": "http_controller_action",
  "projectPath": "src/AccountOpenAPI/AccountOpenAPI.csproj",
  "handler": { "type": "AccountsController", "member": "GetById",
               "filePath": "src/AccountOpenAPI/Controllers/AccountsController.cs",
               "lineStart": 42, "lineEnd": 58 },
  "http": { "verb": "GET", "routeTemplate": "api/accounts/{id}",
            "routing": "attribute",
            "parameters": [ { "name": "id", "type": "int", "source": "route" } ],
            "returnType": "ActionResult<AccountDto>",
            "authorisation": "[Authorize(Policy = \"AccountRead\")]" },
  "confidence": 1.0,
  "confidenceReasons": []
}
```

Other kinds populate their own block — `wcf`, `grpc`, `messaging`, `schedule` —
instead of `http`.

`entryPointId` is derived, not random, so it is stable across rescans. The same
reasoning as stable project ids: anything keyed to an entry point survives a rescan.

`parameters[].source` is `route`, `query`, `body`, `header`, `form` or `inferred`,
from `[FromRoute]` and siblings, or inferred per the `[ApiController]` conventions.

`authorisation` records the attribute as written. It matters to contract snapshot and
to risk scoring, and a public endpoint is a different risk from an authorised one.

### B4. Tables and artifact

`entry_points` — one row per entry point: `id` (derived) PK, `repository_id`,
`project_id`, `kind`, `handler_type`, `handler_member`, `file_path`, `line_start`,
`line_end`, `detail` JSONB (the kind-specific block), `confidence`,
`confidence_reasons` JSONB, `step_execution_id`, `detected_at`.

Indexes on `(project_id, kind)` and `(repository_id, kind)`.

Artifact `entry-point-inventory@1.0.0` — per project, entry points sorted by kind then
route or handler. Deterministic per `application-fingerprinting`'s rules.

A per-project summary: count by kind, count by HTTP verb, count unauthorised. The
unauthorised count is worth surfacing prominently.

### B5. As implemented (`entry-point-inventory`, scanner 2.1.0)

**Layout.** `Fingerprinting.EntryPoints` (detectors, composition) and
`Fingerprinting.EntryPoints.Cli` (exe, published to
`publish/entry-point-inventory/`). `application-fingerprinting`'s shared plumbing moved into libraries,
not copied: `Fingerprinting.Analysis` now holds the file walk, `SourceFileScanner`
and the Roslyn name helpers; the new `Fingerprinting.StepHost` holds the envelope,
`StepBootstrap` (MSBuildLocator, stdout guard, culture), `StepEnvelopeRunner`, the
schema gate, artifact URIs and `PlatformDatabase`. `application-fingerprinting`'s artifacts are
byte-identical before and after the move.

**Inputs (A3).** Both `consumes` entries are required, and
`phase0-repository-discovery` v7 wires them (`${artifacts.solution-project-inventory}`,
`${artifacts.application-fingerprint}`). They are the only input path. The "no job
definition change" rule holds only while a step's consumes and produces are unchanged,
and `entry-point-inventory` gained two inputs. An earlier build registered them optional and read
`solution-discovery`'s and `application-fingerprinting`'s tables when they were unwired; that fallback is deleted. Two input
paths are two behaviours that can drift, and a fallback keeps working silently when
the wiring breaks. Registering the required inputs invalidated v6 — validator rule 9,
`UNWIRED_INPUT`, as intended — and v7 replaces it. The engine records each run's
resolved inputs, with artifact versions and ids, in `wf_step_executions.inputs_resolved`.

**Additions to the record (B3).** `handler.namespace`; top-level `unauthorised`
(true / false / null — null where neither source nor config declares it); on
`http`, `controller` and `action`, `mappedTemplate`, `groupPrefix {resolution,
prefix, expression}` and `handlerForm` (`lambda` / `method_group`). `source:
inferred` parameters carry `inferredSource` where the conventions decide one
syntactically — `[ApiController]`: route name → route, `IFormFile` → form, simple
→ query, complex → body; minimal APIs leave a complex type null (body or DI
service is not decidable without binding). `[FromServices]` and framework types
(`CancellationToken`, `HttpContext`, ...) are not parameters.

**Confidence rules.** Each is the minimum across what applies, with its reason:

| Condition | Confidence |
|---|---|
| A route token resolved by convention (`[controller]`, `[action]`, `[area]`) | 0.9 |
| `[action]` on a method ending `Async` (ASP.NET Core drops the suffix by default) | 0.8 |
| `[area]` with no `[Area]` attribute — token left in place | 0.5 |
| Controller base or route reached through an in-project base class; Ardalis `EndpointBase*` | 0.9 |
| `[ApiController]` action with no verb attribute — verb `ANY` | 0.7 |
| Web API 2 verb inferred from a method-name prefix / defaulting to POST | 0.8 / 0.7 |
| Route template not a literal — composed route null | 0.5 |
| `MapGroup` prefix not statically resolvable (a variable, a caller's group) — route null | 0.6 |
| WCF implementation matched by interface name, not named by a `.svc` or `ServiceHost` / one of several | 0.9 / 0.6 |
| WCF contract nothing in the repository implements | 0.5 |
| gRPC base with no Grpc package or `.proto` in the project | 0.7 |

**Decisions.**
- **WCF.** An implementation in the contract's own project takes precedence over
  a match elsewhere, because two copies of one service in a repository would
  otherwise claim each other's. When a `.svc` file or `new ServiceHost(typeof(X))`
  names an implementation, the others (mocks) are not recorded. A contract
  implemented only by `ClientBase<T>` proxies is outbound (`outbound-invocation-inventory`), not an entry
  point.
- **Authorisation.** Every inbound entry point is true, false or null. Null
  means *not assessed*: neither source nor config declares its authorisation.
  `[AllowAnonymous]` anywhere wins. HTTP, gRPC, SignalR and Razor Pages are decided
  in source. WCF, ASMX and WebForms are decided from config as well (1.1.0, below).
  Project-wide authorisation written in source —
  a global `AuthorizeFilter` or MVC 5 `AuthorizeAttribute` filter,
  `MapControllers().RequireAuthorization()`, a fallback policy — is applied to the
  entry points it covers, and listed per project.
- **Conventional route tables** (`MapControllerRoute`, `routes.MapRoute`,
  `MapHttpRoute`) are recorded per project as written, for the reader, and are
  never used to fill in a template.
- **`console_main`** applies only when a project has no other entry point. So
  top-level statements in a web app are not recorded, and a WinForms `Main` is
  recorded, flagged `staThread`.
- **`entryPointId`** hashes repository + project + kind + handler (namespace-
  qualified, with parameter types) + route + verb, truncated to 32 hex digits. The
  repository is included because the id is the table's key and a fork can hold
  identical projects. A lambda handler's identity holds no line number, so moving
  code does not change the id. A genuine duplicate registration gets an ordinal.
- **Tables.** `entry_points` gains an `unauthorised` column, so the count is a
  query. `entry_point_scans` — one row per repository, as `fingerprint_scans` is
  for `application-fingerprinting` — holds the summaries the rows cannot: skipped projects, global
  authorisation, conventional routes.

**1.1.0 — `razor_page`.** A twelfth kind: a `.cshtml` whose first directive is `@page`
(a BOM and CRLF endings are both allowed), its `PageModel` code-behind (or the class
its `@model` names), and one entry point per handler: `OnGet`, `OnPostAsync`,
`OnPostDeleteAsync` (named handler `Delete`). A page with no GET handler still
renders, so it gets a GET entry with no member. The route follows the default
convention: the path under `Pages/` or `Areas/{area}/Pages/` without the extension;
an `Index` page answers at its folder; `@page "t"` appends, and `@page "/t"` replaces.
Authorisation comes from `[Authorize]` / `[AllowAnonymous]` on the model, the Razor
Pages conventions (`AuthorizePage`, `AuthorizeFolder`, `AllowAnonymousTo…`, area
variants), global MVC filters and a fallback policy. Entries use the `http` block,
with `routing: razor_page`, `pageFile` and `pageHandler`.

**1.1.0 — WCF security from config and code.** A service's hosts are indexed
repository-wide:
- `.svc` files anywhere, including an IIS folder that is no project, with the
  endpoints the web.config in the same folder declares for the service;
- `new ServiceHost(typeof(X))` with its `AddServiceEndpoint(typeof(C), binding,
  address)` calls, plus the endpoints the hosting project's app.config declares;
- CoreWCF `AddServiceEndpoint<TService, TContract>(binding, address)`.

A generic hosting helper (`Build<TService, TContract>(…)` with `typeof(TService)`
inside) is followed to each call site, which binds the type arguments and literal
arguments. A credential type written as `flag ? Certificate : None` then resolves per
call. The binding's security comes from `bindingConfiguration` (or the unnamed default
binding configuration), from constructor arguments (`new NetTcpBinding(SecurityMode.
Transport)`), from object initialisers, and from later `binding.Security…` assignments.

A value left out falls back to WCF's documented default for that binding. It is marked
`securitySource: binding_default` — `basicHttpBinding` → None; `netTcpBinding` →
Transport / Windows; `wsHttpBinding` → Message / Windows — and never passed off as
declared. Where no default is certain, it stays `unresolved`. An endpoint added
under an `if` records the condition as written.

A WCF operation is unauthorised when any endpoint takes no client credential (mode
None, or credential type None), authorised when every endpoint takes one or a
`[PrincipalPermission]` demand applies, and *not assessed* otherwise — including a
service with no declared endpoint. That last case is WCF's default endpoints, which
the config does not declare. As with implementations, hosts inside the
implementation's own project win over same-named hosts elsewhere.

**1.1.0 — ASP.NET `<authorization>` for ASMX and WebForms.** Rules from `<location
path>` blocks and folder web.config files, nearest the page first, then the root
`<system.web>`. The first rule naming `?` or `*` decides. If rules exist but none
names an anonymous user, machine.config's `allow users="*"` lets anonymous users in.
With no `<authorization>` on the path at all, the page is not assessed. WCF ignores
`<authorization>` unless ASP.NET compatibility is on, so it is not applied to WCF.

**2.0.0 — `auth_declared`, not "unauthorised".** Every entry point that can be called
from outside carries `authDeclared`: `declared`, `none_declared` or `not_assessed`.
Kinds that are never called from outside carry null. The count is
`noDeclaredAuthenticationCount`, "no declared authentication", in the artifact, the
table, the API and the UI. Gateway, reverse-proxy and header-based authentication — an
API gateway such as Apigee, an access manager such as ISAM injecting identity headers
— sit in front of the code and are invisible to static analysis. So `none_declared` is
a prompt to review how an entry point is protected, not a finding that it is open. The
artifact states this in `authDeclaredScope`, and the UI shows it beside every count. The
artifact is 2.0.0 because the field rename is breaking.

**2.0.0 — seven kinds**, ported from the find-dotnet-entry-points pattern catalog
(`references/dotnet-entry-point-patterns.md`). The catalog supplied the rules; its
regex-based code was not used, and the rules are reimplemented on syntax trees:
- `windows_service` — `System.ServiceProcess.ServiceBase` subclasses; the lifecycle
  hooks they override, the service name and where `ServiceBase.Run` starts them.
  Confidence 0.7 if `ServiceBase` is not confirmed as System.ServiceProcess's.
- `http_handler` — `IHttpHandler` / `IHttpAsyncHandler` / `HttpTaskAsyncHandler` and
  `IHttpModule` in source; `.ashx` files; `<httpHandlers>`, `<handlers>`,
  `<httpModules>` and `<modules>` registrations. A registered framework or package
  type with no source is recorded too, `inRepository: false`. A folder web.config's
  `path` is qualified with its folder. Handlers take web.config `<authorization>` for
  their path; modules carry no auth.
- `global_asax` — `Application_*` / `Session_*` methods on `HttpApplication`
  subclasses, with scope (application, request, session).
- `owin_startup` — `[assembly: OwinStartup(typeof(X))]`, the `owin:appStartup` app
  setting, or a `Startup` class with `Configuration(IAppBuilder)` by convention; the
  middleware registered across every partial part.
- `blazor_component` — `@page` routes in `.razor` files, with `@attribute [Authorize]`.
- `azure_function` — `[FunctionName]` (in-process) and `[Function]` (isolated), with
  the trigger type. An HTTP trigger's authorization level decides `authDeclared`:
  `Anonymous` is `none_declared`, and a key level (including the omitted default,
  `Function`) is `declared`.
- `desktop_app` — WinForms `[STAThread] Main` (the form `Application.Run` or
  `ShowDialog` opens) and WPF `App.xaml` applications. Recorded instead of
  `console_main`.

`message_consumer` extends to MassTransit `IConsumer<T>` and NServiceBus / Rebus
`IHandleMessages<T>`, one entry per message type. Kafka's `IConsumer<TKey, TValue>` is
now told from MassTransit's by type-argument count.

**2.0.0 — the capability manifest.** `schemas/entry-point-capabilities-1.0.0.json`
publishes every kind `entry-point-inventory` detects — what it detects, what identifies it, how
`authDeclared` is decided, the version it arrived in — and the patterns it does not
cover. It ships beside the exe, every artifact is stamped with its version and kinds,
and the scan row stores the stamp. `GET /api/workflow/steps/entry-point-inventory/
capabilities` serves it with how often each kind is found across the estate. Workflow
Administration shows it under Detection capabilities, beside `application-fingerprinting`'s extractor
readiness. This is the extractor-readiness principle applied to entry points: a listed
kind with none found is a result; a pattern under not covered is a declared gap, not a
silent miss. A test holds the manifest and the scanner's kinds together.

**2.1.0 — `origin` and `entryClass`** on every entry point (additive; capability
manifest 1.1.0 records each kind's class).
- `origin: application | framework`. Framework is a web.config handler or module
  registration of a type no project in the repository declares — Application Insights,
  session state, Autofac, `TransferRequestHandler`, `HttpNotFoundHandler`. It is
  decided by looking the full type name up across every project, not by a list of
  vendor prefixes like the skill's `THIRD_PARTY_PREFIXES`: a list goes stale, and it
  misclassifies a module whose source sits in another project of the same repository.
  Framework entries stay in the inventory, since `IHttpModule` registrations matter for
  the move to middleware, but they migrate through their package's own path rather than
  by rewriting.
- `entryClass: request | lifecycle`. Lifecycle is bootstrap and wiring: Global.asax
  events, OWIN startup, HTTP modules (which hook pipeline events at `Init`), hosted and
  Windows services, console and desktop mains. Everything else is request: HTTP
  actions, minimal APIs, Razor Pages, WCF, ASMX, gRPC, SignalR, WebForms, Blazor, Azure
  Functions, message consumers, scheduled jobs, HTTP handlers.
- Downstream, only request entry points are surface. Risk scoring (`risk-scoring-tier-assignment`), contract
  snapshots (`contract-snapshot`) and test generation (`characterization-test-generation`) read request entry points only.
  Lifecycle hooks carry no `authDeclared` — a database constraint enforces it — so
  "no declared authentication" counts request entry points only.
- Totals are reported as `requestEntryPointCount` and `lifecycleHookCount`, with
  `countByOrigin`.

**Known limitations, for later steps.**
- *Origin is decided per repository.* A module registered in one repository's
  web.config whose source lives in another repository — a shared in-house library —
  is classified `framework`, because the scan only sees the repository it runs on.
  `dependency-and-context-map` has the estate-wide view to reconcile this: a `framework` registration whose
  full type name some other repository declares is `application` code.
- *A poll-loop service has no request entry point.* A `BackgroundService` (or Windows
  service) that loops with no timer and no recognised consumer yields one lifecycle
  hook and zero request entry points, although it does real work on every iteration.
  `risk-scoring-tier-assignment` must not read zero request entry points as low risk when a
  `hosted_service` or `windows_service` is present: the work those services do is
  invisible to the request count.

**Not covered yet** (listed in the manifest): ASP.NET Core middleware, `IRouteHandler`,
WebForms control events, the Azure Service Bus SDK processor, RabbitMQ client consumers,
Hangfire `BackgroundJob.Enqueue`, `function.json`, WebJobs, Service Fabric, Orleans,
Dapr, BizTalk, SSIS, Sitecore / Umbraco pipelines, in-house dispatchers. Also not
covered: actions inherited from an abstract base controller, WCF `serviceAuthorization`
behaviours, and web.config transforms.

### B6. Architecture signals (scanner 2.2.0, signal registry 1.8.0)

A service is often assembled across projects. In the WCF sample the contracts are in
`Catalog.Contracts`, the implementations in `Catalog.Services`, the `ServiceHost` and
`system.serviceModel` in `Catalog.Host`, and the `.svc` files in `Hosting.Iis`, which has
no project file. A detection rule over `application-fingerprinting` signals matches signals within one project, so it cannot
see the service. `entry-point-inventory` has already put it together, so it is also a **signal
producer**, in the same way as `dependency-assessment`.

- **Registration.** `entry-point-inventory` is registered as the producer `EntryPointInventory` in
  `extractors.yaml` and in signal registry 1.8.0. The registration, the artifact and the
  scanner are 2.2.0, and the capability manifest is 1.2.0.
- **Writing.** At the end of a run, `entry-point-inventory` deletes its own `fingerprint_signals` rows for
  the repository (`extractor = 'EntryPointInventory'`) and writes the new set. `item-detection`
  reads them like any other signal.
- **Scope.** Only application-origin entry points count. A framework-origin entry point
  (an external base class) does not make a project expose a service.
- **Evidence.** The evidence is the implementing class (type, member and line span) or the
  host construction. A signal carries at most 20 evidence entries, in deterministic order.

| Signal | Project | Value |
|---|---|---|
| `EXPOSES_WCF_SERVICE` | the project implementing a service contract | the contract |
| `WCF_SERVICE_HOSTING` | the implementing project | where it is hosted, for example `ServiceHost in src/Catalog.Host/Catalog.Host.csproj` or `IIS .svc in src/Hosting.Iis (no project file)`, or `no host found` |
| `HOSTS_WCF_SERVICE` | the project that constructs the `ServiceHost`, or owns the `.svc` file | the contract |
| `EXPOSES_HTTP_API` | controllers or minimal APIs | the handler type |
| `EXPOSES_ASMX_SERVICE` | `[WebMethod]` services | the service path |
| `EXPOSES_GRPC_SERVICE` | gRPC service implementations | the service |
| `EXPOSES_WEBFORMS_UI` | `.aspx` pages | the page path |

A host file with no project file has no project to hold `HOSTS_WCF_SERVICE`. It is still
recorded, through `WCF_SERVICE_HOSTING` on the implementing project. The owner of a host
file is the project whose directory is the longest prefix of the file's path.

On the WCF sample, `Catalog.Services` carries `EXPOSES_WCF_SERVICE` five times (once per
contract) and `Catalog.Host` carries `HOSTS_WCF_SERVICE` five times. `Catalog.Services`
also has two hosting values: the IIS `.svc` files and the `ServiceHost`.

### B7. Framework delta signals (scanner 2.3.0, signal registry 1.10.0)

The discovery side of the framework delta catalog (34-CONVERSION-ARCHITECTURE.md C6): known
breaking changes between a project's framework and a later one, emitted as signals so a
conversion plan fixes them before the retarget. They are structural facts, emitted whatever
the engagement's target; the delta catalog says from which framework each one breaks. The
step reads `solution-discovery`'s project references (resolved, transitive) and project SDKs
alongside each project's syntax. Scanner and registration 2.3.0, capability manifest 1.3.0
(the same kinds); the artifact stays 2.2.0, unchanged in shape.

| Signal | Project | Value |
|---|---|---|
| `AMBIGUOUS_TOP_LEVEL_PROGRAM_ON_NET10` | a project that names `Program` and references two or more projects whose `Program` is public on net10.0, at least one of them only from net10.0 | the file with the top-level statements of each project whose `Program` becomes public only on net10.0 — where the fix goes |

From .NET 10, ASP.NET Core generates `public partial class Program` for a `Microsoft.NET.Sdk.Web`
project with top-level statements, unless the project declares Program's accessibility itself.
On net8.0 that Program is internal. A project referencing two web projects and naming
`Program` (`WebApplicationFactory<Program>`) therefore compiles on net8.0 and fails with CS0433
on net10.0. Not emitted when the project has a Program of its own (the name binds to it), when
it never names `Program`, or when it is already ambiguous on its own framework. On eShopOnWeb:
`tests/PublicApiIntegrationTests` references `Web` (implicit Program) and `PublicApi` (`public
partial class Program`); the value is `src/Web/Program.cs`.

---

## Part C — `outbound-invocation-inventory`

### C1. Mechanisms

| Mechanism | Detected from |
|---|---|
| `http_client` | `HttpClient` usage, `IHttpClientFactory` named and typed clients, `BaseAddress` |
| `soap_client` | WCF `ClientBase<T>`, `ChannelFactory<T>`, generated service references, `<client><endpoint>` config |
| `grpc_client` | `GrpcChannel.ForAddress`, generated gRPC clients |
| `database` | Connection strings by name and provider |
| `message_producer` | Kafka producers, MSMQ sends |
| `message_consumer` | Kafka consumers, MSMQ receives — the outbound connection to the broker |
| `cache` | Redis connection configuration |
| `secret_store` | Vault configuration |
| `file_share` | UNC paths from `application-fingerprinting`'s `UNC_PATH_LITERAL` |
| `smtp` | `SmtpClient`, mail configuration |
| `ldap` | `System.DirectoryServices` usage |

### C2. The binding type is the point

For `soap_client`, **record the binding**, and with it the security mode and credential type:
the three together decide whether the call works on Linux (C6, C10). The binding alone does
not. NetTcp works cross-platform, while its *default* transport credential, `Windows`,
negotiates Kerberos and needs configuring on Linux. Named pipes and MSMQ have no Linux
client at all.

Sources, in order of preference: `<client><endpoint binding=…>` in config; a binding
constructed in client code (`new NetTcpBinding()`); the binding inside a generated
`Reference.cs` — which, per `application-fingerprinting`'s precedent, is read for this purpose only.

**Clients built by a custom helper (scanner 1.6.0).** AccountsApi creates every SOAP client
through one helper: `_wcfClientHelper.CreateClient<ICreditCheckService>(ClientName)`, which
caches `BuildFactory<TChannel>(name)` in a `GetOrAdd`, which builds
`new ChannelFactory<TChannel>(WcfBindingFactory.Create(client.BindingName, bindingSettings), …)`
from `_settings.Clients.TryGetValue(clientName, out var client)` and
`_settings.Bindings.TryGetValue(client.BindingName, out var bindingSettings)` — options bound
from the `Wcf` section. Before 1.6.0 that was one client, contract `TChannel`, binding unknown.
Two additions, both syntactic (`SoapClientDetector.Options.cs`):

- Call sites are followed up through the helper's callers while a site only forwards the
  enclosing method's type or value parameters (at most three levels). A parameter of a lambda
  handed to `GetOrAdd(key, name => …)` / `AddOrUpdate` is the key. So each
  `CreateClient<I>(name)` is its own client, with its contract and name bound, and its
  operations are followed on the channel it returns. An unqualified constant (`ClientName`,
  declared by five classes) resolves in its own type first.
- An options-bound dictionary lookup gives a variable a configuration section
  (`Wcf:Clients:CreditCheck`); a lookup keyed by a member of that variable reads it
  (`Wcf:Bindings:{BindingName}`). The binding section's type, security mode and credential
  type are read by key name — `BindingType`/`Binding`/`Type`, `BindingMode`/`SecurityMode`/`Mode`,
  `ClientCredentialType`/`CredentialType` — falling back to a settings property's initializer
  when every declaration agrees (`BindingMode = "Transport"`), because the code maps them
  through a switch this step does not evaluate. The address is the client section's member that
  reaches `new EndpointAddress(…)`, through `Uri.TryCreate(…, out var address)`. Every environment
  whose files set any key read is one binding with its own address and security
  (`bindingSource: config`, confidence 0.9).
- A credential attached under `if (!string.IsNullOrWhiteSpace(client.CertificateName))` is
  attached only when some environment sets that key, and carries it as `keyPath`.

Tests: `SoapHelperClientTests`.

Also record `securityMode` where declared — `Transport`, `Message`,
`TransportWithMessageCredential`, `None` — and `clientCredentialType`. Where nothing is
declared, the binding's default applies, and that default is what gets judged (C10).

### C3. Endpoint normalisation

The endpoint register in `dependency-and-context-map` aggregates by endpoint, so endpoints must normalise to
comparable values.

```
record:  scheme · host · port · path
strip:   userinfo, query string, fragment
case:    host lowercased
```

`http://svc:pass@wsse0.saifg.rbc.com:8080/Account.svc?wsdl` records as scheme `http`,
host `wsse0.saifg.rbc.com`, port `8080`, path `/Account.svc`. The credentials and query
never reach storage.

### C4. Configuration resolution

Endpoints mostly live in configuration, often across environment files, sometimes as
placeholders.

- resolve an endpoint from `appsettings*.json`, `web.config` and `app.config`, recording
  **which file and key** it came from
- the same logical endpoint differing by environment file records **one invocation with
  several environment values**, not several invocations. `appsettings.DEVOCP.json` and
  `appsettings.PROD.json` pointing at different hosts is one dependency with two
  environment bindings
- a value that is a placeholder (`${SERVICE_URL}`, `%SERVICE_URL%`, `{{…}}`) or reads an
  environment variable records `resolution: unresolved` with the placeholder name. Do
  not guess
- a URL built by string concatenation in code records the literal fragments and
  `resolution: partial`

### C5. Secrets — stricter than `application-fingerprinting`

- connection strings: name, provider, and **server host only**. Never database name,
  user, password or any other key. Host matters for the endpoint register; nothing else
  does
- URLs: userinfo, query and fragment stripped before storage, per C3
- configuration keys matching the sensitive-key pattern: key path only, never value
- API keys, tokens and certificates referenced by a client: record that one is
  configured and its key path, never its value
- test: a fixture containing a connection string with a password, a URL with embedded
  credentials, and an API key must produce an artifact whose text contains none of the
  three secret values

### C6. Linux-compatibility verdict

Each invocation carries a verdict with a reason:

| Condition | Verdict |
|---|---|
| SOAP | From the **WCF client platform matrix** (C10), keyed by binding, effective security mode and credential type — never a rule in code. In 1.1.0: |
| — `basicHttpBinding` None/None and Transport/None; `netTcpBinding` Transport/None and Transport/Certificate | `compatible` — specific entries, each with a passing probe (C11) |
| — `wsHttpBinding` TransportWithMessageCredential/Certificate | `incompatible` on probe evidence — the backend's owner must offer another security mode or credential (C11) |
| — any HTTP binding or `netTcpBinding` with a `Windows` credential (declared, or the binding's default) | `requires_change` — Kerberos configuration on our side, or a credential change by the backend's owner (C10) |
| — HTTP bindings with an `Ntlm` credential | `incompatible` — the backend's owner must accept another credential |
| — `netNamedPipeBinding`, `netMsmqBinding`, `msmqIntegrationBinding`, `netPeerTcpBinding` | `incompatible` — the backend's owner must offer another binding |
| — every other mode and credential of the HTTP bindings and `netTcpBinding` | `unknown` — unprobed: a wildcard may not assert compatible (the wildcard rule, C10) |
| — `customBinding`, `wsDualHttpBinding`, or binding or security unresolved | `unknown` — no entry |
| SQL with Integrated Security or SSPI | `requires_change` — needs SQL auth or a Kerberos keytab |
| SQL with SQL authentication | `compatible` |
| MSMQ | `incompatible` |
| UNC file share | `requires_change` — needs an SMB mount |
| LDAP via `System.DirectoryServices` | `incompatible` |
| Kafka with SASL/GSSAPI | `requires_change` — "Kerberos keytab required". GSSAPI is directly visible where stated: `SaslMechanism.Gssapi` in code, `sasl.mechanism=GSSAPI` in configuration, or a SASL security protocol with no mechanism (librdkafka's default is GSSAPI) |
| Kafka with another SASL mechanism, or none | `compatible` (PLAIN, SCRAM, OAUTHBEARER; or a config built in code with no SASL) |
| Kafka with no stated mechanism | `unknown` — only where the mechanism genuinely cannot be determined: a config object supplied from elsewhere, nothing in configuration |
| HTTP, gRPC, Redis, Vault | `compatible` |
| Anything unresolved | `unknown` |

**Per environment.** Every environment binding carries its own verdict; the
invocation's verdict is the worst of them — a summary. The per-environment verdict
is the answer for a migration target: an OpenShift environment
(`appsettings.DEVOCP.json`) already on SQL authentication is `compatible` even where
a legacy Windows environment's Integrated Security is not.

**Unused clients.** A client with no construction site and no configuration — a
`ClientBase` subclass nothing builds or configures — is `usage: unused`. It stays in
the inventory but is left out of every count, and `dependency-and-context-map`'s endpoint register reads
`usage = 'used'` only, so no one asks a backend team about an endpoint nothing calls.

`unknown` is an honest answer, not a failure. The client needs to know what could not
be assessed as much as what could.

### C7. Invocation record

```json
{
  "invocationId": "derived — project + mechanism + normalised endpoint + contract",
  "mechanism": "soap_client",
  "projectPath": "src/AccountOpenAPI/AccountOpenAPI.csproj",
  "endpoint": { "scheme": "net.tcp", "host": "wsse0.saifg.rbc.com", "port": 808,
                "path": "/AccountService.svc", "resolution": "resolved" },
  "environmentBindings": [
    { "sourceFile": "appsettings.DEVOCP.json", "keyPath": "Services:Account:Url",
      "host": "wsse0-dev.saifg.rbc.com" },
    { "sourceFile": "appsettings.PROD.json", "keyPath": "Services:Account:Url",
      "host": "wsse0.saifg.rbc.com" }
  ],
  "soap": { "contract": "IAccountService", "binding": "netTcpBinding",
            "securityMode": "Transport", "clientCredentialType": "Windows" },
  "callSites": [ { "filePath": "src/AccountOpenAPI/Services/AccountClient.cs",
                   "lineStart": 31, "lineEnd": 31 } ],
  "operations": [
    { "operation": "OpenAccount", "verb": null, "path": null, "member": "OpenAccount",
      "resolution": "resolved", "reason": null,
      "callSite": { "filePath": "src/AccountOpenAPI/Services/AccountClient.cs",
                    "lineStart": 44, "lineEnd": 44 } }
  ],
  "linuxCompatibility": { "verdict": "requires_change",
                          "reasons": ["netTcpBinding Transport/Windows: requires change on Linux — …",
                                      "change: Kerberos configuration on our side, or a credential change by the backend's owner"] },
  "confidence": 0.9
}
```

### C8. Tables and artifact

`outbound_invocations` — one row per invocation: `id` (derived) PK, `repository_id`,
`project_id`, `mechanism`, `endpoint_scheme`, `endpoint_host`, `endpoint_port`,
`endpoint_path`, `resolution`, `detail` JSONB, `environment_bindings` JSONB,
`call_sites` JSONB, `linux_verdict`, `linux_reasons` JSONB, `confidence`,
`step_execution_id`, `detected_at`.

Indexes on `(repository_id, mechanism)`, `(endpoint_host)` and `(linux_verdict)` — the
host index is what `dependency-and-context-map`'s aggregation reads.

Artifact `outbound-invocation-inventory@1.0.0`. Per-project summary: count by
mechanism, count by verdict, and the incompatible invocations listed explicitly.

### C9. As implemented (`outbound-invocation-inventory`, scanner 1.3.0)

**Where it lives.** `src/Fingerprinting.Outbound` (detection, configuration
resolution, verdicts) and `src/Fingerprinting.Outbound.Cli` (envelope, database,
published to `publish/outbound-invocation-inventory/`). Registration:
`registration/outbound-invocation-inventory.json`. Schema:
`schemas/outbound-invocation-inventory-1.0.0.schema.json`. Job
`phase0-repository-discovery` v8 wires both inputs, and both are required.
There is no fallback source.

**Shared with `entry-point-inventory` in `Fingerprinting.Analysis`:**
- `ProjectSource`, `SyntaxHelpers`, `ConfigFiles`, `WcfSecurity`.
- `CallSiteEvaluator`, the generic-helper binding that resolved
  `BuildTcpHost<TService, TContract>`.
- `Secrets` and `JsonConfigWalker`.
- The `AuthDeclared` vocabulary and `ProjectScanStatuses`.

`application-fingerprinting` and `entry-point-inventory` outputs were byte-identical before and after the move.

**Configuration resolution (C4).**
- `RepositoryConfig` reads every `appsettings*.json`, `web.config` and
  `app.config`, including environment transforms. The environment comes from
  the file name: `default`, `Docker`, `Release`, ...
- A project's config is its own directory plus its `wwwroot`.
- `ValueResolver` evaluates the following:
  - literals, interpolation, concatenation and `??` defaults (recorded as
    `(code default)`)
  - helper call-site arguments
  - locals, consts and single-assignment members
  - `ConfigurationManager.AppSettings[...]`, including through an alias local
  - `ConnectionStrings[...]`, `IConfiguration[...]`, `GetValue` and
    `GetConnectionString`
  - options binding (`Configure<T>(GetSection(X))` makes `T.Prop` read
    `X:Prop`)
  - `Environment.GetEnvironmentVariable`, which becomes `env:NAME`
- An invocation that reads configuration is evaluated once per environment
  whose file sets a key it reads. Each evaluation becomes one
  `environmentBinding`. The primary endpoint is the default environment's
  value; where no default file sets the key, it is `unresolved`, with
  placeholder `config:KEY`.

**Endpoints (C3, C5).**
- An `Endpoint` holds only scheme, host, port and path, so userinfo, query
  and fragment have nowhere to go.
- A partial endpoint keeps its path only up to the first hole (`/api/{…}`),
  so calls that differ only at run time merge.
- Hole labels are code expressions with string-literal contents removed.

**Credentials.**
- Recorded by kind (`certificate`, `password`, `api_key`, `token`,
  `client_secret`, `windows`) and key path or code location only.
- `authDeclared` uses `entry-point-inventory`'s vocabulary:
  - `declared` when any credential is visible
  - `none_declared` only when declared as none (a WCF client credential type
    of `None`)
  - otherwise `not_assessed`
- The artifact carries an `authDeclaredScope` note.
- `origin` and `entryClass` are not carried. `soap.clientSource`
  (`hand_written` | `generated` | `config_only`) is the only origin-like fact
  that matters for an outbound call.

**1.1.0 (additive).**
- `environmentBindings[].linuxVerdict` and `linuxReasons` on every binding, for
  every mechanism. Database and Kafka bindings can differ by environment; for
  every other mechanism each binding carries the invocation's verdict.
- `usage` (`used` | `unused`) on every invocation. `unusedCount` is added to
  both summaries, and `countByMechanism`, `countByVerdict` and the incompatible
  list count used invocations only. Unused invocations sort last.
- Kafka SASL (`Sasl` in `KafkaSasl.cs`), in order: code (the config object's
  `SaslMechanism` and `SecurityProtocol`, `config.Set("sasl.mechanism", …)`,
  dictionary entries); then configuration (any `sasl.mechanism` /
  `SaslMechanism` / `SecurityProtocol` key, per environment file). A SASL
  protocol with no mechanism is GSSAPI. A config built entirely in code and
  never bound from configuration with no SASL is `none`. Otherwise `unknown`.
- Migration `b8e2f4a6c917` adds `outbound_invocations.usage` with an index on
  `(usage, endpoint_host)`.

**1.2.0 (additive): the operation each call site invokes.** Every invocation
carries `operations`, one per call site, each `{operation, verb, path, member,
resolution, reason, callSite}`. `dependency-and-context-map` matches them to `entry-point-inventory`'s entry points
(31-DEPENDENCY-AND-CONTEXT-MAP Part I). `OperationTracer` (syntax only) produces them:
- **SOAP.** It follows the client from where it is created to the variable or
  field holding it (through `await`, casts and `using`). For a
  `ChannelFactory<T>`, including one returned by a generic helper per call
  site, it goes through `CreateChannel()` to the proxy variables. The
  operations are the methods called on those: `utility.Ping()` is `Ping`.
  - Only methods the contract interface declares count. The interface is
    taken from the client's own project first, then a `[ServiceContract]`
    interface in the repository, then any interface of the name. A domain
    interface sharing the contract's name therefore does not filter the
    operations.
  - `FooAsync` on a generated proxy is kept as written; `dependency-and-context-map` matches it to
    the `Foo` operation.
  - Where the proxy is passed on (a WinForms form handing it to a
    controller), every call on a receiver declared with the contract or client
    type in the project is taken, with a reason saying so.
- **HTTP.** The verb comes from the request method (`GetAsync` is GET,
  `UploadString(url, "PUT", …)` is PUT). The path is the request URL's path,
  with unread parts written `{…}` and the resolution `partial`.
  - A request inside a wrapper whose URL uses the wrapper's parameters
    (`HttpGet(uri)` building `$"{_apiUrl}{uri}"`) is recorded once per caller
    of the wrapper, at the caller's call site, with the path it passes.
  - A client configured with a base address (`new HttpClient { BaseAddress }`,
    `AddHttpClient<T>`, a named client through `CreateClient("name")`) records
    the relative requests made through it, joined to the base address's path.
  - `SendAsync` and `WebRequest` have no readable verb and are `partial`.
    RestSharp is not traced.
- **gRPC.** These are the methods called on the stub constructed over the
  channel, or on a receiver of `<Service>Client` for `AddGrpcClient<T>`.
  `SayHelloAsync` is recorded as the `SayHello` RPC (`member` keeps the name
  as written).
- **Unresolved.** When nothing can be followed statically, one operation is
  recorded with `resolution: unresolved` and the reason. Examples: the client
  is never held in a variable, nothing is called on it, it is declared in
  configuration only, or the client class is never constructed. It is never
  guessed.
- Operations merge with their invocation (an invocation found at several
  call sites carries the operations of all of them), deduplicated by call
  site and sorted.
- Schema `outbound-invocation-inventory-1.2.0.schema.json` (generated from
  1.1.0 by `schemas/make_outbound_schema_1_2_0.py`). Migration `b8e2d4f61a07`
  adds `outbound_invocations.operations` JSONB.

**1.3.0 (additive).** Schema `outbound-invocation-inventory-1.3.0.schema.json`,
generated by `schemas/make_outbound_schema_1_3_0.py`. Migration `c4a7e1d93b26`.
Job `phase0-repository-discovery` v10 wires the `entry-point-inventory` artifact
into this step as an optional input.

- **Configuration through the host process.**
  - In .NET, App.config and web.config belong to the executable or web host.
    A class library reads its host's configuration at run time and has none
    of its own.
  - So a project that is not a host and has no configuration file is
    resolved through its hosts. A host is an `Exe`/`WinExe` output type, a
    `.Web` SDK, or a project with a web.config. It is found through `solution-discovery`'s
    project references, transitively through other libraries
    (`ResolveHosts`).
  - Key lookups (`Lookup`, `EnvironmentsFor`) and WCF client endpoints search
    the hosts' configuration after the library's own (`InScope`).
  - The "configured but never referenced" sweeps (connection strings, Kafka,
    Key Vault, SMTP) stay per project, so a host's entry is not reported a
    second time in its library.
  - A library's client claims its host's endpoint entry. SOAP code detection
    runs for every project before any project looks for config-only entries,
    so the host no longer reports the same endpoint as "declared in config
    only". The result is one invocation: call sites from the library,
    configuration from the host.
  - With several hosts, each host's configuration is its own binding.
    `environmentBindings[].hostProject` names the host.
  - Not covered: a host that `solution-discovery` does not know, such as a folder of `.svc`
    files and a web.config with no project file (the WCF sample's
    `Hosting.Iis`).
- **Web Deploy SetParameters.** `DeployParameterFiles` in Fingerprinting.Analysis
  is shared with `application-fingerprinting`.
  - **Discovery.** Files come from the engagement's `deploy_parameter_globs`,
    defaulting to `**/SetParam*.xml` and `**/SetParameters*.xml`.
  - **Environment.** A filename suffix names the environment
    (`SetParam.PROD.xml`); otherwise the parent folder does
    (`SetParamFiles\PROD\SetParam.xml` is PROD; `DEV\LOCAL\SetParam.xml` is
    LOCAL).
  - **Project.** The file belongs to the project whose name a folder on its
    path carries (`CustomFiles\Catalog.Host\…`), or under whose directory it
    sits. A file with no project is a warning, and its values are not applied.
  - **Every environment is read.** Each linked parameter becomes that
    environment's value: a client endpoint's address, an appSettings key read
    the way the replaced key is read, or a connection string as facts only.
    It is then evaluated like any environment file. The binding carries
    `deployParameter`, `linkMethod` and `linkConfidence`.
  - **Linking.**
    - `parameters.xml` in the project's directory: its `parameterEntry match`
      XPath decides, recorded as `parameters_xml` at 1.0. Recognised XPaths
      are `client/endpoint[@name]/@address`, `appSettings/add[@key]/@value`
      and `connectionStrings/add[@name]/@connectionString`.
    - Otherwise, a URL parameter whose name contains the endpoint's name or
      contract and whose URL path ends as the endpoint's does (`name_and_path`,
      0.8 for both matches, 0.6 for one).
    - Otherwise, an appSettings key of the same name (0.7).
  - **Secrets.** `deployParameters` on each project records every parameter,
    each with its name, kind (`url`, `path`, `connection_string`, `sensitive`,
    `other`), environment, file and link.
    - A value is kept only for a path, or for a URL that a used invocation's
      binding cites. Such a URL is stored normalised, as the binding holds it.
    - A password, a connection string, a user id or anything else is recorded
      as present, never with its value. The schema forbids a value on those
      kinds.
    - The secrets fixture now includes a SetParam file with a password and a
      connection string.
  - Which environment is production is the engagement's existing
    `production_environment` setting; `dependency-and-context-map` and the repository page use it.
- **Call sites are invocations.** `callSites` is now where the dependency is
  invoked: each followed operation's call site (`service.PlaceRealTimeFTOrder(req)`
  at line 56). Where the client is created (`using (… = new FundsTransferWSSoapClient())`
  at 51) is kept in `constructionSites` when it differs.
- **Inbound operations → backend calls (`BackendReach`).**
  - For each `entry-point-inventory` entry point, from its handler method: the outbound call
    sites in the method itself (depth 0), then through methods of the same
    class it calls (`M()`, `this.M()`), breadth-first, up to depth 3.
  - Each call records its depth, the methods walked, and whether it is
    conditional or in a loop. Both are read from the syntax between the entry
    point and the call:
    - conditional: `if` or `else`, a `switch` case or arm, `?:`, the right
      side of `&&`, `||` or `??`, `catch`, or an earlier `if (…) return/throw`
      in the same block (an early-return guard);
    - loop: `for`, `foreach`, `while`, `do`, or a lambda passed to
      `ForEach`, `Select` and similar.
  - The code text is kept in `context`. A human-readable condition ("not for
    practice accounts") is advisory LLM work and is left out.
  - A call into another class, or into an injected dependency (an interface,
    or a field assigned from a constructor parameter), whose type makes
    backend calls is recorded under `unresolved` and not followed. So is a
    same-class path deeper than 3.
  - Status:
    - `yes`: a call is reached;
    - `no`: none, and nothing unfollowed;
    - `unresolved`: none found, but something was not followed.
  - Written to `entry_point_backend`, one row per entry point, replaced per
    repository. Served by `GET /api/repositories/{id}/entry-point-backend`,
    shown as the table on the repository page's Surface section.
- **Unqualified hostnames.** A SOAP, HTTP or gRPC binding whose host is a single
  label (`appsrv0341`) is at least `requires_change` in that environment.
  - The reason: it resolves on Windows through NetBIOS or the DNS suffix
    search, but in a pod only if the cluster's search domains cover it.
  - The invocation's verdict follows.
  - Database and cache hosts are exempt: a one-label name there is commonly a
    cluster Service name.

**Verdicts (C6), interpretations to review.**
- HTTP, gRPC, Redis, Vault, Key Vault and SMTP are `compatible` even when the
  endpoint is unresolved. The protocol decides portability, and the reason
  says the endpoint is unresolved. `unknown` is reserved for an unresolved
  fact the verdict depends on: a SOAP binding, a database's authentication,
  Kafka authentication.
- LocalDB is `requires_change` (a connection-string change), not
  `incompatible`.
- Across environments, the worst binding decides. Reasons are prefixed with
  the environment.
- `System.DirectoryServices.Protocols` is `compatible` (it needs libldap).
  `DirectoryServices` and `AccountManagement` are `incompatible`.
- Windows credentials on HTTP or SMTP (`UseDefaultCredentials`) are
  `requires_change`.

**Known limitations.**
- A helper is followed one call level deep. The same holds for operations: a
  proxy passed on is found through receivers declared with its type, not by
  following the value.
- A runtime URL on an injected `HttpClient` whose base address is not visible
  is not recorded, because relative and absolute cannot be told apart. A
  runtime URL on a locally created `HttpClient` is recorded as unresolved.
- Kafka records the first bootstrap server as the endpoint.
- Configuration builders (`configBuilders="Secrets,Environment,AzureKeyVault"`)
  are noted as possibly replacing a connection string at run time. They are
  not evaluated.

**Tables.**
- `outbound_invocations` follows C8, with these columns added:
  - `placeholder`
  - `credentials`
  - `auth_declared`
  - `confidence_reasons`
- `detail` is `{endpoint, block}`.
- `outbound_scans` holds the per-project summaries, including the
  incompatible list.
- Migration: `a5d1e7c9b203`. API: `GET /api/repositories/{id}/outbound-invocations`.

### C10. Will the SOAP call still work on the target .NET? (scanner 1.4.0, artifact 1.4.0)

Every SOAP client invocation gets **two verdicts on every environment binding**:

| Verdict | Question | From |
|---|---|---|
| `linuxVerdict` (**platform**) | Does it work on Linux? | The WCF client platform matrix (scanner 1.5.0), applied to each environment's own security |
| `runtimeVerdict` (**runtime**) | Does the target .NET's WCF client support this binding, security mode and credential type? | The WCF client support matrix |

**Each environment's own security.** One endpoint can be configured differently in two
environment files (`Web.config` and `Web.Release.config`). Each environment binding now
carries `soap`: its binding, effective security mode, the credential type that mode uses, and
`securitySource`. A SetParameters value keeps its base entry's security; a binding built in
code applies in every environment. **Effective** means declared, or else the binding's
default: a `wsHttpBinding` with nothing declared is evaluated as `Message` security with
`Windows` credentials, which is what it uses. The defaults are `WcfSecurity.Defaults` in code;
a test holds them equal to the matrix file's `defaults`, which cite Microsoft Learn's
*System-provided bindings* and the bindings' `<security>` element pages (pinned to dotnet/docs
commits).

**The runtime rules are data.** `schemas/wcf-client-support-<version>.json` (1.0.0),
published beside the step's schemas, never in code. Keyed by target framework, binding,
security mode and credential type (`None` when the mode is `None`; `*` matches any — an exact
entry wins), with verdicts `supported`, `supported_with_caveat` or `unsupported`. Each entry
names its sources and a basis line, and carries a `confirmation` (`unconfirmed` or
`confirmed`, by whom, when). The sources:

- **The dotnet/wcf supported-features chart**, `release-notes/SupportedFeatures-v2.1.0.md`
  at commit `4429ddf` (2021-02-11), sha256 recorded. It is the newest chart dotnet/wcf
  publishes, written for .NET Core 2.1 and not updated since; its Windows column is read
  for the runtime verdict; its Linux column feeds the platform matrix (below).
- **dotnet/wcf release notes** for what came later: BasicHttpsBinding and NetHttpsBinding
  (v1.0.0-rc2), TransportWithMessageCredential on HTTP (v3.0.0), WSHttpBinding with the
  WS-Federation work (v3.1.0), WS2007HttpBinding and the Federation package (v3.2.0-preview3),
  NetNamedPipe (v6.0.0-preview1), and the package list (8.1.2) for bindings no client has.

Every entry starts `unconfirmed`. **A person confirms each one before a report built on it
goes to a client**, by editing the file in a pull request; a new matrix version is a new file,
and the artifact records which version (and its sha256) its verdicts came from
(`wcfClientSupport`, with the count of unconfirmed entries).

`runtimeVerdict` is `unknown` — never a guess — when the binding or security could not be
read, or the matrix has no entry (or no entries at all for the engagement's target). Its
reasons name the entry, its basis and caveat, and say when the entry is not yet confirmed.
The invocation's `runtimeCompatibility` is the worst environment's, with the target and matrix
version; `outbound_invocations.runtime_verdict` / `runtime_reasons` hold it (migration
`f3a9c6e1b245`). The target is the engagement's `target_framework`.

**The platform rules are data too** (scanner, registration and artifact 1.5.0).
`schemas/wcf-client-platform-<version>.json` (1.0.0) has the same shape, sourcing and
confirmation flow as the runtime matrix. Entries are keyed by target framework, `linux`,
binding, effective security mode and credential type, and the most specific match wins.
Verdicts are `compatible`, `requires_change` or `incompatible`. Every entry that is not
`compatible` carries a `fix`: what must change, and who changes it:

- `we`: the calling application, inside this migration;
- `backend_owner`: the service's owner;
- `we_or_backend_owner`: either, not yet known which.

The effective credential is the declared one, or else the binding's default, as for the
runtime matrix. Sources: the chart's Linux column, the v1.0.0-rc2 release notes (Windows
stream security on other operating systems works with Kerberos, given GSSAPI), v2.0.0
(Windows authentication on HTTP on Linux), v6.2.0, and the 8.1.2 package list for bindings no
client has. Each environment binding records the entry it was judged by
(`platformMatrixEntry`), and the artifact stamps the matrix version and sha256
(`wcfClientSupport.platformMatrixVersion`, `platformSha256`).

**NetTcp.** C6's flat rule, "netTcpBinding is incompatible on Linux", was wrong. The chart
lists NetTcpBinding, TCP transport and certificate client credentials as supported on Linux.
What needs configuring is NetTcp's *default* transport credential: `Windows` negotiates
Kerberos. `net10.0/linux/netTcpBinding/*/*` is `compatible`.
`net10.0/linux/netTcpBinding/*/Windows` (and the HTTP bindings' `*/Windows`) is
`requires_change`, with the fix `we_or_backend_owner`, "Kerberos configuration on our side,
or a credential change by the backend's owner". Kerberos is configured on the calling side:
a Kerberos client and GSSAPI in the image, a `krb5.conf` for the domain, and credentials or a
keytab for the calling identity. So it may need nothing from the backend's owner. It is not
counted as a required backend change until a probe in a Kerberos environment says which
(C11). `dependency-and-context-map` lists it apart, as a possible backend change.

On the WCF sample, all 13 SOAP invocations were rescanned with 1.5.0:

- `FundsTransferWSSoap` (basicHttpBinding, nothing declared, so `None`) is runtime
  `supported` in all six environments, and platform `compatible` except in DEV, whose host
  `appsrv0341` is unqualified (`requires_change`).
- The test client's five netTcp calls (Transport, with Certificate or None) **changed from
  platform `incompatible` to `compatible`**: IAccountService, IFundsTransferService and
  IOrderService (Transport/Certificate), and IProductService and IUtilityService
  (Transport/None). All five now rest on `net10.0/linux/netTcpBinding/*/*`.
- Every other verdict is unchanged, in both repositories.

**Matrices 1.1.0** (scanner 1.5.1, artifact 1.5.0 unchanged). A new version is a new file; 1.0.0
stays, since earlier runs cite it, and each file carries its `versionHistory`. Two changes:

- **The wildcard rule** (each file's `rules`). A wildcard entry, with `*` for security mode or
  credential type, may not assert that a call works (platform `compatible`, runtime `supported`
  or `supported_with_caveat`) for a binding whose behaviour depends on its security mode or
  credential. Every binding in the matrices has one, so only a specific entry can say a call
  works. A wildcard may still say a call does not work, needs a change, or is unprobed
  (`unknown`, whose fix is ours: probe it). A test over both files enforces it
  (`No_wildcard_entry_asserts_that_a_call_works`). Applying it changed eleven entries:
  - the platform matrix's ten compatible wildcards (basicHttp, basicHttps, netHttp, netHttps,
    netTcp, webHttp, ws2007FederationHttp, ws2007Http, wsFederationHttp, wsHttp `*/*`) became
    `unknown`, unprobed;
  - the runtime matrix's `customBinding/*/*` (`supported_with_caveat`) became `unknown`.

  Four specific platform entries carry the passing probes the wildcards held:
  `basicHttpBinding/None/None`, `basicHttpBinding/Transport/None`,
  `netTcpBinding/Transport/None` and `netTcpBinding/Transport/Certificate`.
- **Reviewer decisions, Rohit Khanna, 2026-10-12.**
  - `net10.0/linux/wsHttpBinding/*/*` (compatible) is replaced:
    `…/wsHttpBinding/TransportWithMessageCredential/Certificate` is `incompatible` on the
    probe's evidence (C11), and records the exception, the same binary passing on Windows, and
    `revision` (who, when, what it replaces). Every other wsHttp mode and credential is
    unprobed (`unknown`), not assumed compatible.
  - Confirmations, each recorded against a decision that names its entries (below):
    - `RK-2026-10-12-a`: the four specific platform entries whose probes passed, and the
      revised wsHttp `incompatible` entry;
    - `RK-2026-10-12-b`: the five runtime entries basicHttpBinding None/None and
      Transport/None, netTcpBinding Transport/None and Transport/Certificate (each
      `supported`), and wsHttpBinding TransportWithMessageCredential/Certificate
      (`supported_with_caveat`: the same binary passes on Windows, and the Linux failure is
      recorded on the platform entry).

    That is all ten entries the WCF sample's report rests on, so it is `readyForClient`.

**A confirmation records a person's decision; the tool never extends it.** Each matrix file
keeps the `decisions` its confirmations rest on: `id`, `by`, `on`, the `instruction` verbatim,
and the `entries` it names by id. `wcf_matrix.record_decision` is the only writer of a
confirmation. It confirms exactly the named entries, refuses a decision that names none or
lacks a person, date or instruction, and refuses ids no matrix has. A confirmed entry records
its `decision`. `wcf_matrix.confirmation_violations` lists any confirmed entry no recorded
decision names, and a test holds every matrix file to zero (`tests/test_wcf_confirmations.py`).
A confirmation that loses its basis is reverted with `revert_confirmation`, which keeps what
was reverted and why. On 2026-10-12, the five runtime confirmations were reverted for this
reason: four had rested on "confirm the four entries whose probes passed", which named no
entry, so the tool had chosen which four, and Rohit's decision did not name the fifth. They
were then confirmed again under `RK-2026-10-12-b`, which names all five.

On the WCF sample, the rescan with 1.5.1 changed one verdict of 13 invocations:
IAccountService over wsHttp TransportWithMessageCredential/Certificate, platform `compatible`
→ `incompatible`. Its host, `localhost@wcf`, is the one host needing a backend change: a
service inside this migration (wcf), whose owner is this programme.

**The probe evidence boundary: one client per deployment.** The platform ships to each client
as code, the matrices with it, and each client's data lives only in that client's database. The
boundary is set before any probe runs in a client's environment. The Kerberos onboarding task
(C11) will be the first such run.

- **Shipped matrices hold platform knowledge only:** entries confirmed on platform-sample
  evidence, which ships with them under `probes/evidence/` (today the WCF sample and
  wcf-backend, `"source": "platform-sample"`). No client confirmation, client probe record or
  client evidence is ever written into a matrix file, even as a reference.
- **A client's probe evidence is client data, stored with the engagement in the database**
  (`engagement_probe_evidence`). Each row holds the evidence document exactly as written and
  its sha256, the scenario, outcome, exception type, what it covers, and the shipped entries it
  bears on. A probe plan declares its owner: `"platformSample": true`, or
  `"engagement": "<id>"`, in which case the driver writes the evidence to that engagement's rows
  and changes no matrix file. A plan that declares neither, or both, is refused.
- **A confirmation made in a client deployment, on that client's evidence, is client data
  too** (`engagement_matrix_confirmations`). It records who and when, the instruction verbatim,
  the entries the decision names, and the evidence ids each rests on. The database refuses a
  confirmation of an entry its decision does not name, or one with no evidence. It is recorded
  by `engagement_matrix.record_decision`, also
  `POST /api/engagements/{id}/estate/matrix-confirmations`, which also requires the evidence
  to be intact and to bear on the entry. It is never deleted: `…/matrix-confirmations/revert`
  keeps who reverted it and why.
- **The report reads the shipped matrix with the engagement's confirmations and probes applied
  on top** (`engagement_matrix.overlay`, `apply`), the way engagement decisions overlay the
  shipped catalog. A shipped confirmation is platform knowledge and stays. The engagement's
  confirmation applies where the shipped entry is unconfirmed, and is shown as "confirmed … in
  this engagement on its own evidence". The repository page's SOAP section applies the same
  overlay.
- **Evidence missing.** When a confirmation's or probe's evidence row is gone, emptied, or no
  longer matches its sha256, the entry shows "evidence missing" (`evidenceMissingEntries`, the
  CSV's confirmation column), and that engagement's report is not ready for the client.
- **Enforced** by `wcf_probe.evidence_boundary_violations`. `tests/test_wcf_probe_evidence_boundary.py`
  fails if any shipped matrix holds a client's probe, reference or confirmation, or a
  confirmation resting on evidence that does not ship, or if the platform's evidence folder holds
  anything attributed to an engagement or any file no entry references. It plants each kind of
  violation to prove the check catches it. It also exercises the database side: a client
  confirmation applied on top, altered or emptied evidence showing as missing, the decision
  rules, and reverts kept. It checks that no matrix file changes while it runs.

### C11. Probes: evidence on the matrix entries

A matrix entry is a reading of documents. A probe adds evidence: a minimal .NET 10 WCF client
(`probes/WcfClientProbe`: System.ServiceModel.* 8.1.2) runs in a Linux container
(`mcr.microsoft.com/dotnet/runtime:10.0`, pinned by digest). It calls a real service using one
binding, security mode and credential type, and the outcome is recorded on every entry it bears
on, in both matrices. A probe never changes a verdict or a confirmation: **a person still
confirms each entry**, now with the probe result in front of them.

```powershell
cd backend
.venv\Scripts\Activate.ps1
python -m app.estate.wcf_probe --plan runs\probes\probe-plan.json --make-certificates
```

- **Certificates are files, never a certificate store.** `--make-certificates` has
  `WcfClientProbe make-certificates` write `server.pfx`/`server.cer` (CN=localhost),
  `client.pfx`/`client.cer` and `pfx.password` to the plan's scratch folder
  (`backend/runs/probes/certs`, gitignored). The client pins the server by the thumbprint of
  `server.cer`, and the services pin the client by `client.cer`. Nothing is imported into, or
  read from, CurrentUser or LocalMachine. Keys loaded from a `.pfx` live in a temporary key
  container that goes away with the process. No trust setting, http.sys binding or URL
  reservation is made, and no admin rights are needed.
- **The plan** (`probes/probe-plan.example.json`, copied to `backend/runs/probes/`) names each
  scenario's service address, whether it pins the server certificate, and whether it presents
  the client certificate.
- **The services** are the WCF sample's and wcf-backend's, run from copies under
  `backend/runs/probes/wcf-sample`, never the registered repositories:
  - FundsTransferWS under IIS Express (`Start-FundsTransferWS.ps1`): plain HTTP, no
    certificate;
  - `probes/Start-ProbeServices.ps1` builds and runs `probes/ProbeServices`. On .NET Framework,
    it hosts the sample's own `UtilityService` and `AccountService` (loaded by path) on the
    sample's bindings: Catalog.Host's netTcp (8101 Transport/None, 8202 Transport/Certificate)
    and Hosting.Iis's HTTPS (basicHttp Transport/None, wsHttp
    TransportWithMessageCredential/Certificate). basicHttpsBinding (2026-10-13) calls the same
    HTTPS UtilityService through the `BasicHttpsBinding` client type: Transport/None on 44301, and
    Transport/Certificate on 44302, a second TLS terminator that requires a client certificate
    and accepts only the pinned `client.cer`, as IIS does with client certificates required.
    Both bear on the runtime entries `net10.0/basicHttpsBinding/Transport/None|Certificate` and
    the platform matrix's one basicHttps entry, the wildcard `net10.0/linux/basicHttpsBinding/*/*`.
  - **HTTPS without a store.** .NET Framework WCF serves HTTP only through http.sys, which
    takes its certificate from LocalMachine, and WCF's hosted activation under IIS Express
    needs full IIS. So the HTTP services listen on plain `http://localhost:8601`, behind a
    TLS terminator on 44301 that uses the certificate file. wsHttp's security element sets
    `AllowInsecureTransport`, the standard SSL-offload arrangement. The client sees HTTPS
    to `https://localhost:44301`, and its messages are unchanged.
- **A service on the host** is addressed as `localhost`, the name its certificate carries.
  The probe's TCP relay forwards it to `host.docker.internal` byte for byte.
- **Evidence, bound to versions.** Each run writes `probes/evidence/<utc>-<scenario>-<where>.json`
  (the command without secrets, the image digest, the pinned server thumbprint, the full
  result) and records its sha256 in the probe record: `probedOn`, `scenario`, `where`,
  `outcome`, `summary`, `service`, `address`, `client`, `evidence` and `sha256`. It also records
  **`covers`**, the WCF client package version (read from the probe's project, and checked
  against the assembly that ran) and the .NET runtime it ran against. An entry shows what its
  evidence covers: the newest WCF client among its probes, and the runtimes. The SOAP report
  flags an entry whose evidence covers an older WCF client than the engagement targets: the
  engagement's `target_wcf_client_version` (estate settings), or else the version the matrices
  record for its target framework (`targets.<framework>.wcfClientVersion`). The report stays a
  draft until it is re-probed.
- **Controls.** When a Linux probe fails, two controls attribute it:
  - the same scenario with the System.Security.Cryptography.Xml that WCF brings by itself
    (the probe pins 10.0.12; WCF 8.1.2 brings 8.0.x, which has high-severity advisories);
  - the same client binary on the Windows host.

  A Linux failure that passes on Windows is `attribution: platform`. It contradicts the
  platform entry, not the runtime one.
- **Contradictions are under review.** Where an entry's latest probe for a scenario disagrees
  with its verdict (a failure where it says the call works, a pass where it says it does not),
  the entry is under review until a reviewer revises it. Every verdict resting on it reads
  "contradicted by probe — under review", never its unrevised verdict, which is kept as
  `unrevisedVerdict` for the reviewer. The changes it implied are withdrawn, and every total
  counts it apart: the SOAP report's summary and host chips, the CSV, and the endpoint
  register (`underReview`, which stops its fix from counting as a backend change). The register
  reads contradictions when it runs, and the report reads them live.
- **Not probed, and an open item.** Windows-credential NetTcp needs a Kerberos environment: a
  KDC, an SPN, and a keytab or ticket for the caller. None is available, so its entries
  (`net10.0/netTcpBinding/Transport/Windows`, `net10.0/linux/netTcpBinding/*/Windows`) record
  `outcome: not_probed`, "needs Kerberos", rather than a guess. Each carries an `openItem`:

  > **Onboarding task — needs the client's identity team.** Probe it in the client's
  > environment: from a Linux container holding a keytab for a test identity, call a
  > non-production NetTcp service that uses Windows credentials. The identity team provides a
  > service principal name for the service, a keytab for the caller, and the domain's
  > `krb5.conf`. Until then, the fix stays "Kerberos configuration on our side, or a
  > credential change by the backend's owner". This probe runs in the client's
  > environment: its plan names the engagement, and its evidence and any confirmation on it
  > follow the probe evidence boundary (C10). They are stored with the engagement in that
  > client's database, and no matrix file changes.

  If no Linux container runtime is available, the probe stops and says so, and records nothing.

The probes of 2026-10-12, rerun from file-based certificates, used Ubuntu 24.04.5, .NET 10.0.12
and WCF client 8.1.2, with the image digest `sha256:b89586dc…`:

| Entry the report relies on (runtime / platform) | Scenario and service | Result |
|---|---|---|
| `net10.0/basicHttpBinding/None/None` / `…/linux/basicHttpBinding/None/None` | `basicHttp-None-None`, wcf-backend FundsTransferWS (ASMX) | passed |
| `net10.0/basicHttpBinding/Transport/None` / `…/linux/basicHttpBinding/Transport/None` | `basicHttp-Transport-None`, UtilityService over HTTPS | passed |
| `net10.0/netTcpBinding/Transport/None` / `…/linux/netTcpBinding/Transport/None` | `netTcp-Transport-None`, UtilityService | passed |
| `net10.0/netTcpBinding/Transport/Certificate` / `…/linux/netTcpBinding/Transport/Certificate` | `netTcp-Transport-Certificate`, AccountService (mutual TLS) | passed |
| `net10.0/wsHttpBinding/TransportWithMessageCredential/Certificate` / `…/linux/wsHttpBinding/TransportWithMessageCredential/Certificate` | `wsHttp-TransportWithMessageCredential-Certificate`, AccountService over HTTPS | **failed on Linux**; passed on Windows with the same binary |
| `net10.0/netTcpBinding/Transport/Windows` / `…/linux/netTcpBinding/*/Windows` | — | not probed: needs Kerberos (open item) |

The wsHttp failure is the client's, on Linux, before anything is sent. Signing the message
with the client certificate throws `UriFormatException` inside XML canonicalization
(`XmlTextReaderImpl.ConvertAbsoluteUnixPathToAbsoluteUri`, called from
`ExcCanonicalXml` / `SignedXml.ComputeSignature`). It fails the same way with
System.Security.Cryptography.Xml 10.0.12 and 8.0.10. The first run contradicted 1.0.0's
`net10.0/linux/wsHttpBinding/*/*` (compatible); the reviewer's revision is matrices 1.1.0's
specific `incompatible` entry (C10).

---

## Part D — UI

A **Surface** section on repository detail with two panels.

**Inbound** — entry points grouped by kind. HTTP as a route table: verb, template,
handler, parameters, authorisation, with unauthorised endpoints flagged. Each row links
to its handler's source location.

**Outbound** — invocations grouped by mechanism, verdict badge on each
(`incompatible` red, `requires_change` amber, `unknown` grey, `compatible` teal).
Environment bindings expandable. Incompatible invocations sorted first — that is the
list someone will act on.

`dependency-and-context-map` builds the estate-wide endpoint register from these rows; this view is
per-repository.

---

## Acceptance criteria

**`entry-point-inventory`**
- [ ] Controller routes compose `[Route]` with verb templates, resolving `[controller]`,
      `[action]` and `[area]`
- [ ] An action template beginning with `/` replaces rather than appends
- [ ] Conventional routing records `routing: conventional` with a null template
- [ ] Minimal APIs compose statically resolvable `MapGroup` prefixes; variable prefixes
      are recorded unresolved
- [ ] WCF operations, gRPC methods, SignalR hub methods, message consumers, hosted
      services, scheduled jobs and console mains are each detected
- [ ] `entryPointId` is stable across rescans
- [ ] Authorisation is recorded; unauthorised endpoints are counted

**`outbound-invocation-inventory`**
- [ ] SOAP clients record binding and security mode from config, code, or a generated
      `Reference.cs`
- [ ] A SOAP client's platform verdict comes from the platform matrix by binding, effective
      security mode and credential: NetTcp Transport with a certificate is `compatible`, NetTcp
      on its default Windows credential `requires_change`, a named pipe `incompatible`
- [ ] No wildcard matrix entry asserts that a call works; only a specific entry can
- [ ] Probes use certificates from files only, and record the WCF client and runtime they ran
      against; a contradicted entry is shown and counted as under review
- [ ] Endpoints normalise: host lowercased, userinfo, query and fragment stripped
- [ ] One logical endpoint across environment files is one invocation with several
      environment bindings
- [ ] Placeholders and environment variables record `resolution: unresolved`
- [ ] Connection strings yield name, provider and server host only
- [ ] The secrets fixture produces an artifact containing none of its three secrets
- [ ] Kafka authentication is `unknown` until a SASL/GSSAPI signal exists
- [ ] `invocationId` is stable across rescans

**Both**
- [ ] Extend the `application-fingerprinting` solution, sharing the analysis library
- [ ] Registered as `process` steps; `phase0-repository-discovery` validates with no
      YAML change
- [ ] Two runs produce identical artifact checksums
- [ ] `git status` in each scanned repository is clean afterwards
