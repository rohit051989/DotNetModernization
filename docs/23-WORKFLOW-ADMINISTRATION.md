# 23 — Workflow Administration

Master-scope administration of the workflow: the step registry, job definitions, and
policy at both global and engagement level.

Amends `22-STEP-SEQUENCING-AND-POLICY.md`. Read that first — this adds a third policy
layer and the UI to manage all of it.

---

## Part A — Three-layer policy model

Spec 22 has two layers: enabled-by-default, and an engagement override. That covers
"Client B is not modernizing SSIS" but not "this step is not ready for anyone yet".

Add a global layer, mirroring the catalog's master/client structure:

| Layer | Scope | Set by | Answers |
|---|---|---|---|
| **Default** | Everything | Nobody — absence of a row | Enabled |
| **Global policy** | All engagements | Admin, master view | "Nobody should run this yet" |
| **Engagement policy** | One engagement | Operator, client view | "This client does not want this" |

**Precedence: engagement beats global beats default.** An engagement policy row is an
explicit local decision and overrides a global one in either direction — an engagement
can re-enable a globally disabled step.

`implementation_status: stub` is orthogonal, not a policy. A stub step still runs and
returns `NOT_IMPLEMENTED`; the flow's `stub_policy` governs what happens next. Do not
conflate "not built" with "disabled".

### Table change

Rename `engagement_step_policies` to **`step_policies`** and make `engagement_id`
nullable, where `NULL` means global. One table keeps resolution logic in one place.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `engagement_id` | `TEXT` NULL FK → `engagements.id` | **Null means global** |
| `step_name` | `TEXT` NOT NULL FK | |
| `enabled` | `BOOLEAN` NOT NULL | |
| `reason` | `TEXT` NOT NULL | Required whenever a row exists, in either direction |
| `set_by` | `TEXT` | Free text until auth exists |
| `set_at` | `TIMESTAMPTZ` NOT NULL | |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |

Two partial unique indexes:
- `(step_name) WHERE engagement_id IS NULL` — one global row per step
- `(engagement_id, step_name) WHERE engagement_id IS NOT NULL`

Migrate existing rows unchanged; they all have an `engagement_id`.

`reason` is required even when re-enabling. "Why is this step running for Client A
when it is globally off" needs an answer as much as the reverse.

### Effective resolution

```
effective_enabled, source =
    engagement row exists  → (row.enabled, "engagement")
    global row exists      → (row.enabled, "global")
    otherwise              → (true, "default")
```

Resolve once at job launch and snapshot into `execution_context.step_policy_snapshot`
per spec 22, recording `source` alongside `enabled` so the timeline can say *why*.

Skip reason at runtime distinguishes the layers:
`POLICY_DISABLED_GLOBAL` and `POLICY_DISABLED_ENGAGEMENT`, replacing the single
`POLICY_DISABLED`. Update the `skip_reason` CHECK constraint.

### Dependency guard across layers

Spec 22's guard already refuses a policy that would orphan a required input. Extend it:

- A **global** disable is validated against every active job definition, and the 409
  names dependents as before.
- A global disable must additionally report which engagements have an engagement-level
  row re-enabling the step, since those engagements are unaffected and the admin
  should know the change is partial.
- An **engagement** re-enable of a globally disabled step is validated the same way —
  re-enabling a step whose upstream producer is globally disabled must be refused.

---

## Part B — API

```
GET    /api/workflow/step-policies                          global rows
POST   /api/workflow/step-policies                          create or update global
DELETE /api/workflow/step-policies/{step_name}              revert global to default
POST   /api/workflow/step-policies/validate                 dry run

GET    /api/engagements/{eid}/step-policies                 engagement rows
POST   /api/engagements/{eid}/step-policies                 unchanged from spec 22
DELETE /api/engagements/{eid}/step-policies/{step_name}      unchanged
POST   /api/engagements/{eid}/step-policies/validate         unchanged

GET    /api/workflow/effective-policies?engagement_id=      resolved view
GET    /api/workflow/policy-matrix                          steps × engagements
```

**`effective-policies`** returns, per step in scope, `enabled`, `source`, `reason`,
and the raw layer rows, so the UI can show inheritance without recomputing it.

**`policy-matrix`** is the master-view overview:

```json
{
  "engagements": [ { "id": "client-a-ocp4", "client_name": "Client A" } ],
  "steps": [
    {
      "step_name": "application-fingerprinting",
      "lifecycle_step_no": 3,
      "display_name": "Application fingerprinting",
      "implementation_status": "implemented",
      "global": { "enabled": true, "source": "default" },
      "engagements": {
        "client-a-ocp4": { "enabled": false, "source": "engagement", "reason": "…" },
        "reference-engagement-b": { "enabled": true, "source": "default" }
      }
    }
  ]
}
```

Only include steps that appear in at least one active job definition — the other 44
have no policy meaning yet, and listing all 51 makes the matrix unreadable.

All endpoints per `18-API-CONVENTIONS.md`.

---

## Part C — Master view: Workflow Administration tab

New tab, visible **only in Master Catalog view**. Four sections.

### C1. Step registry

Read-only table of every registered step. Registration is a build-time operation and
stays API-only; this is for inspection.

Columns: lifecycle number, step name (monospace), display name, owner code, adapter
type, implementation status, version, owner team, consumes, produces.

Filters: implementation status, owner code, adapter type. Search on name.

Group by phase using the `17-LIFECYCLE-STEPS.md` boundaries, with a per-phase counter:
`Phase 0 — 3 of 12 implemented`. This is the single clearest view of how far the
platform has been built, and it is worth having for its own sake.

Row expands to show `adapter_config` as formatted JSON — the resolved command or URL
for that step. That answers "where does `application-fingerprinting` actually run from" without psql.

### C2. Job definitions

The viewer from spec 22 Part E, in master scope with no engagement selected — so
policy state shows global and default only.

List every job definition: name, active version, validation status, step count,
implemented count, scope. Selecting one opens the flow view with consumes, produces,
inputs wiring, and `when:` conditions rendered as prose.

Include definitions that are **not** active or **not** valid, clearly marked. A job
that failed validation should be visible here rather than only discoverable through
an API call.

### C3. Global policy

One row per step appearing in an active job definition. Columns: step, effective
global state, reason, set by, set at, and the count of engagements overriding it.

Toggling requires a reason. On 409, show the dependent steps and any overriding
engagements, and offer explicit cascade confirmation as in spec 22.

A banner when any global disable exists: *"3 steps are globally disabled"* with a
link. Global disables are consequential and should not be easy to forget about.

### C4. Policy matrix

Grid: steps down, engagements across. Each cell shows effective state with its source
distinguished visually:

| Cell | Meaning |
|---|---|
| Solid enabled | Default — no row anywhere |
| Enabled, outlined | Enabled by an engagement row overriding a global disable |
| Disabled, filled | Disabled globally |
| Disabled, hatched | Disabled by an engagement row |

Hover shows source and reason. Clicking opens the relevant policy editor.

Sparse by design — most cells are default. That is the point: the matrix makes
deviations obvious rather than requiring them to be hunted.

---

## Part D — Client view

Unchanged from spec 22 Parts E and F, with two additions.

**Inheritance is shown.** A step disabled globally reads
*"Disabled globally — <reason>"* with an option to override for this engagement.
An engagement row overriding a global one reads
*"Enabled for this engagement — overrides global disable"*.

**The policy summary strip** lists every step whose effective state differs from
default, with the layer responsible. An operator on a client engagement should be able
to see at a glance which steps are not running and who decided that.

---

## Part E — Timeline

Extend the treatments in spec 22 Part D:

| Skip reason | Chip |
|---|---|
| `POLICY_DISABLED_GLOBAL` | `SKIPPED — GLOBAL POLICY` |
| `POLICY_DISABLED_ENGAGEMENT` | `SKIPPED — ENGAGEMENT POLICY` |

Both show the reason in the collapsed row, per spec 22's non-negotiable rule.

---

## Part F — Out of scope

- **Editing job definitions from the UI.** Viewer only. Definitions stay in git.
- **Registering or editing steps from the UI.** Build-time operation, API only.
- **Policy change history.** Current state only. An append-only event table can be
  added later if audit becomes a requirement.
- **Role-based access.** The Master Catalog view is already noted as admin-only in a
  future auth model (`04-FRONTEND-SPEC.md`). Leave TODO markers at the global policy
  mutations and at the tab itself, where the permission check will go.

---

## Acceptance criteria

- [ ] `engagement_step_policies` renamed to `step_policies` with nullable
      `engagement_id`, existing rows migrated unchanged, both partial unique indexes
      present
- [ ] A global disable produces `SKIPPED` / `POLICY_DISABLED_GLOBAL` for every
      engagement
- [ ] An engagement row re-enabling a globally disabled step causes it to run for that
      engagement only
- [ ] An engagement disable of a globally enabled step yields
      `POLICY_DISABLED_ENGAGEMENT`
- [ ] A global disable of `solution-discovery` returns 409 naming
      `application-fingerprinting`, and lists any engagements overriding it
- [ ] Re-enabling a step for one engagement while its upstream producer is globally
      disabled is refused
- [ ] `reason` is required when creating a row in either direction
- [ ] Policy is resolved and snapshotted at launch with its `source` recorded
- [ ] The Workflow Administration tab appears only in Master Catalog view
- [ ] Step registry shows all 51 steps grouped by phase with per-phase implemented
      counts, and `adapter_config` visible on expand
- [ ] Job definitions section shows invalid and inactive definitions, clearly marked
- [ ] Global policy section warns when any global disable exists
- [ ] Policy matrix distinguishes all four cell states, with source and reason on hover
- [ ] Client view shows inherited global state and allows an explicit override
- [ ] Timeline chips distinguish global from engagement skips, reason visible collapsed
- [ ] Everything achievable via the spec 22 API calls is achievable from the UI
