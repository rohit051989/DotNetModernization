# 02 — Data Model

PostgreSQL 16. All tables use `TIMESTAMPTZ` with `now()` defaults for
`created_at` / `updated_at`. `updated_at` is maintained by the application layer on
write.

## Enumerated values

Implement as Postgres `TEXT` columns with `CHECK` constraints, not native enum
types — new values will be added and altering a native enum is painful.

| Concept | Allowed values |
|---|---|
| `lifecycle_status` | `draft`, `active`, `deprecated` |
| `consumer_impact` | `none`, `low`, `medium`, `high` |
| `effort` | `low`, `medium`, `high` |
| `decision_status` | `parked`, `in_review`, `approved`, `superseded` |

**Semantics of `consumer_impact`** — how much existing callers of the application
are affected:
- `none` — contract, endpoints and payloads unchanged; callers need no change
- `low` — internal change only; callers unaffected but configuration or hosting moves
- `medium` — callers may need reconfiguration but not code change
- `high` — callers must change code or contracts

## Table: `patterns`

Layer 1. Client-agnostic. Never contains engagement data.

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT` PK | Human-readable slug, e.g. `wcf-iis-servicemodel`. Lowercase, hyphenated |
| `name` | `TEXT` NOT NULL | Display name |
| `summary` | `TEXT` NOT NULL | One sentence |
| `description` | `TEXT` | Longer markdown description |
| `legacy_stack` | `TEXT` NOT NULL | e.g. `.NET Framework 4.7`, `SSIS / SQL Server 2016` |
| `category` | `TEXT` NOT NULL | `web-api`, `web-ui`, `service`, `batch`, `library`, `data-etl` |
| `detection_rules` | `JSONB` NOT NULL | See structure below |
| `typical_indicators` | `TEXT` | Human-readable hints for a reviewer |
| `known_risks` | `TEXT` | What tends to go wrong with this pattern |
| `status` | `TEXT` NOT NULL DEFAULT `'active'` | `lifecycle_status` |
| `version` | `INTEGER` NOT NULL DEFAULT 1 | Bumped on material change |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |
| `deleted_at` | `TIMESTAMPTZ` NULL | Soft delete marker. See "Soft delete vs deprecate" below |
| `deleted_by` | `TEXT` NULL | Identity of whoever soft-deleted the row, when known |

### `detection_rules` JSONB structure

Keep it declarative so a future scanner can execute it without code changes.
All arrays are optional; an empty or absent array means "no constraint".

```json
{
  "target_frameworks": ["netcoreapp2.0", "netcoreapp2.1", "netcoreapp2.2"],
  "required_namespaces": ["Microsoft.AspNetCore.Mvc"],
  "forbidden_namespaces": ["System.ServiceModel"],
  "required_packages": ["Microsoft.AspNetCore.App"],
  "file_globs": ["**/Startup.cs", "**/Controllers/*.cs"],
  "forbidden_file_globs": ["**/*.svc"],
  "project_properties": { "OutputType": "Library" },
  "config_markers": ["system.serviceModel"],
  "confidence_weight": 1.0,
  "notes": "Free text explaining the rule's intent"
}
```

`confidence_weight` allows a future scanner to rank competing matches when an
application matches more than one pattern.

## Table: `target_state_options`

Layer 2. Grows across clients. Still client-agnostic.

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT` PK | Slug, e.g. `corewcf-net10` |
| `pattern_id` | `TEXT` NOT NULL FK → `patterns.id` | `ON DELETE RESTRICT` |
| `name` | `TEXT` NOT NULL | |
| `summary` | `TEXT` NOT NULL | One sentence |
| `target_stack` | `TEXT` NOT NULL | e.g. `.NET 10 + CoreWCF`, container on OCP4 |
| `consumer_impact` | `TEXT` NOT NULL | `consumer_impact` |
| `effort` | `TEXT` NOT NULL | `effort` |
| `linux_compatible` | `BOOLEAN` NOT NULL DEFAULT true | |
| `container_ready` | `BOOLEAN` NOT NULL DEFAULT true | Can it run as a container on OCP4 |
| `is_lift_and_shift` | `BOOLEAN` NOT NULL DEFAULT false | True when it preserves behaviour and contracts |
| `engine_support` | `JSONB` | See below |
| `playbook_md` | `TEXT` | Markdown playbook — the reusable IP |
| `prerequisites` | `TEXT` | |
| `known_limitations` | `TEXT` | |
| `status` | `TEXT` NOT NULL DEFAULT `'active'` | `lifecycle_status` |
| `version` | `INTEGER` NOT NULL DEFAULT 1 | |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |
| `deleted_at` | `TIMESTAMPTZ` NULL | Soft delete marker. See "Soft delete vs deprecate" below |
| `deleted_by` | `TEXT` NULL | Identity of whoever soft-deleted the row, when known |

Unique constraint on `(pattern_id, name)`.

### `engine_support` JSONB structure

Records what the bought engine can do for this option, and what we must supply.
This is what makes the coverage argument measurable later.

```json
{
  "engine": "github-copilot-app-modernization",
  "coverage": "strong",
  "scenarios": ["dotnet-upgrade"],
  "skills": ["upgrade-wcf-to-corewcf"],
  "gaps": [
    "OCP4 containerization",
    "Windows-to-Linux remediation beyond Azure targets"
  ],
  "custom_skills_required": ["ocp4-container-packaging"]
}
```

`coverage` allowed values: `none`, `partial`, `strong`.

## Table: `engagements`

Layer 3 container. One row per client program.

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT` PK | Slug, e.g. `client-a-ocp4` |
| `client_name` | `TEXT` NOT NULL | |
| `description` | `TEXT` | |
| `target_platform` | `TEXT` | e.g. `Linux / OpenShift Container Platform 4` |
| `default_posture` | `TEXT` NOT NULL DEFAULT `'lift-and-shift'` | Records the engagement's default bias |
| `status` | `TEXT` NOT NULL DEFAULT `'active'` | `lifecycle_status` |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |
| `deleted_at` | `TIMESTAMPTZ` NULL | Soft delete marker. See "Soft delete vs deprecate" below |
| `deleted_by` | `TEXT` NULL | Identity of whoever soft-deleted the row, when known |

## Table: `decision_records`

Layer 3. Engagement-specific. Never referenced by patterns or target states.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | Generated |
| `engagement_id` | `TEXT` NOT NULL FK → `engagements.id` | |
| `pattern_id` | `TEXT` NOT NULL FK → `patterns.id` | |
| `selected_target_state_id` | `TEXT` NULL FK → `target_state_options.id` | NULL while `parked` |
| `candidates_considered` | `JSONB` | Array of target state option ids presented |
| `evaluation_notes` | `TEXT` | OCP4 fit, contract constraints, effort, readiness |
| `forcing_factor` | `TEXT` | Required when the selected option is not the lowest-impact candidate |
| `rationale` | `TEXT` | |
| `approver_name` | `TEXT` | |
| `approver_role` | `TEXT` | |
| `decision_date` | `DATE` | |
| `status` | `TEXT` NOT NULL DEFAULT `'parked'` | `decision_status` |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |
| `deleted_at` | `TIMESTAMPTZ` NULL | Soft delete marker. See "Soft delete vs deprecate" below |
| `deleted_by` | `TEXT` NULL | Identity of whoever soft-deleted the row, when known |

Unique constraint on `(engagement_id, pattern_id)` where `status <> 'superseded'
AND deleted_at IS NULL` — one live decision per pattern per engagement. Implement
as a partial unique index. Soft-deleting a decision record (not exposed via the API
yet, but the column exists for consistency) frees this constraint exactly as
superseding it does, so a new decision can be recorded in its place.

### Validation rules (enforce in the API layer, not just the DB)

1. `status = 'approved'` requires `selected_target_state_id`, `rationale`,
   `approver_name` and `decision_date` to be non-null.
2. `selected_target_state_id` must belong to the same `pattern_id`. Reject
   cross-pattern references with a 422.
3. If the selected option is **not** the lowest `consumer_impact` among
   `candidates_considered`, `forcing_factor` is required. This is the
   lift-and-shift default made enforceable rather than advisory.
4. Soft-deleting a pattern or target state option that is referenced by a
   non-deleted, non-superseded decision record must be refused — supersede the
   decision, or deprecate the pattern/option instead. See "Soft delete vs
   deprecate" below: referential guards only ever count non-deleted referencing
   records, since a deleted reference no longer represents live use.

## Soft delete vs deprecate

These are two orthogonal mechanisms. Soft delete is **not** a fourth
`lifecycle_status` value — it is tracked independently via `deleted_at` /
`deleted_by` on every table, alongside whatever `status` already is.

- **Deprecate** — a catalog lifecycle state. Sets `status = 'deprecated'`. The
  record stays fully visible in the UI and API; it is simply hidden from the
  *default* list view and surfaced again via the status filter. This is the
  existing, unchanged behaviour: use it when a pattern or target state option is
  no longer the recommended path but is still real, historical catalog content.
- **Soft delete** — removal. Sets `deleted_at` (and optionally `deleted_by`).
  The record disappears from all normal API responses and from the UI entirely,
  regardless of its `status`. `status` itself is left untouched, so restoring the
  record returns it to exactly the lifecycle state it was in before deletion.
  Use it when a record should not have existed, or should no longer be
  discoverable at all — a stronger action than deprecating.
- **Restore** — clears `deleted_at` (and `deleted_by`). Backend-only for now;
  there is no UI control for it. Intended to become an admin-only operation once
  authentication exists; it is currently unguarded like everything else in this
  build.

A record can be deprecated and soft-deleted independently and in either order:
deprecating a soft-deleted record (or soft-deleting a deprecated one) is a
well-defined, if unusual, state — `status='deprecated', deleted_at=<timestamp>`.
Restoring it later reveals a deprecated record, not an active one, which is the
correct behaviour since restore must not silently change lifecycle state.

## Indexes

- `patterns(status)`, `patterns(category)`
- `patterns(id) WHERE deleted_at IS NULL` — partial index for the default
  (non-deleted) read path, which is the overwhelming majority of queries
- `target_state_options(pattern_id)`, `target_state_options(status)`
- `target_state_options(id) WHERE deleted_at IS NULL` — same rationale as above
- `decision_records(engagement_id)`, `decision_records(pattern_id)`,
  `decision_records(status)`

## Design notes

- Slug primary keys on patterns and target states are deliberate: they appear in
  export files, playbook folder paths and future accelerator bindings, so they must
  be stable and human-readable. Do not switch to surrogate integer keys.
- The `patterns` and `target_state_options` tables must remain free of any
  engagement reference. That separation is the product thesis; enforce it in review.
