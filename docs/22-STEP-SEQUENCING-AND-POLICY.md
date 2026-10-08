# 22 — Step Sequencing, Conditions & Engagement Policy

How the flow is defined, how steps are conditionally skipped, and how a client
disables a step without forking a job definition.

Amends `12-JOB-DEFINITION-FORMAT.md`, `10-ENGINE-CONCEPTS.md` and
`20-WORKFLOW-OBSERVABILITY-UI.md`.

---

## The two-layer principle

| Layer | Question it answers | Lives in | Changed by |
|---|---|---|---|
| **Design** | Does this step make sense to run here, given the data? | Job definition YAML — `when:` conditions | Engineer, via YAML plus a version bump |
| **Configuration** | Does this client (or every client) want this step at all? | `step_policies` table | Operator or admin, from the UI, no version bump |

Keep these separate. "Only generate characterization tests when coverage is below
threshold" is design — it belongs in the flow and applies to every client. "Client B
is not modernizing SSIS" is configuration — it belongs in data and applies to one
engagement. "Nobody should run this yet" is also configuration, one layer up —
`23-WORKFLOW-ADMINISTRATION.md` Part A splits Configuration itself into a global and
an engagement layer within this same table, distinguished by whether
`engagement_id` is null.

Per-engagement job definitions were considered and rejected: they fragment the
definition set and every engine improvement then needs copying N times.

---

## Part A — Validator bug fix (do this first)

Rule 2 in `12-JOB-DEFINITION-FORMAT.md` validates that a step's declared `consumes`
is *satisfiable* by some upstream `produces`, but not that the flow node actually
**wires** it through an `inputs` mapping. A definition with a required `consumes` and
no corresponding `inputs` entry passes static validation and then fails at runtime
with "input was not resolved" — exactly the failure static validation exists to
prevent. This happened with `application-fingerprinting`.

Add validation rule 9:

> For every step in the flow, every non-optional `consumes` entry must have a
> corresponding key in that flow node's `inputs` mapping, and the referenced source
> must resolve. A required input that is never wired is `UNWIRED_INPUT`.

```json
{
  "code": "UNWIRED_INPUT",
  "step": "application-fingerprinting",
  "detail": "requires solution-project-inventory ^2.0.0 but the flow node declares no inputs mapping for it. Add inputs: { solution-project-inventory: \"${artifacts.solution-project-inventory}\" }",
  "affected_steps": ["solution-discovery"]
}
```

Also: when a step registration adds a new non-optional `consumes`, any **active** job
definition containing that step becomes invalid. Re-validate active definitions on
step registration change and report which are now invalid, rather than discovering it
at the next launch.

---

## Part B — `when:` conditions

Optional on any flow step. Structured rather than free-form expressions — safe to
evaluate, trivially validated, and introspectable by the viewer UI.

```yaml
  - step: characterization-test-generation
    when:
      all:
        - { context: "test_coverage_percent", lt: 60 }
        - { param: "engagement_id", ne: "reference-engagement-b" }
    inputs:
      coverage_report: "${artifacts.test-coverage-report}"
```

### Grammar

**Combinators:** `all` (AND), `any` (OR), `not` (single nested condition). Nestable.

**Leaf sources:** exactly one of

- `param: "<name>"` — a declared job parameter
- `context: "<key>"` — a job execution context key
- `step_status: "<step_name>"` — a prior step's exit status in this execution

**Operators:** one per leaf — `eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `in`, `not_in`,
`exists` (boolean), `matches` (anchored regex, strings only).

No arithmetic, no function calls, no free-form expressions. If a condition needs
logic beyond this, it belongs in a decider (`12-JOB-DEFINITION-FORMAT.md`) which is
already deterministic Python with a named outcome.

### Evaluation rules

- **A missing `param` fails validation** at load time — parameters are declared, so a
  typo is catchable statically.
- **A missing `context` key with `exists` evaluates false.** With any comparison
  operator it **fails the step** rather than skipping it. This is deliberate: a
  typo'd context key must never silently skip a verification step. Fail loud.
- **`step_status`** referencing a step not earlier in the flow fails validation.
- Type mismatches (comparing a string to a number) fail the step, not skip it.
- Evaluation is side-effect free and must not touch the database.

### Precedence

Evaluated in this order; the first that resolves to "do not run" wins:

1. **Engagement policy** (Part C) — an explicit operator decision overrides everything
2. **`when:` condition**
3. **`gate.tier_condition`** for gate steps, as already specified
4. **`stub_policy`** for `NOT_IMPLEMENTED` steps

---

## Part C — Step policy: global and engagement layers

Amended by `23-WORKFLOW-ADMINISTRATION.md` Part A, which added the global layer
below and renamed the table; this section reflects that current state rather than
the two-layer design as first shipped.

### Table `step_policies`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `engagement_id` | `TEXT` NULL FK → `engagements.id` | **Null means global** |
| `step_name` | `TEXT` NOT NULL FK → `wf_step_registrations.step_name` | |
| `enabled` | `BOOLEAN` NOT NULL DEFAULT true | |
| `reason` | `TEXT` NOT NULL | Required whenever a row exists, in either direction |
| `set_by` | `TEXT` | Operator name. Free text until auth exists |
| `set_at` | `TIMESTAMPTZ` NOT NULL | |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |

Two partial unique indexes, not one plain unique constraint — a plain
`UNIQUE(engagement_id, step_name)` treats every `NULL` engagement_id as distinct,
which would let multiple global rows exist for the same step:

- `(step_name) WHERE engagement_id IS NULL` — one global row per step
- `(engagement_id, step_name) WHERE engagement_id IS NOT NULL` — one row per
  engagement per step

Was `engagement_step_policies`, `engagement_id NOT NULL`, `reason` required only
when disabling. Renamed and widened by `23-WORKFLOW-ADMINISTRATION.md` Part A;
existing rows migrated unchanged (they all had an `engagement_id` already).

### Three layers, one table

| Layer | Scope | Set by | Answers |
|---|---|---|---|
| **Default** | Everything | Nobody — absence of a row at either layer | Enabled |
| **Global** | All engagements | Admin, master view | "Nobody should run this yet" |
| **Engagement** | One engagement | Operator, client view | "This client does not want this" |

**Precedence: engagement beats global beats default.** An engagement row is an
explicit local decision and overrides a global one in either direction — an
engagement can re-enable a step that is globally disabled, and can disable a step
that is globally enabled.

**Absence means enabled.** No row at either layer is the default, so a newly
registered step is active everywhere with no backfill — the same lazy-overlay
pattern used for `engagement_patterns`.

`reason` is required whenever a row exists, in either direction. "Why didn't
contract verification run on application 412" must be answerable from the UI —
and so must "why is this step running for Client A when it is globally off."

### The dependency problem

Skipping a step means its `produces` artifacts do not exist. Any downstream step with
a **non-optional** `consumes` on those artifacts then cannot run.

Three options were considered. Failing at runtime is unacceptable. Silently
cascade-skipping dependents is dangerous — disabling one step could quietly disable
half the pipeline. So:

**Validate the policy at save time against the active job definition's dependency
graph, and refuse if it would orphan a required input.**

```
POST /api/engagements/{eid}/step-policies
{ "step_name": "solution-discovery", "enabled": false, "reason": "…" }

→ 409
{
  "detail": [{
    "code": "POLICY_ORPHANS_DEPENDENTS",
    "message": "Disabling solution-discovery would leave application-fingerprinting without its required input solution-project-inventory.",
    "dependent_steps": ["application-fingerprinting"],
    "resolution": "Disable the dependent steps in the same request, or leave this step enabled."
  }]
}
```

The request may carry `cascade: true` plus the explicit dependent list, in which case
the API creates a policy row for each with reason
`"cascaded from disabling <step_name>"`, **at the same layer as the change being
made** — a global disable's cascade rows are global; an engagement disable's are
engagement-scoped. The operator confirms in the UI; nothing cascades implicitly.

Downstream steps whose `consumes` is `optional: true` are unaffected — they run
without that input, which is what optional means.

This guard extends across layers (`23-WORKFLOW-ADMINISTRATION.md` Part A):

- A **global** disable is validated against every active job definition the same
  way, and additionally reports which engagements have their own row re-enabling
  the step — those engagements are unaffected, and the admin should know the
  change is partial.
- An **engagement** re-enable of a globally disabled step is validated the same
  way: re-enabling a step whose upstream producer is effectively disabled — by an
  engagement row or a global one — is refused.

### Runtime behaviour

When a step's effective policy is disabled, the engine still **creates a
`wf_step_executions` row** with `batch_status: COMPLETED`, `exit_status: SKIPPED`
and `skip_reason: POLICY_DISABLED_GLOBAL` or `POLICY_DISABLED_ENGAGEMENT` — matching
whichever layer's row is the one actually in effect — carrying the policy reason in
`exit_message`. It produces no artifacts and consumes no inputs.

The policy is read **once at job launch**, resolved across both layers
(engagement beats global beats default), and snapshotted into the job execution
context, so a policy change mid-execution cannot produce a run that half-honoured
it. Record the snapshot in `wf_job_executions.execution_context` under
`step_policy_snapshot`, keyed by step name, each entry carrying `enabled`, `reason`,
and `source` (`"global"` or `"engagement"`) so the timeline can say which layer
decided it.

---

## Part D — Skip semantics

### New column on `wf_step_executions`

| Column | Type | Notes |
|---|---|---|
| `skip_reason` | `TEXT` | Null unless `exit_status` is `SKIPPED`. CHECK IN (`POLICY_DISABLED_GLOBAL`, `POLICY_DISABLED_ENGAGEMENT`, `CONDITION_FALSE`, `TIER_NOT_APPLICABLE`, `UPSTREAM_SKIPPED`, `CASCADED_POLICY`) |

`POLICY_DISABLED_GLOBAL` and `POLICY_DISABLED_ENGAGEMENT` replace the original
single `POLICY_DISABLED` value (`23-WORKFLOW-ADMINISTRATION.md` Part A) — the
timeline should say which layer disabled the step, not only that policy did.

`SKIPPED` is added to the exit status vocabulary in `10-ENGINE-CONCEPTS.md`. It is a
**success** outcome for flow purposes — the job continues.

`UPSTREAM_SKIPPED` covers a step whose optional input was not produced and which
therefore has nothing to do. It is distinct from a policy decision.

### Non-negotiable rule

**A skipped step always appears in the timeline.** Never omit the row, never collapse
it, never leave it visually identical to a step that never ran. At 600 applications,
a silently absent step destroys the audit trail this platform exists to produce.

### Timeline rendering

Extend the visual treatment table in `20-WORKFLOW-OBSERVABILITY-UI.md`:

| State | Treatment |
|---|---|
| `SKIPPED` — `POLICY_DISABLED_GLOBAL` | Hollow marker, dashed outline, `SKIPPED — GLOBAL POLICY` chip, reason inline in the collapsed row |
| `SKIPPED` — `POLICY_DISABLED_ENGAGEMENT` | Hollow marker, dashed outline, `SKIPPED — ENGAGEMENT POLICY` chip, reason inline in the collapsed row |
| `SKIPPED` — `CONDITION_FALSE` | Hollow marker, `NOT APPLICABLE` chip, the condition that evaluated false shown when expanded |
| `SKIPPED` — `TIER_NOT_APPLICABLE` | Hollow marker, `TIER N` chip |
| `SKIPPED` — `UPSTREAM_SKIPPED` | Hollow marker, `UPSTREAM SKIPPED` chip, naming the upstream step |
| `SKIPPED` — `CASCADED_POLICY` | Hollow marker, `CASCADED` chip, naming the originating step |

Skip reasons appear in the **collapsed** row, not only on expand. The point is that
someone scanning a timeline sees why immediately.

Add a skipped count to `step_summary` on the execution detail payload, and to the
segmented progress bars on the Repositories and Dashboard tabs.

---

## Part E — Job definition viewer

Read-only. An updater is explicitly future work.

`GET /api/workflow/jobs/{job_name}/definition?engagement_id=`

Returns the active definition resolved for display, with policy state merged in when
`engagement_id` is supplied:

```json
{
  "job_name": "phase0-repository-discovery",
  "version": 4,
  "is_active": true,
  "validation_status": "valid",
  "description": "…",
  "parameters": [ { "name": "engagement_id", "type": "string", "required": true, "description": "…" } ],
  "flow": [
    {
      "sequence": 1,
      "step_name": "repository-ingest",
      "lifecycle_step_no": 1,
      "display_name": "Repository estate ingest & inventory creation",
      "owner_code": "P",
      "adapter_type": "python",
      "implementation_status": "implemented",
      "step_version": "1.0.0",
      "consumes": [],
      "produces": [ { "artifact_type": "repository-inventory", "artifact_version": "1.1.0" } ],
      "inputs": {},
      "when": null,
      "gate": null,
      "policy": { "enabled": true, "source": "default", "reason": null }
    }
  ],
  "raw_yaml": "…"
}
```

`policy.source` is `default` when no row applies at either layer, `global` when only
a global row applies, and `engagement` when an engagement row overrides it — see
`23-WORKFLOW-ADMINISTRATION.md` Part A for the precedence rule.

### UI — new section in the Workflow tab

Below the jobs list. Selecting a job shows:

**Header** — job name, active version, validation status, description, scope, and a
counter: `1 of 7 steps implemented`.

**Parameters** — name, type, required, default, description.

**Flow** — an ordered list, one card per step:

- sequence number, lifecycle step number, display name, owner code badge
- adapter type chip and implementation status chip (`IMPLEMENTED` / `STUB`)
- **consumes** and **produces** as artifact chips (`solution-project-inventory@2.0.0`)
- **inputs wiring** shown explicitly — logical name to source expression. This is the
  thing that was silently missing for `application-fingerprinting`; make it visible
- `when:` condition rendered as readable prose, e.g.
  *"Runs when test_coverage_percent < 60 and engagement_id ≠ reference-engagement-b"*
- policy state: `Enabled` or `Disabled — <reason>`, with an edit affordance when an
  engagement is selected

Artifact chips should visually connect producer to consumer — at minimum, hovering a
`produces` chip highlights the matching `consumes` chip downstream. The dependency
chain is the hardest thing to hold in your head from YAML alone.

**Raw YAML** — collapsed, monospace, copyable.

### Policy management UI

From the flow card, an operator can toggle a step for the selected engagement. On
toggle off, a required-reason dialog. If the API returns
`POLICY_ORPHANS_DEPENDENTS`, show the dependent steps and offer an explicit
"also disable these" confirmation which resubmits with `cascade: true`.

A `Policy` summary strip lists every disabled step for the engagement with its reason
and who set it, so the deviations from default are visible in one place.

---

## Part F — API

```
GET    /api/workflow/jobs/{job_name}/definition?engagement_id=
GET    /api/engagements/{eid}/step-policies
POST   /api/engagements/{eid}/step-policies          create or update; validates dependencies
DELETE /api/engagements/{eid}/step-policies/{step_name}   revert to next layer (global, else default)
POST   /api/engagements/{eid}/step-policies/validate      dry run, returns what would be orphaned
```

All per `18-API-CONVENTIONS.md`. The `validate` endpoint lets the UI warn before the
operator commits.

The mirror-image global-layer endpoints (`GET`/`POST`/`DELETE`/`validate` under
`/api/workflow/step-policies`), plus the cross-layer `effective-policies` and
`policy-matrix` read views, are added by `23-WORKFLOW-ADMINISTRATION.md` Part B —
listed there rather than duplicated here.

---

## Part G — What this does not cover

Deliberately out of scope, recorded so the boundary is explicit:

- **Job definition editing from the UI.** Viewer only. Definitions stay in git, which
  is where reviewable change belongs.
- **Repository-level policy.** Engagement-level only. The table can gain a nullable
  `repository_id` later without restructuring.
- **Policy history.** Current state only. If an audit trail of policy changes becomes
  necessary, add an append-only `step_policy_events` table rather than versioning
  rows.
- **Reordering steps per engagement.** Order is design and stays in YAML. A client
  wanting a different order needs a different job, and that should be a deliberate
  conversation.

---

## Acceptance criteria

- [ ] Validation rule 9 catches a required `consumes` with no `inputs` mapping, and
      the current `phase0-repository-discovery` v4 still validates
- [ ] Adding a non-optional `consumes` to a registered step marks affected active
      definitions invalid, reported at registration time
- [ ] A `when:` condition referencing an undeclared parameter fails validation
- [ ] A `when:` condition referencing a missing context key with `exists` skips the
      step; with a comparison operator it **fails** the step
- [ ] A step with a false `when:` condition produces a `SKIPPED` row with
      `skip_reason: CONDITION_FALSE`
- [ ] Disabling a step by engagement policy produces a `SKIPPED` row with
      `skip_reason: POLICY_DISABLED_ENGAGEMENT` and the reason in `exit_message`
      (global-layer criteria — `POLICY_DISABLED_GLOBAL`, cross-layer overrides — are
      in `23-WORKFLOW-ADMINISTRATION.md`'s acceptance criteria)
- [ ] Disabling `solution-discovery` returns 409 naming `application-fingerprinting`
      as orphaned
- [ ] The same request with `cascade: true` creates both policy rows, the second with
      `skip_reason: CASCADED_POLICY` at runtime
- [ ] Disabling a step whose only dependent has `optional: true` succeeds without cascade
- [ ] Policy is snapshotted at launch; changing it mid-execution does not affect the
      running execution
- [ ] Absence of a policy row means enabled — a newly registered step needs no backfill
- [ ] Every skipped step appears in the timeline with its reason visible **collapsed**
- [ ] Skipped counts appear in `step_summary` and in the progress bars on Repositories
      and Dashboard
- [ ] The job definition viewer shows the flow with consumes, produces and inputs
      wiring, and renders `when:` conditions as readable prose
- [ ] The viewer shows policy state per step when an engagement is selected
- [ ] Reverting a policy via DELETE returns the step to enabled
- [ ] Deleting a policy row for a step disabled by cascade does not silently re-enable
      an orphaned dependent — re-validate and warn
