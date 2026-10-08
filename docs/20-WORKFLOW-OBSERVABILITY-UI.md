# 20 — Workflow Observability UI

The execution surface: what ran, what it produced, and why it failed. This is the
debugging tool for every step built from here on, and it is also the screen that
carries the fleet-view demo narrative.

Build this **before `solution-discovery`**. Adding a parser-heavy step without execution
visibility means debugging through psql and log tails.

---

## Part A — Missing endpoints

Most of what the UI needs exists. These do not.

### Artifact access

```
GET /api/workflow/executions/{execution_id}/artifacts
→ 200 [ArtifactSummary]   grouped-ready list: type, version, size, checksum,
                          producing step_name and step_execution_id, created_at

GET /api/workflow/artifacts/{artifact_id}
→ 200 ArtifactDetail      metadata plus resolved local path

GET /api/workflow/artifacts/{artifact_id}/content
→ 200 the parsed JSON body, for inline viewing
→ 413 when the file exceeds ARTIFACT_INLINE_MAX_BYTES (default 5 MB)
→ 415 when the artifact is not JSON

GET /api/workflow/artifacts/{artifact_id}/download
→ 200 the raw file with Content-Disposition attachment
```

`content` returns the parsed object so the UI can render it directly. `download`
always works regardless of size or type.

Both must verify the on-disk checksum against `wf_artifacts.checksum` before
returning, and respond **409** with a clear message if they differ. An artifact that
has drifted from its recorded checksum is a real finding, not something to serve
silently.

### Execution detail enrichment

`GET /api/workflow/executions/{id}` currently returns the execution row. Extend it:

```json
{
  "job_execution_id": "…",
  "job_name": "phase0-repository-discovery",
  "job_definition_version": 1,
  "execution_number": 2,
  "batch_status": "COMPLETED",
  "exit_status": "COMPLETED",
  "exit_message": null,
  "started_at": "…",
  "ended_at": "…",
  "duration_seconds": 4.812,
  "engine_version": "0.2.0",
  "triggered_by": "api",
  "job_instance_id": "…",
  "parameters": {
    "engagement_id": "client-a-ocp4",
    "repository_id": "…",
    "ingest_token": "…"
  },
  "resolved_context": {
    "engagement_name": "Client A",
    "repository_slug": "order-management",
    "repository_name": "Order Management"
  },
  "step_summary": { "total": 7, "completed": 1, "not_implemented": 6, "failed": 0, "pending": 0 },
  "artifact_count": 1,
  "can_restart": false,
  "can_resume": false
}
```

`resolved_context` is the important addition — it turns opaque UUIDs into names, so
the UI never has to make three extra calls to label a row. Populate it by looking up
whichever parameters are present; omit keys that do not apply.

`can_restart` and `can_resume` let the UI render actions without duplicating the
engine's state rules.

### Step execution enrichment

`GET /api/workflow/executions/{id}/steps` should return, per step:

```json
{
  "step_execution_id": "…",
  "step_name": "repository-ingest",
  "lifecycle_step_no": 1,
  "display_name": "Repository estate ingest & inventory creation",
  "owner_code": "P",
  "step_version": "1.0.0",
  "adapter_type": "python",
  "implementation_status": "implemented",
  "sequence": 1,
  "attempt": 1,
  "batch_status": "COMPLETED",
  "exit_status": "COMPLETED",
  "exit_message": "Scanned order-management: 1842 files, 48.2 MB",
  "metrics": { "read_count": 1, "write_count": 1, "skip_count": 0, "commit_count": 1 },
  "started_at": "…",
  "ended_at": "…",
  "duration_seconds": 3.104,
  "diagnostics": [ { "level": "warning", "code": "…", "message": "…", "ref": "…" } ],
  "inputs_resolved": [ { "logical_name": "…", "artifact_type": "…", "artifact_version": "…", "artifact_id": "…" } ],
  "outputs_produced": [ { "artifact_id": "…", "artifact_type": "…", "artifact_version": "…" } ],
  "stdout_tail": "…",
  "stderr_tail": "…",
  "working_dir": "runs/client-a-ocp4/order-management/0002-8f2c1b4a/repository-ingest",
  "carried_forward": false
}
```

`display_name`, `owner_code`, `adapter_type` and `implementation_status` are joined
from `wf_step_registrations`. `carried_forward` marks steps copied from a prior
execution on restart rather than re-run — otherwise a restarted execution looks like
it re-ran everything.

`inputs_resolved` is worth surfacing prominently. It is the visible evidence that the
contract machinery works: you can see `solution-discovery` received `repository-ingest`'s artifact, and which
version.

---

## Part B — Workflow tab

Engagement-scoped, hidden in Master Catalog view. Three panes.

### Jobs list

Small panel at the top. One row per registered job definition:

- job name, active definition version, scope (`per repository`, `per engagement`)
- step count, and how many of those steps are implemented versus stub —
  e.g. `1 of 7 implemented`
- last execution status and relative time
- **Launch** button

Launch opens a drawer that builds its form from
`GET /api/workflow/jobs/{job_name}/parameters` — one input per declared parameter,
using the description as helper text. For `repository_id`, render a select populated
from the engagement's repositories rather than a raw UUID field. Generate
`ingest_token` automatically with a note explaining that each launch is a distinct
run.

### Executions list

Filterable table: job name, repository, batch status, exit status, steps summary
(`1/7`), duration, started, triggered by.

Filters: job name, batch status, repository. Default sort newest first.

Status badges: `COMPLETED` teal, `FAILED` red, `STARTED` amber pulsing, `STOPPED`
grey, `ABANDONED` muted red.

Row click opens the execution detail.

### Execution detail

The main view. Three stacked sections.

**Header** — job name, repository name, batch and exit status badges, execution
number, duration, started and ended, engine version, triggered by. Parameters in a
compact definition list, UUIDs monospace with copy buttons. Restart and Resume
buttons, enabled from `can_restart` / `can_resume`.

**Step timeline** — vertical, one row per step, in flow order.

Each row collapsed shows: sequence number and lifecycle step number, display name,
owner code badge, status badges, duration, and metrics as a compact
`read 1 · write 1 · skip 0`.

Visual treatment by state, so the timeline is readable at a glance:

| State | Treatment |
|---|---|
| `COMPLETED` | Solid teal marker |
| `NOT_IMPLEMENTED` | Grey hatched marker, muted text, `STUB` chip |
| `FAILED` | Red marker, row tinted, expanded by default |
| `STARTED` | Amber pulsing marker |
| `AWAITING_APPROVAL` | Amber marker, `GATE` chip |
| Carried forward on restart | Teal marker, dashed outline, `CARRIED FORWARD` chip |
| Not reached | Empty marker, muted |

Expanded, a row adds: exit message, inputs resolved (each linking to the producing
artifact), outputs produced (each linking to the artifact viewer), diagnostics as a
small table with level, code, message and ref, stdout and stderr tails in monospace
scroll boxes, working directory path with a copy button, attempt number when above 1.

A failed step expands automatically and its stderr tail is visible without a click.
That is the single most common thing you will need.

**Artifacts** — grouped by producing step. Per artifact: type and version as
`repository-inventory@1.1.0`, size, short checksum, created time, and **View** and
**Download** actions.

### Artifact viewer

A drawer, not a new page.

- Header: type, version, size, full checksum with copy, producing step and execution
- Body: pretty-printed JSON with syntax highlighting, collapsible objects and arrays,
  a plain-text toggle, and a copy-all button
- Over the inline size limit: show metadata plus a download prompt instead of the body
- Checksum mismatch (409): show a prominent error rather than the content

This is the "result of that step" view. When `solution-discovery` lands, this is where you will
read the discovered solutions and projects.

---

## Part C — Deep links

Execution state is reachable from wherever a repository appears.

- **Repositories list** — the discovery progress bar links to the latest execution
  detail. Each segment tooltips with its step name and status.
- **Repository detail** — the execution history table links per row. The artifacts
  panel opens the same artifact viewer.
- **Dashboard** — recent activity rows link to execution detail; repository table
  progress bars link to the latest execution.

Use real routes (`/workflow/executions/{id}`) rather than tab state, so an execution
can be linked to and reloaded directly. This matters when you are diagnosing a
failure and want to send someone the exact run.

---

## Part D — Live updates

- Execution detail polls every 2 seconds while `batch_status` is `STARTED` or
  `STARTING`; stops on terminal.
- Executions list polls every 5 seconds while any listed execution is non-terminal.
- Polling stops when the browser tab is hidden and resumes on focus.
- Updates must not reset scroll position or collapse an expanded step. Poll, diff,
  patch — do not re-render the whole timeline.

---

## Part E — Empty and error states

- **No executions for the engagement** — empty state pointing at the Repositories tab
  to register one.
- **Execution not found** — clear message with a link back to the list, not a blank
  screen.
- **Step has no stdout or stderr** — say "no output captured" rather than rendering
  an empty box. Python-adapter steps produce none, which is normal.
- **Artifact file missing on disk** — the row still renders with metadata, and View
  and Download show why they are unavailable. Runs directories can be cleaned up;
  the database record outliving the file is expected, not an error.

---

## Acceptance criteria

- [ ] Workflow tab appears for an engagement and is hidden in Master Catalog view
- [ ] Jobs list shows `phase0-repository-discovery` with its implemented-vs-stub count
- [ ] Launch drawer builds its inputs from the parameters endpoint, with a repository
      select rather than a UUID field, and auto-generates `ingest_token`
- [ ] Executions list filters by job, status and repository
- [ ] Execution detail shows all seven steps in flow order, with `repository-ingest` solid and the
      other six visibly stubbed
- [ ] `repository-ingest` expanded shows metrics, exit message, working directory and its produced
      artifact
- [ ] The artifact viewer renders `repository-inventory` JSON, with copy and download
- [ ] Download returns the file, and the checksum matches what the UI displays
- [ ] Tampering with an artifact file on disk makes View return 409 with a clear error
- [ ] A failed step is expanded by default with its stderr visible
- [ ] Restarting a failed execution shows carried-forward steps distinctly
- [ ] Discovery progress bars on Repositories and Dashboard link through to the
      execution
- [ ] An execution URL can be reloaded directly and resolves
- [ ] Polling stops on terminal status and does not disturb an expanded step
- [ ] `resolved_context` means no UUID appears in the UI without a name beside it
