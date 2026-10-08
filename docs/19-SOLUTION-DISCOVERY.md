# 19 — `solution-discovery`: Solution & Project Discovery

Lifecycle step `solution-discovery`. Owner: **P**. Job: `phase0-repository-discovery`, immediately
after `repository-ingest`.

Built from the `solution-discovery` requirements document. Read that alongside this — it is the
authority on *what* to capture; this spec is the authority on *how* it is modelled,
executed and stored.

---

## Scope discipline

`solution-discovery` is **structural discovery only**. It records what exists and how it relates.
It interprets nothing.

Record `OutputType=Library` as a fact. Do **not** conclude the project is a library
rather than an application — that is `application-fingerprinting`. Record a `System.ServiceModel` package
reference. Do **not** conclude the project is a WCF service — that is `item-detection`.

Practical consequence: after `solution-discovery` the dashboard can show solutions, projects,
standalone projects, framework families and scan quality. The **Applications** and
**Patterns** cards remain unavailable, because deployable application count is an
`application-fingerprinting` output. Do not populate them from project counts.

---

## Part A — `repository-ingest` amendments

Four fields the requirements document needs that `repository-ingest` does not currently capture.
All are cheap additions to the scan it already performs.

### New `repositories` columns

| Column | Type | Notes |
|---|---|---|
| `organization` | `TEXT` | Parsed from the clone URL path. `github.com/acme/orders` → `acme`. Null when unparseable |
| `last_commit_date` | `TIMESTAMPTZ` | Committer date of HEAD. Null when `has_git_history` is false |
| `primary_languages` | `JSONB` | Array of `{language, file_count, percentage}`, descending by count, top 6 |
| `source_status` | `TEXT` | CHECK IN (`active`, `archived`, `disabled`, `inaccessible`). Source-control platform status. **Null for `local_path`** — it is only knowable via a provider API |

`source_status` is deliberately distinct from the two statuses already present:

| Field | Meaning | Set by |
|---|---|---|
| `ingest_status` | Did our scan work? | `repository-ingest` |
| `retirement_status` | Is this in modernization scope? | Human, at registration |
| `source_status` | What does the source-control platform say? | Provider API, later |

Do not collapse them.

### Language detection

During the existing file walk, count files by extension and map to a language:
`.cs` → C#, `.vb` → VB.NET, `.fs` → F#, `.sql` → SQL, `.ps1` → PowerShell,
`.js`/`.ts` → JavaScript/TypeScript, `.xml`/`.config`/`.xaml` → XML,
`.cshtml`/`.aspx`/`.ascx` → Razor/WebForms markup, `.html`/`.css` → Web.

Same exclusions as the size walk: `.git`, `node_modules`, `bin`, `obj`, `packages`.
Percentages are of counted files only, rounded to one decimal.

Bump the `repository-inventory` artifact to **1.1.0** to carry the new fields. Minor
version — additive only, so `solution-discovery`'s `^1.0.0` range still matches. This is a
deliberate, low-risk exercise of the versioning scheme.

---

## Part B — Execution model

### Process adapter, standalone script

`solution-discovery` is delivered as a **standalone script invoked via the `process` adapter**,
not in-process like `repository-ingest`.

This is intentional. Steps from `application-fingerprinting` onward will be written by different people, and the
`process` adapter is the integration path they will use. Proving it end to end with
a step we control — before handing a spec to someone else — is worth the small
runtime cost.

```
steps/step-002-solution-discovery/
  main.py               reads StepContext on stdin, writes StepResult on stdout
  discovery/
    solution_parser.py
    project_parser.py
    artifact_scanner.py
    framework.py        raw → family/version normalisation
    persistence.py      DB writes
  requirements.txt      declares its own dependencies
  README.md             how to run standalone
  tests/
```

At repository root, **outside `backend/app/`**. It is a separate deliverable that
happens to live in the same repo, and it must not import from `backend.app`. Shared
concepts get duplicated rather than coupled — that is the price of decoupling and it
is worth paying here.

### Registration

```yaml
step_name: solution-discovery
lifecycle_step_no: 2
display_name: "Solution & project discovery per repository"
owner_code: P
version: "1.0.0"
owner_team: "platform"
implementation_status: implemented

consumes:
  - artifact_type: repository-inventory
    version_range: "^1.0.0"
    optional: false

produces:
  - artifact_type: solution-project-inventory
    artifact_version: "2.0.0"

adapter_type: process
adapter_config:
  command: ["python", "steps/step-002-solution-discovery/main.py"]
  timeout_seconds: 1800

restart:
  allow_start_if_complete: false
  start_limit: 3
```

The `consumes` declaration matters beyond convenience — it is the first time the
engine's input resolution, artifact lookup and pre-invoke version re-check are
actually exercised. Verify all three fire.

The script reads `local_path` from the resolved `repository-inventory` artifact, not
from the database, so it can be run standalone against a hand-written artifact file.

---

## Part C — Data model

Seven new tables. All rows are owned by `solution-discovery` and **replaced wholesale on rescan** —
delete by `repository_id`, then insert. Simpler than reconciling, and correct given
the artifact is a point-in-time snapshot.

**Except `projects`, which is upserted.** A project's id is derived, not generated:
`uuid5(namespace, "<repository_id>:<relative_path lower-cased>")`
(`main.py` `project_id_for`). A rescan therefore finds the same ids and updates those
rows in place. Everything keyed to `project_id` stays attached across a rescan, even
mid-migration: fingerprints, item occurrences, and later conversion executions.
Replacing the rows would cascade all of that away. Only projects no longer on disk are
deleted. The child tables (packages, references, solution membership) are still
replaced wholesale.

### `repository_structure` — 1:1 with repository

Summary written by `solution-discovery`. Separate from `repositories` so step ownership is
explicit and replacement is trivial.

| Column | Type | Notes |
|---|---|---|
| `repository_id` | `UUID` PK FK | |
| `scan_status` | `TEXT` NOT NULL | CHECK IN (`complete`, `partial`, `failed`) |
| `solution_count` | `INTEGER` | |
| `project_file_count` | `INTEGER` | Every project file found on disk |
| `projects_referenced_count` | `INTEGER` | Distinct projects referenced by any solution |
| `standalone_project_count` | `INTEGER` | On disk but in no solution |
| `shared_project_count` | `INTEGER` | Referenced by more than one solution |
| `unresolved_reference_count` | `INTEGER` | Solution and project references that did not resolve |
| `out_of_scope_project_count` | `INTEGER` | Recognised non-.NET project type (Part D) — present, intentionally not analysed |
| `unknown_project_count` | `INTEGER` | `*proj` extension we do not recognise at all |
| `failed_parse_count` | `INTEGER` | Files we should have been able to parse but could not — malformed `.csproj`/`.sln`, unreadable encoding |
| `legacy_project_count` | `INTEGER` | |
| `sdk_project_count` | `INTEGER` | |
| `framework_families` | `JSONB` | `{"net-framework": 8, "net-core": 3, "net": 2}` |
| `artifact_counts` | `JSONB` | `{"build": 14, "pipeline": 1, "container": 0, ...}` |
| `parse_warnings` | `JSONB` | Array of `{path, warning}` |
| `step_execution_id` | `UUID` | Provenance |
| `scanned_at` | `TIMESTAMPTZ` | |

`scan_status` is driven only by `failed_parse_count`: `partial` when
`failed_parse_count > 0` but the scan completed, `failed` when every recognised
.NET project failed to parse. Out-of-scope project types (Docker Compose, Node.js,
...) and unknown `*proj` extensions are informational — they are inventory findings,
not scan problems, and never degrade `scan_status`. See Part H.

### `solutions`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `repository_id` | `UUID` NOT NULL FK | |
| `name` | `TEXT` NOT NULL | |
| `relative_path` | `TEXT` NOT NULL | Forward-slash normalised, repo-relative |
| `format_version` | `TEXT` | From the `Microsoft Visual Studio Solution File` header |
| `visual_studio_version` | `TEXT` | `VisualStudioVersion` line |
| `minimum_vs_version` | `TEXT` | |
| `project_count` | `INTEGER` | Project entries declared |
| `resolved_project_count` | `INTEGER` | Located on disk |
| `missing_project_count` | `INTEGER` | |
| `solution_folder_count` | `INTEGER` | Entries with the solution-folder type GUID |
| `shared_project_count` | `INTEGER` | Also referenced by another solution |
| `parse_status` | `TEXT` NOT NULL | CHECK IN (`success`, `partial`, `failed`) |
| `parse_error` | `TEXT` | |

Unique on `(repository_id, relative_path)`.

### `projects`

Raw metadata only. No interpretation.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `repository_id` | `UUID` NOT NULL FK | |
| `name` | `TEXT` NOT NULL | Filename without extension |
| `relative_path` | `TEXT` NOT NULL | |
| `extension` | `TEXT` NOT NULL | `.csproj`, `.vbproj`, `.sqlproj`, `.dtproj`, … |
| `structural_type` | `TEXT` NOT NULL | From extension only — see Part D |
| `project_format` | `TEXT` NOT NULL | CHECK IN (`legacy_msbuild`, `sdk_style`, `unknown`) |
| `language` | `TEXT` NOT NULL | CHECK IN (`csharp`, `vb`, `fsharp`, `sql`, `ssis`, `cpp`, `shared`, `unknown`) |
| `assembly_name` | `TEXT` | |
| `root_namespace` | `TEXT` | |
| `output_type` | `TEXT` | Raw value: `Library`, `Exe`, `WinExe`, or null. **Uninterpreted** |
| `target_framework_raw` | `TEXT` | First or only declared value, verbatim |
| `target_frameworks_raw` | `JSONB` | All declared values when multi-targeting |
| `framework_family` | `TEXT` | Normalised for grouping — see Part E |
| `framework_version` | `TEXT` | |
| `is_multi_targeting` | `BOOLEAN` NOT NULL DEFAULT false | |
| `solution_membership_count` | `INTEGER` NOT NULL DEFAULT 0 | |
| `is_standalone` | `BOOLEAN` NOT NULL DEFAULT false | `solution_membership_count = 0` |
| `project_reference_count` | `INTEGER` NOT NULL DEFAULT 0 | |
| `package_reference_count` | `INTEGER` NOT NULL DEFAULT 0 | |
| `package_management_style` | `TEXT` NOT NULL | CHECK IN (`packagereference`, `packages_config`, `mixed`, `none`) |
| `has_packages_config` | `BOOLEAN` NOT NULL DEFAULT false | |
| `parse_status` | `TEXT` NOT NULL | CHECK IN (`success`, `partial`, `failed`, `out_of_scope`) |
| `parse_warnings` | `JSONB` | Array of strings |

Unique on `(repository_id, relative_path)`. Index on `(repository_id, framework_family)`
and `(repository_id, project_format)`.

### `solution_projects` — solution membership

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `solution_id` | `UUID` NOT NULL FK | |
| `project_id` | `UUID` FK | Null when unresolved |
| `raw_path` | `TEXT` NOT NULL | As written in the `.sln`, backslashes preserved |
| `project_guid` | `TEXT` | |
| `project_type_guid` | `TEXT` | Recorded raw. Do not interpret in `solution-discovery` |
| `solution_folder` | `TEXT` | Logical folder path, when nested |
| `resolution_status` | `TEXT` NOT NULL | CHECK IN (`resolved`, `unresolved`) |

Unique on `(solution_id, raw_path)`.

### `project_references`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `source_project_id` | `UUID` NOT NULL FK | |
| `referenced_project_id` | `UUID` FK | Null when unresolved or external |
| `raw_path` | `TEXT` NOT NULL | Verbatim from `<ProjectReference Include=…>` |
| `resolution_status` | `TEXT` NOT NULL | CHECK IN (`resolved`, `unresolved`, `external_repository`) |
| `is_cross_solution` | `BOOLEAN` NOT NULL DEFAULT false | Source and target appear in different solutions |

Unique on `(source_project_id, raw_path)`.

`external_repository` means the resolved path escapes the repository root — a genuine
cross-repository dependency, and a signal `dependency-and-context-map` will need.

### `project_packages`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `project_id` | `UUID` NOT NULL FK | |
| `package_name` | `TEXT` NOT NULL | |
| `version_raw` | `TEXT` | Verbatim, including ranges and floating versions |
| `declaration_source` | `TEXT` NOT NULL | CHECK IN (`packagereference`, `packages_config`) |
| `target_framework_raw` | `TEXT` | From `packages.config` entries |
| `is_malformed` | `BOOLEAN` NOT NULL DEFAULT false | |

Unique on `(project_id, package_name, declaration_source)`.

### `repository_artifacts`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `repository_id` | `UUID` NOT NULL FK | |
| `category` | `TEXT` NOT NULL | CHECK IN (`build`, `package`, `pipeline`, `container`, `script`, `configuration`, `deployment`, `documentation`) |
| `relative_path` | `TEXT` NOT NULL | |
| `file_name` | `TEXT` NOT NULL | |

Unique on `(repository_id, relative_path)`. Presence only — no content interpretation.

---

## Part D — Structural type from extension

Direct mapping, no inference:

| Extension | `structural_type` | `language` |
|---|---|---|
| `.csproj` | `csharp_project` | `csharp` |
| `.vbproj` | `vb_project` | `vb` |
| `.fsproj` | `fsharp_project` | `fsharp` |
| `.sqlproj` | `sql_database_project` | `sql` |
| `.dtproj` | `ssis_project` | `ssis` |
| `.shproj` | `shared_project` | `shared` |
| `.vcxproj` | `cpp_project` | `cpp` |

`.dtproj` is notable: it signals SSIS, which is a catalog pattern with no market
tooling. `solution-discovery` records it structurally; `item-detection` does the matching.

### Known non-.NET project types — out of scope, not failures

Some `*proj` extensions are recognised but are never .NET projects. They belong
in the inventory as present-and-out-of-scope, not as parse failures — a `.dcproj`
(Docker Compose) sitting next to a solution is normal at estate scale and must not
read as a scan problem:

| Extension | `structural_type` | `language` |
|---|---|---|
| `.dcproj` | `docker_compose_project` | `unknown` |
| `.njsproj` | `nodejs_project` | `unknown` |
| `.pyproj` | `python_project` | `unknown` |
| `.esproj` | `javascript_project` | `unknown` |
| `.wapproj` | `windows_packaging_project` | `unknown` |
| `.wixproj` | `wix_installer_project` | `unknown` |
| `.deployproj` | `deployment_project` | `unknown` |
| `.modelproj` | `modeling_project` | `unknown` |

These are recorded with `parse_status: success` and no metadata extracted — no
`target_framework_raw`, no packages, no references. They count toward
`out_of_scope_project_count`, not `project_file_count`'s recognised .NET subset.
`parse_warnings` gets one entry per file, e.g. `"Docker Compose project, recorded
but not analysed (not a .NET project)"`.

### Genuinely unknown project types

Anything else matching `*proj` — not a known .NET extension, not a known
non-.NET extension above — is `structural_type: unknown_project`,
`language: unknown`, `parse_status: out_of_scope`, and counted in
`unknown_project_count`. Never silently skipped — an unrecognised extension is a
discovery finding, not noise, but it is informational rather than a scan problem:
we don't know what it is, so we make no claim about whether it should have parsed.

### Genuine parse failures

A file with a known .NET extension (`.csproj`, `.vbproj`, `.fsproj`, `.sqlproj`,
`.dtproj`, `.shproj`, `.vcxproj`) that cannot be parsed — malformed XML, unreadable
encoding — is `parse_status: failed`, counted in `failed_parse_count`, with a
`parse_warnings` entry prefixed `"parse failed: <reason>"`. This is the only
category that represents `solution-discovery` falling short of what it should have been able to
do, and the only one that degrades `scan_status`. See Part H.

---

## Part E — Framework normalisation

For dashboard grouping only. `target_framework_raw` is always preserved verbatim.

| Raw pattern | `framework_family` | `framework_version` |
|---|---|---|
| `v4.7.2`, `v4.8` | `net-framework` | `4.7.2`, `4.8` |
| `net47`, `net472`, `net48` | `net-framework` | `4.7`, `4.7.2`, `4.8` |
| `netcoreapp2.1`, `netcoreapp3.1` | `net-core` | `2.1`, `3.1` |
| `netstandard2.0`, `netstandard2.1` | `net-standard` | `2.0`, `2.1` |
| `net5.0` … `net10.0` | `net` | `5.0` … `10.0` |
| `net6.0-windows` | `net` | `6.0` (record `windows` as a platform suffix) |
| anything else | `unknown` | null |

Multi-targeting: `target_frameworks_raw` holds all values, `framework_family` and
`framework_version` reflect the **highest** version present, `is_multi_targeting` is
true. Record the reasoning in a parse warning so the choice is visible.

Legacy `.csproj` declares `<TargetFrameworkVersion>v4.7.2</TargetFrameworkVersion>`;
SDK-style declares `<TargetFramework>` or `<TargetFrameworks>`. Presence of the `Sdk`
attribute on the root `<Project>` element determines `project_format`.

---

## Part F — Parsing notes

**Solution files** are not XML. Line-oriented: `Project("{type-guid}") = "Name",
"relative\path.csproj", "{project-guid}"` with `EndProject`. Solution folders use
type GUID `2150E333-8FDC-42A3-9474-1A3956D46DE8` and their "path" is the folder name.
`GlobalSection(NestedProjects)` maps children to folders.

**Project files** are XML but MSBuild-conditional. Read declared values without
evaluating conditions or importing `.props`/`.targets`. When a property appears under
multiple conditions, take the first unconditional occurrence and emit a parse warning.
Full MSBuild evaluation is out of scope — a documented limitation, not a bug.

**Exception: the target framework (artifact 2.1.0).** MSBuild implicitly imports the
nearest `Directory.Build.props` and then the nearest `Directory.Packages.props` above a
project, and a repository often sets `TargetFramework` once there (eShopOnWeb does, in
`Directory.Packages.props`). When the project file declares no framework, those two files
are read — unconditional, literal properties only, `$(Name)` expanded from them, the later
import overriding the earlier — and the project file's own value always wins.
`target_framework_source` records where the framework came from: `project`, or the
repository-relative props file. Explicit `<Import>`s are still not followed. This is the one
place every later step reads the framework from: `dependency-assessment` and `item-detection`'s
role computation and `frameworkFamily` conditions see the same answer.

**Known, not null (2.1.0).** Item detection treats a null metadata field as unknown and
reports the item `not_checked` for that project, so `solution-discovery` records what MSBuild itself
defines rather than leaving it null:

- `project_sdk`: the declared SDK (`<Project Sdk="...">` or `<Sdk Name="..."/>`), version
  stripped — `Microsoft.NET.Sdk.BlazorWebAssembly`, for example — or `none` for a legacy
  MSBuild project, which has no SDK.
- `output_type`: as declared; else from the implicit props files; else MSBuild's default
  for the SDK — `Exe` for `Microsoft.NET.Sdk.Web`, `.Worker` and `.BlazorWebAssembly`,
  `Library` otherwise. `output_type_source` says which: `project`, the props file, or
  `sdk_default`.

**Path resolution.** `.sln` and `<ProjectReference>` paths use backslashes. Normalise
to forward slashes, resolve relative to the containing file, then relative to the
repository root. A resolved path escaping the repository root is
`external_repository`, not `unresolved`.

**Encoding.** Legacy files are frequently UTF-8 with BOM, occasionally UTF-16. Detect
BOM, fall back to UTF-8 with replacement, and warn rather than fail.

**Read-only.** `solution-discovery` writes nothing into the repository folder, same as `repository-ingest`.

---

## Part G — Artifact `solution-project-inventory@2.0.0`

Bumped from 1.0.0 to 2.0.0 when `unsupported_project_count` was removed in favour of
`out_of_scope_project_count`, `unknown_project_count`, and `failed_parse_count` —
removing a field is a breaking change (see 11-STEP-CONTRACT.md's "Artifact
versioning"). Nothing consumed this artifact at the time, so the bump had no
affected-consumer fallout.

Deterministic: sorted keys, solutions sorted by `relative_path`, projects sorted by
`relative_path`, 2-space indent, trailing newline. `generated_at` goes in
`StepOutput.metadata`, **not** in the file — the pattern established in `repository-ingest`, so
unchanged input yields an identical checksum.

```json
{
  "artifact_type": "solution-project-inventory",
  "artifact_version": "2.0.0",
  "repository_id": "…",
  "repository_slug": "order-management",
  "scan_status": "partial",
  "summary": {
    "solution_count": 2,
    "project_file_count": 14,
    "projects_referenced_count": 12,
    "standalone_project_count": 2,
    "shared_project_count": 3,
    "unresolved_reference_count": 1,
    "legacy_project_count": 8,
    "sdk_project_count": 5,
    "out_of_scope_project_count": 1,
    "unknown_project_count": 0,
    "failed_parse_count": 1,
    "framework_families": { "net-framework": 8, "net-core": 3, "net-standard": 2 },
    "artifact_counts": { "build": 16, "package": 3, "pipeline": 1, "configuration": 9 }
  },
  "solutions": [ … ],
  "projects": [ … ],
  "project_references": [ … ],
  "repository_artifacts": [ … ],
  "parse_warnings": [ { "path": "src/Legacy/Old.csproj", "warning": "…" } ]
}
```

---

## Part H — Exit statuses

| Condition | Exit status |
|---|---|
| All solutions and recognised .NET projects parsed | `COMPLETED`, `scan_status: complete` |
| Repository contains only out-of-scope and/or unknown project types, nothing failed | `COMPLETED`, `scan_status: complete`, informational diagnostics only |
| `failed_parse_count > 0`, scan finished | `COMPLETED`, `scan_status: partial`, one `error`-level diagnostic per failure |
| No solution or project files found at all | `COMPLETED`, `scan_status: complete`, `NOOP`-style message. A repository with no .NET projects is a valid finding |
| Repository folder missing | `FAILED` |
| Input artifact unresolvable | `FAILED` — the engine should catch this before invoke |
| Every recognised .NET project failed to parse | `FAILED`, `scan_status: failed` |

`scan_status: partial` is driven **only** by `failed_parse_count > 0`. Out-of-scope
project types (Part D) and unknown `*proj` extensions never degrade `scan_status` —
they are recorded, counted, and surfaced as `info`-level diagnostics
(`PROJECT_OUT_OF_SCOPE`, `PROJECT_UNKNOWN_TYPE`), distinct from the `error`-level
diagnostics (`SOLUTION_PARSE_FAILED`, `PROJECT_PARSE_FAILED`) that genuine failures
produce. A repository containing nothing but a `.dcproj` next to its solution is
`scan_status: complete` with `out_of_scope_project_count: 1`.

Metrics: `read_count` = project files found, `write_count` = projects persisted,
`skip_count` = `failed_parse_count` (genuine parse failures only — out-of-scope and
unknown project types are not skips, they are recorded successfully).

---

## Part I — API and UI

### Endpoints

Per `18-API-CONVENTIONS.md`, fully documented.

```
GET /api/repositories/{id}/structure       repository_structure summary
GET /api/repositories/{id}/solutions       solutions with their projects
GET /api/repositories/{id}/projects        ?framework_family=&project_format=&standalone=&q=
GET /api/repositories/{id}/project-references
GET /api/repositories/{id}/artifacts       ?category=
GET /api/projects/{project_id}             detail incl. packages and references
GET /api/engagements/{eid}/structure-summary   portfolio rollup for the dashboard
```

### Repository detail — new Structure section

Rendered only when `repository_structure` exists; otherwise an empty state naming
`solution-discovery`.

- **Summary strip** — solutions, projects, standalone, shared, unresolved, legacy vs
  SDK, out-of-scope, unknown-type, and failed-parse counts shown separately, scan
  status badge (`complete` teal, `partial` amber, `failed` red) — amber/red are
  reserved for `failed_parse_count > 0`; out-of-scope and unknown counts never tint
  the badge
- **Solutions** — expandable rows listing member projects, missing ones flagged
- **Standalone projects** — separate list, since these are exactly what a
  solution-driven view misses
- **Framework distribution** — small horizontal bars by family
- **Supporting artifacts** — counts by category, expandable to paths
- **Discovery warnings** — collapsed by default, expandable

### Dashboard additions

Per the requirements document's Portfolio Summary. New cards: **Solutions**,
**Projects**, **Standalone projects**, **Unresolved references**, **Legacy vs SDK**.
The repository table gains solutions, projects, standalone, frameworks and scan
status columns.

The **Applications** and **Patterns** cards stay unavailable. Do not populate them
from project counts — a project is not an application, and conflating them would
produce a number that quietly becomes wrong at `application-fingerprinting`.

---

## Acceptance criteria

- [ ] `repository-ingest` populates `organization`, `last_commit_date` and `primary_languages`;
      `source_status` is null for `local_path`
- [ ] `repository-inventory` is version 1.1.0 and `solution-discovery`'s `^1.0.0` still matches
- [ ] `solution-discovery` registers with `adapter_type: process` and
      `phase0-repository-discovery` validates **without any YAML change**
- [ ] Engine resolves the `repository-inventory` input, and the pre-invoke version
      re-check fires — verify by temporarily setting `solution-discovery`'s range to `^2.0.0` and
      confirming the run fails with a version mismatch, then reverting
- [ ] The script runs standalone: `Get-Content sample-context.json | python steps/step-002-solution-discovery/main.py`
- [ ] Multi-project solution parses, with membership recorded
- [ ] A standalone project on disk but in no solution is flagged `is_standalone`
- [ ] A project referenced by two solutions has `solution_membership_count = 2` and
      counts once toward `shared_project_count`
- [ ] A `.sln` entry pointing at a missing file yields `resolution_status: unresolved`
      and increments `missing_project_count`
- [ ] A `<ProjectReference>` resolving outside the repository root yields
      `external_repository`
- [ ] Legacy and SDK-style projects both parse, with `project_format` correct
- [ ] A `.sqlproj` or `.dtproj` is recorded with the right `structural_type`, not skipped
- [ ] A known non-.NET project type (e.g. `.dcproj`) is recorded with
      `parse_status: success`, counted in `out_of_scope_project_count`, and does not
      degrade `scan_status`
- [ ] A genuinely unrecognised `*proj` extension is recorded with
      `parse_status: out_of_scope`, counted in `unknown_project_count`, and does not
      degrade `scan_status`
- [ ] A malformed file with a known .NET extension is counted in
      `failed_parse_count` with `parse_status: failed`, drives `scan_status: partial`,
      and the scan continues
- [ ] Multi-targeting project records all frameworks, with a warning explaining the
      chosen family
- [ ] A UTF-16 or BOM-prefixed project file parses
- [ ] Rescan replaces all `solution-discovery` rows without duplicates
- [ ] Two runs over unchanged input produce identical artifact checksums
- [ ] `git status` in the scanned repository is clean afterwards
- [ ] A repository with no .NET projects completes cleanly rather than failing
- [ ] Applications and Patterns cards still show `—`
- [ ] The script does not import from `backend.app`
- [ ] `solution-project-inventory` is registered and produced at `2.0.0` — the
      major bump required when `unsupported_project_count` was removed — and
      `phase0-repository-discovery` still validates, since nothing yet consumes
      this artifact
