# 16 — Dashboard Spec

Engagement-scoped modernization status, repository by repository. This is the fleet
view from the pitch narrative — the screen that establishes the platform thinks in
estates rather than repositories.

Read `15-REPOSITORY-INGEST-UI.md` Part F first. The honest-metrics rule governs this
entire tab.

## Scope

**Now:** repository-level status driven by real data from `repository-ingest` and the catalog,
with everything downstream honestly marked unavailable.

**Later:** application-level rollups, wave status, verification evidence, engine
coverage measurements. The layout reserves space for these rather than being
redesigned when they land.

The dashboard is read-only. No mutations from this tab.

---

## API

### `GET /api/engagements/{eid}/dashboard`

One call, one payload. The dashboard is a read view; do not make the frontend
assemble it from six endpoints.

```json
{
  "engagement_id": "client-a-ocp4",
  "client_name": "Client A",
  "generated_at": "2026-08-05T12:00:00Z",

  "repositories": {
    "total": 4,
    "registered": 1,
    "cloned": 3,
    "clone_failed": 0,
    "skipped": 0,
    "total_size_bytes": 184320512,
    "with_git_history": 3
  },

  "discovery": {
    "not_started": 0,
    "in_progress": 1,
    "completed": 3,
    "failed": 0,
    "awaiting_approval": 0
  },

  "applications": null,
  "patterns": null,
  "risk_tiers": null,
  "waves": null,

  "decisions": {
    "total_patterns_in_scope": 8,
    "approved": 5,
    "in_review": 1,
    "parked": 2,
    "deferred": 0
  },

  "capabilities": {
    "application_count": false,
    "pattern_classification": false,
    "impact_map": false,
    "test_coverage": false,
    "risk_tier": false,
    "wave_planning": false
  },

  "recent_executions": [
    {
      "job_execution_id": "…",
      "job_name": "phase0-repository-discovery",
      "repository_slug": "order-management",
      "batch_status": "COMPLETED",
      "exit_status": "COMPLETED",
      "steps_completed": 1,
      "steps_total": 7,
      "started_at": "…",
      "ended_at": "…"
    }
  ]
}
```

**`null` versus `0` is load-bearing.** A section is `null` when no implemented step
produces it. It becomes an object once the producing step exists. The frontend
renders a "not yet available" state for null and real figures for objects. Never emit
zeroed structures for unimplemented capabilities.

`decisions` is real now — it comes from the catalog, which is built. It reads
`engagement_patterns` overlay state so deferred and client-deleted patterns are
excluded from the parked count correctly.

### `GET /api/engagements/{eid}/dashboard/repositories`

Per-repository rows. Separate from the summary so the table can be sorted, filtered
and paginated without recomputing aggregates.

```json
{
  "repositories": [
    {
      "repository_id": "…",
      "slug": "order-management",
      "name": "order-management",
      "source_type": "upload",
      "provider": null,
      "ingest_status": "cloned",
      "has_git_history": true,
      "ingest_commit_sha": "a1b2c3d",
      "size_bytes": 48210040,
      "file_count": 1842,
      "last_ingested_at": "…",

      "latest_execution": {
        "job_execution_id": "…",
        "batch_status": "COMPLETED",
        "exit_status": "COMPLETED",
        "steps_completed": 1,
        "steps_not_implemented": 6,
        "steps_failed": 0,
        "steps_total": 7,
        "current_step": null,
        "started_at": "…",
        "ended_at": "…"
      },

      "application_count": null,
      "patterns_identified": null,
      "highest_risk_tier": null,
      "wave": null
    }
  ]
}
```

Query params: `?ingest_status=`, `?discovery_status=`, `?q=`, `?sort=`.

---

## Layout

Three bands, top to bottom.

### Band 1 — Summary cards

A row of cards. Each shows a headline figure, a breakdown line, and a muted
unavailable state where applicable.

| Card | Content now |
|---|---|
| **Repositories** | Total, with a breakdown of cloned / registered / failed |
| **Discovery** | Completed / in progress / failed executions |
| **Applications** | Unavailable — "Awaiting application fingerprinting (`application-fingerprinting`)" |
| **Patterns identified** | Unavailable — "Awaiting pattern classification (`pattern-classification`)" |
| **Target state decisions** | Approved / in review / parked, from the catalog |
| **Waves** | Unavailable — "Awaiting wave planning (`migration-wave-planning`)" |

Unavailable cards keep their position and size, rendered muted with the step name
that will populate them. That is the growth path made visible, and it reads as
deliberate rather than broken.

### Band 2 — Repository status table

The centre of the tab. One row per repository.

Columns: name, source, ingest status, git history indicator, size, applications,
patterns, discovery progress, last run, actions.

- **Discovery progress** — a segmented bar with one segment per step, coloured by
  outcome: completed green, not-implemented grey hatched, failed red, running amber
  pulsing, pending empty. Hovering a segment names the step and its status.
- **Applications / patterns** — `—` with tooltip naming the awaited step.
- **Actions** — View repository, View execution, Re-ingest.

Sortable on every real column. Filters on ingest status and discovery status.

The segmented progress bar is worth building properly. At a glance it shows which
lifecycle steps are real and which are stubs, per repository — it communicates the
platform's completeness better than any percentage.

### Band 3 — Two panels side by side

**Left — Pattern distribution.** Horizontal bars of application count per pattern
once `pattern-classification` exists. Until then, an empty state naming the awaited step and listing
the patterns currently in scope for the engagement from the catalog, which is real
data and worth showing.

**Right — Recent activity.** The last ten job executions: job name, repository,
status badge, duration, relative timestamp. Each links into the Workflow tab's
execution detail.

---

## Behaviour

- **Polling.** While any execution is non-terminal, poll the dashboard endpoint every
  5 seconds. Stop when all executions are terminal. Do not poll indefinitely.
- **Engagement switch.** Reload fully. The dashboard is engagement-scoped and shows
  nothing in Master Catalog view — hide the tab entirely there, as with Repositories.
- **Empty engagement.** No repositories yet: replace bands 2 and 3 with a single
  empty state and a primary action linking to the Repositories tab's ingest drawer.
- **Loading.** Skeleton cards and rows. No layout shift when data arrives.
- **Errors.** A failed dashboard fetch shows an inline retry, not a toast. This is a
  screen someone may leave open on a wall display.

---

## Visual direction

Same restraint as the rest of the UI. Semantic colour only for status. The dashboard
will be the first screen shown in a client demo, so it must read as an operations
console rather than a marketing page — dense with real information, no decorative
charts, no vanity metrics.

Target 1440px. Cards wrap to two rows below 1100px.

---

## Acceptance criteria

- [ ] Dashboard renders for an engagement with repositories and shows correct counts
- [ ] Applications, patterns, risk tiers and waves render as unavailable with the
      awaited step named — not as zero
- [ ] Decision counts match the catalog's coverage endpoint exactly
- [ ] The segmented progress bar shows 1 completed and 6 not-implemented segments per
      repository after a discovery run
- [ ] Uploading a repository in another tab causes the dashboard to reflect it within
      one poll cycle
- [ ] Polling stops once all executions are terminal
- [ ] An engagement with no repositories shows the empty state with a working action
- [ ] The tab is hidden in Master Catalog view
- [ ] Switching engagements fully reloads the data
