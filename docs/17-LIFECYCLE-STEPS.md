# 17 — Lifecycle Step Register

The canonical list of lifecycle steps. **This file is the source of truth for step
names, numbers, owners and viewpoints.** Register steps from here, not from memory.

| Version | Change |
|---|---|
| **2.5** | Inserts `dependency-hierarchy` as step 7, after `dependency-assessment` (`37-DEPENDENCY-HIERARCHY.md`). Steps 7–38 of v2.4 became 8–39, slugs unchanged; 39 steps |
| 2.4 | Inserts `conversion-preparation` as step 11, the last step of the per-repository discovery job (`36-COPILOT-ENHANCED-CONVERSION.md` Part N). Steps 11–37 of v2.3 became 12–38, slugs unchanged; 38 steps. `independent-verification` is implemented by the conversion verifier, in its own job `conversion-verification` |
| 2.3 | Inserts `impact-analysis` as step 9 (`33-IMPACT-ANALYSIS.md`). Steps 9–36 of v2.2 became 10–37, slugs unchanged; 37 steps. Cross-references in step notes corrected |
| 2.2 | Documentation revision. **No change to steps, numbers or slugs.** Corrects stale cross-references, updates descriptions to what was built, adds implementation status and spec pointers, and rewrites the mapping table as v1 → v2.2 directly |
| 2.1 | Inserts `dependency-assessment` as step 6. Steps 6–35 of v2.0 became 7–36, slugs unchanged |
| 2.0 | 35 steps, revised from 51. Track A's transformation steps collapse into two generic conversion steps; target-state governance and accelerator binding move out of the lifecycle |
| 1.0 | The original 51-step lifecycle |

The reduction in v2.0 comes from the item and conversion model in
`28-ITEM-AND-CONVERSION-MODEL.md`.

---

## Implementation status

**Authoritative status is `wf_step_registrations.implementation_status`.** This table is a
snapshot for orientation and will drift; check the registry when it matters.

| Status | Steps |
|---|---|
| **Implemented** | 1, 2, 3, 4, 5, 6, 7, 8, 9 (phase 1 of 3), 10 (deterministic; the LLM residue is deferred), 12, 14, 24 (the conversion verifier: build, tests, canary and re-discovery; no security scan yet) |
| **Stub** | 11, 13, 15, and the rest of Track A (16–30) and all of Track B (31–39) |

The per-repository discovery job runs real work through `impact-analysis`. `risk-scoring-tier-assignment` is a stub within
it, completing as `NOT_IMPLEMENTED` under `stub_policy: continue`. Its last step, `conversion-preparation`, prepares the
repository's conversion, and never fails the run.

### Spec for each implemented or specified step

| Step | Spec |
|---|---|
| 1 | `13-REPOSITORY-INGEST.md`, `15-REPOSITORY-INGEST-UI.md` |
| 2 | `19-SOLUTION-DISCOVERY.md` |
| 3 | `21-APPLICATION-FINGERPRINTING.md` |
| 4 | `29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md` Part B |
| 5 | `29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md` Part C |
| 6 | `30-DEPENDENCY-ASSESSMENT.md` |
| 7 | `37-DEPENDENCY-HIERARCHY.md` |
| 8 | `28-ITEM-AND-CONVERSION-MODEL.md` Parts C–G |
| 9 | `32-TEST-COVERAGE-ASSESSMENT.md` |
| 10 | `33-IMPACT-ANALYSIS.md` |
| 12 | `36-COPILOT-ENHANCED-CONVERSION.md` Part N |
| 14 | `31-DEPENDENCY-AND-CONTEXT-MAP.md` (written when this step was 11; the file keeps its name) |
| 22, 23 | `28-ITEM-AND-CONVERSION-MODEL.md` Parts I–O |
| 24 | `36-COPILOT-ENHANCED-CONVERSION.md` Parts E and N (the verifier) |
| 21, 28, 38 | Gate machinery: the `validation_queue` from `27-PATTERN-VALIDATION.md` Parts A–B. That step was retired; its queue survived as shared gate infrastructure |

---

## Owner codes

| Code | Owner | Meaning |
|---|---|---|
| `P` | Platform (deterministic) | Our code. Reproducible and auditable, no LLM in the path |
| `S` | Custom skill / sub-agent | LLM-based capability for judgment work |
| `H` | Human | Explicit decision or review gate, tier-routed where noted |

The former `C` (Copilot engine) code is retired as a *step* owner. An engine is now an
`invocation.type` on a conversion approach, alongside `python`, `process`, `skill` and
`http` — chosen per approach rather than baked into the lifecycle. A database constraint
rejects `C` on any non-deprecated registration.

Combined codes such as `P + S` mean shared authorship within one step. Store the
combined string verbatim in `wf_step_registrations.owner_code`.

---

## Jobs

| Job | Steps | Scope | Status |
|---|---|---|---|
| `phase0-repository-discovery` | 1 – 12 | Per repository | **Defined, active** |
| `phase0-estate-consolidation` | 13 – 15 | Per engagement | **Defined, active** |
| `conversion-verification` | 24 | Per conversion | **Defined, active**: a person starts it from the repository's Conversion section |
| `trackA-application` | 16 – 30 | Per application | Deferred |
| `trackB-wave` | 31 – 39 | Per wave | Deferred |

The two Phase 0 jobs answer different questions. The per-repository job asks *what is in
this repository*; the estate job asks *what is in the estate* — things no single repository
can answer, such as eight repositories calling the same backend. The estate job runs on a
partial estate and reports its own coverage.

---

## Phase 0 — Repository discovery (steps 1–12, per repository)

| # | step_name | Display name | Owner | Viewpoint | Notes |
|---|---|---|---|---|---|
| 1 | `repository-ingest` | Repository ingest & inventory creation | `P` | DEVELOPMENT | Register, verify path, resolve git metadata, size and language metrics. Folders not under source control are supported |
| 2 | `solution-discovery` | Solution & project discovery | `P` | DEVELOPMENT | Parse solution and project files. Records each project's structural type, SDK, output type and target framework, with the source of each — declared, inherited from `Directory.*.props`, or an SDK default. Project ids are derived, so they are stable across rescans. **Role is not decided here**; it is computed by `item-detection` |
| 3 | `application-fingerprinting` | Application fingerprinting | `P` | DEVELOPMENT | Emit all registered signals with evidence. Extract-then-match: knows nothing about the catalog. Also emits SARIF for external interoperability |
| 4 | `entry-point-inventory` | Entry point inventory | `P` | FUNCTIONAL | The application's inbound surface across nineteen kinds, from HTTP routes and WCF operations to Global.asax hooks and hosted services. Each entry carries `auth_declared`, `origin` (application or framework) and `entry_class` (request or lifecycle). Publishes a capability manifest, so a pattern it does not detect is a visible gap rather than a silent miss. Feeds contract snapshot, test generation and risk |
| 5 | `outbound-invocation-inventory` | Outbound invocation inventory | `P` | CONTEXT | Everything this code calls: HTTP and gRPC clients, SOAP clients **with binding and security mode**, databases, message brokers, caches, secret stores, file shares, SMTP, LDAP. Endpoints normalised with credentials stripped before storage. One invocation per logical endpoint, with a Linux verdict per environment binding. Unused clients are recorded but not counted |
| 6 | `dependency-assessment` | Dependency upgrade assessment | `P` | DEVELOPMENT | For every direct NuGet package: the latest version supporting the target framework, from the client's own feeds first and nuget.org only as fallback; deprecated, vulnerable and not-approved flags; semver plus API-diff classification of safe versus breaking, with confirmed or ambiguous call sites. Emits signals, so item detection picks dependency upgrades up as ordinary occurrences |
| 7 | `dependency-hierarchy` | Dependency hierarchy | `P` | DEVELOPMENT | Each repository's dependency graph: projects (application, library, test or other; framework; SDK-style or legacy), packages (internal or external, with versions; for an internal one, the repository that produces it where estate consolidation knows it) and assembly references, with every edge's kind — ProjectReference, PackageReference, central package management, packages.config, assembly reference, and a package's own dependencies from the restored assets file or the feed's metadata. A graph, not a tree: each node once, each edge once; cycles recorded, depth and size bounded, anything unresolved not checked with the reason. After `dependency-assessment`, whose classification of packages it reads. Feeds the repository page's Dependency graph tab |
| 8 | `item-detection` | Catalog item detection & occurrence mapping | `P` | DEVELOPMENT | Computes each project's role, then matches ready catalog items against signals and metadata, projecting evidence into occurrence rows. Reports `found`, `checked_absent` or `not_checked` — **never `checked_absent` where the scan could not have seen the answer**, including where metadata an item reads is unknown. Carries call-site certainty into the work list |
| 9 | `test-coverage-assessment` | Test coverage & CI maturity | `P` | DEVELOPMENT | Test discovery and classification, source-to-test mapping, three buckets per source file, existing coverage reports, CI maturity. Unknown coverage carries a reason and is never 0%. Its mapping supplies `impact-analysis`'s impacted test files. Gates `characterization-test-generation` |
| 10 | `impact-analysis` | Impact analysis | `P` | DEVELOPMENT | Per work item, every file its conversion touches and what happens to each — update, rewrite, delete, create, review — from per-resolution impact rules in the catalog, with certainty and a traversal path per file. The default resolution always, and the chosen one where decided; hotspots and conflicts across work items. Structural only: client impact is added by `dependency-and-context-map` |
| 11 | `risk-scoring-tier-assignment` | Risk scoring & review tier assignment | `P` | DEVELOPMENT | Deterministic rules over coverage, LOC, `impact-analysis`'s blast radius, shared-library fan-out, **request** entry-point count, external consumers, occurrence count and criticality. Lifecycle hooks must not inflate the count. **A hosted or Windows service with zero request entry points must not read as low risk** — a poll-loop worker has exactly that shape |
| 12 | `conversion-preparation` | Conversion preparation | `P` | DEVELOPMENT | The repository's next conversion, ready for an engine: a branch and worktree from the baseline, the package changes that need no code applied and committed (each building and passing the baseline's tests), the engine's inputs under `.github`, and the runbook. A rescan refreshes a conversion not run yet; one that has been run is left, and a person starts the next. A baseline that does not build or pass its tests skips the package step, which goes to the engine as instructions. **Never fails the discovery run**: what went wrong is recorded on the conversion |

`entry-point-inventory` and `outbound-invocation-inventory` are deliberately separate from `application-fingerprinting`. Fingerprinting detects *presence*
— "this project has controllers". These produce an *inventory* — "`GET
/api/accounts/{id}` handled by `AccountsController.GetById`". Different shape,
different consumers.

`dependency-assessment` sits **before** item detection so that its findings are signals, matched like any
other. Placed after, dependency upgrades would need a parallel pipeline to reach the work
list.

`dependency-hierarchy` sits **after** `dependency-assessment`, whose classification of each declared package (its
version, outcome and findings) it reads, and before item detection, which does not depend on it.

---

## Phase 0b — Estate consolidation (steps 13–15, per engagement)

| # | step_name | Display name | Owner | Viewpoint | Notes |
|---|---|---|---|---|---|
| 13 | `unclaimed-signal-report` | Unclaimed signal report | `P` | DEVELOPMENT | Signals observed across the estate that no catalog item references, grouped by recurring shape. A report for catalog authors, not a gate |
| 14 | `dependency-and-context-map` | Dependency graph, context map & external endpoint register | `P` | CONTEXT | Four outputs. **The external endpoint register is the deliverable**: `outbound-invocation-inventory`'s invocations grouped by host, with `requires_backend_change` marking calls only the endpoint's owner can fix, and annotations that turn it into a conversation tracker. Also the package estate view, the cross-repository dependency graph with shared libraries and cycles, and a C4 context map. Reconciles `entry-point-inventory`'s per-repository origin decisions without rewriting its rows. Adds `impact-analysis`'s **client** impact at the end of each run, from its integration edges |
| 15 | `migration-wave-planning` | Migration wave planning | `P + H` | DEVELOPMENT | Topological grouping from `dependency-and-context-map`'s dependency graph; shared libraries first, cycles as single units. Human confirms boundaries. Emits a C4 container view |

---

## Track A — Dev track (steps 16–30, per application)

| # | step_name | Display name | Owner | Viewpoint | Notes |
|---|---|---|---|---|---|
| 16 | `branch-baseline-record` | Branch creation & baseline SHA | `P` | DEVELOPMENT | |
| 17 | `baseline-verification` | Baseline verification | `P` | DEVELOPMENT | Build and test in a clean container **before** any change. Establishes attributability |
| 18 | `contract-snapshot` | Contract snapshot | `P` | FUNCTIONAL | OpenAPI for REST, WSDL for SOAP, from `entry-point-inventory`. The parity baseline for `contract-parity-verification` |
| 19 | `characterization-test-generation` | Characterization test generation | `S` | FUNCTIONAL | Conditional on `test-coverage-assessment` coverage falling below threshold. Targets request entry points only — never lifecycle hooks |
| 20 | `work-list-assembly` | Work list assembly & dry run | `P` | DEVELOPMENT | Join occurrences to engagement decisions to conversion approaches. Dry-run every approach to produce diffs. Flags `awaiting_decision` and `awaiting_approach` rows. This is the migration plan |
| 21 | `plan-approval-gate` | Plan approval gate | `H` | — | Tier-conditional. The dry-run work list **is** the plan |
| 22 | `application-scope-conversion` | Application-scope conversions | `P` | DEVELOPMENT | Runs first. One invocation per project per item. Includes containerization, OCP4 manifests and CI/CD pipeline changes — anything creating files in the repository |
| 23 | `occurrence-scope-conversion` | Occurrence-scope conversions | `P` | DEVELOPMENT | Per occurrence or batched per the approach's `batching` declaration. Includes package upgrades and their call-site fixes from `dependency-assessment` |
| 24 | `independent-verification` | Independent build, test & scan verification | `P` | DEVELOPMENT | Clean CI. Build, unit and integration tests, characterization replay, Linux compatibility, security and vulnerability scans. **The engine reporting its own success is not verification** |
| 25 | `contract-parity-verification` | Contract parity verification | `P` | FUNCTIONAL | Diff post-migration OpenAPI or WSDL against `contract-snapshot`, with breaking/non-breaking classification. Separate from `independent-verification` because it is the headline consumer-impact evidence |
| 26 | `evidence-bundle-assembly` | Evidence bundle assembly | `P + S` | DEVELOPMENT | Platform assembles the facts; skill writes the narrative only |
| 27 | `pr-creation` | PR creation | `P + S` | DEVELOPMENT | One commit per conversion execution, so the PR reads as named remediations |
| 28 | `code-review` | Code review | `H` | — | Tier-routed |
| 29 | `feedback-capture` | Feedback capture | `P` | DEVELOPMENT | Tag corrections by item, approach and error category |
| 30 | `merge-version-record` | Merge, version record, dashboard update | `P` | DEVELOPMENT | Record approach versions used per application |

### Two engine requirements before Track A

Found by crash-testing the per-step commit engine; both must be met before any step that
writes to a repository is built:

- **Conversions must be safe to run twice.** A step rerun after a crash reapplies its work.
  The `idempotent` field on conversion approaches anticipates this
- **A crashed engine must terminate the step's child processes.** Today a child process a
  step launched keeps running after the engine dies and can still write. Use a Windows job
  object so a step's processes die with it. Otherwise git can hold commits the database has
  no record of

---

## Track B — DevOps track (steps 31–39, per wave)

| # | step_name | Display name | Owner | Viewpoint | Notes |
|---|---|---|---|---|---|
| 31 | `wave-readiness-check` | Wave readiness check | `P` | DEPLOYMENT | |
| 32 | `container-image-build-push` | Image build & registry push | `P` | DEPLOYMENT | Build files were generated in `application-scope-conversion` |
| 33 | `container-smoke-test` | Container smoke test | `P` | DEPLOYMENT | Startup, health endpoints, one representative call |
| 34 | `deploy-non-production-ocp4` | Deploy to non-production OCP4 | `P` | DEPLOYMENT | Whole wave together so inter-application dependencies resolve |
| 35 | `cross-application-integration-testing` | Cross-application integration testing | `P` | OPERATIONAL | The verification impossible per application |
| 36 | `consumer-regression-verification` | Consumer regression verification | `P` | FUNCTIONAL | Consumers exercised against pre-migration contracts |
| 37 | `performance-resource-baseline` | Performance & resource baseline | `P` | OPERATIONAL | Sets OCP4 requests and limits |
| 38 | `release-approval` | Release approval | `H` | — | Wave-level go/no-go on accumulated evidence |
| 39 | `production-cutover` | Production cutover, parallel run & rollback | `P + H` | OPERATIONAL | |

---

## Renumbering and slug stability

`lifecycle_step_no` is ordering only. **`step_name` slugs are what job definitions and
execution history bind to**, so a slug is never changed in place. Where a step's meaning
genuinely changed, the old slug was soft-deleted and a new one inserted, so historical
executions stay resolvable.

| Old slug | New slug | Why |
|---|---|---|
| `pattern-classification` | `item-detection` | Produces occurrences, not a classification |
| `pattern-discovery-clustering` + `pattern-validation` | `unclaimed-signal-report` | Merged; no longer a gate |
| `api-contract-snapshot` | `contract-snapshot` | Renamed in v2.0 |
| `independent-build-test-verification` | `independent-verification` | Absorbed two other steps |
| `dependency-graph-construction` | `dependency-and-context-map` | Scope extended |

New job definitions cannot reference a retired step; validation fails with
`STEP_RETIRED`, naming the successor.

### v1 → v2.5 mapping

Direct from the original 51 steps to today's numbering.

| v1 | Was | Now |
|---|---|---|
| 1 | repository ingest | 1 |
| 2 | solution discovery | 2 |
| 3 | application fingerprinting | 3 |
| 4 | pattern classification | 8 |
| 5, 6 | pattern discovery, pattern validation | 13 |
| 7 | dependency graph construction | 14 |
| 8 | impact map generation | *retired* |
| 9 | test coverage assessment | 9 |
| 10 | risk scoring | 11 |
| 11 | inventory dashboard population | *retired* |
| 12 | migration wave planning | 15 |
| 13, 14, 15 | target state governance | *retired* |
| 16 | accelerator binding | *retired* |
| 17 | branch & baseline | 16 |
| 18 | baseline verification | 17 |
| 19 | API contract snapshot | 18 |
| 20 | characterization test generation | 19 |
| 21 | guardrail playbook generation | *retired* |
| 22, 24 | plan approval gate, plan validation | 21 |
| 23 | engine assessment | 22 or 23 |
| 25 | framework retarget & package upgrade | 22 or 23 — package discovery is now step 6 |
| 26, 27 | build-fix loop, breaking-change remediation | 22 or 23 |
| 28, 29, 30 | Windows-to-Linux, config externalisation, logging & health | 23 |
| 31, 33, 34 | independent verification, characterization execution, Linux & security scan | 24 |
| 32 | contract parity verification | 25 |
| 35 | container build file generation | 22 |
| 36 | evidence bundle | 26 |
| 37 | PR creation | 27 |
| 38 | code review | 28 |
| 39 | feedback capture | 29 |
| 40 | merge & version record | 30 |
| 41 | wave readiness | 31 |
| 42 | OCP4 manifest generation | 22 |
| 43 | image build & push | 32 |
| 44 | container smoke test | 33 |
| 45 | CI/CD pipeline update | 22 |
| 46 – 51 | non-prod deploy through production cutover | 34 – 39 |

**New since v1:** `entry-point-inventory`, `outbound-invocation-inventory` and `work-list-assembly`
in v2.0; `dependency-assessment` in v2.1; `impact-analysis` in v2.3; `conversion-preparation` in v2.4; `dependency-hierarchy` in v2.5 — not v1's
retired impact map revived, but impact per work item and resolution, which the work list
alone does not give.

"22 or 23" is the point of the collapse: the same kind of work runs in whichever conversion
step matches its item's scope.

---

## Retired from the lifecycle

Not deleted — moved somewhere better. Numbers below are **v1**.

| v1 step | Where it went |
|---|---|
| 8 — Impact map generation | **The work list is the impact map.** Same data, better shape. v2.3's `impact-analysis` adds what the work list lacks: each work item's full blast radius per resolution |
| 11 — Inventory dashboard population | A read view over platform tables. Never really a step |
| 13, 14, 15 — Target state governance | **Catalog UI.** Decisions captured per item per engagement, upfront. An occurrence with no decision sits in the work list as `awaiting_decision` |
| 16 — Accelerator binding | **Conversion approach registry**, with its own UI, maintained by the delivery team |
| 21 — Guardrail playbook generation | Guardrails are conversion approach configuration |

---

## Ownership summary

| Owner | Count | Steps |
|---|---|---|
| `P` | 31 | 1–14, 16, 17, 18, 20, 22, 23, 24, 25, 29, 30, 31–37 |
| `H` | 3 | 21, 28, 38 |
| `P + H` | 2 | 15, 39 |
| `P + S` | 2 | 26, 27 |
| `S` | 1 | 19 |

Totals to 39. `dependency-assessment` is `P`; its optional advisory explanation of breaking changes is an
`S` sub-task inside the step, not a separate step.

**No step is owned by an external engine.** Engine choice is a property of a
conversion approach, selected per item and resolution. That is what makes the platform
engine-agnostic in practice rather than in principle — swapping Copilot for a skill on
one item changes a registry row, not the lifecycle.

Human gates total three outright plus two shared: `plan-approval-gate`, `code-review`
and `release-approval`, with wave boundaries (`migration-wave-planning`) and `production-cutover`
shared with the platform.

---

## Registration rules

- `step_name` values above are **fixed**. Job definition YAML binds to them
- Every step registers as a stub initially: `adapter_type: stub`,
  `exit_status: NOT_IMPLEMENTED`, empty `consumes` and `produces`,
  `implementation_status: stub`
- Replacing a stub needs no job definition change **only if `consumes` and `produces` are
  unchanged**. A step that gains inputs must have them wired in the job definition, and
  validation rule 9 (`UNWIRED_INPUT`) enforces it. Never make an input optional to avoid
  wiring it — that works around the tripwire rather than satisfying it
- Renaming a `step_name` after registration breaks every job definition binding to it.
  Register the new name, update affected definitions, then deprecate the old
- A reseed must never revert an implemented step to stub, nor overwrite a catalog edit made in
  the UI (CLAUDE.md rule 10; 28-ITEM Part V)
- **An implemented step's registration is a file in the repository** (CLAUDE.md rule 11):
  `steps/<step>/registration/<step-name>.json` for an external step, or
  `backend/app/steps/<step-name>.registration.json` for a `python` adapter. Job definitions
  are `backend/app/jobs/<job-name>.yaml`.
  - **Seeding.** `python -m app.seed` registers both after the lifecycle stubs
    (`app/seed/platform.py`). A missing row or stub is registered, and a newer file upgrades
    the row. A machine ahead of the repository is never downgraded but is reported, and a
    same-version difference is reported as a conflict and left as is.
  - **Proving it.** `python -m app.seed.reproduce` creates a scratch schema in the same database and
    bootstraps it as a new environment: migrate, then `python -m app.seed`, which takes the
    catalog from the committed export (01-ENVIRONMENT-SETUP.md section 9). It then compares
    it with this machine:
    - step registrations and their adapters;
    - job definitions and the active version;
    - global step policies;
    - the signal registry and extractors;
    - the legacy and item catalogs.

    Client data and run history are not compared. Historical records are intentionally not
    reproduced and are not differences: retired registrations, superseded job versions, and
    soft-deleted catalog rows a bootstrap never creates. A clean run prints one line counting
    them, then "0 differences". Any difference fails the command (exit 1). `--verbose` lists
    the history and the seed output.
  - **The 2026-10-07 sweep.** Three implemented steps existed only in the database and were
    written to files: `repository-ingest`, `solution-discovery` and `item-detection`. `application-fingerprinting`'s
    had been written the round before.

Viewpoints are derived per `25-STANDARDS-AND-VIEWPOINTS.md` Part A2 and drive the
coverage report. Gate steps carry no viewpoint — they are governance, not analysis.
