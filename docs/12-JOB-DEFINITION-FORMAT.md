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
- `phase0-estate-consolidation` — engagement-scoped, steps 5, 6, 7, 11, 12. **Not
  defined yet** — all five steps are stubs. Its precondition, once defined, will be
  that every in-scope, non-deleted repository has a completed
  `phase0-repository-discovery` execution.

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
  - name: source_type
    type: string
    required: false
    default: manifest

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
POST /api/workflow/steps                       register or update a step
GET  /api/workflow/steps                       list, with implementation_status
POST /api/workflow/jobs/validate               validate YAML without storing
POST /api/workflow/jobs                        store, validate, optionally activate
POST /api/workflow/jobs/{name}/activate/{ver}  activate a validated version
GET  /api/workflow/jobs/{name}                 current active definition
```

Activation is refused for an invalid definition. Only one active version per
`job_name`.
