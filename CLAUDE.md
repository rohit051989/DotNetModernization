# CLAUDE.md — Modernization Platform

Repo-level context for Claude Code. Read this before any task in this repository.

## What this is

The **Modernization Platform** — a control plane for running .NET legacy modernization
at fleet scale. It orchestrates existing transformation engines (GitHub Copilot app
modernization) and adds what they do not provide: estate inventory, pattern catalog,
target-state governance, OpenShift landing, independent verification, and program
visibility.

**Current build scope: the Pattern Catalog only.** Everything else is future work.
Do not build inventory scanning, orchestration, or engine integration yet. Stub the
future UI tabs as disabled placeholders so the growth path is visible, but implement
nothing behind them.

## Tech stack (fixed — do not substitute)

| Layer | Choice | Notes |
|---|---|---|
| Database | PostgreSQL 16 (Docker container) | JSONB needed for detection rules |
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2 | |
| Frontend | React 18 + Vite + TypeScript + Tailwind CSS | |
| HTTP client | native `fetch` wrapped in a small `api.ts` | no axios |
| Dev host | Windows 11 + Docker Desktop | PowerShell commands, not bash |

Keep the dependency count low. Do not add state managers, component libraries,
ORMs, or test frameworks that are not listed above without asking first.

## Repository layout

```
modernization-platform/
  CLAUDE.md
  docs/                  specs — read the relevant one before implementing
  docker/
    docker-compose.yml
  backend/
    app/
      main.py
      db.py
      models.py
      schemas.py
      routers/
      seed/
    alembic/
    requirements.txt
    .env.example
  frontend/
    src/
      api/
      components/
      pages/
      types/
    package.json
```

## Working rules

1. **Read the relevant spec in `docs/` before writing code.** The specs are
   authoritative. If a spec is ambiguous, ask rather than guess.
2. **Windows-first.** All shell commands in output, docs, and scripts must be
   PowerShell. Use `.venv\Scripts\Activate.ps1`, not `source .venv/bin/activate`.
   Use `;` not `&&` for command chaining in PowerShell examples.
3. **No secrets in code.** Connection strings come from `.env`, which is
   gitignored. `.env.example` is committed with placeholder values.
4. **Migrations, not `create_all`.** Every schema change is an Alembic migration.
5. **The catalog is versionable IP.** The export endpoint must produce
   deterministic, diffable JSON — stable key order, stable record order — so the
   catalog can be committed to git and reviewed as a pull request.
6. **Client-agnostic vs engagement-specific separation is architectural.**
   Patterns and target-state options are reusable across clients. Decision records
   belong to an engagement. Never let engagement data leak into the pattern or
   target-state tables. This separation is the point of the product.
7. **Soft delete only.** Nothing in the catalog is hard-deleted; set
   `status = 'deprecated'`. Historical decision records must remain resolvable.
8. Prefer boring, readable code over clever code. This will be handed to a
   delivery team.

## Domain vocabulary

Use these terms exactly and consistently in code, APIs, and UI copy.

- **Pattern** — a client-agnostic legacy structure with a detection rule.
  Example: "WCF service hosted in IIS using System.ServiceModel".
- **Target state option** — one possible modernization destination for a pattern.
  A pattern may have several. Example: "CoreWCF on .NET 10".
- **Engagement** — one client program.
- **Decision record** — an engagement's approved choice of one target state option
  for one pattern, with rationale and approver.
- **Consumer impact** — how much a target state option changes what existing
  callers see. The lift-and-shift default means the lowest-impact viable option is
  presumptive.
- **Forcing factor** — the security requirement or decommissioned dependency that
  justifies choosing something other than the lowest-impact option.

## Out of scope for this build

Authentication, RBAC, multi-user concurrency, audit logging, repository scanning,
dependency graphs, wave planning, orchestration, engine integration, deployment.
Do not scaffold these "for later".
