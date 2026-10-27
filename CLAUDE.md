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

Each developer runs their own platform, backend and frontend, on their own machine, against **one shared database**,
so everyone sees the same engagements and repositories. The orchestration engine, the UI and the repositories a
developer registers live on that developer's machine; every lifecycle step executes locally against local paths.

This is what justifies local filesystem paths as first-class API input, in-process background execution
(`BackgroundTasks`, not a job queue), no object storage and no distributed workers. It is also why a repository has
an owner and a machine: only its owner (or an admin) acts on it, and only from the machine it was registered on, where
its folder and run output are. One backend runs per machine (`app.heartbeat`); a backend runs only the jobs queued on
its own machine, and at startup fails only its own machine's jobs left `STARTED`.

Everyone sees every repository's results in full from the database, without the owner's machine (`app.results`):
every result a view reads is copied into the database when its step registers it (the newest `RESULTS_KEEP` of each
kind kept), and every list that grows with a repository is served a page at a time. Raw outputs no view reads (logs,
timing profiles, SARIF, evidence files) stay in the owner's `RUNS_DIR`; elsewhere the UI names whose machine has them.
A new view reads the database, never another machine's files; a new list that grows with a repository is paged.

Matching a person's Windows account and machine at sign-in deters shared credentials; it is not a hard security
boundary, since the platform runs on the user's own machine.

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
   **Never edit a migration that has been applied** — to any database, including
   the local one. A database that ran the old text will never run the new one,
   so the two silently disagree. Add a new migration instead, even for a
   one-column fix, and never patch a database by hand to match an edited file.
5. **The catalog is versionable IP.** Its exports must be deterministic and
   diffable — stable key order, stable record order — so the catalog can be
   committed to git and reviewed as a pull request. The item catalog is exported
   to `catalog/items/<item-id>.yaml` (`python -m app.items.catalog_export export`,
   28-ITEM Part W). That export is for review and history, never a place to edit:
   change the catalog in the UI, then re-export.
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
   - Engagement data is not the catalog: a person can hard delete a
     repository or a whole engagement on purpose (`app/deletion/`,
     `docs/VDI-SETUP.md` "Deleting a repository or an engagement"). It shows what will go, needs the name
     typed, is refused while a job runs, never touches the catalog, the
     package lookup cache or another engagement, and leaves a
     `deletion_audit` record. Nothing else hard-deletes.
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
10. **A reseed never undoes work.** It must never revert an implemented step to
    stub (`17-LIFECYCLE-STEPS.md`), and it must never overwrite a catalog edit
    made in the UI. The database is authoritative for the item catalog;
    `catalog_items.yaml`, the pattern tables and the amendments in code are
    factory defaults. Every seed write to `catalog_items`, `item_resolutions`
    and `resolution_derivations` goes through `app/items/baseline.py`. A row is
    updated only if it has not been edited since it was seeded (its
    `seeded_hash`). Where both the database and the default changed, the seed
    reports a conflict and leaves the row as it is. Never write catalog rows
    from a seed, script or migration any other way.
11. **The platform reproduces from the repository alone.** Every implemented
    step registration lives in a file (`steps/*/registration/*.json` or
    `backend/app/steps/*.registration.json`), every job definition in
    `backend/app/jobs/*.yaml`, and the seed loads them (`app/seed/platform.py`).
    Registering a step or storing a job through the API is not enough on its
    own: commit the file in the same change. The catalog's record in the
    repository is the export in `catalog/items/`, and a new environment imports
    it (`01-ENVIRONMENT-SETUP.md` section 9). After catalog changes, export and
    commit. Before calling such work done, run `python -m app.seed.reproduce`.
    It bootstraps a scratch database from the repository and compares it with
    this machine, and must report 0 differences.
12. **Docs name lifecycle steps by slug, never by number.** Write
    `item-detection`, not "step 7". Steps get renumbered whenever one is
    inserted, and every numbered reference goes stale. Slugs never change in
    place (`17-LIFECYCLE-STEPS.md`, "Renumbering and slug stability"). The same
    applies to doc file names: name a step's spec after its slug
    (`33-IMPACT-ANALYSIS.md`), not its number. `17-LIFECYCLE-STEPS.md` is
    the one place numbers belong: its step tables, version history and
    mapping. New code comments do the same; older comments still carry
    numbers and are converted when their file is next edited. Applied
    migrations keep the names they were written with (rule 4).
13. **Every active item has exactly one default resolution.** The database
    enforces it: `uq_item_resolutions_one_default` allows at most one, and the
    deferred trigger `trg_item_resolutions_one_default` requires at least one,
    at commit. The API moves the default with make-default; it never unsets,
    deprecates or deletes it while the item has other resolutions. List any
    violations with `python -m app.items.catalog_seed --check-defaults`.
14. **Never change certificate stores, trust settings or other machine security
    configuration without explicit approval.** That covers importing into or
    removing from any CurrentUser or LocalMachine certificate store, trusted
    roots or peers, http.sys certificate bindings and URL reservations,
    firewall rules, and registry security keys. A sample's own setup script
    that does any of these counts too. Prefer file-based material in a scratch
    folder: generate certificates as `.pfx`/`.cer` files under `backend/runs/`
    (gitignored), load them by path, and trust by pinning a thumbprint. The WCF
    client probe shows how (`29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md` C11:
    `WcfClientProbe make-certificates`, `ProbeServices`). If a task truly needs
    a machine change, ask first, saying exactly what changes and how to undo it.

15. **Every commit on master upgrades an existing installation in place, keeping all its data.** Migrations keep
    existing data intact: they add or extend, never drop or rewrite what a client's schema holds (rule 4 still
    applies). Every new setting is optional with a default, so an upgrade never requires editing `.env`.
    Existing data a new rule would refuse (one checkout registered in two engagements before release 2) is
    reported — in preflight, the backend's startup log and the UI — and left working, never broken or deleted;
    code that acts on such data, a hard delete included, must not damage the other side of it. A change that
    cannot upgrade in place says so explicitly, with the reason, in `docs/VDI-SETUP.md` "Upgrade notes". Every
    change that touches the database, step registrations or settings proves it: upgrade an installation of the
    previous master commit, with data in it, as "Updating the platform" (a client install) or "Appendix: upgrading
    from a bundle of master" (our own) says. A change that needs an action after updating (a rescan, a package a
    mirror must carry, a new setting) adds a dated entry, naming its commit, at the top of "Upgrade notes".

16. **The platform may run in a folder of someone else's repository.** A client keeps it in a subfolder of a
    shared repository, without our `.git`, on the operator's own branch (`docs/VDI-SETUP.md`, Part 1), or at the
    root of a repository dedicated to it, where the whole repository is the platform ("Two layouts"; the scripts
    work out which from the path, and a `PLATFORM_SOURCE.json` at a root marks it as an installation). Every git
    check the platform makes of itself looks only at its own folder, from the host repository's real root
    (`git -C <top> status -- <folder>`), never at the rest of the host repository. Its identity is our source
    commit from `PLATFORM_SOURCE.json`, recorded beside the host repository's commit (`app.experiment.instrument`).
    Nothing the platform or its scripts do commits outside its folder or to another branch:
    `scripts/update-platform.ps1` stages and commits with `-- <folder>` only.

17. **master is always deployable.** Every installation follows master (`scripts/update-platform.ps1` pulls it),
    so every commit on master passes the full test suites: backend, frontend and C#. Unfinished work stays on a
    branch until it does. Commit on master with neutral messages, and never rewrite its history: an update refuses
    to go backwards. **Never create, move or delete a tag; the owner does**, by hand, as a reference point for a
    bigger milestone. Nothing installs a tag. Bundles for our own installs are made from master
    (`scripts/master-bundle.ps1`), only when asked.

18. **No client's name, anywhere.** This platform serves many clients. No client's name, business unit,
    application or repository code, or host name appears in it: not in code, comments, tests, test data,
    documentation, file names, branch names, tag names or commit messages. Write "the client" or "client A"
    (client B, ...) instead, and an example domain such as `client-a.example` for a host. What a client's
    repositories contain belongs in that client's own database and runs folder, never in this repository.

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

Repository scanning beyond the lifecycle steps, wave planning, engine integration beyond what is built, deployment.
Do not scaffold these "for later".

**Sign-in, roles and ownership exist** (`app/auth/`; `04-FRONTEND-SPEC.md` "Sign-in and roles"; `docs/VDI-SETUP.md`
"Users and sign-in"). Every API call needs a signed-in session and passes `app.auth.policy`: admins change everything;
a developer registers repositories and acts on the ones they own. People ask for access from their own platform's
sign-in page and an admin approves them as developers (`app.auth.requests`); after `create-first-admin`, only an
admin's `promote` makes an admin, and no other route may. A new route that changes something is admins-only
until the policy names it: list it there, with its rule, when developers or owners should reach it. Edits to shared
records carry a version check (`app.auth.versions`); every change is recorded with who and from which machine
(`app.auth.activity`). Command-line tools act as the registered user running them (`service.cli_actor`).
