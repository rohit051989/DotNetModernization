# 11 — Step Contract

The contract every step conforms to, regardless of who wrote it or what language it
is in.

## The stability rule

Two layers, with different change policies:

| Layer | Contents | Change policy |
|---|---|---|
| **Envelope** | Invocation shape, exit status vocabulary, output declaration shape, metric keys | **Stable.** Breaking change requires `envelope_version` bump and coordinated adapter update |
| **Payload** | Artifact type schemas, step `config` contents | **Evolves freely.** Semver'd per artifact type, validated by the engine |

Everything that follows in this document is envelope. Artifact schemas live with
their producing step's spec.

## Artifact versioning

The payload layer "evolves freely" above means semver'd, not unversioned. Every
artifact type has a version, and that version is a promise to whoever reads the
schema — including a future step that doesn't exist yet. The rule is plain:

- **Adding an optional field is a minor bump.** Existing consumers ignore what
  they don't know about; nothing breaks.
- **Removing or renaming a field, or changing its type or meaning, is a major
  bump.** Anything reading the old shape can break, so semver has to say so.
- **The bump happens in the same change as the schema edit, never afterwards.**
  A schema change and its version bump are one commit, not two. Bumping later,
  once someone notices, defeats the entire point: registered consumers use the
  version to decide whether new output is safe to read, and a stale version
  number lies to that check.
- **A step author must not edit an artifact schema without changing its
  version.** This applies even when nothing currently consumes the artifact —
  "nothing depends on it yet" is not an exemption, because the version is what a
  future consumer will trust. See `10-ENGINE-CONCEPTS.md`'s contract-change
  detection for what a major bump triggers against steps that already declare a
  `consumes` range on the artifact.

## Invocation — StepContext

The engine passes this JSON to the step. `envelope_version` is `"1.0"`.

```json
{
  "envelope_version": "1.0",
  "step_name": "repository-ingest",
  "step_version": "1.0.0",
  "job_name": "phase0-estate-discovery",
  "job_execution_id": "8f2c...",
  "step_execution_id": "b41a...",
  "attempt": 1,
  "partition_key": null,

  "parameters": {
    "engagement_id": "client-a-ocp4"
  },

  "config": {
    "source_type": "manifest",
    "manifest_path": "./input/repos.yaml"
  },

  "inputs": {
    "repo_manifest": {
      "artifact_type": "repo-manifest",
      "artifact_version": "1.0.0",
      "uri": "file:///.../repos.yaml",
      "checksum": "sha256:..."
    }
  },

  "job_context": { "arbitrary": "job-scoped state" },
  "step_context": { "arbitrary": "step-scoped state, survives restart" },

  "working_dir": "/.../runs/client-a-ocp4/order-management/0001-8f2c1a3b/repository-ingest",
  "output_dir": "/.../runs/client-a-ocp4/order-management/0001-8f2c1a3b/repository-ingest/out",

  "database_url": "postgresql+psycopg://...",
  "log_level": "INFO"
}
```

Notes:

- `config` comes from the job definition. The engine does not interpret it.
- `inputs` keys are declared in the job definition, mapping a logical name to a
  resolved upstream artifact. Steps address inputs by logical name, never by
  guessing which upstream step produced them.
- `working_dir` is scratch and may be wiped. `output_dir` is where artifacts are
  written and is preserved.
- `database_url` is provided because most `P`-owned steps write directly to platform
  tables. Steps from other teams may ignore it.
- `step_context` is how a step resumes mid-work after a failure — a chunk-oriented
  step records its cursor here.

### Run directory layout

`working_dir` and `output_dir` are built from:

```
runs/{engagement_id}/{repository_slug}/{execution_number:04d}-{execution_id_short}/{step_name}/out
```

Falls back to `runs/{engagement_id}/_no-repo/...` for a job whose parameters declare
no `repository_id` — or whose `repository_id` doesn't resolve to a `repositories`
row. `execution_id_short` is the first 8 characters of the job execution's UUID.

This exists so a directory on disk is browsable back to the client and repository it
belongs to — a bare `runs/{execution_id}/{step_name}/out` tells you nothing without
a database lookup. `{execution_number:04d}-{execution_id_short}` keeps every
execution of the same repository in its own directory, ordered numerically, while
still being unique even if two instances somehow shared an execution number.
Computed once per job execution (`app/workflow/runtime/executor.py`), not
per-step — every step in the same execution shares the same base directory.

## Response — StepResult

The step returns this JSON.

```json
{
  "envelope_version": "1.0",
  "exit_status": "COMPLETED",
  "exit_message": "Ingested 52 repositories, 3 skipped",

  "metrics": {
    "read_count": 55,
    "write_count": 52,
    "skip_count": 3,
    "commit_count": 6
  },

  "outputs": [
    {
      "artifact_type": "repository-inventory",
      "artifact_version": "1.0.0",
      "uri": "file:///.../out/repository-inventory.json",
      "checksum": "sha256:...",
      "metadata": { "repository_count": 52 }
    }
  ],

  "job_context_updates": { "repository_count": 52 },
  "step_context_updates": { "cursor": null },

  "next": null,

  "diagnostics": [
    { "level": "warning", "code": "CLONE_FAILED", "message": "...", "ref": "repo-x" }
  ]
}
```

Rules:

- `exit_status` is required. Everything else optional.
- `checksum` on outputs is required — the engine verifies it and refuses mismatches.
  This is how a corrupt or truncated artifact is caught at the boundary.
- `next` is only honoured for steps declared as deciders. Ignored otherwise.
- `job_context_updates` is shallow-merged into job context. Steps cannot delete keys
  another step set; pass an explicit null to clear.
- `diagnostics` surface in the UI without failing the step. Use for per-item
  problems that should not halt a batch of 600.

## Adapters

How the engine delivers a StepContext and collects a StepResult. Same envelope
across all of them — that is the point.

### `python` — in-process

For our own steps. Fastest, no serialisation overhead, shares the DB session pool.

```yaml
adapter_type: python
adapter_config:
  entrypoint: "app.steps.repository_ingest:run"
```

The callable takes a `StepContext` and returns a `StepResult`.

### `process` — local executable

For steps written by anyone, in any language. StepContext arrives on **stdin** as
JSON; StepResult must be written to **stdout** as a single JSON object. Anything
else the step wants to log goes to **stderr**.

```yaml
adapter_type: process
adapter_config:
  command: ["python", "tools/ssis_parser/main.py"]
  cwd: "./external"
  env:
    SOME_FLAG: "1"
```

Exit code handling:
- `0` → parse stdout as StepResult
- non-zero → step `FAILED`, `stderr` tail captured as the exit message
- exit code `0` with unparseable stdout → `FAILED` with a clear parse error

This adapter is how a colleague's script drops in with no engine change. Their only
obligation is: read JSON from stdin, write JSON to stdout, exit 0.

A registration's `adapter_config.timeout_seconds` is no longer read (rbc-release-5): every step's time limit comes
from "Time limits, progress and stopping" below.

#### Path resolution — `command` and `cwd` are relative to `PLATFORM_ROOT`, never to the backend process's own working directory

A relative `command[0]` (the executable) or a relative `cwd` is resolved against
`settings.platform_root` — a config value defaulting to the repository root, resolved
from the backend package's own location (`backend/app/config.py`'s directory, two
levels up). This is deliberate: the backend is started from `backend/`
(`01-ENVIRONMENT-SETUP.md`'s run commands), so a path written relative to the
repository root — the natural way to write it in a job definition, since that's what
every step's own directory layout is relative to — would otherwise resolve against
the wrong directory and fail with an opaque `WinError 2` / `FileNotFoundError`,
depending on what else happens to exist under `backend/`.

Rules, implemented once in `ProcessAdapter.__init__` so no step author has to think
about it:

- `command[0]` is left untouched only if it has no path separator (`/` or `\`) —
  a bare name like `python` is a deliberate PATH lookup and is not touched.
- Otherwise (it contains a separator, i.e. it names a file), it is resolved against
  `PLATFORM_ROOT` unless it is already absolute.
- `cwd`, if given, is resolved the same way. If omitted, it defaults to
  `PLATFORM_ROOT` itself — never to the backend process's ambient working directory.
- If the resolved `command[0]` still does not exist on disk, the step fails with
  `exit_message` naming both the resolved absolute path and the `PLATFORM_ROOT` value
  used to resolve it, rather than a bare OS error — e.g. *"Step executable not found:
  'D:\...\steps\step-003-fingerprinting\publish\Fingerprinting.Cli.exe' (resolved
  against PLATFORM_ROOT='D:\...')"*. This is what used to surface as an opaque
  `WinError 2` before the executable was even located.

A bare command name (`python`, `node`, ...) still relies on `PATH`, and — on
Windows — passing it as a list element to `subprocess.run` does not reliably resolve
to an active virtualenv's interpreter, even with the venv activated (`CreateProcess`'s
executable search does not behave like a shell's). Prefer a path relative to
`PLATFORM_ROOT` for the interpreter itself (e.g.
`["backend/.venv/Scripts/python.exe", "steps/step-002-solution-discovery/main.py"]`)
over a bare `python`/`node` whenever the interpreter lives in a project-local
virtualenv — this is what `solution-discovery` and `application-fingerprinting` both do, consistently, for exactly this
reason.

**Known constraint — command paths are currently Windows-resolved.** The examples
above (and every `process`-adapter step registered today) use Windows path
separators and, for compiled steps, a `.exe` suffix. This matches the single-machine,
Windows-first operating model this build targets (`CLAUDE.md`); nothing here does
POSIX-style path handling or extension-less executable resolution. A Linux worker
profile — raised and deliberately deferred in `21-APPLICATION-FINGERPRINTING.md` Part A5
— would need this revisited, not just the step's own build output.

### `http` — remote service

```yaml
adapter_type: http
adapter_config:
  url: "http://localhost:9100/steps/fingerprint"
  method: POST
  timeout_seconds: 1800
  headers:
    Authorization: "${FINGERPRINT_TOKEN}"
  poll:
    enabled: true
    status_url: "http://localhost:9100/steps/{correlation_id}"
    interval_seconds: 10
    max_wait_seconds: 7200
```

Synchronous by default: POST StepContext, receive StepResult. For long-running
work, `poll.enabled` makes the service return `202` with a `correlation_id` and the
engine polls until terminal.

`${VAR}` in adapter_config is resolved from engine environment at invocation time.
Never store secrets in job definitions.

### `event` — message-based

```yaml
adapter_type: event
adapter_config:
  publish_to: "steps.fingerprint.request"
  reply_to: "steps.fingerprint.reply"
  correlation_field: "step_execution_id"
  timeout_seconds: 7200
```

Publishes StepContext, awaits a StepResult correlated by `step_execution_id`.

**Specify this adapter now; implement it last.** It needs a broker, which we do not
have yet. Register it as a known adapter type that raises `NOT_IMPLEMENTED` if used,
so job definitions can reference it before the transport exists.

### `stub` — not yet built

```yaml
adapter_type: stub
adapter_config:
  exit_status: NOT_IMPLEMENTED     # or NOOP to pass through
  message: "Awaiting implementation by platform team"
```

Every one of the 51 lifecycle steps should be registered as a stub at the outset.
That gives a runnable end-to-end pipeline immediately and makes progress visible as
stubs are replaced.

## Step declaration

Every step declares its contract at registration. This is what the engine validates.

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
    optional: false

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

`version_range` uses npm-style semver ranges: `^1.0.0` accepts 1.x, `~1.2.0`
accepts 1.2.x, `>=1.0.0 <3.0.0` for explicit windows.

## Time limits, progress and stopping (rbc-release-5)

No step can make the engine wait forever.

**Limits.** Every step has a time limit and a stall limit, from `app.workflow.time_limits`: the most specific of
(this step, this repository), (every step, this repository), (this step, every repository), and the defaults
`STEP_TIMEOUT_SECONDS` (3600) and `STEP_STALL_SECONDS` (900). Overrides live in `step_time_limits` and change without
code (`python -m app.workflow.time_limits`, `/api/workflow/time-limits`). The engine passes what applies in
`step_context.time_limits`: `timeout_seconds`, `stall_seconds`, and, for the work inside a step,
`project_seconds` and `file_seconds` (`STEP_PROJECT_SECONDS`, `STEP_FILE_SECONDS`). A job definition's step-level
`timeout_seconds` (`12-JOB-DEFINITION-FORMAT.md`) is not read.

**Progress.** A step reports, at least every 15 seconds, its phase and items done out of the total, and the item it
is on. A `process` step writes lines to stderr:

```
##progress {"phase": "detect", "done": 41, "total": 170, "item": "src/Shop/Shop.csproj", "elapsedSeconds": 812.4}
```

A `python` step uses `app.workflow.progress.Reporter` (`progress.for_step(context)`), which writes the step
execution row. Either way the step writes `progress.json` and `timing-profile.json` in `output_dir`: time per phase,
and the slowest projects and files by path and duration only, never code, so it can be shared. The engine records
the last progress on the step execution (`progress`, `progress_at`); the job page shows it with the elapsed time.

**Stopping.** When the time limit is reached the step ends `TIMED_OUT`; when its phase, count and item have not
changed for the stall limit, `STALLED`; when an operator stops the job, `STOPPED`. Each is reported with where the
step was, and `stopped.json` beside its timing profile. A `process` step runs in a Windows job object, and its whole
process tree is ended, not just the step: nothing it started is left running, and no pipe a grandchild holds keeps
the engine waiting (`app.workflow.processes`). A `python` step is asked to stop and stops at its next
`Reporter.check()`; any child process it runs through `app.workflow.processes.run` is ended with its tree at once.
TIMED_OUT and STALLED fail the job as FAILED does; STOPPED stops it.

**Inside a step.** Loading one project and analysing one file each have their own limit. Over it, the project or
file is recorded "not checked" with the reason (warning code `NOT_CHECKED`) and the step carries on.

**Resume.** A step that works project by project keeps each completed project's result in
`step_context.checkpoint_dir`, keyed by its version and its inputs' checksums. A rerun after a time limit, a stall
or a crash reuses them and continues from there; a completed run clears them. A resume never repeats a stall: a
project the earlier run recorded "not checked", or was still analysing after 60 s when it stopped (`inflight.json`,
written at every heartbeat), is listed in `skip.json` and recorded "not checked: not retried" instead of being
analysed again. A person retries it with `python -m app.workflow.time_limits retry`, which removes that list; a
different project time limit starts afresh.

**Conformance.** A record that does not conform to the artifact schema, or leaves a required field empty, never
costs the rest: it is left out and recorded `NOT_CHECKED` on its project with the record and the field named, and
the rest is written, conforming (outbound-invocation-inventory: `OutboundInventoryCli.Conform`;
`Fingerprinting.StepHost.RequiredFields`).

## Obligations on a step implementation

1. **Idempotent.** Re-running with the same context must not duplicate work or
   corrupt state. At 600 applications, steps will be re-run.
2. **Never modify inputs.** Input artifacts are read-only.
3. **Write outputs to `output_dir` only.**
4. **Report honest metrics.** `read_count` and `write_count` drive the dashboard.
5. **Fail loudly.** A step that swallows an error and reports `COMPLETED` is worse
   than one that crashes.
6. **No interactive prompts.** Steps run headless.
7. **Respect `step_context`** for resumability if the work is chunked.
8. **Report progress and never wait forever** ("Time limits, progress and stopping"): progress at least every 15
   seconds; a limit on each project and file; every child process run so that its whole tree ends with the step.

## Testing a step in isolation

Every step must be runnable without the engine. This is the decoupling test.

```powershell
Get-Content sample-context.json | python tools/ssis_parser/main.py | ConvertFrom-Json
```

Each step spec must ship a `sample-context.json` alongside it. A step that only
works when launched by the engine is not properly decoupled.
