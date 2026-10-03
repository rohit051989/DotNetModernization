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

## Operating model

The platform runs on a single machine, operated by one person per client engagement.
The orchestration engine, the database, the UI and the repositories it registers all
live on that machine. Every lifecycle step executes locally against local paths.

This assumption is what justifies: local filesystem paths as first-class API input,
in-process background execution (`BackgroundTasks`, not a job queue), no object
storage, no distributed workers, and no per-user access control.

When it changes — multiple operators, a shared server, containerised deployment —
the things that break first are local path validity (a path is only meaningful on
the machine that registered it), `BackgroundTasks` durability (in-memory; does not
survive a process restart, hence the startup reconciliation that fails anything left
`STARTED`), and the absence of user scoping (nothing today distinguishes which
operator registered what). See `15-REPOSITORY-INGEST-UI.md`'s "Operating model"
section for the source of this note.

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
7. **Never hard-delete. Deprecate and soft-delete are two distinct mechanisms —
   do not conflate them.** Nothing in the catalog is ever hard-deleted from the
   database.
   - **Deprecate** sets `status = 'deprecated'`. It is a catalog lifecycle state:
     the record stays fully visible via the status filter, and historical
     decision records referencing it must remain resolvable.
   - **Soft delete** sets `deleted_at`/`deleted_by`, independent of `status`. It
     means removal: the record disappears from all normal API responses, the
     export, and the UI, until an admin-only `restore` clears `deleted_at`. See
     `02-DATA-MODEL.md`'s "Soft delete vs deprecate" section for the full
     semantics before touching either.
8. Prefer boring, readable code over clever code. This will be handed to a
   delivery team.
9. **Client-scoped operations must never mutate master catalog tables.**
   Anything under `/api/engagements/{eid}/patterns/...` (the client catalog: defer,
   reactivate, client-scoped delete/restore) may only write to
   `engagement_patterns` and, via the existing decisions endpoints,
   `decision_records`. It must never write to `patterns` or
   `target_state_options` under any circumstance. If a change to a client-scoped
   endpoint seems to require touching a master table, that change belongs on the
   master endpoints (`/api/patterns`, `/api/target-states`) instead — see
   "Master catalog vs client catalog" in `02-DATA-MODEL.md`.

## Domain vocabulary

Use these terms exactly and consistently in code, APIs, and UI copy.

- **Pattern** — a client-agnostic legacy structure with a detection rule.
  Example: "WCF service hosted in IIS using System.ServiceModel".
- **Target state option** — one possible modernization destination for a pattern.
  A pattern may have several. Example: "CoreWCF on .NET 10".
- **Recommendation** — the master catalog's own recommended target state option
  for a pattern (`is_recommended`), set independent of any engagement's decision.
  At most one per pattern. Distinct from the "presumptive choice" (lowest
  consumer impact), which the two may or may not agree on.
- **Engagement** — one client program.
- **Decision record** — an engagement's approved choice of one target state option
  for one pattern, with rationale and approver.
- **Master catalog** — the reusable IP: `patterns` and `target_state_options`.
  Client-agnostic, editable in one place only, shared by every engagement.
- **Client catalog** — the master catalog as seen and acted on by one
  engagement: the merged view of master pattern data with that engagement's
  `engagement_patterns` overlay and `decision_records`. Editing here never
  changes the master catalog or any other engagement.
- **Engagement pattern overlay** (`engagement_patterns`) — the row, one per
  `(engagement, pattern)`, carrying that engagement's `scope_status`
  (active/deferred) and client-scoped soft delete. Lazy: no row means active and
  not deleted. Never confuse this with a decision record — the overlay is about
  whether an engagement is engaging with a pattern at all; the decision record is
  about what it chose.
- **Defer** — an engagement's client-scoped decision not to tackle a pattern
  right now (`engagement_patterns.scope_status = 'deferred'`). Not the same as
  **deprecate**, which retires a pattern from the master catalog for everyone.
  Different words for different layers, deliberately.
- **Consumer impact** — how much a target state option changes what existing
  callers see. The lift-and-shift default means the lowest-impact viable option is
  presumptive.
- **Forcing factor** — the security requirement or decommissioned dependency that
  justifies choosing something other than the lowest-impact option.

## Out of scope for this build

Authentication, RBAC, multi-user concurrency, audit logging, repository scanning,
dependency graphs, wave planning, orchestration, engine integration, deployment.
Do not scaffold these "for later".

**Access control is parked, not forgotten.** The intent — admins see the master
catalog and every engagement; non-admins see only their own engagement, with the
master view hidden entirely — is recorded in `04-FRONTEND-SPEC.md`'s "Future:
access control" section, with `// TODO: gate ... once auth exists` markers left
at the view switcher and every master-scoped mutation. Leave those markers alone;
they're the map for when auth lands. Do not implement the checks now.

Never start the backend as a background process. The user runs it from their own
terminal so they can read its logs and it survives the session. If a check needs a
running backend, ask the user to start it.
