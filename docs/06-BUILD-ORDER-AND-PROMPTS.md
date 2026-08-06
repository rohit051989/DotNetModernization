# 06 — Build Order and Prompts

Run these in order in Claude Code from the repository root. Each step is a separate
prompt with its own verification gate. Do not batch them — verify each before
moving on, or debugging becomes guesswork.

Copy the prompt text verbatim into Claude Code.

---

## Step 0 — Repository setup

**Prompt:**

```
Read CLAUDE.md and docs/00-PROJECT-OVERVIEW.md.

Create the repository skeleton described in docs/01-ENVIRONMENT-SETUP.md
sections 1 and 2: folder structure, .gitignore, and docker/docker-compose.yml.

Then verify my machine has the prerequisites listed in section 0 and report the
versions found. Do not install anything — tell me what is missing if anything is.

Do not create backend or frontend code yet.
```

**Gate:** folders exist, `docker-compose.yml` present, prerequisite versions reported.

---

## Step 1 — Database up

**Prompt:**

```
Start the PostgreSQL container per docs/01-ENVIRONMENT-SETUP.md section 2.
Confirm it reaches a healthy state and that you can connect to it.
Report the connection string that the backend should use.
```

**Gate:** `docker compose ps` shows healthy. Note it is on port **5433**, not 5432.

---

## Step 2 — Backend scaffold and data model

**Prompt:**

```
Read docs/02-DATA-MODEL.md and docs/03-BACKEND-SPEC.md.

Set up the backend per docs/01-ENVIRONMENT-SETUP.md sections 3 and 4:
Python venv, requirements.txt, .env and .env.example, Alembic configured to read
DATABASE_URL from the environment.

Then implement:
- app/config.py, app/db.py
- app/models.py with all four tables exactly as specified in 02-DATA-MODEL.md,
  including CHECK constraints, the partial unique index on decision_records,
  and all indexes listed
- the initial Alembic migration
- app/main.py with CORS and the /api/health endpoint only

Run the migration and confirm all four tables exist with correct constraints.
Show me the resulting DDL.

Do not implement the CRUD routers yet.
```

**Gate:** `alembic upgrade head` succeeds, `/api/health` returns
`{"status":"ok","database":"connected"}`, DDL matches the spec.

---

## Step 3 — Backend CRUD

**Prompt:**

```
Read docs/03-BACKEND-SPEC.md.

Implement all routers: patterns, target_states, engagements, decisions, catalog.
Include every Pydantic schema, all validation rules from 02-DATA-MODEL.md, and the
error handling conventions in 03-BACKEND-SPEC.md.

Pay particular attention to:
- target state options sorted by consumer_impact ascending then effort ascending
- the forcing_factor validation rule, with the readable error message shown in the spec
- deterministic catalog export: sorted keys, sorted records, timestamps excluded
  by default
- soft delete only, and 409 on referential refusal

When done, list every endpoint with its method and path so I can check coverage
against the spec.
```

**Gate:** `/docs` shows every endpoint. Manually exercise one create and one
validation failure.

---

## Step 4 — Seed data

**Prompt:**

```
Read docs/05-SEED-CATALOG-DATA.md.

Implement app/seed/ so that `python -m app.seed` loads all 8 patterns, 16 target
state options, 2 engagements and 10 decision records. It must be idempotent
(upsert by id) and support a --reset flag that truncates first.

Store the seed content as YAML data files under app/seed/data/ rather than
hardcoding it in Python, so the catalog content can be edited without touching code.

Run it and print the summary. Then call GET /api/catalog/export and show me the
first 40 lines so I can confirm the output is deterministic and diffable.
```

**Gate:** summary reports `approved: 5, in_review: 1, parked: 2` for Client A.
Run the seed twice — the second run must change nothing.

---

## Step 5 — Frontend scaffold

**Prompt:**

```
Read docs/04-FRONTEND-SPEC.md.

Set up the frontend per docs/01-ENVIRONMENT-SETUP.md section 5: Vite, React,
TypeScript, Tailwind. Then build only the shell:
- AppShell with header, API health pill, and engagement selector wired to
  GET /api/engagements
- TabBar with Catalog active and the five future tabs visibly disabled
- api/client.ts fetch wrapper with error normalisation
- types/catalog.ts mirroring the API response models

The Catalog tab can render a placeholder for now. Confirm the health pill shows
connected and the engagement dropdown lists both engagements.
```

**Gate:** shell renders, health pill green, both engagements in the dropdown,
disabled tabs are visibly inert.

---

## Step 6 — Catalog browse

**Prompt:**

```
Read docs/04-FRONTEND-SPEC.md.

Implement the read-only Catalog tab: PatternList with search and filters,
PatternDetail with the three sections (definition, detection rules rendered
readably with a raw-JSON toggle, target state option cards).

Target state cards must show impact and effort badges with the specified colours,
the LIFT & SHIFT pill, engine coverage with gaps listed, and the "Presumptive
choice" label on the first card.

No create or edit yet.
```

**Gate:** all 8 patterns browsable. Check `wcf-iis-servicemodel` shows three
options with CoreWCF first and labelled presumptive. Check `ssis-package` shows
coverage `none` prominently.

---

## Step 7 — Catalog editing

**Prompt:**

```
Read docs/04-FRONTEND-SPEC.md.

Implement the Drawer component and both forms: PatternForm and TargetStateForm,
including the structured detection-rules editor with tag inputs and the raw-JSON
escape hatch. Wire create, edit and deprecate, with ConfirmDialog on deprecate and
Toast on success or failure. Surface 422 field errors inline.

Verify a detection_rules object round-trips through the structured editor without
data loss.
```

**Gate:** create a throwaway pattern, edit it, deprecate it, confirm it leaves the
default list and returns via the status filter. Confirm round-trip fidelity.

---

## Step 8 — Decision panel

**Prompt:**

```
Read docs/04-FRONTEND-SPEC.md.

Implement DecisionPanel and DecisionForm, driven by the engagement selector in the
header. Include the client-side forcing-factor warning when the selected target
state is not the lowest consumer impact among the chosen candidates.

Verify against seed data:
- Client A / wcf-iis-servicemodel shows approved with CoreWCF
- Client A / aspnet-webforms shows parked with no selected target state
- Reference Engagement B / wcf-iis-servicemodel shows approved with gRPC and a
  visible forcing factor
- Switching engagement in the header changes the panel without a page reload
```

**Gate:** all four checks pass. Deliberately select gRPC for Client A and confirm
the forcing-factor warning appears and the server rejects submission without one.

---

## Step 9 — Polish and demo readiness

**Prompt:**

```
Walk the acceptance checks at the end of docs/04-FRONTEND-SPEC.md and the success
criteria in docs/00-PROJECT-OVERVIEW.md. Fix anything failing.

Then:
- Write a root README.md with the three-terminal run instructions from
  docs/01-ENVIRONMENT-SETUP.md section 6, plus a demo reset command
- Add a scripts/reset-demo.ps1 that truncates and reseeds in one step
- Confirm no unhandled 500s are reachable from the UI by exercising each form
  with invalid input
```

**Gate:** a cold start from `docker compose up` to a working seeded UI, following
only the README.

---

## Notes on working with Claude Code here

- **One step per prompt.** These specs are detailed; batching causes it to skim.
- **Make it show you things.** Every prompt above ends with a report-back
  instruction. Keep that habit — it catches drift early.
- **The specs are the source of truth.** If Claude Code proposes a different data
  model or stack, push back and point at the doc. Deviations here propagate into
  the platform later.
- **Commit after each gate.** Small commits per step make it easy to roll back one
  bad generation without losing the rest.
- **When something is ambiguous,** fix the spec first, then re-prompt. Do not patch
  it verbally only — the spec is what the next person reads.

## What comes after

Once the catalog is working, the next build is the repository scanner
(lifecycle steps 1-10), which populates the inventory the Catalog tab already sits
alongside. The Applications and Repositories tabs light up at that point. Keep the
disabled tabs in place until then.
