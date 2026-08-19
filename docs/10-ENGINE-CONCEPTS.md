# 10 — Engine Concepts

The execution engine for the modernization platform. Modelled deliberately on
Spring Batch semantics — this is a batch job executor, not a DAG runner and not an
agentic planner.

## Non-negotiable principle

**The engine never reasons.** It resolves a declared graph, invokes steps, records
state. Individual steps may call an LLM; the engine does not decide what runs next.
Control flow comes from job definitions and deciders, both deterministic.

## Vocabulary

Use these terms exactly, in code, APIs and UI.

| Term | Meaning |
|---|---|
| **Job** | A phase from the lifecycle. `phase0-estate-discovery`, `phase1-governance`, `trackA-application`, `trackB-wave` |
| **Job definition** | Declarative YAML describing a job's steps and flow. Versioned |
| **Job parameters** | The identity of a run: engagement id, plus application id or wave id as applicable |
| **Job instance** | A job name + a unique hash of its parameters. Re-running the same parameters resumes the same instance rather than creating a new one |
| **Job execution** | One attempt at a job instance. An instance may have several executions across restarts |
| **Step** | One lifecycle step, 1–51. Independently implemented and independently executable |
| **Step execution** | One attempt at a step within a job execution |
| **Execution context** | Key/value state. Job-scoped context is visible to all steps; step-scoped context survives restart of that step |
| **Artifact** | A typed, versioned output of a step, referenced by URI and checksum. How steps pass real data |
| **Decider** | A deterministic function returning a named outcome that selects the next flow branch |
| **Partition** | A slice of work within a step, executed in parallel by workers |
| **Job repository** | The Postgres tables recording all of the above |

## Statuses

**Batch status** — the engine's own view. Values:
`STARTING`, `STARTED`, `COMPLETED`, `FAILED`, `STOPPING`, `STOPPED`, `ABANDONED`, `UNKNOWN`

**Exit status** — what a step reports. Drives flow decisions. Core values:

| Exit status | Meaning |
|---|---|
| `COMPLETED` | Success. Continue |
| `FAILED` | Failure. Job halts, restartable from this step |
| `NOOP` | Nothing to do; treated as success. E.g. characterization tests skipped because coverage was sufficient |
| `AWAITING_APPROVAL` | Human gate reached. Job execution ends cleanly; a separate trigger resumes it |
| `NOT_IMPLEMENTED` | Step is registered but has no implementation yet. Behaviour configurable per job: halt or continue |
| `SKIPPED` | The engine decided not to run this step — by policy, a false `when:` condition, or a gate's tier not applying. A **success** outcome for flow purposes: the job continues. See `skip_reason` below and `22-STEP-SEQUENCING-AND-POLICY.md` Parts B–D |
| Custom | Any uppercase token, used by deciders for branching |

`AWAITING_APPROVAL` matters. Human gates in this lifecycle take days (target state
approval, plan approval, code review, release approval). The job execution must end
rather than block a worker. Resumption is triggered externally — a merged pull
request, an API call — which creates a new job execution continuing from the gate.

`NOT_IMPLEMENTED` is what makes out-of-order construction possible. Every step in
the lifecycle can be registered as a stub from day one, so a full pipeline is
runnable end to end before most steps exist.

`SKIPPED` is engine-assigned, never step-reported — unlike every other value in this
table, no adapter is invoked to produce it. The engine decides before invocation
(`22-STEP-SEQUENCING-AND-POLICY.md` Part B's precedence: policy, then `when:`, then
`gate.tier_condition`, then `stub_policy`) and writes the `wf_step_executions` row
itself. A skipped step still always gets a row — never an absent one — so the
timeline never shows a gap indistinguishable from a step that never ran.

## Restart semantics

- Restart resumes from the first non-`COMPLETED` step of the previous execution.
- A step may declare `allow_start_if_complete: true` to always re-run (useful for
  verification steps).
- `start_limit` caps retry attempts per step; exceeding it marks the job `ABANDONED`.
- Restart requires identical job parameters. Different parameters means a different
  job instance.

## Job repository schema

All tables prefixed `wf_`, in the same Postgres database as the catalog, separate
Alembic migration branch not required — same migration chain is fine.

### `wf_step_registrations`

The registry of known steps. A step must be registered before a job definition can
reference it. This table is what makes contract change detectable.

| Column | Type | Notes |
|---|---|---|
| `step_name` | `TEXT` PK | Slug, e.g. `repository-ingest` |
| `lifecycle_step_no` | `INTEGER` | 1–51, from the v2 document. Nullable for helper steps |
| `display_name` | `TEXT` NOT NULL | |
| `owner_code` | `TEXT` NOT NULL | `P`, `C`, `S`, `H` per the lifecycle document |
| `version` | `TEXT` NOT NULL | Semver of the step implementation |
| `adapter_type` | `TEXT` NOT NULL | `python`, `process`, `http`, `event`, `stub` |
| `adapter_config` | `JSONB` NOT NULL | See `11-STEP-CONTRACT.md` |
| `consumes` | `JSONB` NOT NULL | Array of `{type, version_range}` |
| `produces` | `JSONB` NOT NULL | Array of `{type, version}` |
| `implementation_status` | `TEXT` NOT NULL | `stub`, `implemented`, `deprecated` |
| `owner_team` | `TEXT` | Who built it — relevant when steps come from other devs |
| `registered_at` / `updated_at` | `TIMESTAMPTZ` | |

### `wf_job_definitions`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `job_name` | `TEXT` NOT NULL | |
| `version` | `INTEGER` NOT NULL | Incremented on any change |
| `definition` | `JSONB` NOT NULL | Parsed YAML |
| `checksum` | `TEXT` NOT NULL | Of the source YAML |
| `validation_status` | `TEXT` NOT NULL | `valid`, `invalid` |
| `validation_errors` | `JSONB` | Populated when invalid |
| `is_active` | `BOOLEAN` NOT NULL DEFAULT true | Only one active version per job_name |
| `created_at` | `TIMESTAMPTZ` | |

Unique on `(job_name, version)`. Partial unique on `job_name where is_active`.

### `wf_job_instances`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `job_name` | `TEXT` NOT NULL | |
| `job_key` | `TEXT` NOT NULL | SHA-256 of canonicalised parameters |
| `parameters` | `JSONB` NOT NULL | |
| `created_at` | `TIMESTAMPTZ` | |

Unique on `(job_name, job_key)`.

### `wf_job_executions`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `job_instance_id` | `UUID` NOT NULL FK | |
| `job_definition_id` | `UUID` NOT NULL FK | Which definition version ran |
| `execution_number` | `INTEGER` NOT NULL | 1, 2, 3… per instance |
| `batch_status` | `TEXT` NOT NULL | |
| `exit_status` | `TEXT` | |
| `exit_message` | `TEXT` | |
| `execution_context` | `JSONB` NOT NULL DEFAULT `'{}'` | Job-scoped state |
| `started_at` / `ended_at` | `TIMESTAMPTZ` | |
| `engine_version` | `TEXT` NOT NULL | Recorded per the v2 doc's versioning rule |
| `triggered_by` | `TEXT` | `manual`, `api`, `resume`, `schedule` |
| `created_at` | `TIMESTAMPTZ` | |

### `wf_step_executions`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `job_execution_id` | `UUID` NOT NULL FK | |
| `step_name` | `TEXT` NOT NULL | |
| `step_version` | `TEXT` NOT NULL | Recorded at execution time |
| `partition_key` | `TEXT` | Null for unpartitioned steps |
| `attempt` | `INTEGER` NOT NULL DEFAULT 1 | |
| `batch_status` | `TEXT` NOT NULL | |
| `exit_status` | `TEXT` | |
| `exit_message` | `TEXT` | |
| `skip_reason` | `TEXT` | Null unless `exit_status` is `SKIPPED`. One of `POLICY_DISABLED`, `CONDITION_FALSE`, `TIER_NOT_APPLICABLE`, `UPSTREAM_SKIPPED`, `CASCADED_POLICY` — see `22-STEP-SEQUENCING-AND-POLICY.md` Part D |
| `read_count` / `write_count` / `skip_count` / `commit_count` | `INTEGER` DEFAULT 0 | Chunk metrics |
| `execution_context` | `JSONB` NOT NULL DEFAULT `'{}'` | Step-scoped state |
| `stdout_tail` / `stderr_tail` | `TEXT` | Last 8KB, for diagnosis without leaving the UI |
| `started_at` / `ended_at` | `TIMESTAMPTZ` | |

Index on `(job_execution_id, step_name)`.

### `wf_artifacts`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `step_execution_id` | `UUID` NOT NULL FK | Producer |
| `job_execution_id` | `UUID` NOT NULL FK | Denormalised for query convenience |
| `artifact_type` | `TEXT` NOT NULL | e.g. `repository-inventory` |
| `artifact_version` | `TEXT` NOT NULL | Semver |
| `uri` | `TEXT` NOT NULL | File path or object-store URI |
| `checksum` | `TEXT` NOT NULL | SHA-256 of content |
| `size_bytes` | `BIGINT` | |
| `metadata` | `JSONB` | |
| `created_at` | `TIMESTAMPTZ` | |

Index on `(job_execution_id, artifact_type)`.

## Contract change detection

This is the mechanism that answers "how does the engine know when a contract
changed".

**At step registration:** if a step's `produces` declares a new major version of an
artifact type, the engine queries every registered step whose `consumes` includes
that type with an incompatible range, and reports them. Registration succeeds but
returns a warning listing affected steps and their owners.

**At job definition load:** full static validation. For every step in the flow,
every declared `consumes` entry must be satisfiable by an upstream step's
`produces` within the same job, or by an artifact declared as an external job
input. Unsatisfied inputs mean the definition is marked `invalid` and cannot be
activated. **Nothing executes until this passes.**

**At runtime, before invoking a step:** the engine resolves each declared input to
a concrete artifact row and re-checks the version against the range. A mismatch
fails the step with an explicit message rather than passing bad data downstream.

Three layers, cheapest first. The static layer is the one that matters — it turns
a contract change from a runtime surprise into a load-time error naming both sides.

## What the engine does not do

- Does not clone repositories, parse code, or call transformation engines. Steps do.
- Does not decide sequence beyond what job definitions declare.
- Does not retry indefinitely. `start_limit` is mandatory.
- Does not hold worker threads waiting for humans. See `AWAITING_APPROVAL`.
