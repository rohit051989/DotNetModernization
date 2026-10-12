# 34 — Conversion Architecture: Recipes, Units & Equivalence

**Status: Proposed.** Nothing this proposal adds is registered as a lifecycle step; Part L marks
the discovery additions that other work has built since, and "As built: the minimum" (before
the acceptance criteria) records the slice of C1, C4, E and F built to prove the unit loop. It amends
`28-ITEM-AND-CONVERSION-MODEL.md` Parts J–N and Track A of `17-LIFECYCLE-STEPS.md`. Both
documents are updated only once this proposal is accepted (Part N). The first worked recipe
is `35-RECIPE-WCF-SERVICE-REST.md`.

Conversion today is designed as **one approach per decision, one invocation, one commit**.
That is right for a Serilog sink and wrong for a WCF service. This document keeps everything
28 got right, and changes how a large conversion is broken down, executed and proven.

---

## Section index

| Part | Covers |
|---|---|
| A | Why: what the current design cannot do |
| B | Principles |
| C | Model changes: recipes, supporting items, anchors, units, slices, framework deltas |
| D | Target layout: in place or side by side |
| E | The unit loop: how a plan executes |
| F | Automation classes: deterministic, assisted, manual |
| G | Target contract design |
| H | Behaviour baseline and equivalence verification |
| I | Drift reconciliation |
| J | Approach certification |
| K | Lifecycle changes |
| L | Discovery additions |
| M | Engine requirements |
| N | Changes to 17, 28 and 33 on acceptance |
| O | Open questions |
| P | Impact: one producer per fact (catalog impact rules or the recipe's dry run) |
| — | Acceptance criteria |

---

## Part A — Why

28 models a conversion as `item → resolution → decision → approach → execution`, with
**one active approach per (item, resolution)**. Seven consequences, each visible on the WCF
sample (`sampleapps\WCF`) analysed in `MODERNIZATION-NET10-REST.md`:

| # | Gap | Evidence on the WCF sample |
|---|---|---|
| A1 | **A large conversion is one opaque invocation.** `wcf-service` is application scope, so its REST resolution is one approach, one invocation and one commit for the whole project | The REST move is ~15 distinct, mostly mechanical changes: 18 fault throw sites, 5 behaviour attributes, 1 identity read, 2 config reads, 3 client constructions, a host rewrite, per-environment config. Each can be small and checked on its own |
| A2 | **Verification comes too late to attribute failure.** `independent-verification` and `contract-parity-verification` run after every conversion, and 28 Part N makes rollback on a failed approach verification optional | A red build at `independent-verification` cannot name which of ~40 commits caused it |
| A3 | **Checks prove the edit, not the behaviour.** Check types are `file_contains`, `json_parses`, `shell`, `signal_absent` | Nothing shows `PlaceOrder` still rejects a missing product with the same fault |
| A4 | **Contract parity cannot diff across protocols.** `contract-parity-verification` diffs OpenAPI or WSDL against `contract-snapshot` | WSDL vs OpenAPI needs a declared mapping, and nobody designs or signs off the target contract |
| A5 | **No re-run against a moving legacy.** Side-by-side engagements keep legacy in production while the new stack is built | Fixes land in legacy after the baseline commit; nothing finds or re-applies them |
| A6 | **Progress is per item; delivery is per slice.** The work list is item × file | Clients move per operation group; "Product is proven, Order is next" cannot be expressed |
| A7 | **Approaches are trusted, not proven.** `draft → active` is a status flip | Nothing runs an approach on representative code before it touches a client repository |

The engine, adapters, gates, policy and observability are not the problem. **The conversion
model is.**

---

## Part B — Principles

Not open for re-litigation without a reason, in the spirit of 28 Part S.

| # | Principle | Meaning |
|---|---|---|
| B1 | **Small units, green at every commit** | A conversion is a sequence of units. Each unit is applied, checked, built and tested before it is committed. The branch never holds a red commit |
| B2 | **Deterministic first** | A codemod or template does the bulk. An LLM handles only what is left, under the same checks plus review. A human handles named exceptions |
| B3 | **Evidence of equivalence, not of edit** | A unit passes when the code still behaves the same, shown by replayed recordings, not when the expected text appears |
| B4 | **Re-runnable from a recorded legacy commit** | Every unit can be re-applied to a newer legacy commit. This is what makes a side-by-side parallel run safe |
| B5 | **The slice is the unit of delivery** | Plans, readiness and sign-off are per operation group, not per item |
| B6 | **Approaches are software** | An approach is proven on fixture repositories before it is `active`, and its success rate is tracked after |
| B7 | **Legacy is read-only in side-by-side layout** | No unit may write under the legacy root. Enforced like `allowed_paths` |
| B8 | **Unchanged from 28** | `allowed_paths`, one commit per execution, mandatory dry run, conversions never write platform tables, decisions as data |

---

## Part C — Model changes

```
catalog item ── resolution ── decision                       (28, unchanged)
                    │
                    └── recipe ── recipe steps ── approach      (new: C1)
                                      │
supporting items ── occurrences ── anchors                    (new: C2, C3)
                                      │
conversion plan ── slices ── units ── executions              (new: C4, C5)
```

### C1. Recipes

A **recipe** is the ordered set of approaches that carries out one resolution. It replaces
"one active approach per (item, resolution)".

**`conversion_recipes`**

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT` PK | e.g. `wcf-service-rest` |
| `version` | `TEXT` NOT NULL | Semver. Recorded on every plan |
| `item_id` / `resolution_id` | `TEXT` NOT NULL FK | The binding |
| `supported_layouts` | `JSONB` NOT NULL | Subset of `["in_place", "side_by_side"]` (Part D) |
| `blockers` | `JSONB` NOT NULL DEFAULT `'[]'` | Item ids whose presence on the project stops the recipe (e.g. `wcf-duplex-contract`) |
| `status` | `TEXT` NOT NULL | `draft`, `certified`, `active`, `deprecated`. `active` requires `certified` (Part J) |
| `owner_team`, `created_at`, `updated_at` | | |

Unique on `(item_id, resolution_id)` where `status = 'active'`.

**`conversion_recipe_steps`**

| Column | Type | Notes |
|---|---|---|
| `recipe_id`, `step_id` | `TEXT` PK | `step_id` e.g. `F05`, `S02` |
| `phase` | `TEXT` NOT NULL | `foundation` or `slice` (C5) |
| `approach_id` | `TEXT` NOT NULL FK | The approach that does the work |
| `targets` | `JSONB` NOT NULL | What the step iterates: a supporting item's occurrences, the project, or the slice's contract (C2) |
| `depends_on` | `JSONB` NOT NULL DEFAULT `'[]'` | Step ids within the recipe |
| `optional_when` | `TEXT` | A `when:` expression (`22-STEP-SEQUENCING-AND-POLICY.md` grammar). Skipped, not failed, when false |

A plain item keeps working as today: a **one-step recipe** wraps its approach. The Serilog
example in 28 Part O needs no change beyond that wrapper.

### C2. Supporting items

The targets of a recipe's steps are detected the same way as any item, as **supporting
items**: `catalog_items.kind = 'supporting'` with a `parent_item_id`.

- Detected by `item-detection` like any item. Occurrences, evidence and two-state readiness are
  unchanged.
- **No decision of their own.** Their decision is derived from the parent's decision, using
  28 Part U's coupling machinery with a new rule `supporting-follows-parent`.
- **Hidden from the decision UI.** Shown in the plan and work list under their parent.
- Example: `wcf-fault-throw` (each `throw new FaultException<T>(…)`), parent `wcf-service`.

This reuses detection, readiness and coupling instead of adding a second detection path.

### C3. Occurrence anchors

A codemod must hit exactly the code that was detected, and must know when that code has
changed since. File and line are not enough. **New columns on `item_occurrences`:**

| Column | Type | Notes |
|---|---|---|
| `anchor_kind` | `TEXT` | `project`, `file`, `syntax`, `config_key` |
| `anchor_symbol` | `TEXT` | Roslyn documentation id of the containing member, e.g. `M:WcfCatalog.Services.OrderService.GetOrder(System.Guid)` |
| `anchor_span` | `JSONB` | Start and end line and column of the matched node |
| `anchor_hash` | `TEXT` | SHA-256 of the matched node's text, whitespace-normalised |
| `anchor_ordinal` | `INTEGER` | Position among identical matches in the same member, so two identical throws stay distinct |
| `anchor_commit` | `TEXT` | Repository commit the anchor was computed at |

**Staleness.** Before a unit runs, its anchor is re-resolved at the current commit:

- symbol and hash match → `fresh`;
- symbol found, hash differs → `stale`, re-planned (Part I);
- symbol gone → `stale_missing`, reported.

Anchors are computed by `application-fingerprinting`'s Roslyn pass and carried through by `item-detection` (Part L).

### C4. Conversion plan and units

`work-list-assembly` produces a **plan** instead of a flat work list. A plan expands each active recipe
over its targets into **units**.

**`conversion_plans`**: id, application/repository, engagement, `legacy_commit` (the baseline),
`target_layout`, recipe ids and versions, `status`, `created_at`, `approved_at`.

**`conversion_units`**

| Column | Notes |
|---|---|
| `unit_id` | Derived: `plan + recipe step + anchor`, stable across re-plans |
| `plan_id`, `slice_id`, `recipe_id`, `step_id`, `approach_id` + `version` | |
| `occurrence_ids` | The anchors this unit edits. Empty for project-level steps |
| `sequence` | Total order within the plan |
| `automation_class` | `deterministic`, `assisted`, `manual` (Part F) |
| `status` | See below |
| `commit_sha`, `execution_id` | Set when committed |
| `evidence` | Check, build and replay results for this unit |

**Unit statuses:** `planned` → `applied` → `verified` → `committed`; or `not_applicable`
(pre-check), `failed`, `stale`, `awaiting_review` (assisted), `awaiting_human` (manual).

The 28 work list becomes a **view over units**, so estimation, grouping and dashboards keep
working.

### C5. Slices

A **slice** is a group of entry points delivered and proven together. Two kinds:

| Slice | Holds | Runs |
|---|---|---|
| **Foundation** (one per plan) | Project-wide reshaping: target framework, packages, host, configuration, shared abstractions, dead-code removal | First. Every other slice builds on it |
| **Operation slice** | One service contract or operation group, from `entry-point-inventory`'s entry points, with every unit anchored inside it | After the foundation, in an order set at plan time (risk, consumer count, dependencies) |

**Slice assignment.** A unit belongs to the slice owning its anchor's containing type. A unit
whose anchor sits outside every slice's code (shared helpers, repositories) goes to the
foundation.

**`conversion_slices`**: `slice_id`, `plan_id`, `kind`, `name`, `entry_point_ids`, `order`,
`status`, and a readiness scorecard reference (Part H).

### C6. Framework deltas

A retarget is more than a TFM edit: a later framework can break code that built on the
earlier one. **The framework delta catalog** is the retarget's list of those known breaking
changes — item `target-framework-retarget`, recipe `framework-retarget`, step `D01`, data in
`backend/app/conversion/framework_deltas.yaml`. Client-agnostic, like the rest of a recipe.

| Field | Meaning |
|---|---|
| `id` | `net10-public-top-level-program` |
| `breaks_from` | The framework it breaks from. It applies when the retarget crosses it: from < `breaks_from` <= to |
| `signal` | How discovery detects it — a registered signal, so the plan knows before anything runs |
| `symptom` | What the build says without the fix |
| `fix` | The approach, its version and automation class, and the `basis` for trusting it |

**Detected in discovery, fixed before the retarget.** The planner expands each delta the
retarget crosses into one unit per place discovery found it. The unit runs **before** the
retarget and builds on **both** frameworks, and the retarget depends on it, so every commit
stays green: the source framework's build proves the fix changes nothing there, and the
retarget's build proves it was enough.

**Deterministic only when the rewrite is reliable** — proven to build on both frameworks and to
change nothing on the source one. Otherwise the fix is `assisted`: planned, never applied by the
deterministic runner, left for T1b (the assisted conversion work), and the retarget waits on it.

The first entry: from .NET 10, ASP.NET Core generates `public partial class Program` for a web
project with top-level statements. A test project that references two web projects and names
`Program` (`WebApplicationFactory<Program>`) sees two public Program types and fails with
CS0433. Detected by `entry-point-inventory` (signal `AMBIGUOUS_TOP_LEVEL_PROGRAM_ON_NET10`,
29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md B7) from project references, SDKs and top-level
statements. Fixed deterministically by `pin-program-internal`: `internal partial class Program
{ }` beside the implicit project's top-level statements, the accessibility it already has on
every earlier framework, which the .NET 10 generator respects — proven on a two-web-project
fixture on net8.0 and net10.0 before it was written down.

---

## Part D — Target layout

A per-application choice, recorded on the plan.

| | `in_place` | `side_by_side` |
|---|---|---|
| Output | A branch of the legacy repository (`branch-baseline-record` as today) | A new solution root next to the untouched legacy, in the same or a new repository |
| Legacy | Changed on the branch | **Read-only** (B7). `allowed_paths` may never include the legacy root |
| First foundation step | — | `scaffold-side-by-side`: copy the legacy source at `legacy_commit` into the target root |
| Drift reconciliation | Not needed | Required (Part I) |
| Use when | Legacy will not run in production after cutover | Legacy keeps serving production during a parallel run |

The client scenario in `35` is side by side.

---

## Part E — The unit loop

`application-scope-conversion` and `occurrence-scope-conversion` become executors of the plan's units (Part K). For each unit, in `sequence`:

```
 1. re-resolve anchors          stale?           → status stale, re-plan, stop the slice
 2. pre-checks                  fail?            → not_applicable, continue
 3. apply in a scratch worktree (dry run first; diff kept as evidence)
 4. allowed_paths + B7 guard    violated?        → failed
 5. post-checks                 fail?            → discard worktree, failed
 6. build (scope declared by the approach: project or solution)
 7. targeted replay             the behaviour baseline cases for the unit's slice (Part H)
 8. commit                      one commit, message from the approach; status committed
```

**Failure policy: by dependency, not by phase.** Every unit records what it depends on
(`depends_on`, each edge with its reason), and a failure stops exactly what depends on it.

| What | Effect |
|---|---|
| The failed unit | The worktree is discarded and the unit is recorded `failed` with its reason and evidence. **Nothing red is ever committed**, so no rollback machinery is needed |
| Units that depend on it, transitively | Recorded `blocked`, naming the unit they wait on. They are never applied |
| Every other unit | Continues. Being in the foundation does not widen a failure: a failed retarget blocks the units placed after it because they depend on it, while the package units before it, which do not, still run |
| The plan | Ends `partial` when any unit is failed, blocked or waiting for assisted work. It is `stopped` only by what invalidates every unit: a failed baseline, or a change to the repository's checked-out working tree |

Where the edges come from: the recipe's step order (`depends_on` in C1); a package's nuspec
dependencies (a dependency's unit before its dependent's); placement around a retarget (a
package that cannot build on the current framework after it, one that cannot build on the
target before it); and the framework delta fixes (C6), which the retarget depends on.

**The platform records; nobody excludes.** A failed unit's status and reason are recorded by
the loop itself. An agent never excludes a unit, and the runner has no switch to skip one:
leaving something out is a planning decision, recorded with the plan and its reason
(`conversion_plans.exclusions`), made by a person before the run.

**Resume.** A rerun retries every unit that is not `committed` or `not_applicable`, in
`sequence`: a failed unit runs again, and a blocked unit runs once what it waited on has
committed. Units are idempotent (28 requirement); an assisted unit is never auto-retried
(Part F).

**Targeted replay cost.** Step 7 runs only the slice's cases, not the whole suite. The full
suite runs at the slice boundary and again at `independent-verification`.

**Before any unit runs.** The legacy baseline must build and pass its tests (`baseline-verification`), and the
behaviour baseline must exist for every slice in the plan (Part H). Without these, a red unit
cannot be told apart from a pre-existing failure.

---

## Part F — Automation classes

Every recipe step declares a class, and every unit inherits it. `work-list-assembly` may downgrade a unit
when its anchor falls outside what the approach handles, for example a fault thrown through a
helper method instead of inline.

| Class | Who does it | Extra rules |
|---|---|---|
| `deterministic` | Codemod, template or tool (`python`, `process` invocation) | Re-runnable unattended. The default expectation for a recipe step |
| `assisted` | LLM (`skill` or `copilot` invocation) | Same loop and checks. Committed with `requires_review`. Model, prompt template and version recorded on the execution. **Never re-applied automatically** during drift reconciliation |
| `manual` | A person | The unit becomes a work item with instructions. The loop pauses that slice until the unit is marked done and passes the same checks |

The plan reports the mix per slice, e.g. "S4 Order: 11 deterministic, 1 assisted, 0 manual".
That makes the review effort visible before `plan-approval-gate` approves.

---

## Part G — Target contract design

New step `target-contract-design`, for resolutions that change the protocol (Part K). It
produces the consumer-facing contract **before** any conversion, for human sign-off.

**Inputs:** `contract-snapshot`'s source contract snapshot; `entry-point-inventory`'s entry points; the engagement's
**contract conventions**.

**Contract conventions** (`engagement_contract_conventions`, data, not code):

| Convention | Example |
|---|---|
| Verb rules | `Get*`/`Search*` with simple inputs → GET; `Create*`/`Place*` → POST; `Update*` → PUT; others → POST to an action route |
| Route template | `/api/{version}/{resource-plural}` with typed ids in the path |
| Fault → status map | `ValidationFault` 400; `*NotFoundFault` 404; state and stock conflicts 409; downstream unavailable 503; other 500 |
| Serialisation | Property naming kept as declared; enums as numbers; dates ISO 8601 |
| Versioning | `/api/v1` |

**Outputs:**

1. **Mapping table**: one row per source operation, with route, verb, request and response
   types, and fault → status rows.
2. **Target OpenAPI document**, generated from the mapping and the same DTO types.
3. **Exceptions list**: operations the conventions cannot map (message headers, `out`
   parameters, sessions, callbacks), each needing a human decision.

**Sign-off:** `plan-approval-gate` approves the mapping and the plan together. A change to the mapping
after approval re-opens the gate for the affected slices.

**`contract-parity-verification` uses the mapping.** When the protocol changes, contract parity checks each mapped
pair for equivalence (operations, fields, types, optionality, enum values, faults) instead of
diffing two documents of the same format.

---

## Part H — Behaviour baseline and equivalence verification

### H1. Baseline (`characterization-test-generation`, upgraded — Part K)

Captured from legacy at `legacy_commit`, before conversion. **Mandatory** for any plan with a
protocol-changing or application-scope recipe.

| Source | What it gives |
|---|---|
| **Recorded traffic** | Real request/response pairs per operation, sanitised, including faults |
| **Outbound recordings** | What the app sent to each downstream system and what came back, e.g. the `PlaceRealTimeFTOrder` request XML |
| **Generated cases** | Boundary, validation and fault cases per operation from the schema (the `S` part of the step), filling gaps in recorded traffic |
| **Existing tests** | Whatever the repository already has, indexed by entry point (`test-coverage-assessment`, Part L) |

Every case is tagged with its operation, so it belongs to exactly one slice.

### H2. Normalisation rules

Responses are compared after normalisation. Rules are data, per recipe, and reviewed:

| Rule kind | Example |
|---|---|
| Envelope | Strip the SOAP envelope; read JSON and XML into one model |
| Generated id | `OrderSummary.OrderId`: present and a GUID |
| Time | `*Utc` fields: within a tolerance |
| Order | Collections without a contractual order compared as sets |
| Format | `xs:dateTime` and ISO 8601 compared as instants |

### H3. Equivalence verification (new step — Part K)

Each case is replayed against legacy and target with **identical downstream behaviour**
(recorded or stubbed downstream systems), from identical starting data.

| Level | Compared |
|---|---|
| Response | Normalised body |
| Fault | The legacy fault ↔ the mapped HTTP status and fault body |
| Side effects | Database changes, files written, messages sent |
| Outbound | Payloads sent downstream, **byte-equivalent** where the downstream is unchanged |

**Write operations are never replayed against real downstream systems.** In production
parallel runs, only reads may be mirrored (`35` Part H).

### H4. Readiness scorecard

One per operation, rolled up per slice. An operation is **ready** when all hold **at the
current legacy commit**:

- [ ] Mapped and signed off (Part G)
- [ ] Contract parity passes (`contract-parity-verification`)
- [ ] Every baseline case equivalent, or on an approved list of known differences
- [ ] Every fault row passes
- [ ] Side effects and outbound payloads equivalent
- [ ] Configuration resolves the same in every environment
- [ ] Security and performance within agreed limits
- [ ] No unreconciled drift (Part I)

The last line is why scorecards are invalidated by drift: an operation ready in March is not
ready in May if a legacy fix landed in between.

---

## Part I — Drift reconciliation

New step `drift-reconciliation`, side-by-side layout only. Runs on demand, or whenever the
legacy repository moves.

```
1. diff legacy_commit..new_legacy_commit
2. recompute anchors at the new commit (`application-fingerprinting` Roslyn pass, scoped to changed files)
3. classify each change:
     touches a unit's anchor          → unit stale
     touches a slice's code, no anchor → slice re-verify (copied logic changed)
     changes the source contract      → back to target-contract-design for that slice
     touches nothing converted         → recorded, no action
4. deterministic stale units          → re-planned and re-run through the unit loop
   assisted or manual stale units     → awaiting_review / awaiting_human
5. copied logic changed               → re-copy the changed members into the target, re-run
                                         the slice's replay
6. invalidate affected scorecards; set legacy_commit to the new commit once all slices pass
```

**Copied logic.** In side-by-side layout, business logic is copied as is, and only recipe
units change it. Step 5 therefore re-applies only **changed members**, matched by symbol, not
whole files. Recipe edits made inside those members are then re-applied by their units.

---

## Part J — Approach certification

An approach (and so a recipe) is proven on **fixture repositories** before it may run on
client code.

**`approach_fixtures`**

| Column | Notes |
|---|---|
| `approach_id`, `fixture_id` | |
| `repository_path`, `commit` | The fixture's before-state, e.g. `sampleapps\WCF` |
| `expected` | Either a golden after-diff, or **property assertions** (e.g. "zero `FaultException<` in `Catalog.Services`", "builds on `net10.0`") |
| `last_run_at`, `last_result` | |

**Rules.**

- `draft → certified` requires every fixture to pass. The sample apps
  (`sampleapps\WCF`, `WCF-backend`, `eShopModernizing`, `legacy-grpc-suite`) are the
  starting corpus.
- `certified → active` is a deliberate promotion, by owner or tier.
- **Field metrics** per approach version: units attempted, committed, failed, stale, and
  review corrections (fed by `feedback-capture`).
- **Auto-demotion:** an `active` approach whose failure rate crosses a threshold drops to
  `certified`, so new plans stop using it until someone looks.
- A fixture that a new approach version fails blocks that version. **Fixtures are regression
  tests for conversions.**

Property assertions are preferred over golden diffs, because golden diffs break on harmless
formatting changes.

---

## Part K — Lifecycle changes

Slugs follow 17's rules: an extended meaning keeps its slug; a changed meaning gets a new
slug and the old one is soft-deleted. Steps are named by slug (CLAUDE.md rule 12); rows are
in lifecycle order, and a new step sits where its row is. Numbers are assigned when 17 is
revised (v3.0).

| Slug | Change | Owner | Kind |
|---|---|---|---|
| `branch-baseline-record` | Records `target_layout`; side by side creates the target root instead of a branch | P | Extended |
| `baseline-verification` | Unchanged. Now a **hard precondition** for the unit loop (Part E) | P | — |
| `contract-snapshot` | Unchanged | P | — |
| `target-contract-design` | Part G. `when:` the plan contains a protocol-changing recipe | P + H | **New** |
| `characterization-test-generation` → **`behaviour-baseline-capture`** | Part H1. Mandatory, recorded first, generated for gaps. Old slug soft-deleted (meaning changed) | P + S | **Replaced** |
| `work-list-assembly` | Produces the **plan**: recipes expanded into slices and units, triaged (Part F), with a chained dry run per slice in a scratch worktree | P | Extended (new artifact major version) |
| `plan-approval-gate` | Approves the plan **and** the target contract mapping | H | Extended |
| `application-scope-conversion` | Executes the **foundation slice** through the unit loop | P | Extended |
| `occurrence-scope-conversion` | Executes **operation slices** through the unit loop, partitioned per slice | P | Extended |
| `independent-verification` | Unchanged: clean CI over the whole solution | P | — |
| `contract-parity-verification` | Mapping-aware when the protocol changes (Part G) | P | Extended |
| `behavioural-equivalence-verification` | Part H3–H4. Produces scorecards | P | **New** |
| `drift-reconciliation` | Part I. `when: target_layout == 'side_by_side'`; also runnable on its own | P | **New** |
| `evidence-bundle-assembly` | Includes scorecards, unit evidence and the automation-class mix | P + S | Extended |
| `feedback-capture` | Feeds approach field metrics (Part J) | P | Extended |

On `application-scope-conversion` and `occurrence-scope-conversion`: keeping the slugs keeps 28's principle, "reshape first, then targeted
edits", and avoids re-binding job definitions. Only the display names change ("Foundation
conversions", "Slice conversions"). See Part O, question 1.

---

## Part L — Discovery additions

What conversion accuracy depends on, added to Phase 0. **Status** records what has been
built since this proposal was written; the rest is still to do.

| Addition | Why conversion needs it | Where | Status |
|---|---|---|---|
| **Syntax anchors** (C3) | Precise, re-runnable codemods; staleness detection | `application-fingerprinting` Roslyn pass emits anchors with signal evidence; `item-detection` carries them into occurrences | To do |
| **Reachability** | Do not convert code nothing reaches. The WCF sample has 12 dead items (`MODERNIZATION-NET10-REST.md` §5) | New step `reachability-analysis` after `outbound-invocation-inventory`: call graph from `entry-point-inventory`'s entry points; unreachable members, write-only fields, config keys read by nothing | To do |
| **Deploy-time configuration** | The real per-environment values live in `Parameters.xml`/`SetParam.xml`, transforms and settings stores | `outbound-invocation-inventory`'s configuration resolution | **Built.** `outbound-invocation-inventory` reads Web Deploy `SetParam`/`SetParameters` files, with per-engagement globs, as deploy-time configuration (`29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md` Part C9) |
| **Per-operation consumer usage** | Slice order and readiness; skip operations nobody calls | `dependency-and-context-map`, per operation | **Built from code:** operation-level integration edges, each caller's call site matched to the entry point it invokes (`31-DEPENDENCY-AND-CONTEXT-MAP.md`). **To do:** usage from traffic or logs, where they exist |
| **Coverage** | Shows which operations have no tests, so their baseline must be recorded or generated | `test-coverage-assessment` | **Built per file:** every source file in a bucket with existing-report coverage (`32-TEST-COVERAGE-ASSESSMENT.md`). **To do:** coverage per entry point |
| **Blocker items** | Route unconvertible shapes to humans before planning: duplex contracts, sessions, message contracts and headers, `KnownType` hierarchies, WS-Security message signing, transaction flow, MSMQ | New catalog items, referenced by `conversion_recipes.blockers` | To do |

---

## Part M — Engine requirements

Small, and mostly already anticipated by 17's "two engine requirements".

1. **Unit-level checkpointing.** Unit status is the resume point; a crashed step resumes at
   the first unit not `committed`.
2. **Scratch worktrees.** One per unit for apply and dry run; one per slice for the chained
   dry run at `work-list-assembly`. Created and destroyed by the platform, never by the approach.
3. **Child-process containment** (17's existing requirement). A step's processes die with it,
   so git never holds a commit the database does not know about.
4. **Partitioning per slice** for `occurrence-scope-conversion`, using the existing partition construct
   (`12-JOB-DEFINITION-FORMAT.md`) with `continue_on_error` across slices.

No change to job definitions, adapters, gates or policy.

---

## Part N — Changes to 17, 28 and 33 on acceptance

| Document | Change |
|---|---|
| `17-LIFECYCLE-STEPS.md` | v3.0: the new slugs, the replaced `characterization-test-generation`, display names for `application-scope-conversion` and `occurrence-scope-conversion`, renumbering, updated ownership summary |
| `28-ITEM-AND-CONVERSION-MODEL.md` Part J | Uniqueness moves to `conversion_recipes`. An approach's `scope` becomes the scope of its targets, not of the item |
| 28 Part L `ConversionContext` | Adds `unit_id`, `slice`, `anchors[]` (C3 columns), `target_layout`, `legacy_root` (read-only) and `target_root` |
| 28 Part M `ConversionResult` | Adds `anchors_resolved`, `automation_class`, and for assisted units `model`, `prompt_template`, `prompt_version` |
| 28 Part N checks | Adds check types `replay_cases` (Part H, slice-scoped), `no_writes_under` (B7), `anchor_fresh` |
| 28 Part S | Revisit "approach version recorded, no re-run policy": Part I is that policy |
| 28 acceptance criteria | Merge with this document's |
| `33-IMPACT-ANALYSIS.md` Parts C, D and I | Part P: impact for a resolution with a certified recipe comes from the recipe's chained dry run; its impact rules are marked superseded; a computed resolution records which producer it came from |

---

## Part O — Open questions

| # | Question | Proposal |
|---|---|---|
| 1 | Keep `application-scope-conversion` and `occurrence-scope-conversion` as foundation/slice executors, or register one new `conversion-execution` step? | Keep. Same ordering principle, no job re-binding |
| 2 | Compute anchors in `application-fingerprinting` (all signals) or only for supporting items' signals? | Only for signals some supporting or occurrence-scope item references, to bound cost |
| 3 | Where do recorded production traffic and outbound recordings come from on a client estate? | An ingestion contract (file drop of sanitised pairs) rather than a capture agent. Decide per engagement |
| 4 | Stop the whole plan or only the slice on an operation-slice failure? | Only the slice (Part E), unless the slice is a declared dependency of another |
| 5 | Can an assisted unit's output become deterministic? | Yes: when the same correction recurs in `feedback-capture`, promote it into the deterministic approach as a new version, certified on fixtures |
| 6 | Part P: `impact-analysis` runs in phase 0, but the chained dry run was to be produced by `work-list-assembly` in Track A. What does a repository show for a resolution with a certified recipe in discovery? | **Decided: `impact-analysis` runs the dry run itself, in phase 0** (Part P1) — deterministic units only, chained, in a scratch copy; no build, tests, commits or LLM; cached by commit; a failure is unknown with its reason, never the superseded rules. Rejected: "awaiting dry run", which would show the best-understood items least in discovery, blind risk scoring where knowledge is strongest, and leave the plan without units for certified recipes until Track A |

---

## Part P — Impact: one producer per fact

A recipe's steps and the catalog's impact rules (`33-IMPACT-ANALYSIS.md` Part D) both
describe what converting an item by one resolution touches: which files are changed,
created, deleted or need review. That is one fact with two producers, and two producers
drift: a rule saying the `.svc` is rewritten while the recipe deletes it is exactly the
kind of disagreement `impact-analysis` already had to correct in its own rules. So each
(item, resolution) has **one producer** of its impact at any time.

| The resolution has | Impact comes from | Impact rules |
|---|---|---|
| No recipe, or a recipe that is `draft` | **Catalog impact rules** (`impact-analysis`), as today. An estimate | In force |
| A recipe that is `certified` or `active` (Part J) | **The recipe's chained dry run**, run by `impact-analysis` itself in phase 0 (below): the files each deterministic unit's codemod touches, chained in a scratch copy | **Superseded.** Kept, not deleted, and not evaluated |
| A recipe that drops back to `draft` or is `deprecated` | Catalog impact rules again | In force again |

**From the dry run.** A deterministic unit's diff gives the actions directly: a new file is
`create`, a removed file is `delete`, a modified file is `update` or `rewrite` (by the share
of the file the unit replaces, with the threshold set in the recipe), all `confirmed`. An
assisted or manual unit (Part F) has no diff before a person or model acts, so its anchored
files are `review`, `possible`. The traversal path of each entry becomes the unit and the
anchor that produced it. Hotspots and conflicts (`33-IMPACT-ANALYSIS.md` Part G) are
computed the same way over whichever producer is in force for each work item, so a recipe
can be compared with a neighbouring item still on rules.

**Superseded rules.** Certification marks the resolution's impact rules superseded; they
stay in the catalog and the export as history, and come back into force automatically if
the recipe is no longer certified. Authors are told when they edit superseded rules: the
edit has no effect while the recipe is certified. Catalog rule conflicts naming a superseded
rule are resolved by the recipe, not by editing the rule.

**Recorded producer.** Each computed resolution in `impact_summaries` records its producer
(`rules_source` gains `recipe`, beside `explicit` and `default`) and, for a recipe, its
id, version and the dry run's plan id, so a figure can always be traced to what produced it.

**Client impact** is unchanged in kind: `dependency-and-context-map` still decides *who*
calls a converted service. What happens at each caller comes from the caller's own
producer — the coupled recipe (`wcf-client-to-rest` in `35`) once that is certified, the
`client_call_sites` rule until then.

### P1. The dry run in phase 0

Decided (Part O, question 6): **`impact-analysis` runs a certified recipe's dry run itself**,
in phase 0, so the transformation path is known at the end of discovery.

- **Deterministic units only, chained.** The recipe's deterministic units (Part F) are
  applied in plan order, each on the result of the last, and the cumulative diff is
  recorded. No build, no tests, no commits and no LLM: the codemods are applied and the diff
  read, nothing more. That keeps a phase 0 run cheap and free of anything that can execute
  the client's code.
- **The repository is never written.** Units run in a scratch copy outside the repository —
  a git worktree where the repository has history, a file copy where it has none — created
  and destroyed by the platform, never by an approach (Part M). It is the same discipline as
  `dependency-assessment`'s transitive restore in a scratch directory
  (`30-DEPENDENCY-ASSESSMENT.md`) and `test-coverage-assessment`'s scratch copy for test
  execution (`32-TEST-COVERAGE-ASSESSMENT.md` Part F3). `git status` is clean afterwards.
- **Cached by repository commit**, keyed with the recipe id and version and the version of
  each approach it applies, as `test-coverage-assessment` caches its results
  (`32-TEST-COVERAGE-ASSESSMENT.md` Part I): a rerun at the
  same commit with the same recipe reuses the dry run. A working tree with uncommitted
  changes to files the recipe's anchors touch, or a repository with no history, is always
  run fresh.
- **Assisted and manual units** are not applied; their anchored files come out as `review`,
  `possible`, as above.
- **A dry run that fails is unknown, with its reason.** A unit whose anchor does not resolve,
  a codemod that throws, or a post-condition the unit declares and the diff does not meet
  makes that resolution's impact `unknown` for the work item, with the failing unit and the
  reason recorded. It is a **finding**: a certified recipe has met a shape it does not
  handle, which is evidence against its certification (Part J) and goes to the recipe's
  owner through `feedback-capture`. It **never** falls back to the superseded impact rules —
  an estimate standing in for a failed recipe would hide exactly the case that most needs
  seeing.

**Why phase 0, not Track A.** Waiting for `work-list-assembly` would mean "awaiting dry run"
through all of discovery, and that is backwards:

- the best-understood items — the ones with a certified recipe — would show the *least*
  impact in discovery, while uncertified items showed rule estimates;
- `risk-scoring-tier-assignment` would be blind exactly where knowledge is strongest;
- the transformation plan would have no units for certified recipes until Track A.

**Track A reuses it.** `work-list-assembly`'s chained dry run per slice (Part K) is the same
fact. It reuses the phase 0 dry run when the commit, recipe version and approach versions
still match, and reruns it only when one has changed — one producer per fact, here too.

---

## As built: the minimum

Built to prove the unit loop on a version bump, nothing more: no slices beyond foundation,
no anchors, no certification, no lifecycle step, no LLM. Code in `backend/app/conversion/`.

**Model.** `conversion_recipes`, `conversion_recipe_steps`, `conversion_plans`,
`conversion_units` (migrations `d05f33540904`, `e81b4c2d9a07`). Every unit carries
`automation_class` and `depends_on` — `[{sequence, reason}]`, always earlier units. Statuses
beyond C4: `blocked` (Part E's failure policy), and plan statuses `partial` and `stopped`.
`excluded` survives only as the first proof's history: nothing sets it now.

**Recipes.** `recipes.yaml`, all `draft`, loaded by the seed after the catalog by the platform
seed's rules (never overwrites a newer row, never deletes a step) and compared by
`python -m app.seed.reproduce`:

- `framework-retarget` 0.2.0 (item `target-framework-retarget`): step `D01`, the framework
  delta fixes (C6, `framework_deltas.yaml`), then `F01`, `retarget-tfm`, which depends on `D01`;
- `package-upgrade-safe-bump` 0.2.0 (item `package-upgrade-safe`): `package-upgrade-safe` 0.2.0;
- `package-upgrade-breaking-adapt` 0.1.0 (item `package-upgrade-breaking`): `package-upgrade-adapt`,
  `assisted` — no implementation; its units are left for T1b.

`target-framework-retarget` is a catalog item, `not_ready`: its signal
`TARGET_FRAMEWORK_BELOW_ENGAGEMENT_TARGET` is declared for `dependency-assessment` but not yet
emitted, so the planner takes the framework declarations from `solution-discovery` directly.

**Approaches are code** (`approaches.py`), each with a pre-check, an apply, its allowed paths
and a post-check:

- `retarget-tfm` edits `TargetFramework` wherever `solution-discovery`'s
  `target_framework_source` says it is declared, and raises a `global.json` SDK pin below the
  target's major version to `<major>.0.100` (`rollForward` is kept);
- `package-upgrade-safe` 0.2.0 edits each version where it is declared — `PackageReference`,
  central `PackageVersion`, `VersionOverride`, or the shared MSBuild property a central version
  refers to (`$(AspNetVersion)`) — for one occurrence, or for every package of a group at once
  (`bumps`). A shared property whose packages recommend different versions is refused;
- `pin-program-internal` 0.1.0, the fix for delta `net10-public-top-level-program`.

**Ordering** (`planner.py`). Package dependencies come from dependency-assessment 1.2.0, which
records each version's nuspec dependency groups in `package_lookup_cache`
(30-DEPENDENCY-ASSESSMENT.md). Two rules:

1. A's new version requires plan package B above B's current version: if B also crosses a
   major version they **only resolve together** — one atomic unit; otherwise A depends on B.
2. A and B both raise a shared third-party dependency (framework-family packages such as
   `Microsoft.Extensions.*` left out): one family, or raised to the same version — one unit;
   different families — the one that raises it less depends on the other.

A group with an `upgrade_breaking` package is one **assisted** unit. Then placement around the
retarget, by framework support (`package_lookup_cache`):

| A move's packages | Placed | Why |
|---|---|---|
| a recommended version drops the current framework | after | it cannot build before the retarget |
| a current version not known to support the target | before; the retarget depends on it | it cannot stay through the retarget |
| both of the above | after, expected to fail | no order builds |
| recommended version's support for the current framework not known | after | there it is known to fit |
| everything supports both | before | the retarget commit then changes the framework alone |

A move placed before that depends on one placed after goes after too; every move placed after
depends on the retarget; within each side, dependencies first. "Not known" is not "no". The
plan records the couplings, placements and reasons (`ordering`), each unit its `order_reason`
and `depends_on`.

**The unit loop** (`runner.py`, Part E). Layout `in_place` only: a branch `conversion/<plan8>`
in its own worktree under `runs/<engagement>/<repository>/conversion/<plan8>/target`; the
registered checkout is never written. The baseline first: build the solution and run the unit
test projects (`test-coverage-assessment`'s `unit` test classes) at the legacy commit, in a
scratch worktree; zero tests fails it. Each unit then: its dependencies (blocked if one is not
committed), pre-check, a scratch worktree at the branch tip, apply, keep the diff, the
allowed-paths guard, post-check, build, unit tests compared test by test with the baseline, the
guard again, one commit fast-forwarded onto the branch. A failure discards the scratch worktree
and blocks exactly its dependents. Builds run without build servers so Windows can delete the
scratch worktree. A fingerprint of the registered checkout is taken before and after each run;
a difference stops the plan.

**Evidence** is files: per unit, the diff, build log, test logs and TRX, each recorded as
`{kind, path, sha256}` in `conversion_units.evidence`; a claim is never evidence. The
repository page's **Conversion** section shows the plan, its units in order with status,
commit, failure reason and evidence links — `GET /api/conversion/plans/{id}/evidence?path=`
serves a file only if the plan records that path and the file still has its sha256 — and the
unit tests before (the baseline) and after (the last committed unit).

```powershell
cd backend; .venv\Scripts\Activate.ps1
python -m app.conversion.planner --repository eshoponweb
python -m app.conversion.runner --plan <plan-id>
```

### The first proof: eShopOnWeb, net8.0 to net10.0 (plan `caacced1`)

Baseline at `4da8212`: 44 of 44. Seventeen package units committed; five were excluded by
hand after failing; the retarget failed on CS0433 and, under the policy then — a foundation
failure stops the plan — nothing after it ran. It found: package couplings the framework data
could not see (NU1605 twice with excluded partners, NU1605 on an order the plan got wrong, an
Azure.Core collision), a breaking change classified `upgrade_safe` (Swashbuckle 10 pulls
Microsoft.OpenApi 2), and a retarget that needs a code change (.NET 10 makes a web project's
implicit `Program` public). Each became a fix above: dependency edges and atomic groups, the
transitive API diff (30-DEPENDENCY-ASSESSMENT.md), the framework delta catalog (C6), and the
failure policy by dependency.

### The second proof: the same bump, rerun (plan `90bc71e0`)

No exclusions. 33 units: 27 package units before the retarget (three of them atomic groups,
two of those assisted), the framework delta fix, the retarget, four after. Baseline 44 of 44.

**eShopOnWeb reached net10.0.** The delta fix (`internal partial class Program { }` in
`src/Web/Program.cs`) committed at 44 of 44 on net8.0, and the retarget after it at 44 of 44 on
net10.0. Final state, after one rerun: 19 committed, every one 44 of 44; 11 not applicable (a
shared declaration already moved); 3 assisted groups left for T1b — MSTest (TestFramework 4
breaks `Assert.AreEqual` call sites), Swashbuckle (Microsoft.OpenApi 2), and Ardalis.Specification
(9's API, and it waits on EF Core 10). Plan `partial`; nothing failed or blocked; the registered
checkout unchanged.

What refused to go green, and why: the ASP.NET Core and EF Core group (10.0.12) failed its
first attempt on NU1107. EF Core Tools 10 pins `Microsoft.CodeAnalysis.Common` at exactly 5.0.0
three levels down, while the still-unbumped CodeGeneration.Design 8 pinned it at exactly
4.8.0. Only that group's dependent (the Ardalis group) was blocked; the CodeGeneration.Design
unit, independent, committed after it; and the rerun then committed the group at 44 of 44. The
planner's coupling rules read each package's direct dependencies only, so an exact-version
clash between two transitive pins is invisible to them: the remaining known gap in ordering.

---

## Acceptance criteria

### Model

- [ ] A resolution's conversion is a recipe of ordered steps; one active recipe per (item, resolution)
- [ ] A plain item converts as a one-step recipe with no other change
- [ ] Supporting items are detected by `item-detection`, take their decision from their parent, and are hidden from the decision UI
- [ ] Occurrences of anchored signals carry symbol, span, hash, ordinal and commit
- [ ] A unit whose anchor hash no longer matches is `stale` and does not run
- [ ] `work-list-assembly` produces a plan of slices and units with an automation class per unit
- [ ] The foundation slice is first; every unit belongs to exactly one slice
- [ ] For each (item, resolution), impact has one producer: catalog impact rules without a certified recipe, the recipe's chained dry run with one (Part P)
- [ ] Certifying a recipe marks its resolution's impact rules superseded; losing certification puts them back in force
- [ ] A certified recipe's impact in phase 0 comes from its dry run, run by `impact-analysis`, and the repository is unchanged afterwards
- [ ] A failed phase 0 dry run reports that resolution's impact as unknown with the failing unit and reason, and never falls back to the superseded impact rules

### Execution

- [ ] No commit is made for a unit whose post-checks, build or targeted replay fail
- [ ] A failed unit blocks only the units that depend on it, transitively; every other unit continues
- [ ] A rerun resumes at the first unit not `committed`
- [ ] In side-by-side layout, any write under the legacy root fails the unit
- [ ] Assisted units are committed with `requires_review` and record model and prompt version
- [ ] Assisted and manual units are never re-applied automatically by drift reconciliation

### Evidence

- [ ] A plan with a protocol-changing recipe cannot pass `plan-approval-gate` without a signed-off mapping
- [ ] `contract-parity-verification` checks mapped pairs when the protocol changes
- [ ] Every baseline case belongs to exactly one operation and one slice
- [ ] Equivalence compares response, fault, side effects and outbound payloads after declared normalisation
- [ ] Write operations are never replayed against real downstream systems
- [ ] A scorecard is invalidated when drift touches its operation

### Certification

- [ ] An approach or recipe cannot become `active` without passing every fixture
- [ ] An `active` approach above the failure threshold is demoted automatically
- [ ] A new approach version that fails a fixture cannot be certified
