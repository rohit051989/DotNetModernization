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
   remote URL; set `has_git_history: true` and `source_control_status: GIT`. If
   absent, set `ingest_commit_sha` null, `has_git_history: false` and
   `source_control_status: NONE` — a working folder without history is valid input.
   If `.git` is newly present and the row has no `clone_url` yet, backfill it from
   the detected remote (Part D) rather than leaving it null with
   `source_control_status: GIT`, which the schema forbids.
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
| `source_control_status` | `TEXT` NOT NULL DEFAULT `'NONE'` | CHECK IN (`GIT`, `NONE`). Whether the folder has a `.git` directory. Re-derived on every scan, not just at registration — a folder can be migrated into source control after being registered |
| `clone_url` | `TEXT` | Nullable. User-asserted canonical identity. **Required when `source_control_status` is `GIT`** — enforced both at registration (422) and by `ck_repositories_clone_url_required_for_git`. Null for a folder that was never under source control, unless the operator supplies one anyway (e.g. a repository being migrated into source control) |
| `clone_url_normalised` | `TEXT` | Nullable, mirroring `clone_url`. Duplicate check — see below |
| `detected_clone_url` | `TEXT` | What `.git` actually reports. Null when no git |
| `clone_url_verification` | `TEXT` NOT NULL DEFAULT `'unverifiable'` | CHECK IN (`verified`, `mismatch`, `unverifiable`, `not_applicable`). `not_applicable` means there is no `clone_url` at all to verify — distinct from `unverifiable`, which means a `clone_url` exists but there is nothing to check it against (no git remote, or no git at all but the operator supplied one anyway) |
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

- `(engagement_id, clone_url_normalised)` — the canonical identity check.
  **Additionally scoped `AND clone_url_normalised IS NOT NULL`** — the check applies
  only where there is a clone URL to compare. A folder with no clone URL cannot
  collide on this index; `root_folder_name` and `local_path_normalised` remain the
  identity checks for those.
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
  "source_control_status": "GIT",
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
`source_control_status` tells the form whether the clone URL field is required
(`GIT`) or optional (`NONE`) — the field itself never hardcodes that decision.

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
| `.git` present, no `origin` remote configured | `unverifiable` | Proceed with a note |
| No `.git`, but the operator supplied a clone URL anyway | `unverifiable` | Proceed with a note. `source_control_status` stays `NONE` — supplying a URL does not retroactively make the folder git-tracked; see the "migrating into source control" case below |
| No `.git`, and no clone URL supplied | `not_applicable` | Proceed. There is nothing to verify, not merely something unverified — a folder that was never under source control has no canonical URL, and `docs/15` treating that as a form of "unverifiable" was the original spec error |

A mismatch is a warning, not a rejection. Legitimate causes exist — the repository
moved, the folder is a fork or a mirror, or the remote was never updated. But it is
also exactly what a wrong pasted path looks like, so it must be visible in the UI and
on the repository detail page rather than buried.

**A folder that was never under source control is a real, common case for a legacy
estate** — a file share, an old FTP drop, code that predates the team's adoption of
git — not an edge case. `clone_url` is nullable and required only when
`source_control_status` is `GIT`; making it universally mandatory made step 1 unable
to register exactly the repositories a modernization program most needs visibility
into. The operator may still supply a clone URL on a non-git folder — the
"repository being migrated into source control" case — in which case it is recorded
with `clone_url_verification: unverifiable` (there is a URL, just nothing to check it
against) while `source_control_status` stays `NONE` until `.git` actually appears.
Verification, and `source_control_status` itself, are both re-derived on every
scan — not just at registration — so a folder that gains `.git` after being
registered is caught on the next rescan. If the operator never supplied a clone URL
and the rescan detects one via `.git`'s `origin` remote, it is backfilled from the
detected remote rather than left null, since `source_control_status: GIT` requires a
non-null `clone_url`.

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

`local_path` is always mandatory. `clone_url` is mandatory only when the folder has
a `.git` directory — omitting it (or sending `null`) for a git folder returns 422,
`code: CLONE_URL_REQUIRED_FOR_GIT`, naming the `clone_url` field. `name` defaults to
`root_folder_name`. `criticality` defaults to `medium`, `retirement_status` to
`active`.

A folder with no `.git` needs no `clone_url` at all:

```
POST /api/engagements/{eid}/repositories/register
{
  "source_type": "local_path",
  "local_path": "D:\\samples\\no-git-repo",
  "name": "No-Git Legacy Folder",
  "description": "Legacy code that lived on a file share and was never put under source control.",
  "criticality": "medium",
  "retirement_status": "active",
  "tags": ["legacy", "no-source-control"]
}

→ 202
{
  "repository_id": "…",
  "slug": "no-git-repo",
  "ingest_token": "…",
  "job_execution_id": "…",
  "clone_url_verification": "not_applicable",
  "status": "processing"
}
```

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
- Clone URL, when supplied, must parse as an `https` URL or match the
  `git@host:org/repo` SSH form. Reject embedded credentials (`https://user:token@…`)
  with a message pointing at environment variables. Not supplying one at all is
  valid — see Part C — unless the folder has `.git`, in which case it is required.
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
- **Git indicator** — a small marker showing `verified`, `mismatch` (amber warning),
  `unverifiable` (muted), or `not_applicable` (muted, labelled "not under source
  control").
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
2. **Git clone URL** — entered by the user. Required only when `inspect-path`
   reported `source_control_status: GIT`; the field's own label reflects this
   ("Git clone URL" vs. "Git clone URL (optional)"), and submission is never blocked
   on it for a folder with no `.git`. When required, helper text: "The repository's
   canonical URL. It identifies this repository independently of where it sits on
   disk." Once a path has been inspected, show a live verification indicator beneath
   the field:
   - `.git` present, match → green "Verified against the folder's git remote"
   - `.git` present, differ → amber "Does not match the folder's remote: {detected}.
     Check the path is correct. You can continue if this is intentional."
   - `.git` present, no remote → muted "Cannot be verified — no git remote found in
     this folder. It will be recorded unverified."
   - no `.git`, field empty → muted "No .git directory found — this folder was never
     under source control. Leave this blank, or enter a URL if it is being migrated
     into source control."
   - no `.git`, field filled → muted "Cannot be verified — no git remote found in
     this folder. It will be recorded unverified."

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
button), clone URL with its verification badge and the detected URL when different —
**"Not under source control"**, not an empty field, when `clone_url` is null —
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
- [ ] A folder without `.git` and with no `clone_url` supplied yields `not_applicable`
- [ ] A folder without `.git` but with a `clone_url` supplied anyway yields
      `unverifiable`, and `source_control_status` stays `NONE`
- [ ] Registering a folder with no `.git` and no `clone_url` succeeds — this is the
      case docs/15 originally made unsatisfiable: a legacy folder that was never
      under source control
- [ ] Registering a folder with `.git` and no `clone_url` returns 422,
      `code: CLONE_URL_REQUIRED_FOR_GIT`, naming the `clone_url` field
- [ ] Registering a valid path creates the row and launches discovery, returning 202
      with a resolvable `job_execution_id`
- [ ] Registering the same clone URL again returns 409 naming the existing repository
- [ ] Registering two different no-`.git` folders with no `clone_url`, in the same
      engagement, does **not** 409 on the clone URL check — only on root folder name
      or local path, if those also collide
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
- [ ] Registering a no-`.git` folder with no `clone_url`, then running `git init` +
      adding a remote in that folder on disk and Rescanning, sets
      `source_control_status: GIT` with `clone_url` backfilled from the detected
      remote — the "migrating into source control" case, caught on rescan
- [ ] `PUT` cannot change `local_path`, `clone_url` or `root_folder_name`
- [ ] `PUT` can change criticality, retirement status, owner and notes
- [ ] A repository marked `slated_for_retirement` renders muted and is excluded from
      dashboard modernization scope counts
- [ ] Selecting GitHub disables submission and explains why
- [ ] Restarting the backend mid-execution leaves nothing stuck in `STARTED`
- [ ] `git status` in the registered folder is clean after a discovery run
- [ ] The tab is hidden in Master Catalog view
