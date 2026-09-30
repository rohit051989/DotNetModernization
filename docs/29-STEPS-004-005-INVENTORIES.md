# 29 — Steps 4 & 5: Entry-Point and Outbound-Invocation Inventories

Lifecycle steps 4 and 5. Owner: **P**. Job: `phase0-repository-discovery`, after
step 3. Implemented in **C# / .NET**, invoked via the `process` adapter.

Step 3 detects **presence** — "this project has controllers". These steps produce
**inventories** — "`GET /api/accounts/{id}` is handled by
`AccountsController.GetById`", and "this project calls `wsse0.saifg.rbc.com` over
NetTcp". Different shape, different consumers.

| | Step 4 — inbound | Step 5 — outbound |
|---|---|---|
| Question | What can call this application? | What does this application call? |
| Viewpoint | FUNCTIONAL | CONTEXT |
| Feeds | Contract snapshot (14), test generation (15), risk (8) | Endpoint register (10), risk (8), decisions |

---

## Part A — Shared decisions

### A1. Extend the step 3 solution

Both steps are new projects in `steps/step-003-fingerprinting/`, sharing
`Fingerprinting.Analysis` for project loading and Roslyn parsing, and the Cli
infrastructure for the envelope.

This reuses what step 3 already solved: `MSBuildLocator` registered before any MSBuild
type loads, stdout carrying only the StepResult, deterministic JSON with sorted keys and
`\n` line endings, generated-code exclusion, SARIF-safe path encoding, and the secrets
rules. Rebuilding any of that is risk with no benefit.

Each step still has its own registration, its own published binary, its own artifact
and its own tables. Sharing a library is not sharing a contract.

### A2. Syntax analysis, with honest confidence

Semantic analysis stays off, per step 3's Part A4. Route templates, type names and
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

Step 2 supplies the project list and paths. Step 3 supplies which projects are
out-of-scope, so these steps skip what step 3 skipped. Neither re-derives project
structure.

### A4. Secrets

Both steps inherit docs/21 Part G. Step 5 carries the most risk, since outbound
configuration is where credentials live. Specific rules in Part C5.

---

## Part B — Step 4: entry-point inventory

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
route or handler. Deterministic per step 3's rules.

A per-project summary: count by kind, count by HTTP verb, count unauthorised. The
unauthorised count is worth surfacing prominently.

### B5. As implemented (step 4, scanner 2.1.0)

**Layout.** `Fingerprinting.EntryPoints` (detectors, composition) and
`Fingerprinting.EntryPoints.Cli` (exe, published to
`publish/entry-point-inventory/`). Step 3's shared plumbing moved into libraries,
not copied: `Fingerprinting.Analysis` now holds the file walk, `SourceFileScanner`
and the Roslyn name helpers; the new `Fingerprinting.StepHost` holds the envelope,
`StepBootstrap` (MSBuildLocator, stdout guard, culture), `StepEnvelopeRunner`, the
schema gate, artifact URIs and `PlatformDatabase`. Step 3's artifacts are
byte-identical before and after the move.

**Inputs (A3).** Both `consumes` entries are required, and
`phase0-repository-discovery` v7 wires them (`${artifacts.solution-project-inventory}`,
`${artifacts.application-fingerprint}`). They are the only input path. The "no job
definition change" rule holds only while a step's consumes and produces are unchanged,
and step 4 gained two inputs. An earlier build registered them optional and read
steps 2 and 3's tables when they were unwired; that fallback is deleted. Two input
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
  implemented only by `ClientBase<T>` proxies is outbound (step 5), not an entry
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
  for step 3 — holds the summaries the rows cannot: skipped projects, global
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
publishes every kind step 4 detects — what it detects, what identifies it, how
`authDeclared` is decided, the version it arrived in — and the patterns it does not
cover. It ships beside the exe, every artifact is stamped with its version and kinds,
and the scan row stores the stamp. `GET /api/workflow/steps/entry-point-inventory/
capabilities` serves it with how often each kind is found across the estate. Workflow
Administration shows it under Detection capabilities, beside step 3's extractor
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
- Downstream, only request entry points are surface. Risk scoring (step 8), contract
  snapshots (step 14) and test generation (step 15) read request entry points only.
  Lifecycle hooks carry no `authDeclared` — a database constraint enforces it — so
  "no declared authentication" counts request entry points only.
- Totals are reported as `requestEntryPointCount` and `lifecycleHookCount`, with
  `countByOrigin`.

**Known limitations, for later steps.**
- *Origin is decided per repository.* A module registered in one repository's
  web.config whose source lives in another repository — a shared in-house library —
  is classified `framework`, because the scan only sees the repository it runs on.
  Step 10 has the estate-wide view to reconcile this: a `framework` registration whose
  full type name some other repository declares is `application` code.
- *A poll-loop service has no request entry point.* A `BackgroundService` (or Windows
  service) that loops with no timer and no recognised consumer yields one lifecycle
  hook and zero request entry points, although it does real work on every iteration.
  Step 8 risk scoring must not read zero request entry points as low risk when a
  `hosted_service` or `windows_service` is present: the work those services do is
  invisible to the request count.

**Not covered yet** (listed in the manifest): ASP.NET Core middleware, `IRouteHandler`,
WebForms control events, the Azure Service Bus SDK processor, RabbitMQ client consumers,
Hangfire `BackgroundJob.Enqueue`, `function.json`, WebJobs, Service Fabric, Orleans,
Dapr, BizTalk, SSIS, Sitecore / Umbraco pipelines, in-house dispatchers. Also not
covered: actions inherited from an abstract base controller, WCF `serviceAuthorization`
behaviours, and web.config transforms.

---

## Part C — Step 5: outbound-invocation inventory

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
| `file_share` | UNC paths from step 3's `UNC_PATH_LITERAL` |
| `smtp` | `SmtpClient`, mail configuration |
| `ldap` | `System.DirectoryServices` usage |

### C2. The binding type is the point

For `soap_client`, **record the binding**. This is the client's primary Linux blocker:
NetTcp uses a Windows binary framing protocol with no reliable Linux support, while
HTTP-based bindings port cleanly.

Sources, in order of preference: `<client><endpoint binding=…>` in config; a binding
constructed in client code (`new NetTcpBinding()`); the binding inside a generated
`Reference.cs` — which, per step 3's precedent, is read for this purpose only.

Also record `securityMode` where declared — `Transport`, `Message`,
`TransportWithMessageCredential`, `None` — and `clientCredentialType`. Windows-integrated
security modes are a second Linux blocker independent of the binding.

### C3. Endpoint normalisation

The endpoint register at step 10 aggregates by endpoint, so endpoints must normalise to
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

### C5. Secrets — stricter than step 3

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
| SOAP over `netTcpBinding` | `incompatible` |
| SOAP with Windows-integrated security | `incompatible` |
| SOAP over `basicHttpBinding` or `wsHttpBinding` | `compatible` |
| SQL with Integrated Security or SSPI | `requires_change` — needs SQL auth or a Kerberos keytab |
| SQL with SQL authentication | `compatible` |
| MSMQ | `incompatible` |
| UNC file share | `requires_change` — needs an SMB mount |
| LDAP via `System.DirectoryServices` | `incompatible` |
| Kafka with SASL/GSSAPI | `requires_change` — keytab. **Undetectable until a config signal exists**; record `unknown` for Kafka authentication until then |
| HTTP, gRPC, Redis, Vault | `compatible` |
| Anything unresolved | `unknown` |

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
  "linuxCompatibility": { "verdict": "incompatible",
                          "reasons": ["netTcpBinding", "Windows client credentials"] },
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
host index is what step 10's aggregation reads.

Artifact `outbound-invocation-inventory@1.0.0`. Per-project summary: count by
mechanism, count by verdict, and the incompatible invocations listed explicitly.

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

Step 10 builds the estate-wide endpoint register from these rows; this view is
per-repository.

---

## Acceptance criteria

**Step 4**
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

**Step 5**
- [ ] SOAP clients record binding and security mode from config, code, or a generated
      `Reference.cs`
- [ ] A NetTcp client is `incompatible`; a BasicHttp client is `compatible`
- [ ] Endpoints normalise: host lowercased, userinfo, query and fragment stripped
- [ ] One logical endpoint across environment files is one invocation with several
      environment bindings
- [ ] Placeholders and environment variables record `resolution: unresolved`
- [ ] Connection strings yield name, provider and server host only
- [ ] The secrets fixture produces an artifact containing none of its three secrets
- [ ] Kafka authentication is `unknown` until a SASL/GSSAPI signal exists
- [ ] `invocationId` is stable across rescans

**Both**
- [ ] Extend the step 3 solution, sharing the analysis library
- [ ] Registered as `process` steps; `phase0-repository-discovery` validates with no
      YAML change
- [ ] Two runs produce identical artifact checksums
- [ ] `git status` in each scanned repository is clean afterwards
