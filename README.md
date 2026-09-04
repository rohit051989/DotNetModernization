# .NET Modernization Platform

A control plane for running .NET legacy modernization at fleet scale. It
orchestrates transformation engines (GitHub Copilot app modernization) and adds
what they don't provide: estate inventory, a versioned pattern catalog,
target-state governance, and program visibility.

See `CLAUDE.md` for the full architectural context, domain vocabulary, and
current build scope.

## Quick start

New to this checkout? Follow these in order:

1. **`docs/01-ENVIRONMENT-SETUP.md`** — one-time machine setup: Docker Desktop,
   Python, the backend venv, Alembic migrations, and the .NET SDK (needed for
   step 3, application fingerprinting).
2. **`docs/26-RUNNING-THE-PHASE0-DEMO.md`** — running lifecycle steps 1-5
   (repository ingest → solution discovery → fingerprinting → pattern
   classification → pattern discovery clustering) end to end via VS Code Tasks.

## Lifecycle steps implemented so far (Phase 0)

| Step | Name | Status |
|---|---|---|
| 1 | Repository ingest | Implemented |
| 2 | Solution & project discovery | Implemented |
| 3 | Application fingerprinting | Implemented (.NET) |
| 4 | Pattern classification against catalog | Implemented |
| 5 | Pattern discovery clustering (unmatched applications) | Implemented — structural pass always on; LLM-assisted pass runs only if `ANTHROPIC_API_KEY` is configured |
| 6+ | Pattern validation, impact mapping, and beyond | Not yet built |

Each step's design doc lives in `docs/` — e.g. `docs/23-STEP-005-PATTERN-DISCOVERY.md`.

## Repository layout

```
.
├── CLAUDE.md               Architectural context — read before any task here
├── docs/                   Specs, one per lifecycle step / subsystem
├── docker/                 docker-compose.yml — Postgres only
├── backend/                FastAPI + SQLAlchemy + Alembic control plane
│   └── e2e_run/            Scripts that drive the full steps 1-5 demo
├── frontend/                React + Vite + TypeScript UI (pattern catalog)
├── steps/                  Each lifecycle step's own standalone implementation
│   ├── step-002-solution-discovery/
│   ├── step-003-fingerprinting/    (.NET — the one non-Python step)
│   ├── step-004-classification/
│   └── step-005-pattern-discovery/
├── e2e_run_demo.ps1                 VS Code task: full steps 1-5 demo
├── run_step5_demo.ps1               VS Code task: step 5 standalone
├── run_netcoreupgrade_demo.ps1      VS Code task: steps 1-4 against a real repo
└── _run-output/                     Results land here when you run a task (gitignored)
```

## Tech stack

PostgreSQL 16 (Docker) · Python 3.11+ / FastAPI / SQLAlchemy 2.x / Alembic ·
React 18 + Vite + TypeScript · .NET 10 SDK (step 3 only). Windows + PowerShell is
the primary dev environment — see `CLAUDE.md`.
