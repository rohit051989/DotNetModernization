# 21 — Step 3: Application Fingerprinting

Lifecycle step 3. Owner: **P**. Job: `phase0-repository-discovery`, after step 2.
Implemented in **C# / .NET**, invoked via the `process` adapter.

Read `step-3-application-fingerprinting.md` alongside this. That document is the
authority on **what** to extract; this spec is the authority on **how** it integrates,
executes and persists, and it overrides that document where the two disagree.

---

## Part A — Decisions that override the requirements document

Seven adjustments. Everything not listed here stands as written.

### A1. No object storage, no separate API

§36 proposes object storage for raw results and an ASP.NET Core Web API. Neither
applies.

- **Raw output** goes to the existing artifact mechanism: a file under `output_dir`,
  registered in `wf_artifacts` with a checksum. That already provides immutable,
  auditable, reprocessable raw output — §38.9 satisfied without new infrastructure.
- **Step 3 exposes no API.** Its entire interface is StepContext on stdin, StepResult
  on stdout. Read endpoints for fingerprint data belong in the existing FastAPI
  backend, per `18-API-CONVENTIONS.md`.

### A2. The artifact version *is* the schema version

§32 puts `schemaVersion: "1.0"` inside the payload while `produces` declares an
artifact version. Two sources of truth for the same fact.

The artifact version wins. `application-fingerprint@1.0.0`, three-part semver, per
the versioning rules in `11-STEP-CONTRACT.md`. Do not emit a `schemaVersion` field.
JSON Schema files (§33) are worth keeping, named to match:
`schemas/application-fingerprint-1.0.0.schema.json` (superseded by
`-1.1.0.schema.json` per Part F's `evidenceKind` addendum — the old file stays on
disk as a historical record, per the same "never delete, only add" rule the signal
registry follows).

### A3. Volatile fields go in metadata, not the artifact

§32's `scanId` and any timestamp break checksum determinism, which §38.10 requires.
They go in `StepOutput.metadata`. Same rule already applied in steps 1 and 2.

`scannerVersion` **stays in the artifact** — it is a genuine input to reproducibility
and only changes when the scanner changes.

### A4. Semantic analysis is off by default in v1

This is the significant risk in the document, and the one place I would go further
than it does.

§27 Level 4 and §26.2 propose Roslyn semantic analysis via `MSBuildWorkspace`. On
legacy non-SDK projects that requires the correct MSBuild instance, .NET Framework
developer packs, resolvable imported targets, and usually a successful NuGet restore.
Across 600 legacy projects on one machine it will fail often, fail slowly, and fail
for reasons unrelated to the code being analysed.

The document already treats it as optional (§27, §38.3). v1 goes further:

- **Levels 1–3 are the shipped path.** File system, structured parsing, Roslyn
  syntax. These never fail to load and work on code that does not compile.
- **Level 4 is implemented but gated** behind `config.enable_semantic_analysis`,
  default `false`. When enabled and it fails, degrade to Level 3 with a warning —
  never fail the project.
- Record `semanticAnalysis: false` in `analysisCapabilities` so consumers know the
  precision ceiling.

The main thing semantics buys is disambiguating a user-defined `Controller` from
`System.Web.Mvc.Controller` (§26.2). Real, but rare, and syntax plus the package and
assembly reference context from step 2 resolves most of it. Take the precision hit
in exchange for a scanner that runs on a broken estate.

### A5. One Windows worker

§29 proposes cross-platform and Windows-legacy worker profiles. Over-engineered for a
single-machine, single-operator model. Build one worker, run it on Windows, keep the
code free of Windows-only APIs so a Linux profile is a packaging change later rather
than a rewrite.

### A6. Consolidated solution structure

§34 proposes nine source projects and four test projects. Disproportionate for one
lifecycle step of fifty-one, and it fragments code that changes together.

```
steps/step-003-fingerprinting/
  Fingerprinting.sln
  src/
    Fingerprinting.Cli/            entry point, StepContext/StepResult envelope
    Fingerprinting.Domain/          models: signals, evidence, fingerprint, status
    Fingerprinting.Analysis/        MSBuild evaluation, Roslyn, config parsers
    Fingerprinting.Extractors/      IFingerprintExtractor implementations
  tests/
    Fingerprinting.Tests/           unit plus golden-file
    fixtures/                       fixture repositories per §35
  schemas/
  publish/                          gitignored build output
  README.md
```

Four source projects. Split further only when a boundary is genuinely load-bearing.

### A7. Do not re-extract what step 2 already captured

§4 and §5 substantially duplicate step 2's `projects` and `project_packages` tables.
Re-extracting invites divergence between two sources of the same fact.

Step 3 **reads** project metadata and package declarations from step 2's artifact.
It re-derives a value only where MSBuild evaluation produces something step 2's raw
XML parse could not — resolved conditional properties, expanded properties, imported
`Directory.Build.props` values. Where it does, keep both per §26.1:

```json
"targetFramework": { "raw": "$(DefaultTargetFramework)", "evaluated": "net472", "source": "MSBUILD_EVALUATED" }
```

New in step 3 and not in step 2: SDK identity, nullable, implicit usings, and
anything requiring evaluation.

---

## Part B — Integration contract

### Invocation

Published binary, not `dotnet run` — `dotnet run` recompiles on invoke, which is slow
and introduces failure modes unrelated to the step.

```yaml
step_name: application-fingerprinting
lifecycle_step_no: 3
display_name: "Application fingerprinting"
owner_code: P + S
version: "1.0.0"
owner_team: "platform"
implementation_status: implemented

consumes:
  - artifact_type: solution-project-inventory
    version_range: "^2.0.0"
    optional: false

produces:
  - artifact_type: application-fingerprint
    artifact_version: "1.0.0"

adapter_type: process
adapter_config:
  command: ["steps/step-003-fingerprinting/publish/Fingerprinting.Cli.exe"]
  timeout_seconds: 3600

restart:
  allow_start_if_complete: false
  start_limit: 3
```

Owner code is `P + S` per `17-LIFECYCLE-STEPS.md`. The `S` share is reserved for a
future LLM-assisted summarisation pass; **v1 is entirely deterministic** and calls no
model. Record that in the README so nobody assumes an LLM is involved.

Note the `^2.0.0` range — step 2's artifact is at 2.0.0. This is the first consumer
of it, so verify resolution works.

### Three hard rules for a .NET step

**1. stdout is the response channel and nothing else.** A single stray
`Console.WriteLine` anywhere in the call tree — or inside a library — corrupts the
StepResult. All logging goes to stderr:

```csharp
// Program.cs, before anything else
var stdout = Console.Out;
Console.SetOut(Console.Error);   // anything careless now goes to stderr
// write the StepResult with `stdout` at the very end, and only there
```

Configure `Microsoft.Extensions.Logging` to a stderr console provider explicitly.

**2. Determinism requires explicit configuration.** `System.Text.Json` does not sort
keys, and `Environment.NewLine` is `\r\n` on Windows, which breaks checksum
stability across platforms.

- Custom property ordering, alphabetical at every level
- `WriteIndented = true`, two-space indent
- `\n` line endings explicitly, never `Environment.NewLine`
- Sort all collections: projects by relative path, signals by
  `(category, name, sourcePath)`, evidence by `(path, line)`
- Invariant culture for every number and date format
- Parallel extraction is fine, but sort after collection, never rely on completion
  order

**3. MSBuildLocator must run before any MSBuild type is touched.**
`MSBuildLocator.RegisterDefaults()` is the first statement in `Main`, before any
method that references a `Microsoft.Build` type is even JIT-compiled — put MSBuild
usage behind an interface resolved after registration. Do not set copy-local on
`Microsoft.Build.*` assemblies. This is the single most common way MSBuild-hosting
tools fail to start.

### Runtime and packages

Target the latest LTS SDK on the machine; report the version detected. Pin
`Microsoft.CodeAnalysis.*` and `Microsoft.Build.*` to explicit versions —
floating versions here produce unreproducible output, contradicting §38.10.

The scanner's own target framework is unrelated to the frameworks it analyses. It
reads `net472` projects while itself running on modern .NET.

### Database access

The step receives `database_url` in StepContext and writes its own rows, consistent
with steps 1 and 2. Use `Npgsql`. It must not call the FastAPI backend.

### Standalone execution

Required by `11-STEP-CONTRACT.md`:

```powershell
Get-Content tests\fixtures\sample-context.json | steps\step-003-fingerprinting\publish\Fingerprinting.Cli.exe
```

Also support a developer-convenience mode that takes a repository path directly and
writes the artifact to a folder, bypassing the envelope. Useful for iterating on
extractors without the engine.

---

## Part C — Unit of work

**One fingerprint per project row from step 2.** No aggregation, no judgement about
which projects are applications.

The requirements document uses "project or application candidate" (§3). To be
unambiguous: step 3 fingerprints **projects**. Deciding which projects constitute
deployable applications is interpretation and belongs to step 4.

Out-of-scope projects are skipped with `fingerprintStatus: SKIPPED`. Step 2 signals
this two different ways, both of which must be checked — `parse_status: out_of_scope`
alone is not sufficient:

- A **known non-.NET project type** (`.dcproj`, `.njsproj`, `.pyproj`, `.esproj`,
  `.wapproj`, `.wixproj`, `.deployproj`, `.modelproj`) is recorded with
  `parse_status: success` — it parsed fine, it just isn't a .NET project. The
  out-of-scope-ness lives entirely in `structural_type`
  (`docker_compose_project`, `nodejs_project`, `python_project`,
  `javascript_project`, `windows_packaging_project`, `wix_installer_project`,
  `deployment_project`, `modeling_project` — see
  `discovery/project_parser.py`'s `OUT_OF_SCOPE_EXTENSION_MAP`).
- A **genuinely unrecognised** `*proj` extension gets `structural_type:
  unknown_project` and *that* case does carry `parse_status: out_of_scope`.

So the skip check is: `parse_status == "out_of_scope"` **or** `structural_type` is one
of the nine values above (`unknown_project` plus the eight known non-.NET types) —
not `parse_status` alone, which misses the more common known-non-.NET case entirely.

Projects with `parse_status: failed` are attempted anyway — Level 1 and 2 analysis
may still yield signals from a project whose XML would not parse.

Repository-level signals (§32's `repositorySignals`) cover evidence that belongs to
no single project: pipeline files, repository-root scripts, scheduler definitions,
Dockerfiles outside project directories. Store them against the repository, not
duplicated onto every project.

---

## Part D — Signal vocabulary

The requirements document shows signal names (§31: `SVC_FILE`,
`SERVICE_CONTRACT_ATTRIBUTE`) but no controlled vocabulary. Without one, step 4's
rules cannot bind reliably and every extractor invents its own naming.

**Maintain a versioned signal registry**, committed as
`schemas/signal-registry-1.0.0.json`:

```json
{
  "registry_version": "1.0.0",
  "signals": [
    {
      "name": "SVC_FILE",
      "category": "FILE_INDICATOR",
      "type": "FILE_PRESENCE",
      "description": "Presence of a .svc service host file",
      "extractor": "FileIndicatorExtractor",
      "evidence_kind": "FILE",
      "value_semantics": "count of matching files"
    },
    {
      "name": "SERVICE_CONTRACT_ATTRIBUTE",
      "category": "FRAMEWORK_ANNOTATION",
      "type": "ATTRIBUTE",
      "description": "ServiceContract attribute on a type",
      "extractor": "AttributeExtractor",
      "evidence_kind": "FILE",
      "value_semantics": "count of decorated types"
    }
  ]
}
```

Rules:

- `SCREAMING_SNAKE_CASE`, stable once published
- Categories are the sixteen from §19
- Every emitted signal must exist in the registry; an unregistered signal name is a
  validation failure, not a warning
- Adding a signal is a minor registry bump; renaming or changing meaning is major
- `evidence_kind` is one of `FILE`, `FOLDER`, `NONE` — what the signal's
  `sourcePath` names. Get this wrong and a downstream consumer that assumes every
  `sourcePath` is an openable file (a SARIF viewer, a future evidence UI) breaks on
  the first folder-presence signal it sees. Audit it per signal, not per extractor —
  `FileIndicatorExtractor` alone emits both `FILE` (`SVC_FILE`, `CSHTML_FILE`, ...)
  and `FOLDER` (`CONTROLLERS_FOLDER`, `SERVICES_FOLDER`, ...) signals
  (25-STANDARDS-AND-VIEWPOINTS.md Part A3 addendum)

### Signal types

Every signal has one `type`. It tells a consumer what the signal's `value` holds and
what its evidence entries carry. Twelve types:

| Type | Signal `value` | Evidence entries carry | Example |
|---|---|---|---|
| `ATTRIBUTE` | Fully qualified attribute | line span, declaring type, member | `SERVICE_CONTRACT_ATTRIBUTE` |
| `BASE_CLASS` | Fully qualified base type | line span, declaring type | `DB_CONTEXT_BASE_CLASS` |
| `FILE_PRESENCE` | — | — (the `sourcePath` is the evidence) | `SVC_FILE`, `CONTROLLERS_FOLDER` |
| `CONFIG_ELEMENT` | Element or key path | line span | `SYSTEM_SERVICE_MODEL_CONFIG` |
| `PACKAGE` | Package id | — | `DAPPER_PACKAGE` |
| `ASSEMBLY` | Assembly name | — | `SYSTEM_WEB_ASSEMBLY` |
| `NAMESPACE` | Namespace | line span | `SYSTEM_WEB_MVC_NAMESPACE` |
| `ROUTE` | Route template | line span, declaring type, member | *(none registered)* |
| `ENTRY_POINT` | Entry-point shape | line span, declaring type, member | `MAIN_METHOD_ENTRY_POINT` |
| `INVOCATION` | — | — | *(none registered; see below)* |
| **`API_INVOCATION`** | **Fully qualified member used**, e.g. `System.DateTime.Now` | line span, declaring type and member **of the caller** | `DATETIME_NOW_USAGE`, `ENCODING_DEFAULT_USAGE` |
| **`LITERAL`** | **The matched value**, e.g. `G:\Logs\App\` | line span, **plus `matchedValue`** | `WINDOWS_PATH_LITERAL` |

`API_INVOCATION` and `LITERAL` were added with `application-fingerprint@1.2.0`, for the
RBC-style findings: API usages and literals whose behaviour changes on Linux. Since
signal registry 1.4.0 they are emitted by `ApiUsageExtractor` and `PathLiteralExtractor`
(see "Extractor batch 2" below). An artifact containing either declares
`artifactVersion: 1.2.0`, which step 3 now always emits.

**`API_INVOCATION`** — one use of one specific member: a property access, method call
or constructor. Distinct from `ENTRY_POINT`, which also matches named invocations but
means "this is how the application starts". An `API_INVOCATION` signal says "this
member is used here, and the member is the problem".

- `evidence_kind: FILE`
- One row per `(file, member)`, with a line span per use
- `value` is required and names the member, so one signal can cover a small family
  (`DateTime.Now` and `DateTime.Today`) with distinct rows
- A match that is purely syntactic (A4: semantic analysis off by default) reports
  `extractionConfidence` below `1.0`, since `DateTime` could be a user type or an alias.
  Symbol-resolved matches report `1.0`

**`LITERAL`** — a value in C# source or configuration that matches the signal's
pattern, which is stated in the registry `description`.

- `evidence_kind: FILE`
- `sourceType` tells source code from configuration
- `value` is required and holds the matched value. One row per `(file, distinct
  value)`, so the 20-entry evidence cap never hides a distinct value, and a catalog item
  can project with `group_by: source_path_and_value`
- Each evidence entry also carries **`matchedValue`**: exactly the text matched at that
  span. The conversion needs to know which path it found, and a `snippetHash` cannot
  say. `matchedValue` is required on `LITERAL` evidence and forbidden on every other
  type
- `matchedValue` is subject to Part G's secrets rules. It is only the substring the
  pattern matched, never the enclosing literal or line, capped at 512 characters, and
  never taken from a connection string or a sensitive-key value. A `LITERAL` pattern
  that could match credential material must not be registered

`INVOCATION` has been in the vocabulary since 1.0.0 with no definition and no signal
using it. **Do not use it for new signals**; use `API_INVOCATION`. It is kept only
because removing a value from a published schema enum is a major change.

Adding a type is a minor bump of the artifact schema (`application-fingerprint`), not
of the signal registry. Registering a signal of a new type is a minor registry bump,
as for any new signal.

### Extractor batch 2 — signal registry 1.4.0

Findings from a client assessment of .NET 8/10 APIs and workers on Windows moving to
OpenShift. 28 signals, 91 → 119. Scanner version 1.1.0.

| Extractor | Signals |
|---|---|
| `ApiUsageExtractor` *(new, `API_INVOCATION`)* | `ENCODING_DEFAULT_USAGE`, `DATETIME_NOW_USAGE`, `USE_WINDOWS_SERVICE_INVOCATION`, `SYSTEM_DRAWING_USAGE`, `REGISTRY_ACCESS_USAGE`, `DIRECTORY_SERVICES_USAGE`, `PROCESS_START_USAGE`, `ADD_HEALTH_CHECKS_INVOCATION`, `MAP_HEALTH_CHECKS_INVOCATION` |
| `PathLiteralExtractor` *(new, `LITERAL`)* | `WINDOWS_PATH_LITERAL`, `UNC_PATH_LITERAL` |
| `ConfigurationExtractor` | `SERILOG_FILE_SINK_CONFIG`, `WINDOWS_AUTH_CONNECTION_STRING_CONFIG`, `WCF_CLIENT_ENDPOINT_CONFIG`, `KAFKA_BOOTSTRAP_CONFIG`, `REDIS_CONNECTION_CONFIG`, `VAULT_CONFIG` |
| `FrameworkReferenceExtractor` | `SYSTEM_DRAWING_COMMON_PACKAGE`, `SYSTEM_DRAWING_NAMESPACE`, `CONFLUENT_KAFKA_PACKAGE`, `STACKEXCHANGE_REDIS_PACKAGE`, `VAULTSHARP_PACKAGE`, `MICROSOFT_EXTENSIONS_HOSTING_WINDOWSSERVICES_PACKAGE`, `WCF_CLIENT_PACKAGE` |
| `FileIndicatorExtractor` | `DOCKERFILE_FILE`, `WEB_CONFIG_FILE`, `OCP4_MANIFEST_FILE`, `HELM_CHART_FILE` |

Decisions taken with it:

- **Absence findings are not signals.** "No Dockerfile", "no health endpoint" and "no
  manifests" are catalog items with a `none` condition over the presence signals above.
- **No per-binding signals.** `WCF_BINDING_CONFIG` already carries the binding type as its
  value (`netTcpBinding`); a code-configured .NET WCF client shows up as
  `WCF_CLIENT_PACKAGE` with value `System.ServiceModel.NetTcp`.
- **Client versus service WCF.** A namespace cannot tell them apart, so client usage is
  `WCF_CLIENT_PACKAGE` plus `WCF_CLIENT_ENDPOINT_CONFIG`. `WCF_SERVICE_ENDPOINT_CONFIG` now
  counts only `<services>` endpoints; before 1.4.0 it also counted client endpoints,
  contradicting its own description.
- **`SYSTEM_DRAWING_NAMESPACE` is registered but not for detection.** The namespace also
  holds the cross-platform `Color`/`Point`/`Size` types. `SYSTEM_DRAWING_USAGE` matches only
  the Windows-only GDI+ types.
- **Deliberate narrowing:**
  - `DIRECTORY_SERVICES_USAGE` ignores `System.DirectoryServices.Protocols`, which works on
    Linux
  - `VAULT_CONFIG` ignores Azure Key Vault keys (`KeyVaultName`)
  - `PROCESS_START_USAGE`, `KAFKA_BOOTSTRAP_CONFIG` and `REDIS_CONNECTION_CONFIG` record
    presence and key paths, never commands, hosts or values
- **`appsettings*.json`, not just `appsettings.json`.** Environment variants carry the
  same connection strings, sinks and paths; reading only the base file was an
  undercount. The JSON walker now records a line number for every configuration signal,
  and walks arrays, which Serilog's `WriteTo` needs.
- **Repository-level signals.** Deployment files outside every fingerprinted project
  directory (a root `k8s/`, `charts/` or `Dockerfile`) are emitted in the artifact's
  `repositorySignals` and stored with a null `project_id`. Item detection must see them
  when evaluating each project (`28-ITEM-AND-CONVERSION-MODEL.md` Part E).
- **Registry 1.5.0 / scanner 1.2.0 — the client's own WCF binding.**
  - `WCF_BINDING_CONFIG` records every endpoint's binding without saying whose, so a
    NetTcp *service* beside an HTTP client looked like a NetTcp client. Two signals now
    carry the binding of client endpoints only:
    - `WCF_CLIENT_BINDING_CONFIG` (ConfigurationExtractor, from `<client><endpoint>`)
    - `WCF_CLIENT_BINDING_USAGE` (ApiUsageExtractor, a binding constructed in a
      `ClientBase<T>` / `ChannelFactory<T>` file that hosts no service)
  - `WCF_CLIENT_PACKAGE` = `System.ServiceModel.NetTcp` is **not** NetTcp evidence:
    Visual Studio and dotnet-svcutil add the whole WCF package set to every client.
  - **Generated code, one exception.** Generated files stay excluded everywhere (Part G)
    except for `WCF_CLIENT_BINDING_USAGE`, because svcutil puts the client's binding in
    its generated `Reference.cs`. Every other rule still skips them.
  - The first signal on a path containing a space (`Connected Services/…`) exposed a
    SARIF bug: raw paths are not valid URI references. SARIF `artifactLocation.uri` is
    now percent-encoded per segment.
- **Hosted services were already covered.** `BACKGROUND_SERVICE_BASE_CLASS`,
  `IHOSTED_SERVICE_BASE_CLASS` (InheritanceExtractor) and `ADD_HOSTED_SERVICE_ENTRY_POINT`
  (EntryPointExtractor) have been in the registry since 1.1.0. None of the four sample
  repositories contains a worker, which is why they never fire there.

**Extractor backlog is driven by step 4, not by this document.** Signals the
catalog needs but no extractor emits yet are recorded on the pattern that wants
them, as `required_signals_pending[].expected_extractor`
(`24-STEP-004-CLASSIFICATION.md` Part B2), and surface grouped by extractor in
each scan's coverage report. Two extractors are named there and not yet built:

| Extractor | Signals wanted | Wanted by |
|---|---|---|
| `SsisExtractor` | package-internals signals (connection managers, data flow components) | `ssis-package` |
| `DesktopUiExtractor` | `SYSTEM_WINDOWS_FORMS_NAMESPACE`, `SYSTEM_WINDOWS_FORMS_ASSEMBLY`, `FORM_BASE_CLASS`, `SYSTEM_WINDOWS_NAMESPACE`, `PRESENTATION_FRAMEWORK_ASSEMBLY`, `WINDOW_BASE_CLASS`, `STA_THREAD_ATTRIBUTE` | `winforms-desktop`, `wpf-desktop` |

### gRPC is invisible to step 3

Found by step 5: cluster `b582b6fa716a` is two gRPC services in
`legacy-grpc-suite`, and its whole signature is `PROGRAM_CS_FILE`,
`SERVICES_FOLDER`, `TOP_LEVEL_STATEMENTS_ENTRY_POINT`,
`WEB_APPLICATION_CREATE_BUILDER_ENTRY_POINT` — four signals that describe *any*
minimal-hosting ASP.NET Core application. Nothing in the registry distinguishes
a gRPC service from a Hello World web app.

**This one is worse than an ordinary gap**, because gRPC is one of the three
candidate target states for WCF in our own catalog. We can recommend migrating
*to* a technology we cannot detect — which means we cannot verify the migration
landed, cannot classify the result on a later scan, and cannot tell an estate's
existing gRPC services apart from the ones we created.

Four of the five wanted signals need no new extractor; one does not fit the
existing model:

| Signal | Extractor | Fit |
|---|---|---|
| `GRPC_ASPNETCORE_PACKAGE` | `FrameworkReferenceExtractor` | **Clean.** `<PackageReference Include="Grpc.AspNetCore">` is the same shape as `MICROSOFT_ASPNETCORE_PACKAGE` — a new entry in its package list, nothing more |
| `GRPC_NAMESPACE` | `FrameworkReferenceExtractor` | **Clean.** `using Grpc.Core;` is the same shape as `DAPPER_NAMESPACE` |
| `PROTO_FILE` | `FileIndicatorExtractor` | **Clean.** A `*.proto` glob, the same shape as `SVC_FILE`. `evidence_kind: FILE` |
| `MAP_GRPC_SERVICE_INVOCATION` | `EntryPointExtractor` | **Fits the technique, not the naming.** The extractor already detects named invocations (`ADD_HOSTED_SERVICE_ENTRY_POINT`), but `app.MapGrpcService<BillingService>()` is a **generic** invocation, which its current matcher may not handle. Also every signal it emits is named `*_ENTRY_POINT`; this is an endpoint registration, not an entry point. Prefer `ADD_GRPC_INVOCATION` from `builder.Services.AddGrpc()` as the primary — non-generic, and present on every gRPC server |
| `GRPC_SERVICE_BASE_CLASS` | `InheritanceExtractor` — **needs a change** | All twelve of its current signals match a **known, fixed** base type (`DbContext`, `ControllerBase`, `Page`). A gRPC service derives from a base generated from the .proto: `service Billing` becomes `class BillingService : Billing.BillingBase`. The name is per-service, so this needs a **shape** match (`<T>.<T>Base`) rather than a name match — a new matching mode, not a new list entry |

So: three one-line additions, one that wants a naming decision and possibly
generic-invocation support, and one that needs `InheritanceExtractor` to learn
pattern-shaped base types. No new extractor is required. `GRPC_ASPNETCORE_PACKAGE`
alone would have identified the cluster, so the cheap three are worth doing
first and independently.

Adding these is a minor registry bump — they are additions, not renames.

`FrameworkReferenceExtractor` covered web, service and data namespaces only, so
the registry has no desktop UI framework evidence at all — `XAML_FILE` is the
one desktop signal it emits, and it separates WPF from WinForms without
identifying either. Both desktop patterns are `active` regardless, detecting on
step 2's `outputType: WinExe` plus XAML presence, and both carry a
`matchWarnings` entry saying so. Adding these signals is a minor registry bump
(they are additions, not renames) and lets both patterns move from
metadata-shaped detection to real positive evidence.

**Note for step 4:** the catalog's `detection_rules` JSONB is currently shaped around
namespaces, globs and packages. Step 4 will most likely need it reshaped to reference
signal names instead. That is step 4's problem, but choose signal names now with that
in mind — they will become the vocabulary the catalog's detection rules are written
in, and renaming them later means rewriting every pattern.

---

## Part E — Data model

Three tables. All rows owned by step 3 and replaced wholesale per repository on
rescan.

### `project_fingerprints` — 1:1 with `projects`

| Column | Type | Notes |
|---|---|---|
| `project_id` | `UUID` PK FK → `projects.id` | |
| `repository_id` | `UUID` NOT NULL FK | Denormalised for query convenience |
| `fingerprint_status` | `TEXT` NOT NULL | CHECK IN (`complete`, `partial`, `failed`, `skipped`, `not_supported`) |
| `scanner_version` | `TEXT` NOT NULL | |
| `analysis_capabilities` | `JSONB` NOT NULL | The §20 capability flags |
| `project_sdk` | `TEXT` | e.g. `Microsoft.NET.Sdk.Web`. New in step 3 |
| `nullable_enabled` | `BOOLEAN` | |
| `implicit_usings` | `BOOLEAN` | |
| `evaluated_properties` | `JSONB` | MSBuild-evaluated values that differ from step 2's raw parse, each with `{raw, evaluated, source}` |
| `signal_count` | `INTEGER` NOT NULL DEFAULT 0 | |
| `evidence_count` | `INTEGER` NOT NULL DEFAULT 0 | |
| `category_summary` | `JSONB` | Signal count per §19 category, for fast dashboard rollups |
| `warnings` | `JSONB` | Array of `{code, message, severity}` |
| `analysis_duration_ms` | `INTEGER` | |
| `step_execution_id` | `UUID` | Provenance |
| `fingerprinted_at` | `TIMESTAMPTZ` | |

### `fingerprint_signals`

Aggregated per `(project, signal_name, source_path)` rather than one row per
occurrence. Twenty-one `OperationContract` attributes in one file is **one row with
`occurrence_count: 21`**, not twenty-one rows. At 600 projects, per-occurrence rows
would reach millions.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `project_id` | `UUID` FK | Null for repository-level signals |
| `repository_id` | `UUID` NOT NULL FK | |
| `signal_name` | `TEXT` NOT NULL | Must exist in the signal registry |
| `signal_category` | `TEXT` NOT NULL | One of the sixteen §19 categories |
| `signal_type` | `TEXT` NOT NULL | `ATTRIBUTE`, `BASE_CLASS`, `FILE_PRESENCE`, `INVOCATION`, `CONFIG_ELEMENT`, `PACKAGE`, `ASSEMBLY`, `NAMESPACE`, `ROUTE`, `ENTRY_POINT`, `API_INVOCATION`, `LITERAL` — see Part D "Signal types" |
| `value` | `TEXT` | Fully qualified name, route template, or element path where meaningful. Required for `API_INVOCATION` (the member) and `LITERAL` (the matched value) |
| `source_type` | `TEXT` NOT NULL | The nine §18 source types |
| `source_path` | `TEXT` | Repository-relative |
| `evidence_kind` | `TEXT` | CHECK IN (`FILE`, `FOLDER`, `NONE`), nullable. What `source_path` names — from the signal registry's `evidence_kind` field. Never treat a `FOLDER` (or `NONE`) row's `source_path` as an openable file location — see Part F's `evidenceKind` note |
| `occurrence_count` | `INTEGER` NOT NULL DEFAULT 1 | |
| `evidence` | `JSONB` | Capped array of `{lineStart, lineEnd, declaringType, member, snippetHash}` (camelCase, as serialized by step 3), plus `matchedValue` on `LITERAL` rows only. **Max 20 entries**; `occurrence_count` carries the true total |
| `extractor` | `TEXT` NOT NULL | |
| `extraction_confidence` | `NUMERIC(3,2)` NOT NULL | 0.00–1.00 |

Unique on `(project_id, signal_name, source_path, value)` — treat null `project_id`
as repository scope via a partial index.
Indexes on `(repository_id, signal_name)` and `(repository_id, signal_category)`.

Store a `snippet_hash` rather than a source snippet. Snippets risk carrying secrets
and inflate storage; a hash still lets you detect change between scans.

### `fingerprint_scans` — 1:1 with repository

| Column | Type | Notes |
|---|---|---|
| `repository_id` | `UUID` PK FK | |
| `scan_status` | `TEXT` NOT NULL | CHECK IN (`complete`, `partial`, `failed`) |
| `scanner_version` | `TEXT` NOT NULL | |
| `signal_registry_version` | `TEXT` NOT NULL | |
| `projects_eligible` | `INTEGER` | |
| `projects_complete` / `projects_partial` / `projects_failed` / `projects_skipped` | `INTEGER` | |
| `total_signals` / `total_evidence` | `INTEGER` | |
| `semantic_analysis_enabled` | `BOOLEAN` NOT NULL | |
| `repository_signal_count` | `INTEGER` | |
| `warnings` | `JSONB` | |
| `step_execution_id` | `UUID` | |
| `scanned_at` | `TIMESTAMPTZ` | |

`scan_status` is `partial` when any project is `partial` or `failed`; `failed` only
when no project could be fingerprinted at all.

---

## Part F — Artifact `application-fingerprint@1.1.0`

Written to `output_dir/application-fingerprint.json`. Deterministic per Part B.

Every signal carries `evidenceKind` — `FILE`, `FOLDER`, or `NONE`, stamped from the
signal registry's `evidence_kind` field (single source of truth per signal name, see
Part D). It says what `sourcePath` names, so no consumer — the SARIF builder, step
4's evidence links, `fingerprint_signals.evidence_kind`, a future "open source" UI —
has to guess. A `FOLDER` signal (e.g. `SERVICES_FOLDER`, whose `sourcePath` is a
directory like `src/ApplicationCore/Services`) must never be treated as something a
viewer can open and jump to a line in; that assumption is exactly what broke the VS
Code SARIF viewer for step 3's SARIF export (25-STANDARDS-AND-VIEWPOINTS.md Part A3
addendum). 1.1.0 added this field; 1.0.0 lacked it and predates the fix.

**1.2.0** (`schemas/application-fingerprint-1.2.0.schema.json`) adds the `API_INVOCATION` and
`LITERAL` signal types and `evidence[].matchedValue` (Part D "Signal types"). The schema
requires `matchedValue` on every `LITERAL` evidence entry and rejects it on any other type,
and requires a non-null `value` on both new types. Every valid 1.1.0 artifact is valid under
1.2.0 apart from the version string. Step 3 emits 1.2.0 from scanner 1.1.0 (registry
1.4.0), and validates against it before writing. 1.2.0 is also the first version whose
`repositorySignals` is populated.

```json
{
  "artifactType": "application-fingerprint",
  "artifactVersion": "1.1.0",
  "scannerVersion": "1.0.0",
  "signalRegistryVersion": "1.0.0",
  "repositoryId": "…",
  "repositorySlug": "order-management",
  "repositoryCommitSha": "35257c0632ec…",
  "scanStatus": "partial",
  "semanticAnalysisEnabled": false,
  "summary": {
    "projectsEligible": 14,
    "projectsComplete": 11,
    "projectsPartial": 2,
    "projectsFailed": 0,
    "projectsSkipped": 1,
    "totalSignals": 412,
    "totalEvidence": 1893,
    "signalsByCategory": { "FRAMEWORK_ANNOTATION": 63, "FILE_INDICATOR": 41 }
  },
  "projects": [
    {
      "projectId": "…",
      "projectPath": "src/Customer.Service/Customer.Service.csproj",
      "fingerprintStatus": "PARTIAL",
      "analysisCapabilities": {
        "fileDiscovery": true,
        "projectMetadataParsed": true,
        "msbuildEvaluated": true,
        "syntaxAnalysis": true,
        "semanticAnalysis": false,
        "configurationParsed": true,
        "deploymentArtifactsParsed": true,
        "generatedCodeExcluded": true
      },
      "projectSdk": null,
      "evaluatedProperties": {
        "targetFramework": { "raw": "v4.7.2", "evaluated": "v4.7.2", "source": "MSBUILD_EVALUATED" }
      },
      "signals": [
        {
          "name": "SERVICE_CONTRACT_ATTRIBUTE",
          "category": "FRAMEWORK_ANNOTATION",
          "type": "ATTRIBUTE",
          "value": "System.ServiceModel.ServiceContractAttribute",
          "sourceType": "SOURCE_CODE",
          "sourcePath": "Services/ICustomerService.cs",
          "evidenceKind": "FILE",
          "occurrenceCount": 4,
          "evidence": [ { "lineStart": 12, "lineEnd": 12, "declaringType": "ICustomerService" } ],
          "extractor": "AttributeExtractor",
          "extractionConfidence": 1.0
        }
      ],
      "warnings": [ { "code": "SEMANTIC_ANALYSIS_DISABLED", "message": "…", "severity": "info" } ]
    }
  ],
  "repositorySignals": [],
  "warnings": []
}
```

No `applicationPattern` field, no `scanId`, no timestamp — §23 and A3.

Validate against the JSON Schema before writing, per §33. A schema validation failure
is a step failure, not a warning.

---

## Part G — Safety, scale and secrets

### Secrets

§8.4 and §38.7 are non-negotiable. Enforce mechanically rather than by convention:

- **Nothing derived from a connection string is ever persisted.** Emit the **name** and
  the **provider** only — never the value, a substring of it, or a hash of it. One read
  of the value is permitted: parsing it in memory to check the Windows-authentication
  keywords (`Integrated Security`, `Trusted_Connection` — synonyms, last one written
  wins, as in SqlClient — including the inner string of an EF6 connection string).
  That check returns a yes/no and nothing is kept. The resulting signal,
  `WINDOWS_AUTH_CONNECTION_STRING_CONFIG`, carries only the connection string's name.
  The rule was "never read"; it is now "never persisted", so that Windows
  authentication can be detected at all.
- Any config key matching `password|pwd|secret|token|apikey|api_key|connectionstring|
  accountkey|sharedaccesskey|credential` (case-insensitive): record the key's
  presence, never its value.
- No source snippets in evidence — `snippet_hash` only. The single exception is
  `LITERAL` evidence's `matchedValue`, and only within Part D's limits: just the
  substring the pattern matched, capped at 512 characters, and never taken from a
  connection string or a sensitive-key value. Text shaped like a connection string is
  skipped wherever it appears, including C# literals and appSettings values, and so is
  a literal assigned to a sensitively named variable.
- `ConfigurationExtractorSecretsTests` is the mechanical proof. It asserts that:
  - a full connection string with credentials produces an artifact whose text contains
    no password
  - a password-bearing Windows-auth connection string yields only its name, with no
    server, keyword or password in the artifact
  - a Windows path inside a connection string (XML, JSON or a C# literal) produces no
    `LITERAL` row

**Web Deploy SetParameters files (scanner 1.3.0, signal registry 1.7.0).**
- SetParameters files mix properties, configuration and secrets, and usually sit
  outside the project directory (`CustomFiles\Catalog.Host\SetParamFiles\PROD\SetParam.xml`).
- They are found by the engagement's `deploy_parameter_globs`, with the same
  discovery and project association as step 5 (`DeployParameterFiles`, 29-STEPS
  Part C9), and given to the project they belong to.
- **PathLiteralExtractor** reads each value whose name is not secret and which is
  not a connection string. `LogDirectory = G:\Logs\…` becomes a
  `WINDOWS_PATH_LITERAL` occurrence on the SetParam file and line.
- **ConfigurationExtractor** records a secret-named parameter as
  `SENSITIVE_CONFIG_KEY` (name only). A connection-string value gives
  `CONNECTION_STRING_CONFIG` (name only), plus `WINDOWS_AUTH_CONNECTION_STRING_CONFIG`
  from the one permitted bool read.
- **`UNQUALIFIED_HOSTNAME_URL`** (new, `ENDPOINT_INDICATOR`, PathLiteralExtractor)
  is a URL whose host is a single label (`http://appsrv0341/…`), in a C# literal,
  a configuration value or a SetParameters value. The value is the host alone,
  never the URL's path, query or credentials. localhost, IP addresses and
  placeholders are not matched.
- The catalog item `unqualified-hostname` (occurrence scope, one per host per
  file) is detected on it. Step 5 gives the same environments `requires_change`.

**Console input (scanner 1.4.0, signal registry 1.9.0, 137 signals).** ApiUsageExtractor
emits two `EXECUTION_INDICATOR` signals. They tell a console application that needs a
person at the keyboard from one that only pauses.
- **`INTERACTIVE_CONSOLE_INPUT`** is input that needs a person:
  - `Console.ReadKey`, which throws when there is no console or input is redirected;
  - a `Console.Read` or `ReadLine` whose result is used;
  - a prompt library: Spectre.Console (`AnsiConsole.Prompt`/`Ask`/`Confirm`, and
    `TextPrompt`, `SelectionPrompt` and `MultiSelectionPrompt` under `using
    Spectre.Console`), or Sharprompt (`Prompt.*` under `using Sharprompt`).

  A same-named type in a file that does not import the library is not matched.
- **`CONSOLE_PAUSE_FOR_INPUT`** is a `Console.Read` or `ReadLine` whose result is
  discarded: a bare statement, or `_ =`. Examples are "Press ENTER to exit", or a
  self-hosted service waiting to be stopped.
  - **Why it is separate.** With no console (a CronJob pod, a scheduled task), `ReadLine`
    returns null and `Read` returns -1 at once; neither blocks. So a pause does not prove
    a person is needed, and a batch job ending in a debug pause is still a batch job.
  - **Not used to exclude.** It is recorded as evidence only.
  - **A real migration risk.** A host that waits on it to stay alive exits immediately in
    a container. The WCF sample's Catalog.Host does exactly that.

Step 3's registration is now in the repository,
`steps/step-003-fingerprinting/registration/application-fingerprinting.json` (1.4.0).
Generated by `schemas/make_signal_registry_1_9_0.py`.

**Signal registry 1.8.0 (135 signals).** Adds step 4's seven architecture signals:
`EXPOSES_WCF_SERVICE`, `HOSTS_WCF_SERVICE`, `WCF_SERVICE_HOSTING`, `EXPOSES_HTTP_API`,
`EXPOSES_ASMX_SERVICE`, `EXPOSES_GRPC_SERVICE` and `EXPOSES_WEBFORMS_UI`. Their extractor
is `EntryPointInventory`. Step 3 does not emit them. Step 4 writes them into
`fingerprint_signals` (29-STEPS Part B6), so the registry is still the one list of every
signal an item can reference. Generated by `schemas/make_signal_registry_1_8_0.py`.

### Scale and timeouts

- Bounded parallelism across projects, default 4, configurable. Not unbounded —
  Roslyn parsing is memory-hungry.
- Per-project timeout, default 120s. On timeout: `fingerprintStatus: PARTIAL` with a
  `PROJECT_ANALYSIS_TIMEOUT` warning. Never fail the repository for one slow project.
- Skip generated code: `*.designer.cs`, `*.g.cs`, `*.g.i.cs`, `*.AssemblyInfo.cs`,
  anything under `obj/`, and files carrying an auto-generated header. Set
  `generatedCodeExcluded`.
- Cap per-project source files analysed, default 5000, with a warning when exceeded.
- Same directory exclusions as steps 1 and 2.

### Read-only

Writes nothing into the scanned repository. Verify with `git status` after a run.
MSBuild evaluation must not trigger restore or write `obj/` — set the relevant
properties and confirm.

---

## Part H — API and UI

Endpoints in the FastAPI backend, per `18-API-CONVENTIONS.md`:

```
GET /api/repositories/{id}/fingerprint-scan          fingerprint_scans summary
GET /api/repositories/{id}/fingerprint-signals       ?category=&signal_name=&project_id=
GET /api/projects/{project_id}/fingerprint           full fingerprint incl. signals
GET /api/engagements/{eid}/signal-distribution       rollup for the dashboard
GET /api/workflow/signal-registry                    the active registry
```

### Repository detail — Fingerprint section

Below the Structure section. Coverage strip per §22.1: eligible, complete, partial,
failed, skipped, average evidence per project. Then a project table with fingerprint
status, signal count, evidence count and top categories, expanding to the §22.3
category tree.

### Project fingerprint detail

Signals grouped by the sixteen categories, each row showing name, value, occurrence
count, source path and confidence, expandable to evidence lines. Warnings collapsed
by default.

### Dashboard

Per §22.2, a **Technical signal distribution** panel. Labelling is mandatory:

> Projects containing WCF-related signals: 145

Never "WCF applications: 145". The **Applications** and **Patterns** cards still show
`—` — step 3 does not produce an application count, and step 4 has not run.

---

## Acceptance criteria

- [ ] Step 3 registers with `adapter_type: process` and `phase0-repository-discovery`
      validates **without any YAML change**
- [ ] Consumes `solution-project-inventory ^2.0.0`; `inputs_resolved` in the Workflow
      tab shows `2.0.0`
- [ ] Runs standalone from stdin per Part B
- [ ] `MSBuildLocator.RegisterDefaults()` runs before any MSBuild type is loaded, and
      the CLI starts cleanly on a machine with only the .NET SDK installed
- [ ] No output on stdout except the StepResult; verified by piping stdout to a file
      and parsing it as JSON with logging turned up
- [ ] Two runs over an unchanged repository produce identical artifact checksums
- [ ] Fixture repositories per §35 exist for at least: legacy WCF, Web Forms, MVC,
      .NET Core API, Windows Service, console batch, broken project reference,
      non-compiling source
- [ ] Golden-file tests pass for every fixture, with volatile fields normalised
- [ ] A project whose source does not compile still produces syntax-level signals
- [ ] A project whose XML fails to parse still produces Level 1 and 2 signals
- [ ] Semantic analysis is disabled by default; enabling it on a fixture that cannot
      restore degrades to syntax with a warning rather than failing
- [ ] Every emitted signal name exists in the signal registry; an unregistered name
      fails validation
- [ ] Artifact validates against the JSON Schema before write
- [ ] A fixture containing a credentialed connection string produces an artifact whose
      text does not contain the password
- [ ] Generated code is excluded and the capability flag reflects it
- [ ] A project exceeding the per-project timeout yields `PARTIAL`, not a failed
      repository
- [ ] `git status` is clean in the scanned repository, and no `obj/` was created
- [ ] Signals from step 2's data are not re-extracted; `evaluated_properties` contains
      only values MSBuild resolved differently
- [ ] Dashboard labels signal counts as signals, and Applications and Patterns still
      show `—`
- [ ] The artifact contains no `applicationPattern`, `scanId` or timestamp field
