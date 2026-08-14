# 13 — Step 1: Repository Ingest

Lifecycle step 1. Owner: **P** (platform, deterministic). Job:
`phase0-repository-discovery`, per repository — see `15-REPOSITORY-INGEST-UI.md`
Part A.

> Enumerate repositories and create the inventory record set that everything
> downstream populates.

The first real step, and the entry point to the whole estate. Everything in Phase 0
builds on its output.

## Scope

**In:** read one already-registered repository's folder in place, resolve its git
metadata when present, verify its asserted clone URL, capture coarse size metrics,
and update its `repositories` row.

**Out:** solution or project parsing (step 2), fingerprinting (step 3), dependency
analysis (step 7). This step does not open a single `.csproj`. Also out: discovering
or registering repositories — that is the registration API (`15-REPOSITORY-INGEST-UI.md`
Part D), which runs before this step and creates the `repositories` row this step
reads.

## Sources

Two source types, replacing the three in earlier drafts of this document — see
`15-REPOSITORY-INGEST-UI.md` Part B. Selected by the `repositories.source_type`
column, **not** by step config.

### `local_path` — the only implemented source

The repository already exists on disk. The step reads it **in place**; nothing is
copied or cloned.

1. Read `local_path` from the `repositories` row — the row is authoritative and was
   validated at registration. Do not take it from step `config`.
2. Verify the path still exists and is a directory. `FAILED` with a clear message
   naming the path if the folder has moved or been deleted.
3. Detect `.git`. If present, resolve HEAD SHA, current branch and the `origin`
   remote URL; set `has_git_history: true`. If absent, set `ingest_commit_sha` null
   and `has_git_history: false` — a working folder without history is valid input.
4. Perform clone URL verification (see "Clone URL verification" below) and record
   the outcome.
5. Compute size and file-count metrics, skipping `.git`, `node_modules`, `bin`,
   `obj`, `packages`.
6. Update the `repositories` row and emit the `repository-inventory` artifact for
   this single repository.

**Phase 0 is read-only against the registered folder.** It must not write anything
there. Track A will later create a working branch; that is separate. Enforced in the
implementation and verified with `git status` during testing.

### `git_clone` — not implemented

Accepted as a shape at registration (parent directory plus an HTTPS clone URL), but
registration itself returns `501` for it (`15-REPOSITORY-INGEST-UI.md` Part D) — a
job never actually launches with `source_type: git_clone` yet. This step still
guards defensively: if it is ever invoked against a repository whose `source_type`
is not `local_path`, it returns `NOT_IMPLEMENTED` rather than guessing.

There is no more `manifest` source and no more `local_directory` source. Repository
discovery is one folder at a time, registered through the UI/API, not enumerated in
bulk by this step. There is no concurrent cloning to configure, because this step
never clones.

## Configuration

None. `config` is not used by this step — everything it needs (`local_path`,
`clone_url`, `source_type`) lives on the `repositories` row, addressed by
`parameters.repository_id`. This is deliberate: the row was validated once, at
registration, and is the single source of truth for every subsequent scan.

## Contract

```yaml
step_name: repository-ingest
lifecycle_step_no: 1
display_name: "Repository estate ingest & inventory creation"
owner_code: P
version: "1.0.0"
owner_team: "platform"
implementation_status: implemented

consumes: []

produces:
  - artifact_type: repository-inventory
    artifact_version: "1.0.0"

adapter_type: python
adapter_config:
  entrypoint: "app.steps.repository_ingest:run"

restart:
  allow_start_if_complete: false
  start_limit: 3
```

`consumes` is empty — this step reads the `repositories` row directly via
`parameters.repository_id`, not an upstream artifact. That is what makes the job
definition's `flow` need no `inputs:` wiring for it (see
`phase0-repository-discovery.yaml`).

## `repositories` table

Defined in full in `15-REPOSITORY-INGEST-UI.md` Part C, which replaces the table
definition this document used to carry. Read that section before touching this
step's persistence — in particular the three partial unique indexes, the
normalisation rules for `clone_url` and `local_path`, and the distinction between
"Scan results" columns (written by this step) and "Lifecycle" / "Engagement
metadata" columns (written by the registration API, not this step).

This step writes only the "Scan results" columns — `has_git_history`,
`ingest_commit_sha`, `size_bytes`, `file_count`, `ingest_status`, `ingest_error` —
plus `detected_clone_url`, `clone_url_verification`, and `last_scanned_at`. It never
sets `first_registered_at`, and never touches `local_path`, `clone_url`,
`root_folder_name`, or any of the engagement-metadata columns — those are identity
or operator-supplied fields owned by registration.

## Clone URL verification

The user **asserts** `clone_url` at registration; this step **verifies** it against
`.git` on every scan. Never silently overwrite what the user entered.

| Condition | `clone_url_verification` | Behaviour |
|---|---|---|
| `.git` present, normalised remote matches `clone_url` | `verified` | Proceed |
| `.git` present, normalised remote differs | `mismatch` | Proceed; both values stored, no rejection |
| No `.git`, or no `origin` remote configured | `unverifiable` | Proceed |

Normalisation (lowercase host, strip trailing `.git`, strip trailing slash, strip
embedded credentials, treat `git@host:org/repo` as `https://host/org/repo`) is the
same rule given in `15-REPOSITORY-INGEST-UI.md` Part C, applied to both sides before
comparing. A mismatch is a warning, not a rejection — see that document for why.

## Artifact: `repository-inventory@1.0.0`

Written to `output_dir/repository-inventory.json`, one artifact per repository (not
a bulk array across many repositories — this step's job is scoped to exactly one via
`parameters.repository_id`). Deterministic — sorted keys, 2-space indent, trailing
newline. Same rules as the catalog export, and for the same reason: this artifact
gets committed and diffed.

```json
{
  "artifact_type": "repository-inventory",
  "artifact_version": "1.0.0",
  "engagement_id": "client-a-ocp4",
  "repository_id": "3f2b8c14-9d7e-4a51-b6c2-8e1d4f70a9b3",
  "slug": "order-management",
  "name": "Order Management",
  "root_folder_name": "order-management",
  "local_path": "D:\\repos\\order-management",
  "source_type": "local_path",
  "clone_url": "https://github.com/example/order-management.git",
  "detected_clone_url": "https://github.com/example/order-management.git",
  "clone_url_verification": "verified",
  "provider": "github",
  "default_branch": "main",
  "current_branch": "main",
  "has_git_history": true,
  "ingest_commit_sha": "a1b2c3d4e5f6...",
  "size_bytes": 48210040,
  "file_count": 1842
}
```

**There is no `generated_at` field in this file.** The task requires "`generated_at`
excluded from the checksum calculation" so two runs over an unchanged repository
produce an identical checksum — and the engine's checksum (`app/workflow/adapters/base.py`)
is computed over the artifact file's actual bytes on disk, to catch a corrupt or
truncated write. The only way to satisfy both — a stable checksum *and* a checksum
that is genuinely the file's own hash, not something computed differently from what
gets verified — is to keep the varying timestamp out of the hashed bytes entirely.
`generated_at` is therefore carried in the `StepResult` output's `metadata` instead:

```json
{
  "outputs": [
    {
      "artifact_type": "repository-inventory",
      "artifact_version": "1.0.0",
      "uri": "file:///.../repository-inventory.json",
      "checksum": "sha256:...",
      "metadata": { "generated_at": "2026-08-05T10:00:00Z" }
    }
  ]
}
```

`current_branch` is informational only — there is no column for it on `repositories`
(only `default_branch`, which is operator-supplied or detected once at registration).
This step never overwrites `default_branch`.

## Processing model

Single item, not chunked — this step's whole job is one `repositories` row, resolved
from `parameters.repository_id`. Earlier drafts of this document described a
chunk-oriented, cursor-resumable model for enumerating many repositories from a
manifest; that no longer applies; registering many repositories means launching this
job once per repository (`phase0-repository-discovery` is per-repository — see
`15-REPOSITORY-INGEST-UI.md` Part A).

Metrics mapping:
- `read_count` — always `1` (the one repository)
- `write_count` — `1` on success, `0` on failure
- `skip_count` — always `0` — there is nothing to skip within a single repository
- `commit_count` — `1` (one row update)

## Exit statuses

| Condition | Exit status |
|---|---|
| Repository scanned successfully | `COMPLETED` |
| `parameters.repository_id` missing, or no matching row | `FAILED` |
| `local_path` does not exist or is not a directory | `FAILED` — `repositories.ingest_status` set to `path_missing` |
| `repositories.source_type` is not `local_path` | `NOT_IMPLEMENTED` |

## Idempotency

Re-running (a rescan) updates the **same** `repositories` row in place — it was
created once, at registration, and this step never creates or deletes a row.
`first_registered_at` is preserved; `last_scanned_at`, `ingest_commit_sha`,
`has_git_history`, `detected_clone_url`, `clone_url_verification`, `size_bytes`,
`file_count` and `ingest_status` are all overwritten with this run's findings. Two
consecutive runs over an unchanged repository produce byte-identical artifacts
(and therefore identical checksums) and leave the row in the same state.

## Validation and safety

- Cap traversal and skip `.git`, `node_modules`, `bin`, `obj`, `packages` when
  computing size metrics, or size computation dominates runtime.
- Never log credentials or full clone URLs containing tokens.
- Path-traversal and embedded-credential rejection for `local_path` / `clone_url`
  happen once, at registration (`15-REPOSITORY-INGEST-UI.md` Part E) — this step
  trusts the row it reads rather than re-validating input shape.

## Test fixtures

Ship alongside the implementation:

- `tests/fixtures/sample-context.json` — a full StepContext for standalone
  invocation. Its `parameters.repository_id` is a placeholder that will not resolve
  to a real row unless you have inserted one with that id — that is expected;
  invoking it demonstrates the standalone stdin/stdout mechanism works even when the
  outcome is a clean `FAILED`, not that the placeholder repository exists.
- The "folder with `.git`", "folder without `.git`", and "non-existent path" cases
  are constructed at test time in `tests/test_repository_ingest.py` (a real,
  disposable git working tree via `git init`), rather than checked in — a `.git`
  directory does not check into another git repository the way a plain fixture file
  does.

Standalone invocation must work, per `11-STEP-CONTRACT.md`:

```powershell
Get-Content tests/fixtures/sample-context.json | python -m app.steps.repository_ingest
```

The module needs a `__main__` entry reading StepContext from stdin and writing
StepResult to stdout, even though the engine calls it in-process via the `python`
adapter. This proves the step is genuinely decoupled and lets another team member
exercise it without the engine.

## Acceptance criteria

- [ ] Registers in `wf_step_registrations` with the declared contract: `consumes: []`,
      `produces: [repository-inventory@1.0.0]`, `adapter_type: python`,
      `implementation_status: implemented`
- [ ] `phase0-repository-discovery` validates with step 1 real and steps 2–10 as
      stubs, with **no change to the job definition YAML**
- [ ] Runs against a local folder with `.git`: resolves HEAD SHA, current branch,
      origin remote, and sets `clone_url_verification` correctly
- [ ] Runs against a local folder without `.git`: `has_git_history: false`,
      `ingest_commit_sha: null`, `clone_url_verification: "unverifiable"`
- [ ] A missing/moved folder yields `FAILED` and `ingest_status: path_missing`,
      naming the path in the message
- [ ] Produces a `repository-inventory` artifact with a verified checksum
- [ ] Two consecutive runs over an unchanged repository produce identical checksums
- [ ] `git status` in the registered folder is clean after a run — nothing written
      there
- [ ] Standalone stdin/stdout invocation works
