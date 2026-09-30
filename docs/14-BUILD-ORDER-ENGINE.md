# 14 — Build Order: Engine Core and Step 1

Continues from the catalog build. One prompt per step, verify at each gate, commit
before moving on.

Prerequisite: catalog build complete and tagged `catalog-v1`.

**Revision note:** this supersedes the earlier revision. Repository input is a local
folder path, not an archive upload. Phase 0 is split into a per-repository job and a
deferred estate-consolidation job. If your `docs/` contains an older copy of this
file or of `15`, replace both.

---

## Step E0 — Add the engine specs to the repo

Copy `10-ENGINE-CONCEPTS.md`, `11-STEP-CONTRACT.md`, `12-JOB-DEFINITION-FORMAT.md`,
`13-STEP-001-REPOSITORY-INGEST.md`, `15-REPOSITORY-INGEST-UI.md`,
`16-DASHBOARD-SPEC.md` and this file into `docs/`.

```powershell
git add -A
git commit -m "Engine specs: concepts, contract, job format, step 1, registration UI, dashboard"
```

---

## Step E1 — Job repository schema

**Prompt:**

```
Read docs/10-ENGINE-CONCEPTS.md and docs/15-REPOSITORY-INGEST-UI.md Part C.

Implement the job repository schema: all six wf_ tables from docs/10 exactly as
specified, including CHECK constraints and all listed indexes.

Also implement the `repositories` table from docs/15 Part C — note this REPLACES the
table definition in docs/13. It includes three partial unique indexes (on
clone_url_normalised, root_folder_name, and local_path_normalised, each WHERE
deleted_at IS NULL) plus the normalised columns.

Add all seven tables to app/models.py alongside the existing catalog models and
generate a single Alembic migration.

Run the migration and show me the DDL for the new tables only.

Do not implement the engine runtime, adapters, or any step yet.
```

**Gate:** seven new tables. Verify all three partial unique indexes on `repositories`
carry their `WHERE deleted_at IS NULL` clause, that `JSONB` columns are JSONB rather
than JSON, and that the `criticality` and `retirement_status` CHECK constraints exist.

---

## Step E2 — Step contract and registration

**Prompt:**

```
Read docs/11-STEP-CONTRACT.md.

Implement:
- Pydantic models for StepContext and StepResult, envelope_version 1.0, in
  app/workflow/contract.py
- a semver range matching helper supporting ^, ~ and explicit ranges
- the step registration service and the /api/workflow/steps endpoints
- contract-change detection at registration: when a step registers a new major
  version of an artifact type it produces, return a warning listing every registered
  step whose consumes range is now incompatible, with their owner_team

Register all 51 lifecycle steps as stubs, with correct lifecycle_step_no,
display_name and owner_code taken from the v2 architecture document sections 6.2
through 6.5. Derive a slug step_name from each display name. All stubs get
adapter_type: stub, exit_status NOT_IMPLEMENTED, empty consumes and produces, and
implementation_status: stub.

Show me the registered step list grouped by phase.
```

**Gate:** 51 stubs registered. Spot-check step 1 is `repository-ingest`, step 23 is
owner `C`, step 28 is owner `S`, step 50 is owner `H`. Test the contract-change
warning by registering a throwaway step producing `repository-inventory@2.0.0` and
confirming it names the consumers — then delete the throwaway.

---

## Step E3 — Adapters

**Prompt:**

```
Read docs/11-STEP-CONTRACT.md.

Implement the adapter layer in app/workflow/adapters/:
- base adapter interface
- python adapter (in-process import and call)
- process adapter (stdin/stdout JSON, exit code handling, timeout, stderr capture)
- http adapter (sync plus optional polling, ${VAR} env resolution)
- event adapter (registered, raises NOT_IMPLEMENTED)
- stub adapter

Each adapter takes a StepContext and returns a StepResult. Checksum verification on
declared outputs happens in the adapter base, not in each adapter.

Include unit tests for the process adapter using a trivial echo script that reads
stdin and writes a valid StepResult, plus cases for non-zero exit, unparseable
stdout, and timeout.
```

**Gate:** process adapter tests pass. This adapter is how other teams contribute
steps, so verify all four of its failure modes behave as specified.

---

## Step E4 — Job definition loader and validator

**Prompt:**

```
Read docs/12-JOB-DEFINITION-FORMAT.md and docs/15-REPOSITORY-INGEST-UI.md Part A.

Implement the job definition loader and validator in app/workflow/definition/:
- YAML parsing into a typed model
- ${params.x}, ${external.x}, ${steps.x.outputs.y}, ${artifacts.x} reference
  resolution
- all 8 validation rules, reporting ALL errors at once in the specified format
- the /api/workflow/jobs endpoints: validate, store, activate, get

Then write backend/app/jobs/phase0-repository-discovery.yaml exactly as specified in
docs/15 Part A — per-repository scope with parameters engagement_id, repository_id
and ingest_token, steps 1, 2, 3, 4, 8, 9, 10, and stub_policy: continue.

phase0-estate-consolidation is now defined too (engagement_id + run_token, steps 5,
6, 7, 11, 12, stub_policy: continue). It was deferred here on the grounds that all
five of its steps are stubs; defining it ahead of them turned out to be the right
order, because removing the estate-completeness precondition is a job-definition
change that step 5 would otherwise have inherited as a blocker.

Update docs/12-JOB-DEFINITION-FORMAT.md to reflect the two-job split, replacing any
reference to phase0-estate-discovery.

Validate the definition and show me the result. Then deliberately break it: change
step 1's registered produces to repository-inventory@2.0.0 while a downstream step
consumes ^1.0.0, and re-validate to prove UNSATISFIED_INPUT fires and names both
steps. Revert afterwards.
```

**Gate:** the definition validates. The deliberate break produces
`UNSATISFIED_INPUT` naming both sides. **This is the contract tripwire and it is the
single most important thing to confirm in the whole engine build.** Do not proceed
until it behaves exactly as specified.

Note: with all steps as stubs having empty `consumes` and `produces`, you will need
to temporarily give one downstream step a `consumes` entry to exercise the break test.
Revert that too.

---

## Step E5 — Execution runtime

**Prompt:**

```
Read docs/10-ENGINE-CONCEPTS.md and docs/12-JOB-DEFINITION-FORMAT.md.

Implement the runtime in app/workflow/runtime/:
- job launch: parameter validation, job_key computation, instance get-or-create,
  precondition evaluation, execution creation
- sequential flow execution with per-step status and context persistence
- input resolution from wf_artifacts, with version range re-check before invoke
- artifact registration with checksum verification
- restart: resume from the first non-COMPLETED step, honouring
  allow_start_if_complete and start_limit
- AWAITING_APPROVAL handling: end the execution cleanly, support resume
- exit status handling including NOOP, NOT_IMPLEMENTED and stub_policy

Endpoints:
  POST /api/workflow/jobs/{name}/launch
  POST /api/workflow/executions/{id}/resume
  POST /api/workflow/executions/{id}/stop
  GET  /api/workflow/executions/{id}
  GET  /api/workflow/executions?job_name=&status=
  GET  /api/workflow/executions/{id}/steps

Defer splits, deciders and partitioning to E8. Sequential only.

Then launch phase0-repository-discovery manually via the API for engagement
client-a-ocp4 with a dummy repository_id and a generated ingest_token, and show me
the execution record with all 7 steps reporting NOT_IMPLEMENTED.
```

**Gate:** an end-to-end run of all 7 stub steps, `COMPLETED` overall with every step
`NOT_IMPLEMENTED`. **A green pipeline before a single step exists** — that is the
out-of-order construction property proven.

---

## Step E6 — Step 1 implementation

**Prompt:**

```
Read docs/13-STEP-001-REPOSITORY-INGEST.md and docs/15-REPOSITORY-INGEST-UI.md
Parts B and C.

First update docs/13: replace its four source types with the two in docs/15 Part B —
local_path (implemented, reads the folder in place, never copies) and git_clone
(returns NOT_IMPLEMENTED). Replace its repositories table definition with a pointer
to docs/15 Part C. Remove all references to manifest and local_directory sources and
to concurrent cloning.

Then implement app/steps/repository_ingest.py:
- reads local_path from the repositories row, not from config
- verifies the path still exists, FAILED with a clear message if not
- detects .git; resolves HEAD SHA, current branch and origin remote URL when present;
  sets has_git_history false and a null commit SHA when absent
- performs clone URL verification per docs/15 Part D, setting clone_url_verification
- computes size and file-count metrics, skipping .git, node_modules, bin, obj,
  packages
- writes nothing into the registered repository folder
- emits the deterministic repository-inventory artifact
- includes the __main__ entry for standalone stdin/stdout invocation

Include test fixtures: a folder with .git, a folder without .git, a non-existent
path, and sample-context.json.

Then update the step registration for repository-ingest to adapter_type python,
implementation_status implemented, with the declared consumes and produces from the
spec. Confirm phase0-repository-discovery still validates WITHOUT any change to the
YAML.

Run it against a local folder I will provide and show me the artifact plus the
repositories row.
```

**Gate:** two things matter most:

- **No job definition change was needed** when the stub became real. That is the
  decoupling property proven.
- Phase 0 wrote nothing into the registered folder. Verify with `git status` in the
  sample repo — it must be clean.

Prepare a sample folder first: clone three or four public .NET repositories somewhere
like `D:\samples\dotnet-legacy`.

---

## Step E7 — Registration UI, API and dashboard

**Prompt:**

```
Read docs/15-REPOSITORY-INGEST-UI.md Parts D through G, and docs/16-DASHBOARD-SPEC.md.

Implement:
- POST inspect-path, returning detected git metadata, estimates, duplicate conflict
  and warnings
- POST register for source_type local_path, with all Part E validation, clone URL
  verification, and the three duplicate checks plus the nesting guard
- POST register for source_type git_clone returning 501
- all supporting endpoints: list, detail, PUT (name/description/tags/criticality/
  retirement_status/owner/notes only), soft delete, restore, rescan, verify-path,
  executions
- synchronous job instance and execution creation, asynchronous execution via
  BackgroundTasks, and the startup reconciliation for executions orphaned in STARTED
- GET /api/workflow/capabilities
- the Repositories tab per Part F, with the registration drawer and disabled
  provider options
- the Dashboard tab per docs/16

Record the single-machine, single-operator operating model from docs/15 in CLAUDE.md.

Then walk the acceptance criteria at the end of both specs.
```

**Gate:** work the acceptance criteria. Four to verify by hand:

- Register the same clone URL twice → 409 naming the existing repository
- Register a parent of an already-registered path → 409
- Enter a clone URL that does not match the folder's git remote → `mismatch`, warned
  but allowed
- Applications and patterns columns show `—`, not `0`

Tag `engine-v1` here.

---

## Step E8 — Splits, deciders, partitioning

**Prompt:**

```
Read docs/12-JOB-DEFINITION-FORMAT.md.

Add to the runtime: split execution with max_concurrency, decision steps with
deciders and exhaustive outcome validation, and partitioned steps with partitioner,
aggregate_outputs, failure_policy and max_failed_partitions.

Add app/partitioners/by_repository.py partitioning over the repositories table, and
app/deciders/ with a trivial always-true decider for testing.

Prove each construct with a throwaway job definition exercising a split, a decision
and a partitioned step over the repositories registered in E7.
```

**Gate:** all three constructs work. Partitioning over real repository rows is what
step 3 will need, so verify `continue_on_error` with a threshold behaves correctly.

---

## Step E9 — Workflow UI

**Prompt:**

```
Read docs/04-FRONTEND-SPEC.md for conventions.

Add a Workflow tab. The Repositories and Dashboard tabs already exist from E7 — do
not rebuild them.

Workflow tab:
- job list with active definition version and last execution status
- manual launch form with parameter inputs
- execution list with batch status, exit status, timings
- execution detail: step timeline showing status, exit status, metrics, duration, and
  expandable stdout/stderr tails
- resume button on AWAITING_APPROVAL executions, restart on FAILED
- artifact list per execution with type, version, size and checksum

Engagement-scoped, following the existing view switcher pattern. Hidden in Master
Catalog view.
```

**Gate:** launch a job from the UI, watch the step timeline populate, inspect the
artifact and drill from a dashboard row into an execution.

---

## Notes

- **Commit after every gate.** Tag `engine-v1` after E7.
- E4 and E5 are load-bearing. If the contract tripwire in E4 or the stub pipeline in
  E5 misbehaves, stop and fix before E6.
- When a colleague delivers a step, the integration path is: they conform to
  `11-STEP-CONTRACT.md`, you register it with `adapter_type: process` or `http`, and
  the job definition does not change. If registering their step requires editing a
  job definition, something has drifted from the spec.
- Steps 2, 3, 4, 8, 9 and 10 are now independent parallel work — each already has a
  slot in `phase0-repository-discovery`. Each needs only its own spec file following
  the shape of `13-STEP-001-REPOSITORY-INGEST.md`, and replacing its stub requires no
  job definition change.
- Steps 5, 6, 7, 11 and 12 need `phase0-estate-consolidation`, which is now defined
  (`backend/app/jobs/phase0-estate-consolidation.yaml`). Replacing any of their stubs
  requires no job definition change.
