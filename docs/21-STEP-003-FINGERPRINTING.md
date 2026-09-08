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

**Extractor backlog is driven by step 4, not by this document.** Signals the
catalog needs but no extractor emits yet are recorded on the pattern that wants
them, as `required_signals_pending[].expected_extractor`
(`24-STEP-004-CLASSIFICATION.md` Part B2), and surface grouped by extractor in
each scan's coverage report. Two extractors are named there and not yet built:

| Extractor | Signals wanted | Wanted by |
|---|---|---|
| `SsisExtractor` | package-internals signals (connection managers, data flow components) | `ssis-package` |
| `DesktopUiExtractor` | `SYSTEM_WINDOWS_FORMS_NAMESPACE`, `SYSTEM_WINDOWS_FORMS_ASSEMBLY`, `FORM_BASE_CLASS`, `SYSTEM_WINDOWS_NAMESPACE`, `PRESENTATION_FRAMEWORK_ASSEMBLY`, `WINDOW_BASE_CLASS`, `STA_THREAD_ATTRIBUTE` | `winforms-desktop`, `wpf-desktop` |

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
| `signal_type` | `TEXT` NOT NULL | `ATTRIBUTE`, `BASE_CLASS`, `FILE_PRESENCE`, `INVOCATION`, `CONFIG_ELEMENT`, `PACKAGE`, `ASSEMBLY`, `NAMESPACE`, `ROUTE`, `ENTRY_POINT` |
| `value` | `TEXT` | Fully qualified name, route template, or element path where meaningful |
| `source_type` | `TEXT` NOT NULL | The nine §18 source types |
| `source_path` | `TEXT` | Repository-relative |
| `evidence_kind` | `TEXT` | CHECK IN (`FILE`, `FOLDER`, `NONE`), nullable. What `source_path` names — from the signal registry's `evidence_kind` field. Never treat a `FOLDER` (or `NONE`) row's `source_path` as an openable file location — see Part F's `evidenceKind` note |
| `occurrence_count` | `INTEGER` NOT NULL DEFAULT 1 | |
| `evidence` | `JSONB` | Capped array of `{line_start, line_end, declaring_type, member, snippet_hash}`. **Max 20 entries**; `occurrence_count` carries the true total |
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

- Connection strings: emit the **name** and the **provider** only. Never the value,
  never a substring of it.
- Any config key matching `password|pwd|secret|token|apikey|api_key|connectionstring|
  accountkey|sharedaccesskey|credential` (case-insensitive): record the key's
  presence, never its value.
- No source snippets in evidence — `snippet_hash` only.
- Add a unit test asserting that a fixture containing a full connection string with
  credentials produces an artifact whose text does not contain the password.

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
