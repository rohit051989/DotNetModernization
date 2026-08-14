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

## Master catalog vs client catalog

Two views over the same patterns, not two copies of the data.

- **Master catalog** — `patterns` and `target_state_options`. Our reusable IP:
  definition, detection rules, target state options, and which option is
  *recommended*. Client-agnostic. Editable only through the master endpoints.
- **Client catalog** — the master catalog as seen and acted on by one engagement,
  via `engagement_patterns` (the overlay, defined below) and that engagement's
  `decision_records`. Definition, detection rules and target state options are
  read-only here; what's editable is the engagement's own posture toward the
  pattern (deferred vs active, deleted vs present) and its decision.

Deleting or deferring a pattern in one engagement's client catalog never touches
the master pattern and never affects any other engagement. Deleting or
deprecating a pattern in the master catalog affects everyone — that's the
tradeoff for it being shared IP, which is exactly why the master delete guard
(below) checks decisions across every engagement before allowing it.

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
| `is_recommended` | `BOOLEAN` NOT NULL DEFAULT false | The master catalog's recommendation for this pattern, independent of any client's decision. At most one `true` per `pattern_id` — enforced in the API layer, not a DB constraint |
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
4. Soft-deleting or deprecating a **master** pattern is refused only by
   non-superseded, non-deleted decision records against it, in **any**
   engagement — never by the mere existence of its target state options. When a
   master pattern is soft-deleted or deprecated, that action **cascades** to all
   of its (non-deleted) target state options: they are soft-deleted, or set to
   `status = 'deprecated'`, alongside the pattern. There is no independent path
   to keep a target state option live under a deleted or deprecated pattern.
   Referential guards only ever count non-deleted referencing records, since a
   deleted reference no longer represents live use. This is the master-level
   guard; the client-level guard on `engagement_patterns` is separate and
   described in that table's section below.

## Table: `engagement_patterns`

The client-scoped overlay. One row represents one engagement's deviation from
the default view of one master pattern — deferred instead of active, or deleted
from that engagement's catalog. It carries no definition data; the pattern's
name, detection rules, target state options and recommendation always come from
the master tables.

| Column | Type | Notes |
|---|---|---|
| `engagement_id` | `TEXT` NOT NULL FK → `engagements.id` | |
| `pattern_id` | `TEXT` NOT NULL FK → `patterns.id` | |
| `scope_status` | `TEXT` NOT NULL DEFAULT `'active'` CHECK IN (`active`, `deferred`) | Client-level posture toward this pattern in this engagement |
| `deferred_reason` | `TEXT` | Why this engagement isn't tackling the pattern right now |
| `deleted_at` / `deleted_by` | `TIMESTAMPTZ` / `TEXT` NULL | Client-scoped soft delete — see below |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |

Unique constraint on `(engagement_id, pattern_id)`.

### Overlay rows are lazy

**Absence of a row means the pattern is `active` and not deleted for that
engagement.** A row is only created the first time an engagement defers or
deletes a pattern — via upsert, not via any bulk provisioning step. There is no
backfill when a new master pattern is added: it simply appears, active and
undeleted, in every engagement's client catalog immediately, because "no row"
already means exactly that. Do not write code that assumes a row exists for
every `(engagement, pattern)` pair; always treat a missing row as
`scope_status='active', deleted_at=NULL`.

### Client-level soft delete guard

Deleting the overlay row (client-scoped soft delete) is refused with 409 if a
non-superseded decision record exists for that specific `(engagement_id,
pattern_id)` — supersede or remove the decision first. This is independent of
the master guard: an engagement can be blocked from removing a pattern from its
own catalog by its own decision, regardless of what any other engagement has
decided, and regardless of whether the master pattern itself could be deleted.

Deferring never touches the decision record and is always allowed.

### Master `deprecated` vs client `deferred`

Deliberately different words for deliberately different concepts, at different
layers:

- **`deprecated`** (master, `patterns.status` / `target_state_options.status`) —
  retired from the catalog for everyone. Nobody should be pointed at this
  pattern or option as a going-forward choice, in any engagement.
- **`deferred`** (client, `engagement_patterns.scope_status`) — not being
  tackled in *this* engagement *right now*. The master pattern is entirely
  healthy and active; this one engagement has simply chosen to sequence it
  later. Another engagement may be actively deciding on the same pattern at the
  same time.

Never conflate the two in code, copy, or conversation — a deferred pattern is
not deprecated, and a deprecated pattern is not merely deferred everywhere.

## Soft delete vs deprecate

These are two orthogonal mechanisms. Soft delete is **not** a fourth
`lifecycle_status` value — it is tracked independently via `deleted_at` /
`deleted_by` on every table, alongside whatever `status` already is.

- **Deprecate** — a catalog lifecycle state. Sets `status = 'deprecated'`. The
  record stays fully visible in the UI and API; it is simply hidden from the
  *default* list view and surfaced again via the status filter. Applied to a
  master pattern, it cascades to that pattern's (non-deleted) target state
  options — see the master delete guard in the `decision_records` section above.
- **Soft delete** — removal. Sets `deleted_at` (and optionally `deleted_by`).
  The record disappears from all normal API responses and from the UI entirely,
  regardless of its `status`. `status` itself is left untouched, so restoring the
  record returns it to exactly the lifecycle state it was in before deletion.
  Use it when a record should not have existed, or should no longer be
  discoverable at all — a stronger action than deprecating. Applied to a master
  pattern, it cascades to that pattern's (non-deleted) target state options.
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
- `engagement_patterns(engagement_id)`, `engagement_patterns(engagement_id, scope_status)`

## Design notes

- Slug primary keys on patterns and target states are deliberate: they appear in
  export files, playbook folder paths and future accelerator bindings, so they must
  be stable and human-readable. Do not switch to surrogate integer keys.
- The `patterns` and `target_state_options` tables must remain free of any
  engagement reference. That separation is the product thesis; enforce it in review.
