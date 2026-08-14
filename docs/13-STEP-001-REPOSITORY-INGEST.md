# 13 — Step 1: Repository Ingest

Lifecycle step 1. Owner: **P** (platform, deterministic). Job:
`phase0-estate-discovery`.

> Enumerate repositories and create the inventory record set that everything
> downstream populates.

The first real step, and the entry point to the whole estate. Everything in Phase 0
builds on its output.

## Scope

**In:** discover repositories from a declared source, register them in the platform
inventory, obtain a local working copy, record a baseline commit SHA, capture
coarse size metrics.

**Out:** solution or project parsing (step 2), fingerprinting (step 3), dependency
analysis (step 7). This step does not open a single `.csproj`.

## Sources

Three source types, selected by `config.source_type`.

### `manifest` — the default, and the only one needed for the demo

A YAML file listing repositories. Clone credentials are never in the manifest.

```yaml
# input/repos.yaml
manifest_version: "1.0"
repositories:
  - name: order-management
    clone_url: "https://github.com/example/order-management.git"
    default_branch: main
  - name: legacy-billing
    clone_url: "https://github.com/example/legacy-billing.git"
    default_branch: master
    tags: ["high-risk"]
```

### `local_directory` — for sample sets and offline work

Scans a directory one level deep for folders containing a `.git` directory. Each
becomes a repository. Useful for the pre-onboarding sample set where repositories are
already on disk.

```yaml
config:
  source_type: local_directory
  root_path: "D:/samples/dotnet-legacy"
```

### `provider_api` — specify now, implement later

GitHub, Azure DevOps or Bitbucket organisation enumeration. Register the code path
and return `NOT_IMPLEMENTED`. We have no client credentials pre-onboarding, so
building it now would be untestable.

## Configuration

```yaml
config:
  source_type: manifest              # manifest | local_directory | provider_api
  manifest_path: "./input/repos.yaml"
  root_path: null                    # local_directory only
  workspace_root: "./workspace/repos"
  clone_mode: shallow                # shallow | full | none
  shallow_depth: 1
  clone_timeout_seconds: 600
  max_concurrent_clones: 4
  skip_on_clone_failure: true
  compute_size_metrics: true
```

`clone_mode: none` registers repositories without cloning — useful for a fast
inventory pass before committing disk to 50+ clones.

`clone_mode: shallow` is the default. Step 18 needs real history for baseline
verification, so it will deepen the clone itself when required. Do not clone full
history here.

Credentials come from engine environment (`GIT_USERNAME` / `GIT_TOKEN`), never from
config or the manifest.

## Contract

```yaml
step_name: repository-ingest
lifecycle_step_no: 1
display_name: "Repository estate ingest & inventory creation"
owner_code: P
version: "1.0.0"
owner_team: "platform"
implementation_status: implemented

consumes:
  - artifact_type: repo-manifest
    version_range: "^1.0.0"
    optional: true            # not required for local_directory or provider_api

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

`consumes` is `optional: true` because only the `manifest` source needs it. The step
validates at runtime that a manifest input is present when `source_type: manifest`,
failing with a clear message otherwise.

## New table: `repositories`

Platform inventory, not a workflow table — no `wf_` prefix.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `engagement_id` | `TEXT` NOT NULL FK → `engagements.id` | |
| `name` | `TEXT` NOT NULL | From manifest or directory name |
| `slug` | `TEXT` NOT NULL | Normalised, `^[a-z0-9]+(-[a-z0-9]+)*$` |
| `source_type` | `TEXT` NOT NULL | CHECK IN (`manifest`,`local_directory`,`provider_api`) |
| `source_uri` | `TEXT` | Clone URL, or absolute path for local |
| `default_branch` | `TEXT` | |
| `local_path` | `TEXT` | Working copy location |
| `ingest_commit_sha` | `TEXT` | Baseline. The estate as of this scan |
| `ingest_status` | `TEXT` NOT NULL | CHECK IN (`registered`,`cloned`,`clone_failed`,`skipped`) |
| `ingest_error` | `TEXT` | |
| `size_bytes` | `BIGINT` | Working tree, excluding `.git` |
| `file_count` | `INTEGER` | |
| `tags` | `JSONB` | From manifest |
| `first_ingested_at` | `TIMESTAMPTZ` | Set once |
| `last_ingested_at` | `TIMESTAMPTZ` | Updated every run |
| `deleted_at` / `deleted_by` | `TIMESTAMPTZ` / `TEXT` | Soft delete, consistent with the catalog |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |

Unique on `(engagement_id, slug)` where `deleted_at IS NULL`.
Indexes on `engagement_id`, `ingest_status`.

## Artifact: `repository-inventory@1.0.0`

Written to `output_dir/repository-inventory.json`. Deterministic — sorted keys,
repositories sorted by `slug`, 2-space indent, trailing newline. Same rules as the
catalog export, and for the same reason: this artifact gets committed and diffed.

```json
{
  "artifact_type": "repository-inventory",
  "artifact_version": "1.0.0",
  "engagement_id": "client-a-ocp4",
  "source_type": "manifest",
  "generated_at": "2026-08-05T10:00:00Z",
  "summary": {
    "total": 52,
    "cloned": 49,
    "clone_failed": 2,
    "skipped": 1,
    "total_size_bytes": 4821004032
  },
  "repositories": [
    {
      "slug": "order-management",
      "name": "order-management",
      "source_uri": "https://github.com/example/order-management.git",
      "default_branch": "main",
      "local_path": "workspace/repos/order-management",
      "ingest_commit_sha": "a1b2c3d4e5f6...",
      "ingest_status": "cloned",
      "size_bytes": 48210040,
      "file_count": 1842,
      "tags": []
    }
  ]
}
```

`generated_at` is excluded from the checksum calculation so that two runs over
unchanged repositories produce an identical checksum. State this explicitly in the
implementation.

## Processing model

Chunk-oriented, because the item count is unbounded.

- **Read:** one repository entry from the resolved source
- **Process:** normalise the slug, clone or verify the working copy, resolve the
  commit SHA, compute size metrics
- **Write:** upsert the `repositories` row, commit every 10 items

Resumability: after each commit, record the last processed slug in
`step_context_updates.cursor`. On restart, skip entries already past the cursor.

Concurrency: clone in a bounded thread pool of `max_concurrent_clones`. Database
writes remain serialised on the main thread — do not share a session across threads.

Metrics mapping:
- `read_count` — entries found in the source
- `write_count` — rows upserted successfully
- `skip_count` — clone failures skipped, plus entries already past the cursor
- `commit_count` — chunk commits

## Exit statuses

| Condition | Exit status |
|---|---|
| All repositories processed | `COMPLETED` |
| Some clones failed, `skip_on_clone_failure: true` | `COMPLETED`, with `diagnostics` per failure |
| Some clones failed, `skip_on_clone_failure: false` | `FAILED` |
| Source unreachable or manifest unparseable | `FAILED` |
| Source resolved to zero repositories | `FAILED` — almost certainly misconfiguration, not a valid empty estate |
| `source_type: provider_api` | `NOT_IMPLEMENTED` |

## Idempotency

Re-running must be safe. Upsert on `(engagement_id, slug)`:

- existing row → update `last_ingested_at`, `ingest_commit_sha`, size metrics,
  status. Preserve `first_ingested_at`.
- working copy already present and valid → fetch and reset to the default branch
  rather than re-cloning.
- repository in the inventory but absent from the source → **do not delete.** Set
  `ingest_status: skipped` with `ingest_error: "not present in current source"`.
  Removal is a human decision, consistent with the catalog's soft-delete philosophy.

## Validation and safety

- Reject `local_path` values escaping `workspace_root` — guard against path
  traversal from a hostile manifest.
- Reject clone URLs with embedded credentials (`https://user:pass@…`). Fail with a
  clear message pointing at environment variables.
- Cap `file_count` traversal depth and skip `.git`, `node_modules`, `bin`, `obj`,
  `packages` when computing size metrics, or size computation dominates runtime.
- Never log credentials or full clone URLs containing tokens.

## Test fixtures

Ship alongside the implementation:

- `tests/fixtures/repos-valid.yaml` — three repositories, one with tags
- `tests/fixtures/repos-empty.yaml` — zero repositories, must fail
- `tests/fixtures/repos-bad-credentials.yaml` — embedded credentials, must fail
- `tests/fixtures/sample-context.json` — a full StepContext for standalone invocation

Standalone invocation must work, per `11-STEP-CONTRACT.md`:

```powershell
Get-Content tests/fixtures/sample-context.json | python -m app.steps.repository_ingest
```

The module needs a `__main__` entry reading StepContext from stdin and writing
StepResult to stdout, even though the engine calls it in-process via the `python`
adapter. This proves the step is genuinely decoupled and lets another team member
exercise it without the engine.

## Acceptance criteria

- [ ] Registers in `wf_step_registrations` with the declared contract
- [ ] `phase0-estate-discovery` job definition validates and activates with step 1
      real and steps 2–12 as stubs
- [ ] Runs against a local directory of at least three sample repositories
- [ ] Runs against a manifest of at least three public repositories
- [ ] Produces a `repository-inventory` artifact with a verified checksum
- [ ] Two consecutive runs over unchanged repositories produce identical checksums
- [ ] Killing the process mid-run and restarting resumes from the cursor without
      duplicate rows
- [ ] A single unreachable repository yields `COMPLETED` with a diagnostic, not a
      failed job
- [ ] Zero repositories yields `FAILED`
- [ ] `provider_api` yields `NOT_IMPLEMENTED`
- [ ] Standalone stdin/stdout invocation works
