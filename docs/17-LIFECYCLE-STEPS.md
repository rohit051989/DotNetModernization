# 17 — Lifecycle Step Register

The canonical list of lifecycle steps. **This file is the source of truth for step
names, numbers, owners and viewpoints.** Register steps from here, not from memory.

**Version 2.1 — 36 steps.** v2.1 inserts `dependency-assessment` as step 6; steps 6–35 of v2.0
became 7–36, slugs unchanged (see *Renumbering and slug stability*).

**Version 2.0 — 35 steps, revised from 51.** The reduction comes from the conversion
model in `28-CONVERSION-MODEL.md`: Track A's transformation steps collapse into two
generic conversion steps, and target-state governance and accelerator binding move out
of the lifecycle into the catalog and conversion-approach UIs. Two discovery steps were
added at the delivery team's request.

---

## Owner codes

| Code | Owner | Meaning |
|---|---|---|
| `P` | Platform (deterministic) | Our code. Reproducible and auditable, no LLM in the path |
| `S` | Custom skill / sub-agent | LLM-based capability for judgment work |
| `H` | Human | Explicit decision or review gate, tier-routed where noted |

The former `C` (Copilot engine) code is retired as a *step* owner. An engine is now an
`invocation.type` on a conversion approach, alongside `python`, `process`, `skill` and
`http` — chosen per approach rather than baked into the lifecycle.

Combined codes such as `P + S` mean shared authorship within one step. Store the
combined string verbatim in `wf_step_registrations.owner_code`.

---

## Jobs

| Job | Steps | Scope | Status |
|---|---|---|---|
| `phase0-repository-discovery` | 1 – 9 | Per repository | **Defined** |
| `phase0-estate-consolidation` | 10 – 12 | Per engagement | **Defined** |
| `trackA-application` | 13 – 27 | Per application | Deferred |
| `trackB-wave` | 28 – 36 | Per wave | Deferred |

---

## Phase 0 — Repository discovery (steps 1–9, per repository)

| # | step_name | Display name | Owner | Viewpoint | Notes |
|---|---|---|---|---|---|
| 1 | `repository-ingest` | Repository ingest & inventory creation | `P` | DEVELOPMENT | Register, verify path, resolve git metadata, size and language metrics |
| 2 | `solution-discovery` | Solution & project discovery | `P` | DEVELOPMENT | Parse solution and project files; classify project, library, test |
| 3 | `application-fingerprinting` | Application fingerprinting | `P` | DEVELOPMENT | Emit all registered signals with evidence. Extract-then-match: knows nothing about the catalog |
| 4 | `entry-point-inventory` | Entry point inventory | `P` | FUNCTIONAL | **New.** The application's inbound surface: HTTP routes and verbs, SOAP operations and bindings, gRPC services, message consumers, scheduled handlers, `Main` methods, `BackgroundService` implementations. Feeds contract snapshot, test generation and risk scoring |
| 5 | `outbound-invocation-inventory` | Outbound invocation inventory | `P` | CONTEXT | **New.** Everything this code calls: HTTP and gRPC clients, SOAP service references **with binding type**, databases by connection name and provider, message producers, file shares, SMTP. Each carries a Linux-compatibility verdict where determinable. NetTcp SOAP bindings are the canonical blocker |
| 6 | `dependency-assessment` | Dependency upgrade assessment | `P` | DEVELOPMENT | **New in v2.1.** For every direct NuGet package: the latest version supporting the target framework, from the client's own feeds first; deprecated, vulnerable and not-approved flags; semver plus API-diff classification of safe versus breaking, with the call sites that break. Emits signals, so item detection picks dependency upgrades up as ordinary occurrences. See `30-STEP-006-DEPENDENCY-ASSESSMENT.md` |
| 7 | `item-detection` | Catalog item detection & occurrence mapping | `P` | DEVELOPMENT | Match catalog items against signals; project matching signals' evidence into occurrence rows. Produces the work list, not a classification |
| 8 | `test-coverage-assessment` | Test coverage & CI maturity | `P` | DEVELOPMENT | Parse coverage reports and CI definitions. Gates characterization test generation |
| 9 | `risk-scoring-tier-assignment` | Risk scoring & review tier assignment | `P` | DEVELOPMENT | Deterministic rules over coverage, LOC, shared-library fan-out, entry-point count, external consumers, occurrence count and criticality |

Steps 4 and 5 are deliberately separate from step 3. Fingerprinting detects *presence*
— "this project has controllers". These produce an *inventory* — "`GET
/api/accounts/{id}` handled by `AccountsController.GetById`". Different shape,
different consumers.

---

## Phase 0b — Estate consolidation (steps 10–12, per engagement)

| # | step_name | Display name | Owner | Viewpoint | Notes |
|---|---|---|---|---|---|
| 10 | `unclaimed-signal-report` | Unclaimed signal report | `P` | DEVELOPMENT | Signals observed across the estate that no catalog item references, grouped by recurring shape. A report for catalog authors, not a gate |
| 11 | `dependency-and-context-map` | Dependency graph, context map & external endpoint register | `P` | CONTEXT | Project and package graph; external actors from step 5 aggregated across repositories. **The endpoint register is the deliverable** — if eight repos call one SOAP endpoint over NetTcp, that is one backend conversation, invisible from eight separate scans |
| 12 | `migration-wave-planning` | Migration wave planning | `P + H` | DEVELOPMENT | Topological grouping from the dependency graph; human confirms boundaries. Emits a C4 container view |

---

## Track A — Dev track (steps 13–27, per application)

| # | step_name | Display name | Owner | Viewpoint | Notes |
|---|---|---|---|---|---|
| 13 | `branch-baseline-record` | Branch creation & baseline SHA | `P` | DEVELOPMENT | |
| 14 | `baseline-verification` | Baseline verification | `P` | DEVELOPMENT | Build and test in a clean container **before** any change. Establishes attributability |
| 15 | `contract-snapshot` | Contract snapshot | `P` | FUNCTIONAL | OpenAPI for REST, WSDL for SOAP, from step 4's entry-point inventory. The parity baseline for step 22 |
| 16 | `characterization-test-generation` | Characterization test generation | `S` | FUNCTIONAL | Conditional on step 8 coverage falling below threshold |
| 17 | `work-list-assembly` | Work list assembly & dry run | `P` | DEVELOPMENT | **New.** Join occurrences to engagement decisions to conversion approaches. Dry-run every approach to produce diffs. Flags `awaiting_decision` and `awaiting_approach` rows. This is the migration plan |
| 18 | `plan-approval-gate` | Plan approval gate | `H` | — | Tier-conditional. The dry-run work list **is** the plan |
| 19 | `application-scope-conversion` | Application-scope conversions | `P` | DEVELOPMENT | Runs first. One invocation per project per item. Includes containerization, OCP4 manifests and CI/CD pipeline changes — anything creating files in the repository |
| 20 | `occurrence-scope-conversion` | Occurrence-scope conversions | `P` | DEVELOPMENT | Per occurrence or batched per the approach's `batching` declaration |
| 21 | `independent-verification` | Independent build, test & scan verification | `P` | DEVELOPMENT | Clean CI. Build, unit and integration tests, characterization replay, Linux compatibility, security and vulnerability scans. **The engine reporting its own success is not verification** |
| 22 | `contract-parity-verification` | Contract parity verification | `P` | FUNCTIONAL | Diff post-migration OpenAPI or WSDL against step 14, with breaking/non-breaking classification. Separate from step 20 because it is the headline consumer-impact evidence |
| 23 | `evidence-bundle-assembly` | Evidence bundle assembly | `P + S` | DEVELOPMENT | Platform assembles the facts; skill writes the narrative only |
| 24 | `pr-creation` | PR creation | `P + S` | DEVELOPMENT | One commit per conversion execution, so the PR reads as named remediations |
| 25 | `code-review` | Code review | `H` | — | Tier-routed |
| 26 | `feedback-capture` | Feedback capture | `P` | DEVELOPMENT | Tag corrections by item, approach and error category |
| 27 | `merge-version-record` | Merge, version record, dashboard update | `P` | DEVELOPMENT | Record approach versions used per application |

---

## Track B — DevOps track (steps 28–36, per wave)

| # | step_name | Display name | Owner | Viewpoint | Notes |
|---|---|---|---|---|---|
| 28 | `wave-readiness-check` | Wave readiness check | `P` | DEPLOYMENT | |
| 29 | `container-image-build-push` | Image build & registry push | `P` | DEPLOYMENT | Build files were generated in step 19 |
| 30 | `container-smoke-test` | Container smoke test | `P` | DEPLOYMENT | Startup, health endpoints, one representative call |
| 31 | `deploy-non-production-ocp4` | Deploy to non-production OCP4 | `P` | DEPLOYMENT | Whole wave together so inter-application dependencies resolve |
| 32 | `cross-application-integration-testing` | Cross-application integration testing | `P` | OPERATIONAL | The verification impossible per application |
| 33 | `consumer-regression-verification` | Consumer regression verification | `P` | FUNCTIONAL | Consumers exercised against pre-migration contracts |
| 34 | `performance-resource-baseline` | Performance & resource baseline | `P` | OPERATIONAL | Sets OCP4 requests and limits |
| 35 | `release-approval` | Release approval | `H` | — | Wave-level go/no-go on accumulated evidence |
| 36 | `production-cutover` | Production cutover, parallel run & rollback | `P + H` | OPERATIONAL | |

---

## Renumbering and slug stability

### v2.1: dependency-assessment inserted at 6

`dependency-assessment` is a new step 6, between the inventories and item detection, so
that its findings are signals item detection matches like any other (docs/30 Part A).
Every v2.0 step numbered 6 or higher moves up by one — `item-detection` is 7,
`production-cutover` is 36 — and **no slug changes**, so execution history and job
definitions bind exactly as before. Only `lifecycle_step_no` and the job descriptions
that quote number ranges changed.

### v2.0

`lifecycle_step_no` was renumbered 1–35. **Where a step survives unchanged, its
`step_name` slug is unchanged** — `wf_step_executions` history references step names,
so renumbering alone preserves linkage.

Four slugs change because the step genuinely does something different. Follow the
insert-new, repoint, soft-delete-old pattern so historical executions stay resolvable:

| Old slug | New slug | Why |
|---|---|---|
| `pattern-classification` | `item-detection` | Produces occurrences, not a classification |
| `pattern-discovery-clustering` + `pattern-validation` | `unclaimed-signal-report` | Merged; no longer a gate |
| `independent-build-test-verification` | `independent-verification` | Absorbed two other steps |
| `dependency-graph-construction` | `dependency-and-context-map` | Scope extended |

### Old to new mapping (v1 → v2.0 numbering; add 1 to any v2.0 number from 6 up for v2.1)

| Old | New | Old | New |
|---|---|---|---|
| 1 | 1 | 27 | 18 or 19 |
| 2 | 2 | 28 | 19 |
| 3 | 3 | 29 | 19 |
| 4 | 6 | 30 | 19 |
| 5, 6 | 9 | 31 | 20 |
| 7 | 10 | 32 | 21 |
| 8 | *retired* | 33 | 20 |
| 9 | 7 | 34 | 20 |
| 10 | 8 | 35 | 18 |
| 11 | *retired* | 36 | 22 |
| 12 | 11 | 37 | 23 |
| 13, 14, 15 | *retired* | 38 | 24 |
| 16 | *retired* | 39 | 25 |
| 17 | 12 | 40 | 26 |
| 18 | 13 | 41 | 27 |
| 19 | 14 | 42 | 18 |
| 20 | 15 | 43 | 28 |
| 21 | *retired* | 44 | 29 |
| 22, 24 | 17 | 45 | 18 |
| 23 | 18 or 19 | 46 – 51 | 30 – 35 |
| 25, 26 | 18 or 19 | | |
| — | 4, 5, 16 *(new)* | | |

Old steps 23 and 25–30 map to 18 or 19 depending on the item's scope, which is the
point of the collapse.

---

## Retired from the lifecycle

Not deleted — moved somewhere better.

| Old step | Where it went |
|---|---|
| 8 — Impact map generation | **The work list is the impact map.** Same data, better shape |
| 11 — Inventory dashboard population | A read view over platform tables. Never really a step |
| 13, 14, 15 — Target state governance | **Catalog UI.** Decisions captured per item per engagement, upfront. An occurrence with no decision sits in the work list as `awaiting_decision` |
| 16 — Accelerator binding | **Conversion approach registry**, with its own UI, maintained by the delivery team |
| 21 — Guardrail playbook generation | Guardrails are conversion approach configuration |

---

## Ownership summary

| Owner | Count | Steps |
|---|---|---|
| `P` | 28 | 1–11, 13, 14, 15, 17, 19, 20, 21, 22, 26, 27, 28–34 |
| `H` | 3 | 18, 25, 35 |
| `P + H` | 2 | 12, 36 |
| `P + S` | 2 | 23, 24 |
| `S` | 1 | 16 |

Totals to 36. (Step 6 is `P`; its advisory explanation of breaking changes is an
optional `S` sub-task inside the step, not a separate step.)

**No step is owned by an external engine.** Engine choice is a property of a
conversion approach, selected per item and resolution. That is what makes the platform
engine-agnostic in practice rather than in principle — swapping Copilot for a skill on
one item changes a registry row, not the lifecycle.

Human gates total three outright plus two shared: plan approval (18), code review
(25) and release approval (35), with wave boundaries (12) and production cutover (36)
shared with the platform.

---

## Registration rules

- `step_name` values above are **fixed**. Job definition YAML binds to them
- Every step registers as a stub initially: `adapter_type: stub`,
  `exit_status: NOT_IMPLEMENTED`, empty `consumes` and `produces`,
  `implementation_status: stub`
- Replacing a stub is a registration update only — no job definition change, provided
  `consumes` and `produces` are unchanged
- Renaming a `step_name` after registration breaks every job definition binding to it.
  Register the new name, update affected definitions, then deprecate the old

Viewpoints are derived per `25-STANDARDS-AND-VIEWPOINTS.md` Part A2 and drive the
coverage report. Gate steps carry no viewpoint — they are governance, not analysis.
