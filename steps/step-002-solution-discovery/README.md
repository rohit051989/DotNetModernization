# `solution-discovery` — Solution & Project Discovery

Lifecycle step `solution-discovery`. See `docs/19-SOLUTION-DISCOVERY.md`.

Standalone by design: invoked by the platform's `process` adapter, but this
directory has no dependency on `backend/app` — it is a separate deliverable
that happens to live in the same repository (Part B). Steps from `application-fingerprinting` onward will be
written by other people, and the `process` adapter is the integration path
they will use.

## Install

```powershell
pip install -r requirements.txt
```

## Run standalone

The script reads a `StepContext` JSON object (see `docs/11-STEP-CONTRACT.md`)
from stdin and writes a `StepResult` JSON object to stdout — nothing else
goes to stdout. Required pieces:

- `parameters.repository_id` — the repository's UUID
- `inputs.repository-inventory` — `{artifact_type, artifact_version, uri, checksum}`
  pointing at a `repository-inventory.json` written by `repository-ingest` (the script
  reads `local_path` and `slug` from *that file*, never from the database)
- `output_dir` — where to write `solution-project-inventory.json`
- `database_url` — a plain `postgresql://user:pass@host:port/db` URL.
  Omit it to skip persistence and only produce the artifact file.

See `sample-context.json` for a filled-in example — point its
`inputs.repository-inventory.uri` at a real `repository-inventory.json` on
disk before running.

```powershell
Get-Content sample-context.json | python main.py
```

## Tests

```powershell
python -m unittest discover -s tests
```

Parser tests (`test_solution_parser.py`, `test_project_parser.py`,
`test_framework.py`) are pure — no database needed. `test_main_integration.py`
exercises `run()` end to end, including persistence, against a real
Postgres — set `DATABASE_URL` (plain `postgresql://` form) in the
environment first; it defaults to the same local dev database the backend
uses (`docker/docker-compose.yml`).
