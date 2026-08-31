# 03 — Backend Spec

FastAPI + SQLAlchemy 2.x + Pydantic v2. All routes under `/api`.

## Layout

```
backend/app/
  main.py            app factory, CORS, router registration
  config.py          pydantic-settings, reads .env
  db.py              engine, session factory, get_db dependency
  models.py          SQLAlchemy ORM models
  schemas.py         Pydantic request/response models
  routers/
    health.py
    patterns.py            master catalog: patterns
    target_states.py       master catalog: target state options
    engagements.py
    engagement_patterns.py client catalog: the engagement-scoped pattern overlay
    decisions.py
    catalog.py       export / import
  seed/
    seed_data.py     loads 05-SEED-CATALOG-DATA.md content
    __main__.py      `python -m app.seed`
```

## Conventions

- Response models are explicit Pydantic classes. Never return ORM objects directly.
- `snake_case` in JSON. The frontend maps to camelCase if it wants to; the API does not.
- **One error shape everywhere** — see `18-API-CONVENTIONS.md` Part C, registered as
  the shared `ErrorResponse` OpenAPI component:
  `{"detail": [{"field": "...", "message": "...", "code": "..."}]}`. `field` is
  null when the error isn't about one field (a 404, or a conflict spanning several
  records); `code` is a short machine-readable slug.
- Business-rule violations (for example an approved decision missing an approver)
  return **422**, not 400, using the same shape.
- Referential refusals (soft-deleting something still referenced) return **409**
  with a message naming what blocks it.
- Not found returns **404**. A soft-deleted record behaves as not-found on every
  normal read — see "Soft delete vs deprecate" below.
- Pagination is not required at this scale for catalog resources — return full
  lists. Workflow execution listings are the exception: `?limit=&offset=` (default
  `limit=50`), since that collection grows with every job launch.
- Every route carries `summary`, `tags`, `operation_id`, and documents its non-200
  `responses` — see `18-API-CONVENTIONS.md` Part A. `operation_id` is set explicitly
  and must not change once a route ships; it is what a generated client binds to.

## Soft delete vs deprecate

Two orthogonal mechanisms, not one. Full semantics are in `02-DATA-MODEL.md`;
the API-level contract is:

- **Deprecate** (`POST .../deprecate`) sets `status = 'deprecated'`. The record
  remains visible everywhere — normal list/get calls still return it, and the UI
  status filter is how a user brings it back into view. Permissive: it always
  succeeds.
- **Soft delete** (`DELETE`) sets `deleted_at` (and `deleted_by` if supplied). The
  record is excluded from every normal list/get response and from the export,
  regardless of its `status`. Guarded: it is refused with 409 if the record is
  still referenced by other non-deleted records (specifics per entity below).
- **Restore** (`POST .../restore`) clears `deleted_at` and `deleted_by`. Backend
  only — no UI control exists for it. **This operation, and soft delete itself,
  are intended to become admin-only once authentication exists. They are
  currently unguarded, like every other endpoint in this build; do not treat
  their presence as evidence that access control has been considered.**

Every list and get endpoint across every resource excludes rows where
`deleted_at IS NOT NULL` by default. List endpoints accept `?include_deleted=true`
to include them (so a deleted record can be inspected without direct DB access);
get-by-id endpoints accept the same flag for the same reason. Without it, a
soft-deleted record 404s exactly as if the row did not exist.

## Master catalog vs client catalog

Full concept and the `engagement_patterns` table are in `02-DATA-MODEL.md`. The
API-level rule that matters most while implementing routes: **the endpoints
under `/api/engagements/{eid}/patterns/...` never write to `patterns` or
`target_state_options`, under any circumstance.** They read master data (joined
in for display) and write only to `engagement_patterns` and, via the existing
decisions endpoints, to `decision_records`. If a change to one of these routes
seems to require touching a master table, that is a sign the change belongs on
the `/api/patterns` or `/api/target-states` routes instead, not here.

The reverse guard also holds: the master guards on `/api/patterns/{id}` (deprecate,
delete) check `decision_records` **across every engagement**, not just one — a
master pattern is shared IP, so retiring it must account for every engagement
that might be relying on it, which is exactly why that check is broader than the
client-scoped one on `engagement_patterns`.

## Routes

### Health

```
GET /api/health
→ 200 {"status": "ok", "database": "connected", "version": "0.1.0"}
```

Performs a real `SELECT 1` against the database. Returns `"database": "error"` and
still 200 if the query fails, so the UI can display a degraded state.

### Patterns

```
GET    /api/patterns
       ?status=active&category=service&q=wcf&include_deleted=false
       → 200 [PatternSummary]
GET    /api/patterns/{pattern_id}
       ?include_deleted=false
       → 200 PatternDetail   (includes nested target_state_options)
POST   /api/patterns
       → 201 PatternDetail
PUT    /api/patterns/{pattern_id}
       → 200 PatternDetail
POST   /api/patterns/{pattern_id}/deprecate
       → 200 {"id": "...", "status": "deprecated", "referenced_by_decisions": n}
DELETE /api/patterns/{pattern_id}
       ?deleted_by=someone
       → 200 {"id": "...", "deleted_at": "..."}
       → 409 if any non-deleted, non-superseded decision record in ANY
         engagement still references the pattern
POST   /api/patterns/{pattern_id}/restore
       → 200 {"id": "...", "deleted_at": null}
```

`q` matches case-insensitively against `name`, `summary` and `legacy_stack`.

`POST /deprecate` is the old `DELETE` behaviour, moved because `DELETE` now
performs an actual deletion. Sets `status = 'deprecated'` and is permissive: if any
non-deleted, non-superseded decision record references the pattern (in any
engagement), deprecation still succeeds, with `"referenced_by_decisions": <count>`
in the response so the UI can warn. It **cascades**: every non-deleted target
state option under this pattern is also set to `status = 'deprecated'` in the
same request.

`DELETE` is the new soft delete. It is guarded, not permissive, but **only by
decision records** — the existence of target state options never blocks it.
Refused with 409 naming the count of non-superseded, non-deleted decision
records (across every engagement, not just one) that still reference the
pattern; supersede or remove those first. If it succeeds, it **cascades**: every
non-deleted target state option under this pattern is soft-deleted in the same
request, with the same `deleted_by`. There is no way to soft-delete a pattern and
leave a live target state option behind.
`deleted_by` is an optional free-text query parameter — there is no auth system
yet to source an identity from.

`POST /restore` clears `deleted_at`/`deleted_by` unconditionally if the pattern
exists, deleted or not. Restoring a pattern that is not currently deleted is a
harmless no-op. `status` is untouched, so a restored pattern reappears exactly as
deprecated/active/draft as it was before deletion.

`POST` validates that `id` is a valid slug: `^[a-z0-9]+(-[a-z0-9]+)*$`. Reject
duplicates with 409 — this includes ids belonging to a soft-deleted pattern, since
the primary key still exists; restore it instead of recreating it.

`PUT` increments `version` when any of `detection_rules`, `name`, `legacy_stack` or
`category` change. Cosmetic edits to `description` do not bump the version.

**PatternSummary** — `id, name, summary, legacy_stack, category, status, version,
target_state_count, updated_at, deleted_at, deleted_by`

**PatternDetail** — all pattern columns plus `target_state_options: [TargetStateSummary]`

### Target state options

```
GET    /api/patterns/{pattern_id}/target-states
       ?include_deleted=false
       → 200 [TargetStateDetail]
POST   /api/patterns/{pattern_id}/target-states
       → 201 TargetStateDetail
GET    /api/target-states/{id}
       ?include_deleted=false
       → 200 TargetStateDetail
PUT    /api/target-states/{id}
       → 200 TargetStateDetail
POST   /api/target-states/{id}/deprecate
       → 200 {"id": "...", "status": "deprecated"}
       → 409 if referenced by a non-deleted, non-superseded approved decision
DELETE /api/target-states/{id}
       ?deleted_by=someone
       → 200 {"id": "...", "deleted_at": "..."}
       → 409 if referenced by any non-deleted, non-superseded decision record
         (not only approved ones — removal is a stronger action than deprecation,
         so the guard is correspondingly broader)
POST   /api/target-states/{id}/restore
       → 200 {"id": "...", "deleted_at": null}
```

On `POST`, reject with 409 if `(pattern_id, name)` already exists.

`POST /deprecate` is the old `DELETE` behaviour, moved and otherwise unchanged:
still refused if a non-superseded **approved** decision references the option,
now additionally requiring that decision record to be non-deleted. (This is the
per-option deprecate guard, separate from the pattern-level deprecate cascade
described above — an individual option can also be deprecated directly.)

`DELETE` is the new soft delete, guarded more broadly than deprecate: refused if
**any** non-superseded decision record (parked, in_review or approved) has this
option as its `selected_target_state_id` and is not itself deleted.

`POST /restore` clears `deleted_at`/`deleted_by` unconditionally if the option
exists. `status` is untouched.

Sort returned options by `consumer_impact` ascending (`none` first), then `effort`
ascending. The lowest-impact option should always appear first — the UI relies on
this to present the presumptive choice at the top.

`is_recommended` marks the master catalog's recommended option for the pattern —
independent of any engagement's decision, which may reasonably choose a different
option under a forcing factor. Enforced in the API layer on both `POST` and `PUT`:
setting `is_recommended: true` on one option clears it on every other option under
the same `pattern_id` in the same request, so at most one is ever `true`. There is
no dedicated endpoint for it; it's just a field on the existing create/update
payloads.

### Client-scoped patterns (the client catalog)

```
GET    /api/engagements/{eid}/patterns
       ?include_deleted=false&include_deferred=true
       → 200 [EngagementPatternView]
GET    /api/engagements/{eid}/patterns/{pid}
       ?include_deleted=false
       → 200 EngagementPatternView
POST   /api/engagements/{eid}/patterns/{pid}/defer
       body: {"deferred_reason": "..."}
       → 200 EngagementPatternView
POST   /api/engagements/{eid}/patterns/{pid}/reactivate
       → 200 EngagementPatternView
DELETE /api/engagements/{eid}/patterns/{pid}
       ?deleted_by=someone
       → 200 {"engagement_id": "...", "pattern_id": "...", "deleted_at": "..."}
       → 409 if a non-superseded decision record exists for this
         (engagement, pattern)
POST   /api/engagements/{eid}/patterns/{pid}/restore
       → 200 {"engagement_id": "...", "pattern_id": "...", "deleted_at": null}
```

**EngagementPatternView** is a merged read model, not a stored row: master
pattern fields (the same shape as `PatternSummary`, plus `target_state_options`
the same as in `PatternDetail`) joined with the overlay's `scope_status` /
`deferred_reason` and a decision summary (`decision_status`,
`selected_target_state_name`, `forcing_perspective` — `25-STANDARDS-AND-
VIEWPOINTS.md` Part A1 — or `null` if no decision has been recorded yet for
this pattern in this engagement). Remember the overlay is lazy (see
`02-DATA-MODEL.md`): when no `engagement_patterns` row exists,
`scope_status` reads as `"active"` and `deleted_at` as `null` in the merged view,
same as if a row existed saying exactly that.

`GET` (list) excludes client-deleted patterns for this engagement by default;
`?include_deleted=true` includes them. `?include_deferred=false` excludes
deferred patterns; it defaults to `true` (deferred patterns show up by default,
just visually distinguished — see `04-FRONTEND-SPEC.md`) since hiding them by
default would make it too easy to lose track of a whole category of work.

`POST /defer` upserts the `engagement_patterns` row: creates it with
`scope_status='deferred'` if absent, or updates it if present. Always succeeds —
deferring is never blocked by anything, including an existing decision record,
and never modifies the decision record. `deferred_reason` is optional free text.

`POST /reactivate` upserts the row with `scope_status='active'`. Also always
succeeds.

`DELETE` is the client-scoped soft delete: upserts the overlay row with
`deleted_at`/`deleted_by` set. Refused with 409 if a non-superseded decision
record exists for this exact `(engagement_id, pattern_id)` — supersede or remove
it first. This check is scoped to this one engagement only; it has no bearing on,
and is not affected by, any other engagement's decision for the same pattern, or
on whether the master pattern itself could be deleted.

`POST /restore` clears `deleted_at`/`deleted_by` on the overlay row.
Unconditional, same as the master restore endpoints; admin-only in intent, not
yet gated (see the note under "Soft delete vs deprecate" above).

**These five endpoints never write to `patterns` or `target_state_options`.**
They read master data for the merged view and write only `engagement_patterns`
(and, indirectly through the existing decisions endpoints, `decision_records`).
A pattern deferred or deleted here is affected in this engagement alone; the
master pattern and every other engagement are untouched.

### Engagements

```
GET    /api/engagements                    ?include_deleted=false → 200 [Engagement]
POST   /api/engagements                    → 201 Engagement
GET    /api/engagements/{id}                ?include_deleted=false → 200 Engagement
PUT    /api/engagements/{id}               → 200 Engagement
GET    /api/engagements/{id}/coverage      → 200 CoverageSummary
GET    /api/engagements/{id}/executions    ?job_name=&batch_status=&limit=&offset=
                                            → 200 [JobExecutionOut]
```

`engagements` gained `deleted_at`/`deleted_by` columns for consistency (see
`02-DATA-MODEL.md`), and its list/get endpoints follow the same `include_deleted`
convention as every other resource. There is no delete/deprecate/restore route for
engagements in this build — the columns exist so the schema does not need another
migration when that capability is added, but nothing in the API can set them yet.

`GET .../executions` is a convenience, engagement-scoped view over
`GET /api/workflow/executions` (see `10-ENGINE-CONCEPTS.md` and
`12-JOB-DEFINITION-FORMAT.md` for the engine itself) — same data, pre-filtered to
executions whose job instance declares this `engagement_id` parameter. The
canonical, flat collection is not nested under engagements: the engagement is a
job *parameter*, not an owner, and a future wave-scoped job may have no
`engagement_id` at all.

**CoverageSummary** — drives the future dashboard and is cheap to add now:

```json
{
  "engagement_id": "client-a-ocp4",
  "total_patterns": 8,
  "approved": 5,
  "in_review": 1,
  "parked": 2,
  "deferred": 1,
  "patterns_without_decision": ["ssis-package"],
  "perspective_breakdown": {"SECURITY": 1, "EVOLUTION": 1}
}
```

`total_patterns` counts non-deleted, active master patterns, minus any this
engagement has client-deleted via `engagement_patterns`. `deferred` counts
patterns this engagement has deferred (independent of whether a decision record
also exists for them — a pattern can be deferred and still have a stale parked
decision, and both facts should be visible). `approved` / `in_review` / `parked`
count this engagement's non-superseded, non-deleted decision records by status,
as before. `patterns_without_decision` lists master patterns with neither a
decision record nor a client-delete/defer overlay row — i.e. patterns still
genuinely untouched by this engagement. `perspective_breakdown` counts this
engagement's non-superseded, non-deleted decisions per `forcing_perspective`
(`25-STANDARDS-AND-VIEWPOINTS.md` Part A1) — only perspectives with at least
one decision appear; this is the programme-level rollup a free-text
`forcing_factor` could never answer.

### Decision records

```
GET    /api/engagements/{id}/decisions                     ?include_deleted=false → 200 [DecisionRecord]
GET    /api/engagements/{id}/patterns/{pid}/decision        → 200 DecisionRecord
                                                              → 404 if none recorded yet
PUT    /api/engagements/{id}/patterns/{pid}/decision         → 200 or 201 DecisionRecord
GET    /api/decisions/{id}                  ?include_deleted=false → 200 DecisionRecord
PUT    /api/decisions/{id}                  → 200 DecisionRecord
POST   /api/decisions/{id}/supersede        → 200 DecisionRecord
```

**Per `18-API-CONVENTIONS.md` Part B**, a decision record is a singleton per
`(engagement, pattern)`, enforced by a partial unique index — so its identity
belongs fully in the path, not in a request body field. There is no longer a
`POST /api/engagements/{id}/decisions` that takes `pattern_id` in the body; the
frontend decision panel always has both ids in context, so this simplifies the
client too.

`GET .../patterns/{pid}/decision` fetches the live (non-superseded, non-deleted)
decision for that pattern in that engagement. 404 means "nothing decided yet" —
the normal empty state, not an error condition to work around.

`PUT .../patterns/{pid}/decision` **upserts** that same singleton: creates it
(responding **201**) if none exists yet, or updates it in place (responding
**200**) if one does. Omitted body fields leave an existing value unchanged.
`PUT /api/decisions/{id}` remains, unchanged, for editing one specific record by
its own id — including historical (superseded) ones, which the pattern-scoped
route can never reach since it only ever touches the live decision.

`decision_records` also gained `deleted_at`/`deleted_by`, and its list/get
endpoints follow the same `include_deleted` convention. No route can set these
columns yet — they exist so the partial unique index (`02-DATA-MODEL.md`) and the
referential guards on pattern/target-state soft delete have something consistent
to check against.

Both write routes enforce every validation rule in `02-DATA-MODEL.md`. In
particular, when transitioning to `approved`:

1. `selected_target_state_id` present and belonging to the same pattern
2. `rationale`, `approver_name`, `decision_date` present
3. If the selected option is not the lowest `consumer_impact` among
   `candidates_considered`, both `forcing_perspective` and `forcing_rationale`
   must be present

Return a clear message for each failure — this validation is a demo talking point,
so the errors should read well. Both missing fields are named, one problem entry
each, sharing the same message text:

```json
{"detail": [
  {
    "field": "forcing_perspective",
    "message": "gRPC rewrite has higher consumer impact (high) than the lowest candidate CoreWCF on .NET 10 (none). Both forcing_perspective and forcing_rationale are required to justify the deviation.",
    "code": "FORCING_PERSPECTIVE_AND_RATIONALE_REQUIRED"
  },
  {
    "field": "forcing_rationale",
    "message": "gRPC rewrite has higher consumer impact (high) than the lowest candidate CoreWCF on .NET 10 (none). Both forcing_perspective and forcing_rationale are required to justify the deviation.",
    "code": "FORCING_PERSPECTIVE_AND_RATIONALE_REQUIRED"
  }
]}
```

`POST /supersede` sets `status = 'superseded'`, freeing the partial unique index so
a new decision can be recorded for that pattern.

**DecisionRecord** response embeds `pattern_name` and `selected_target_state_name`
so the UI does not need extra lookups. It also carries `forcing_perspective`
(`25-STANDARDS-AND-VIEWPOINTS.md` Part A1) alongside the renamed
`forcing_rationale` — the perspective is what makes deviations from
lift-and-shift aggregable across an engagement; the rationale stays the
free-text narrative. `EngagementPatternView`'s decision summary carries
`forcing_perspective` too, so the client catalog can show it without a second
fetch.

### Catalog export / import

```
GET  /api/catalog/export
     ?scope=master|engagement&engagement_id=...&include_engagements=false
     → 200 CatalogExport
POST /api/catalog/import
     body: CatalogExport, query: ?mode=merge|replace
     → 200 {"patterns_created": n, "patterns_updated": n, ...}
```

`scope=master` (the default) exports only `patterns` and their nested
`target_state_options` — no overlay, no decisions, regardless of
`include_engagements`. This is what keeps the exported master catalog clean,
client-agnostic and portable: it must never carry one engagement's deferrals,
deletions or decisions, since those belong to that engagement alone, not to the
shared IP. `scope=engagement` requires `?engagement_id=...` and additionally
includes that one engagement's `engagement_patterns` overlay state (merged onto
each pattern entry as `scope_status` / `deferred_reason`, following the same
lazy-row-means-active rule as the API) and its `decision_records`, still subject
to `include_engagements`/`include_timestamps` as before. Requesting
`scope=engagement` without `engagement_id`, or for an engagement that does not
exist, is a 422.

**The export must be deterministic.** Same data in, byte-identical file out:

- keys sorted alphabetically at every level
- `patterns` sorted by `id`; `target_state_options` sorted by `id` within each pattern
- 2-space indent, `\n` line endings, trailing newline
- timestamps serialised as ISO-8601 UTC with `Z`
- exclude `created_at` / `updated_at` from the export by default (they create noise
  in diffs); include them only when `?include_timestamps=true`
- soft-deleted records are excluded unconditionally, with no override — unlike
  list/get endpoints there is no `?include_deleted` for export. A committed catalog
  file should never contain something that was removed, even for inspection

This is what allows the catalog to be committed to git and reviewed as a pull
request, which is how it becomes durable IP rather than rows in someone's database.

Export shape:

```json
{
  "catalog_version": "1.0",
  "exported_at": "2026-08-05T00:00:00Z",
  "patterns": [
    { "...pattern fields...", "target_state_options": [ ... ] }
  ],
  "engagements": [],
  "decision_records": []
}
```

`mode=merge` upserts by id and leaves unlisted records untouched.
`mode=replace` is destructive; require an explicit `?confirm=true` as well.

## Seeding

`python -m app.seed` must be idempotent — safe to run repeatedly. Upsert by id.
Add a `--reset` flag that truncates all tables first, for demo resets. The seed
data itself does not populate `engagement_patterns` — the overlay is lazy (see
`02-DATA-MODEL.md`), so a freshly-seeded catalog correctly has zero overlay rows,
meaning every pattern starts active and undeleted in every engagement.

Print a summary on completion:

```
Seeded: 8 patterns, 16 target state options, 2 engagements, 10 decision records
  client-a-ocp4          approved: 5   in_review: 1   parked: 2
  reference-engagement-b approved: 2
```

## Error handling

Register exception handlers so that unhandled database integrity errors surface as
409 with a readable message rather than a 500 stack trace. The UI will be shown in
a client demo; unhandled 500s are not acceptable.
