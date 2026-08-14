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

  "working_dir": "/.../runs/8f2c/repository-ingest",
  "output_dir": "/.../runs/8f2c/repository-ingest/out",

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
  timeout_seconds: 3600
  env:
    SOME_FLAG: "1"
```

Exit code handling:
- `0` → parse stdout as StepResult
- non-zero → step `FAILED`, `stderr` tail captured as the exit message
- exit code `0` with unparseable stdout → `FAILED` with a clear parse error

This adapter is how a colleague's script drops in with no engine change. Their only
obligation is: read JSON from stdin, write JSON to stdout, exit 0.

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

## Testing a step in isolation

Every step must be runnable without the engine. This is the decoupling test.

```powershell
Get-Content sample-context.json | python tools/ssis_parser/main.py | ConvertFrom-Json
```

Each step spec must ship a `sample-context.json` alongside it. A step that only
works when launched by the engine is not properly decoupled.
