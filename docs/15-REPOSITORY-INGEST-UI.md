# 15 — Repository Registration UI & Orchestrator Trigger

UI-driven registration for lifecycle step 1. Amends
`13-STEP-001-REPOSITORY-INGEST.md` and `12-JOB-DEFINITION-FORMAT.md`.

**There is no file upload.** The repository already exists on the operating machine;
the user registers its folder path. Any earlier archive-upload design is superseded.

---

## Operating model — read this first

The platform runs on a single machine, operated by one person per client engagement.
The orchestration engine, the database, the UI and the repositories all live on that
machine. Every lifecycle step executes locally against local paths.

This assumption justifies: local filesystem paths as first-class input, in-process
background execution, no object storage, no distributed workers, no per-user access
control.

Record it explicitly in `CLAUDE.md`. When it changes — multiple operators, a shared
server, containerised deployment — the things that break are local path validity,
`BackgroundTasks` durability, and the absence of user scoping.

---

## Part A — Job scope amendment

`phase0-estate-discovery` is replaced by two jobs.

### `phase0-repository-discovery` — per repository

Launched automatically on registration or rescan. Steps 1, 2, 3, 4, 8, 9, 10.

```yaml
job_name: phase0-repository-discovery
version: 1
description: "Per-repository discovery and analysis. Lifecycle steps 1,2,3,4,8,9,10."

parameters:
  - name: engagement_id
    type: string
    required: true
  - name: repository_id
    type: string
    required: true
  - name: ingest_token
    type: string
    required: true

stub_policy: continue

flow:
  - step: repository-ingest
  - step: solution-discovery
  - step: application-fingerprinting
  - step: pattern-classification
  - step: impact-map-generation
  - step: test-coverage-assessment
  - step: risk-scoring-tier-assignment
```

`ingest_token` is a UUID generated per registration or rescan, making each rescan a
distinct job instance rather than a restart. Restarting a failed execution reuses its
token and therefore its instance, preserving restart semantics.

### `phase0-estate-consolidation` — engagement scoped

Steps 5, 6, 7, 11, 12. **Do not define yet** — all five are stubs. Precondition when
defined: every in-scope, non-deleted repository has a completed
`phase0-repository-discovery` execution.

---

## Part B — Step 1 source types

Replaces the four source types in `13-STEP-001-REPOSITORY-INGEST.md` with two.

### `local_path` — the only implemented source

The repository is already on disk. The step reads it **in place**; nothing is copied.

Behaviour:

1. Read `local_path` from the `repositories` row — the row is authoritative and was
   validated at registration. Do not take it from step config.
2. Verify the path still exists and is a directory. `FAILED` with a clear message if
   the folder has moved or been deleted.
3. Detect `.git`. If present, resolve HEAD SHA, current branch and the `origin`
   remote URL; set `has_git_history: true`. If absent, set `ingest_commit_sha` null
   and `has_git_history: false` — a working folder without history is valid input.
4. Perform clone URL verification (Part D) and record the outcome.
5. Compute size and file-count metrics, skipping `.git`, `node_modules`, `bin`,
   `obj`, `packages`.
6. Update the `repositories` row and emit the `repository-inventory` artifact for
   this single repository.

**Phase 0 is read-only against the registered folder.** It must not write anything
there. Track A will later create a working branch; that is separate. Enforce this in
the implementation and verify it with `git status` during testing.

### `git_clone` — accepted shape, not implemented

The user supplies an HTTPS clone URL and a parent directory. The platform clones into
`{parent_directory}/{repo-name}`, then proceeds exactly as `local_path` — cloning is
a preceding action, not a different analysis path.

Return `NOT_IMPLEMENTED`. Implement the route and validation now so the UI is wired
against a real endpoint; only the handler body changes later.

Bulk registration from a manifest is a future addition, out of scope.

---

## Part C — `repositories` table

Replaces the table definition in `13-STEP-001-REPOSITORY-INGEST.md` entirely.

### Identity and location

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | Auto-generated. The repository id |
| `engagement_id` | `TEXT` NOT NULL FK → `engagements.id` | |
| `name` | `TEXT` NOT NULL | Display name. Defaults to `root_folder_name`, editable |
| `root_folder_name` | `TEXT` NOT NULL | Last path segment. Immutable. Duplicate check |
| `slug` | `TEXT` NOT NULL | Normalised from `root_folder_name` |
| `local_path` | `TEXT` NOT NULL | Absolute path on the operating machine |
| `local_path_normalised` | `TEXT` NOT NULL | Duplicate check |
| `clone_url` | `TEXT` NOT NULL | User-asserted canonical identity |
| `clone_url_normalised` | `TEXT` NOT NULL | Duplicate check |
| `detected_clone_url` | `TEXT` | What `.git` actually reports. Null when no git |
| `clone_url_verification` | `TEXT` NOT NULL DEFAULT `'unverifiable'` | CHECK IN (`verified`, `mismatch`, `unverifiable`) |
| `source_type` | `TEXT` NOT NULL | CHECK IN (`local_path`, `git_clone`) |
| `provider` | `TEXT` | Derived from clone URL host: `github`, `bitbucket`, `azure_devops`, `gitlab`, `other` |
| `default_branch` | `TEXT` | Detected or user supplied |

### Engagement metadata — user supplied at registration

| Column | Type | Notes |
|---|---|---|
| `description` | `TEXT` | Optional. What this repository contains |
| `technical_owner` | `TEXT` | Optional. Who to ask about it. Invaluable at 50+ repos |
| `criticality` | `TEXT` NOT NULL DEFAULT `'medium'` | CHECK IN (`low`, `medium`, `high`, `critical`). Business criticality, an input to risk scoring at step 10 |
| `retirement_status` | `TEXT` NOT NULL DEFAULT `'active'` | CHECK IN (`active`, `slated_for_retirement`, `decommissioned`) |
| `tags` | `JSONB` NOT NULL DEFAULT `'[]'` | |
| `notes` | `TEXT` | Free text |

`criticality` and `retirement_status` are deliberate. Criticality feeds the tier
assignment at step 10, which otherwise has only technical signals to work from —
a small, well-tested repository running payments is not Tier 0 regardless of what
static analysis says. Retirement status answers an open question already recorded in
the v2 architecture document: some repositories will be retired rather than
modernized, and discovering that after migrating them is expensive.

Repositories with `retirement_status` other than `active` are still registered and
still scanned — the inventory is useful — but are **excluded from modernization scope
counts** on the dashboard.

### Scan results — written by step 1

| Column | Type | Notes |
|---|---|---|
| `has_git_history` | `BOOLEAN` NOT NULL DEFAULT false | |
| `ingest_commit_sha` | `TEXT` | Nullable. Null when `has_git_history` is false |
| `size_bytes` | `BIGINT` | |
| `file_count` | `INTEGER` | |
| `ingest_status` | `TEXT` NOT NULL | CHECK IN (`registered`, `scanned`, `scan_failed`, `path_missing`) |
| `ingest_error` | `TEXT` | |
| `ingest_token` | `TEXT` | Most recent token; correlates to the job instance |

### Lifecycle

| Column | Type | Notes |
|---|---|---|
| `first_registered_at` | `TIMESTAMPTZ` | Set once |
| `last_scanned_at` | `TIMESTAMPTZ` | Updated per scan |
| `deleted_at` / `deleted_by` | `TIMESTAMPTZ` / `TEXT` | Soft delete, consistent with the catalog |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |

### Duplicate detection

Three partial unique indexes, all `WHERE deleted_at IS NULL`:

- `(engagement_id, clone_url_normalised)` — the canonical identity check
- `(engagement_id, root_folder_name)`
- `(engagement_id, local_path_normalised)`

Normalisation, applied on write:

- **Clone URL** — lowercase host, strip trailing `.git`, strip trailing slash, strip
  embedded credentials, and treat `git@host:org/repo` as equivalent to
  `https://host/org/repo`.
- **Local path** — resolve to absolute, normalise separators, uppercase the Windows
  drive letter consistently, strip trailing separator.

Each violation returns **409** naming which check failed and the existing
repository's slug:

```
This repository is already registered for Client A as "order-management"
(matched on clone URL). Use Rescan to re-run discovery, or delete the existing
registration first.
```

### Nesting guard

Reject registration when the candidate path is a parent or descendant of an
already-registered, non-deleted path in the same engagement. Nested registrations
double-count applications and corrupt the estate inventory. Return 409 naming the
conflict.

Also index: `engagement_id`, `ingest_status`, `retirement_status`.

---

## Part D — Registration API

### Path inspection — called from the form before submission

```
POST /api/engagements/{eid}/repositories/inspect-path
{ "local_path": "D:\\repos\\order-management" }

→ 200
{
  "exists": true,
  "is_directory": true,
  "root_folder_name": "order-management",
  "suggested_name": "order-management",
  "suggested_slug": "order-management",
  "has_git": true,
  "detected_clone_url": "https://github.com/example/order-management.git",
  "detected_provider": "github",
  "detected_branch": "main",
  "detected_commit_sha": "a1b2c3d4e5f6",
  "estimated_file_count": 1842,
  "estimated_size_bytes": 48210040,
  "solution_files_found": 2,
  "project_files_found": 14,
  "duplicate_conflict": null,
  "warnings": []
}
```

Drives the form: the user pastes a path, inspection fires on blur, and name, branch
and provider prefill. It also surfaces a duplicate before the user fills anything else.

`solution_files_found` and `project_files_found` are a shallow glob count, not
analysis — they give the user immediate confidence the right folder was picked.

Warnings where applicable: no `.git` directory found, so the clone URL cannot be
verified; folder appears empty; no `.sln` or `.csproj` found; path is on a network
drive, which will make scanning slow.

Cap traversal for the estimates — sample rather than walking a large tree
exhaustively, and label them as estimates in the UI.

### Clone URL verification

The user **asserts** the clone URL; the platform **verifies** it against `.git`.
Never silently overwrite what the user entered.

| Condition | `clone_url_verification` | Behaviour |
|---|---|---|
| `.git` present, normalised remote matches the entered URL | `verified` | Proceed |
| `.git` present, normalised remote differs | `mismatch` | Proceed with a prominent warning; store both values |
| No `.git`, or no `origin` remote configured | `unverifiable` | Proceed with a note |

A mismatch is a warning, not a rejection. Legitimate causes exist — the repository
moved, the folder is a fork or a mirror, or the remote was never updated. But it is
also exactly what a wrong pasted path looks like, so it must be visible in the UI and
on the repository detail page rather than buried.

Verification runs at registration and again at every scan, so a remote changed later
is caught.

### Register

```
POST /api/engagements/{eid}/repositories/register
{
  "source_type": "local_path",
  "local_path": "D:\\repos\\order-management",
  "name": "Order Management",
  "clone_url": "https://github.com/example/order-management.git",
  "description": "Core ordering API and background workers",
  "technical_owner": "A. Kumar",
  "criticality": "high",
  "retirement_status": "active",
  "default_branch": "main",
  "tags": ["billing"],
  "notes": ""
}

→ 202
{
  "repository_id": "…",
  "slug": "order-management",
  "ingest_token": "…",
  "job_execution_id": "…",
  "clone_url_verification": "verified",
  "status": "processing"
}
```

`local_path` and `clone_url` are mandatory. `name` defaults to `root_folder_name`.
`criticality` defaults to `medium`, `retirement_status` to `active`.

### Clone registration — 501 for now

```
POST /api/engagements/{eid}/repositories/register
{
  "source_type": "git_clone",
  "clone_url": "https://github.com/example/order-management.git",
  "parent_directory": "D:\\repos",
  "name": "Order Management"
}

→ 501
{
  "detail": "Clone-from-URL registration is not yet available. Clone the repository manually and register its local path.",
  "supported_source_types": ["local_path"]
}
```

### Supporting endpoints

```
GET    /api/engagements/{eid}/repositories        list, engagement scoped
GET    /api/repositories/{id}                     detail incl. latest execution
PUT    /api/repositories/{id}                     editable metadata only
DELETE /api/repositories/{id}                     soft delete
POST   /api/repositories/{id}/restore
POST   /api/repositories/{id}/rescan              new ingest_token, relaunch discovery
POST   /api/repositories/{id}/verify-path         re-check the path still exists
GET    /api/repositories/{id}/executions
```

`PUT` may change only `name`, `description`, `technical_owner`, `criticality`,
`retirement_status`, `tags`, `notes` and `default_branch`. It must **not** change
`local_path`, `clone_url` or `root_folder_name` — those are identity. Relocating
means delete and re-register.

`verify-path` sets `ingest_status: path_missing` when the folder has gone, so stale
registrations are visible rather than failing mysteriously at the next scan.

---

## Part E — Registration validation

Lighter than an upload model, but not absent. The operator is trusted; these guards
prevent mistakes, not attacks.

- Path must be **absolute**. Reject relative paths with a clear message.
- Path must exist and be a directory.
- Reject system locations: `C:\Windows`, `C:\Program Files`,
  `C:\Program Files (x86)`, `C:\ProgramData`, and any bare drive root such as `C:\`.
  Registering a drive root would attempt to scan the whole disk.
- Reject a path containing no files at all.
- Clone URL must parse as an `https` URL or match the `git@host:org/repo` SSH form.
  Reject embedded credentials (`https://user:token@…`) with a message pointing at
  environment variables.
- Warn but allow when no `.sln` or `.csproj` is present — the folder may still be in
  scope, and pattern discovery may surface something unanticipated.

### Orchestrator launch

After validation passes:

1. Insert the `repositories` row with `ingest_status: registered` and the
   `ingest_token`.
2. Create the job instance and job execution for `phase0-repository-discovery`
   **synchronously**, so the response carries a trackable execution id.
3. Execute the job **asynchronously**.
4. Return 202.

Use FastAPI `BackgroundTasks`, appropriate to the single-machine model. Add a startup
reconciliation marking executions left in `STARTED` by a previous process as `FAILED`
with exit message "orphaned by engine restart", so the UI never shows a permanently
stuck run after the operator restarts the backend.

---

## Part F — Repositories tab UI

Engagement-scoped. Hidden in Master Catalog view.

### List view

Columns: name, root folder, criticality, ingest status, git indicator, size,
applications, patterns, discovery progress, last scanned, actions.

- **Ingest status** — `registered` grey, `scanned` teal, `scan_failed` red,
  `path_missing` amber with a warning icon.
- **Criticality** — badge; `critical` red, `high` amber, `medium` neutral, `low` muted.
- **Git indicator** — a small marker showing `verified`, `mismatch` (amber warning) or
  `unverifiable` (muted).
- **Applications / patterns** — `—` with a tooltip naming the awaited step wherever
  the producing step is a stub. See Part G. Never display `0`.
- **Discovery progress** — `n/7` with the segmented bar from `16-DASHBOARD-SPEC.md`.
- **Actions** — View, Rescan, Verify path, Delete.

Rows for repositories not `active` render muted with a retirement badge.

Header: **+ Register Repository**. Filters on ingest status, criticality and
retirement status. Search on name, root folder and technical owner.

### Registration drawer

**Source selection** as a segmented control:

| Option | State |
|---|---|
| Local folder path | **enabled** |
| GitHub | disabled — "Coming soon" |
| Bitbucket | disabled — "Coming soon" |
| Azure DevOps | disabled — "Coming soon" |
| Other Git URL | disabled — "Coming soon" |

Disabled options look deliberately inactive, consistent with the future tabs.
Selecting one shows an inline note and keeps submit disabled. Never call the 501
endpoint from the UI.

**Local folder form**, grouped into two sections.

*Location* —

1. **Local folder path** — monospace input, placeholder `D:\repos\my-repository`.
   Calls `inspect-path` on blur, debounced. Below it, an inspection panel showing
   detected folder name, git status, branch, commit, solution and project file
   counts, estimated size, and any warnings. A duplicate conflict renders as a
   blocking error naming the existing repository, with submit disabled.
2. **Git clone URL** — required, entered by the user. Helper text: "The repository's
   canonical URL. It identifies this repository independently of where it sits on
   disk." Once a path with `.git` has been inspected, show a live verification
   indicator beneath the field:
   - match → green "Verified against the folder's git remote"
   - differ → amber "Does not match the folder's remote: {detected}. Check the path
     is correct. You can continue if this is intentional."
   - no git → muted "Cannot be verified — no git remote found in this folder"

*Details* —

3. **Repository name** — prefilled from `suggested_name`, editable.
4. **Description** — optional textarea.
5. **Technical owner** — optional.
6. **Business criticality** — select, default `medium`, with helper text noting it
   feeds risk tiering.
7. **Retirement status** — select, default `active`. Choosing anything else shows an
   inline note that the repository will be inventoried but excluded from
   modernization scope.
8. **Default branch** — prefilled from detection, editable.
9. **Tags** — optional tag input.
10. **Notes** — optional textarea.

Registration is a small JSON POST, so no upload progress indicator. The fetch-only
convention in `04-FRONTEND-SPEC.md` stands unamended.

**On 202:** close the drawer, insert the row with a processing indicator, and poll
`GET /api/repositories/{id}` every 3 seconds until the execution is terminal.

### Repository detail

Metadata panel: name, id (monospace), root folder, local path (monospace with a copy
button), clone URL with its verification badge and the detected URL when different,
provider, description, technical owner, criticality, retirement status, branch,
commit SHA short or "no git history", size, file count, tags, notes, first
registered, last scanned.

A **path status** line showing whether the folder is currently present, with a Verify
path action beside it.

Execution history: `phase0-repository-discovery` executions with batch status, exit
status, duration, and a link into the Workflow tab's execution detail.

Artifacts: the `repository-inventory` artifact per execution with type, version,
size, checksum and a download link.

---

## Part G — Honest metrics

```
GET /api/workflow/capabilities
→ {
  "implemented_steps": ["repository-ingest"],
  "metrics_available": {
    "repository_count": true,
    "application_count": false,
    "pattern_classification": false,
    "impact_map": false,
    "test_coverage": false,
    "risk_tier": false
  }
}
```

Derived from `wf_step_registrations.implementation_status`. The frontend fetches it
once on load and renders `—` with an explanatory tooltip for any metric whose
producing step is still a stub. Do not fabricate zeros.

---

## Acceptance criteria

- [ ] `inspect-path` on a folder with `.git` returns detected clone URL, branch,
      commit SHA, folder name and solution/project counts
- [ ] `inspect-path` on a folder without `.git` returns `has_git: false` with the
      unverifiable warning
- [ ] `inspect-path` on a non-existent path returns `exists: false` without erroring
- [ ] Entering a clone URL matching the folder's remote yields `verified`
- [ ] Entering a different clone URL yields `mismatch`, warns prominently, and still
      allows submission, storing both URLs
- [ ] A folder without `.git` yields `unverifiable`
- [ ] Registering a valid path creates the row and launches discovery, returning 202
      with a resolvable `job_execution_id`
- [ ] Registering the same clone URL again returns 409 naming the existing repository
- [ ] Registering the same root folder name again returns 409
- [ ] Registering a parent or child of an existing registered path returns 409
- [ ] Registering `C:\` or `C:\Windows` is rejected
- [ ] Registering a relative path is rejected
- [ ] A clone URL with embedded credentials is rejected
- [ ] Discovery progress reaches `7/7` — step 1 `COMPLETED`, the other six
      `NOT_IMPLEMENTED`
- [ ] Applications and patterns columns show `—`, not `0`
- [ ] Rescan creates a new job instance rather than restarting the old one
- [ ] Renaming the folder on disk, then Verify path, sets `path_missing`
- [ ] `PUT` cannot change `local_path`, `clone_url` or `root_folder_name`
- [ ] `PUT` can change criticality, retirement status, owner and notes
- [ ] A repository marked `slated_for_retirement` renders muted and is excluded from
      dashboard modernization scope counts
- [ ] Selecting GitHub disables submission and explains why
- [ ] Restarting the backend mid-execution leaves nothing stuck in `STARTED`
- [ ] `git status` in the registered folder is clean after a discovery run
- [ ] The tab is hidden in Master Catalog view
