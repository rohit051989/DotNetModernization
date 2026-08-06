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
    patterns.py
    target_states.py
    engagements.py
    decisions.py
    catalog.py       export / import
  seed/
    seed_data.py     loads 05-SEED-CATALOG-DATA.md content
    __main__.py      `python -m app.seed`
```

## Conventions

- Response models are explicit Pydantic classes. Never return ORM objects directly.
- `snake_case` in JSON. The frontend maps to camelCase if it wants to; the API does not.
- Validation failures return **422** with a body of
  `{"detail": [{"field": "...", "message": "..."}]}`.
- Business-rule violations (for example an approved decision missing an approver)
  also return **422**, not 400.
- Referential refusals (deleting something still referenced) return **409** with a
  message naming what blocks it.
- Not found returns **404**.
- Pagination is not required at this scale. Return full lists.

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
       ?status=active&category=service&q=wcf
       → 200 [PatternSummary]
GET    /api/patterns/{pattern_id}
       → 200 PatternDetail   (includes nested target_state_options)
POST   /api/patterns
       → 201 PatternDetail
PUT    /api/patterns/{pattern_id}
       → 200 PatternDetail
DELETE /api/patterns/{pattern_id}
       → 200 {"id": "...", "status": "deprecated"}
```

`q` matches case-insensitively against `name`, `summary` and `legacy_stack`.

`DELETE` is a soft delete: sets `status = 'deprecated'`. If any non-superseded
decision record references the pattern, still allow deprecation but include
`"referenced_by_decisions": <count>` in the response so the UI can warn.

`POST` validates that `id` is a valid slug: `^[a-z0-9]+(-[a-z0-9]+)*$`. Reject
duplicates with 409.

`PUT` increments `version` when any of `detection_rules`, `name`, `legacy_stack` or
`category` change. Cosmetic edits to `description` do not bump the version.

**PatternSummary** — `id, name, summary, legacy_stack, category, status, version,
target_state_count, updated_at`

**PatternDetail** — all pattern columns plus `target_state_options: [TargetStateSummary]`

### Target state options

```
GET    /api/patterns/{pattern_id}/target-states
       → 200 [TargetStateDetail]
POST   /api/patterns/{pattern_id}/target-states
       → 201 TargetStateDetail
GET    /api/target-states/{id}
       → 200 TargetStateDetail
PUT    /api/target-states/{id}
       → 200 TargetStateDetail
DELETE /api/target-states/{id}
       → 200 {"id": "...", "status": "deprecated"}  soft delete
       → 409 if referenced by a non-superseded approved decision
```

On `POST`, reject with 409 if `(pattern_id, name)` already exists.

Sort returned options by `consumer_impact` ascending (`none` first), then `effort`
ascending. The lowest-impact option should always appear first — the UI relies on
this to present the presumptive choice at the top.

### Engagements

```
GET    /api/engagements                    → 200 [Engagement]
POST   /api/engagements                    → 201 Engagement
GET    /api/engagements/{id}               → 200 Engagement
PUT    /api/engagements/{id}               → 200 Engagement
GET    /api/engagements/{id}/coverage      → 200 CoverageSummary
```

**CoverageSummary** — drives the future dashboard and is cheap to add now:

```json
{
  "engagement_id": "client-a-ocp4",
  "total_patterns": 8,
  "approved": 5,
  "in_review": 1,
  "parked": 2,
  "patterns_without_decision": ["ssis-package"]
}
```

### Decision records

```
GET    /api/engagements/{id}/decisions      → 200 [DecisionRecord]
POST   /api/engagements/{id}/decisions      → 201 DecisionRecord
GET    /api/decisions/{id}                  → 200 DecisionRecord
PUT    /api/decisions/{id}                  → 200 DecisionRecord
POST   /api/decisions/{id}/supersede        → 200 DecisionRecord
```

`PUT` enforces every validation rule in `02-DATA-MODEL.md`. In particular, when
transitioning to `approved`:

1. `selected_target_state_id` present and belonging to the same pattern
2. `rationale`, `approver_name`, `decision_date` present
3. If the selected option is not the lowest `consumer_impact` among
   `candidates_considered`, `forcing_factor` must be present

Return a clear message for each failure — this validation is a demo talking point,
so the errors should read well:

```json
{"detail": [{
  "field": "forcing_factor",
  "message": "gRPC rewrite has higher consumer impact (high) than the lowest candidate CoreWCF on .NET 10 (none). A forcing factor is required to justify the deviation."
}]}
```

`POST /supersede` sets `status = 'superseded'`, freeing the partial unique index so
a new decision can be recorded for that pattern.

**DecisionRecord** response embeds `pattern_name` and `selected_target_state_name`
so the UI does not need extra lookups.

### Catalog export / import

```
GET  /api/catalog/export
     ?include_engagements=false
     → 200 CatalogExport
POST /api/catalog/import
     body: CatalogExport, query: ?mode=merge|replace
     → 200 {"patterns_created": n, "patterns_updated": n, ...}
```

**The export must be deterministic.** Same data in, byte-identical file out:

- keys sorted alphabetically at every level
- `patterns` sorted by `id`; `target_state_options` sorted by `id` within each pattern
- 2-space indent, `\n` line endings, trailing newline
- timestamps serialised as ISO-8601 UTC with `Z`
- exclude `created_at` / `updated_at` from the export by default (they create noise
  in diffs); include them only when `?include_timestamps=true`

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
Add a `--reset` flag that truncates all four tables first, for demo resets.

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
