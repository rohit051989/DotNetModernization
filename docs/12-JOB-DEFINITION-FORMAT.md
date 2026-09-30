# 12 — Job Definition Format

Declarative YAML describing a job's steps and flow. Loaded, validated, and stored in
`wf_job_definitions`. Job definitions live in `backend/app/jobs/*.yaml` and are
committed to git.

## Phase 0 is two jobs, not one

Earlier drafts of this document showed a single `phase0-estate-discovery` job
covering lifecycle steps 1-12. That job does not exist. `15-REPOSITORY-INGEST-UI.md`
Part A splits phase 0 by scope instead:

- `phase0-repository-discovery` — per repository, steps 1, 2, 3, 4, 8, 9, 10. Defined
  in `backend/app/jobs/phase0-repository-discovery.yaml`. Launched automatically on
  registration or rescan.
- `phase0-estate-consolidation` — engagement-scoped, steps 5, 6, 7, 11, 12. Defined in
  `backend/app/jobs/phase0-estate-consolidation.yaml`. All five steps are still stubs,
  so it runs under `stub_policy: continue`. It declares **no preconditions**: an
  estate-completeness precondition is unsatisfiable at fleet scale, and step 5 reports
  its own coverage instead — see `26-STEP-005-PATTERN-DISCOVERY.md` A5.

Steps 5, 6, 7, 11 and 12 are genuinely estate-wide — clustering unmatched patterns,
building a cross-repository dependency graph, or planning waves cannot be done from a
single repository. That is the reason for the split, not an arbitrary size limit.

The minimal example below is illustrative of the format's features, not a literal
job. See `backend/app/jobs/phase0-repository-discovery.yaml` for the real,
currently-defined job.

## Minimal example

```yaml
job_name: example-job
version: 1
description: "Illustrates parameters, external inputs, and input wiring."

parameters:
  - name: engagement_id
    type: string
    required: true
    description: "The engagement this run belongs to."
  - name: source_type
    type: string
    required: false
    default: manifest
    description: "Optional. Where to read repositories from."

external_inputs:
  - logical_name: repo_manifest
    artifact_type: repo-manifest
    version_range: "^1.0.0"
    required: true

flow:
  - step: repository-ingest
    inputs:
      repo_manifest: "${external.repo_manifest}"
    config:
      source_type: "${params.source_type}"
```

Each parameter may carry an optional `description` — plain text explaining what
it's for. Purely documentary; the engine does not read it. It's what
`GET /api/workflow/jobs/{job_name}/parameters` (see below) surfaces to a launch
form or an integrator, so a job author should write one for every parameter that
isn't self-explanatory from its name alone.

## Flow constructs

### Sequential steps

Listed in order. Each proceeds on `COMPLETED` or `NOOP`.

```yaml
flow:
  - step: repository-ingest
  - step: solution-discovery
  - step: application-fingerprinting
```

### Input wiring

Inputs are wired explicitly by logical name. Three sources:

```yaml
  - step: application-fingerprinting
    inputs:
      # from an upstream step's output in this job
      repositories: "${steps.repository-ingest.outputs.repository-inventory}"
      # from a job-level external input
      manifest: "${external.repo_manifest}"
      # from a specific artifact type produced anywhere upstream (first match)
      solutions: "${artifacts.solution-inventory}"
```

Prefer the explicit `steps.<name>.outputs.<type>` form. The `artifacts.<type>`
shorthand is convenient but ambiguous when several steps produce the same type.

### Conditional execution — `when:`

Optional on any flow step. Structured rather than free-form expressions — safe to
evaluate, trivially validated, and introspectable by a viewer UI. Full semantics in
`22-STEP-SEQUENCING-AND-POLICY.md` Part B; summarised here as part of the format.

```yaml
  - step: characterization-test-generation
    when:
      all:
        - { context: "test_coverage_percent", lt: 60 }
        - { param: "engagement_id", ne: "reference-engagement-b" }
    inputs:
      coverage_report: "${artifacts.test-coverage-report}"
```

**Combinators:** `all` (AND), `any` (OR), `not` (single nested condition). Nestable.

**Leaf sources** — exactly one per leaf:

- `param: "<name>"` — a declared job parameter
- `context: "<key>"` — a job execution context key
- `step_status: "<step_name>"` — a prior step's exit status in this execution

**Operators** — exactly one per leaf: `eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `in`,
`not_in`, `exists` (boolean), `matches` (anchored regex, strings only).

No arithmetic, no function calls, no free-form expressions. Logic beyond this
belongs in a decider, which is deterministic Python with a named outcome.

**Evaluation semantics** (side-effect free — no database access):

- A missing `param` or an out-of-flow `step_status` fails **validation**, at load
  time — see rule 10 below.
- A missing `context` key evaluates `false` under `exists`. Under any other
  operator it **fails the step** rather than skipping it — a typo'd context key
  must never silently look like a deliberate skip.
- A type mismatch (comparing a string to a number, or `matches` against a
  non-string) fails the step, the same way.
- `all`/`any` short-circuit natively, so a later leaf that would fail is never
  reached once the combinator's outcome is already decided.

A step whose `when:` is false is not invoked at all: the engine records a `SKIPPED`
step execution with `skip_reason: CONDITION_FALSE` and continues the job — see
`10-ENGINE-CONCEPTS.md`'s exit status table and `22-STEP-SEQUENCING-AND-POLICY.md`
Part D.

**Precedence when several skip/fail sources could apply to the same step** — the
first that resolves to "do not run" wins:

1. Engagement step policy (`22-STEP-SEQUENCING-AND-POLICY.md` Part C)
2. `when:` condition
3. `gate.tier_condition`, for gate steps
4. `stub_policy`, for a step reporting `NOT_IMPLEMENTED`

### Split — parallel execution

```yaml
  - split: verification-checks
    max_concurrency: 4
    branches:
      - - step: contract-parity-verification
      - - step: characterization-test-execution
      - - step: linux-compatibility-scan
```

Each branch is itself a list of steps, run sequentially within the branch. The split
completes when all branches complete. If any branch fails, the split fails, but
sibling branches are allowed to finish rather than being killed mid-write.

### Decision — conditional branching

```yaml
  - decision: coverage-check
    decider: app.deciders.test_coverage:evaluate
    outcomes:
      INSUFFICIENT:
        - step: characterization-test-generation
      SUFFICIENT:
        - step: noop
```

A decider is a deterministic Python callable receiving job and step context and
returning a string outcome. It performs no side effects and produces no artifacts.
Outcomes must be exhaustive — add a `default` branch or validation fails.

### Partitioning — same step over many items

```yaml
  - step: application-fingerprinting
    partition:
      partitioner: app.partitioners.by_repository:partition
      max_concurrency: 8
      aggregate_outputs: true
```

The partitioner returns a list of `{partition_key, config_overrides}`. The engine
creates one `wf_step_executions` row per partition. With `aggregate_outputs: true`,
per-partition artifacts of the same type are merged into a single artifact after all
partitions complete; the merge function is declared on the artifact type.

Partition failure policy:

```yaml
      failure_policy: fail_fast     # or continue_on_error
      max_failed_partitions: 5      # only with continue_on_error
```

At 600 applications, `continue_on_error` with a threshold is usually right — one bad
repository should not halt the estate scan.

### Human gates

```yaml
  - step: target-state-approval
    gate:
      type: pull_request           # or api
      resume_trigger: "pr_merged"
      tier_condition: "tier >= 2"
```

A gate step returns `AWAITING_APPROVAL`. The job execution ends with batch status
`STOPPED` and exit status `AWAITING_APPROVAL`. A resume call creates a new job
execution continuing from this step.

`tier_condition` is evaluated against job context. When false, the gate is skipped
with `NOOP` — this is how Tier 0 and 1 auto-pass while Tier 2 and 3 require sign-off.

### Step-level overrides

```yaml
  - step: contract-parity-verification
    restart:
      allow_start_if_complete: true
      start_limit: 5
    on_failure: continue           # default: halt
    timeout_seconds: 900
```

`on_failure: continue` records the failure and proceeds. Use sparingly and never for
verification steps that gate correctness.

## Job-to-job dependency

Jobs do not call each other directly. Dependency is expressed as a precondition
checked at launch:

```yaml
job_name: trackB-wave
version: 1

preconditions:
  - type: job_completed
    job_name: trackA-application
    scope: all_in_wave
    description: "Every application in the wave must have completed the dev track"
```

The engine evaluates preconditions before creating a job execution and refuses the
launch with a clear message if unmet. This keeps Track B properly gated on Track A
without coupling the definitions.

Supported precondition types: `job_completed`, `artifact_exists`,
`decision_approved` (catalog decision record in `approved` state for the pattern).

## Validation rules

A definition is stored with `validation_status: invalid` and cannot be activated if
any of these fail. Report **all** errors at once, not just the first.

1. Every referenced `step` exists in `wf_step_registrations`.
2. Every declared `consumes` entry for every step is satisfied by an upstream
   `produces` in the same flow, or by an `external_inputs` entry — with a compatible
   semver range. **This is the contract-change tripwire.**
3. No cycles.
4. Every `${...}` reference resolves.
5. Decider outcomes are exhaustive.
6. Partitioned steps declare a partitioner that is importable.
7. `job_name` + `version` is unique.
8. Parameters referenced via `${params.x}` are declared.
9. Every non-optional `consumes` entry is actually **wired** — the flow node's
   `inputs` mapping must contain an entry that resolves to that artifact type, and
   the reference must resolve (rule 4 covers that part). Rule 2 only checks that the
   entry is *satisfiable* by something upstream; rule 9 checks it is *plumbed
   through*. A `consumes` entry can pass rule 2 and still never be resolved at
   runtime because nobody wrote the `inputs:` entry — this is `UNWIRED_INPUT`, and it
   is exactly the gap that let step 3 pass validation and then fail at launch with
   "input was not resolved" (`22-STEP-SEQUENCING-AND-POLICY.md` Part A). The check is
   by resolved artifact type, not by the mapping's key name — a key can legitimately
   differ from the artifact type it wires (see "Input wiring" above), so `UNWIRED_INPUT`
   fires only when *no* entry in `inputs` resolves to the required type at all.
10. Every `when:` leaf's `param` reference is declared, and every `step_status`
    reference names a step earlier in the same flow (`INVALID_STEP_STATUS_REFERENCE`
    if not). A `context` reference is **not** checked here — context keys are
    runtime job-execution state, not statically knowable; a missing one is a
    runtime concern (see "Conditional execution" above), not a load-time one.

Error format:

```json
{
  "validation_errors": [
    {
      "code": "UNSATISFIED_INPUT",
      "step": "application-fingerprinting",
      "detail": "consumes repository-inventory ^1.0.0 but the only upstream producer, repository-ingest, produces 2.0.0",
      "affected_steps": ["repository-ingest"]
    }
  ]
}
```

`UNWIRED_INPUT` looks like this:

```json
{
  "code": "UNWIRED_INPUT",
  "step": "application-fingerprinting",
  "detail": "requires solution-project-inventory ^2.0.0 but the flow node declares no inputs mapping for it. Add inputs: { solution-project-inventory: \"${artifacts.solution-project-inventory}\" }",
  "affected_steps": ["solution-discovery"]
}
```

`affected_steps` names the upstream producer(s) that could satisfy it, same as
`UNSATISFIED_INPUT` — the fix is adding the `inputs:` entry, not registering a new
producer.

### Re-validation on step registration change

`POST /api/workflow/steps` re-validates every **active** job definition that
references the step just registered, immediately — not lazily at next launch. A step
adding a new non-optional `consumes` (or otherwise changing in a way that breaks rule
2 or rule 9 for an active definition) marks that definition `validation_status:
invalid` and reports it in the registration response's `invalidated_definitions`.
The definition is **not deactivated** — an active definition drifting invalid is
surfaced, not silently torn down — see `22-STEP-SEQUENCING-AND-POLICY.md` Part A.

## Building out of order

Register all 51 steps as stubs first, then define the full flow immediately. The
whole pipeline is runnable from day one and every step reports `NOT_IMPLEMENTED`.

Job-level policy controls what that means:

```yaml
stub_policy: continue      # or halt
```

`continue` during construction gives a green end-to-end run showing which steps are
real. Switch to `halt` before anything touches a real repository.

Replacing a stub is a step registration update — change `adapter_type` from `stub`
to its real adapter and set `implementation_status: implemented`. **No job
definition change is required**, provided the declared `consumes` and `produces` are
unchanged. That is the decoupling working: whoever builds step 32 never edits the
job definition.

## Registration and activation

```
POST   /api/workflow/steps                       register or update a step
GET    /api/workflow/steps                       list, with implementation_status
POST   /api/workflow/jobs/validate               validate YAML without storing
POST   /api/workflow/jobs                        store, validate, optionally activate
POST   /api/workflow/jobs/{name}/activate/{ver}  activate a validated version
GET    /api/workflow/jobs/{name}                 current active definition
GET    /api/workflow/jobs/{name}/versions/{ver}  any stored version, active or not
DELETE /api/workflow/jobs/{name}/versions/{ver}  discard a stored version
GET    /api/workflow/jobs/{name}/parameters      declared parameters, for a launch form
POST   /api/workflow/jobs/{name}/launch          launch — see 18-API-CONVENTIONS.md Part B
```

Activation is refused for an invalid definition. Only one active version per
`job_name`.

**Storing is for definitions intended to be activated.** `POST /api/workflow/jobs`
always persists the row, valid or not (so a broken definition can be inspected and
fixed without losing the attempt) — but that persistence is exactly why it's the
wrong tool for demonstrations and experiments: a stored-but-never-activated version
sits there indefinitely, indistinguishable at a glance from a version genuinely
waiting to be activated. **Use `POST /api/workflow/jobs/validate` instead** — it runs
every rule and reports every violation with nothing stored, no version number
consumed, and nothing left to clean up afterward.

If a stored version does turn out to be scaffolding — a one-off demonstration, an
experiment that was meant to be thrown away — `DELETE .../versions/{ver}` discards it.
It refuses with 409 in two cases, both because deleting a `wf_job_definitions` row
must never leave something dangling:

- **The version is currently active.** Discarding the active definition would leave
  the engine with nothing to launch against.
- **At least one `wf_job_execution` references it.** Executions only ever run against
  the active definition at launch time, so this can only happen if the version was
  active at some point in its history — deleting it would orphan that execution's
  `job_definition_id`. This is not always obvious from `is_active` alone: a version
  can be inactive today and still have run for real in the past.

`GET .../parameters` reads the *active* definition's `parameters` block — name,
type, required, default, and description — so a launch form (or an integrator)
never has to hardcode per-job knowledge. See `18-API-CONVENTIONS.md` Part B for
the exact response shape.

Launch (`POST .../launch`) validates the supplied `{"parameters": {...}}` against
that same declared list before doing anything else. Every failure names the
offending parameter and says whether it was missing, unknown, or the wrong
declared type, and points back at `GET .../parameters`:

```json
{
  "detail": [
    {
      "field": "ingest_token",
      "message": "missing required parameter 'ingest_token'. See GET /api/workflow/jobs/phase0-repository-discovery/parameters for the full parameter list.",
      "code": "MISSING_REQUIRED_PARAMETER"
    }
  ]
}
```
