# Step 5 — Pattern Discovery Clustering

Lifecycle step 5 (`pattern-discovery-clustering`). See
`docs/23-STEP-005-PATTERN-DISCOVERY.md`.

Standalone by design, like steps 2 and 3: this directory has no dependency
on `backend/app` — raw psycopg only, no ORM (Part B / discovery/persistence.py's
same rule). **Unlike steps 2 and 3, `database_url` is not optional here.**
Steps 1-3 write to the database as a side effect of an artifact-producing
scan; step 5 has no repository to scan at all — its entire input is a
direct read across the engagement's `fingerprint_signals` /
`project_fingerprints` tables (23-STEP-005 Part A3), so a context with no
`database_url` fails immediately rather than silently producing an empty
result.

## Why this step is engagement-scoped, not repository-scoped

Steps 1-4 process one repository per execution. Step 5 needs to see every
unmatched application across *every* repository in the engagement at once
— you cannot cluster structurally similar applications from a single
repository's residue. See `docs/17-LIFECYCLE-STEPS.md`'s `phase0-estate-
consolidation` job and Part B of the spec doc.

Two consequences that show up directly in `main.py`:

- `parameters` carries `engagement_id`, never `repository_id`.
- There is no `inputs` artifact to resolve. Step 5 reads step 3's signal
  tables straight from Postgres instead of locating and parsing any
  repository's `application-fingerprint.json` — this sidesteps the
  cross-execution artifact-resolution gap recorded in the spec doc's Part
  A3 entirely.

## How step 4's output feeds step 5

Step 4 (`pattern-classification`) writes one row per project to
`project_classifications`, with a `classification_status` of `MATCHED`,
`MULTIPLE_MATCHES`, `AMBIGUOUS`, `NOT_ELIGIBLE`, `INSUFFICIENT_FINGERPRINT`,
`NO_PATTERN_MATCHED`, `SKIPPED` or `CLASSIFICATION_FAILED`.
`clustering.persistence.load_candidate_applications` checks for that table
via `information_schema` at runtime (no import of step-4-owned code) and
includes a project when either it has no `project_classifications` row yet
(step 4 hasn't reached it) or its status is `NO_PATTERN_MATCHED` /
`AMBIGUOUS` — genuinely uncatalogued residue. `MATCHED` / `MULTIPLE_MATCHES`
projects are already covered and drop out; `NOT_ELIGIBLE` /
`INSUFFICIENT_FINGERPRINT` / `SKIPPED` / `CLASSIFICATION_FAILED` are
excluded too, since those mean step 4 couldn't or shouldn't judge the
project at all, not that it's uncovered. Against a database that predates
step 4's migration (no `project_classifications` table), every
fingerprinted application is a candidate — the original interim
behaviour, kept as the fallback.

## The two clustering passes

1. **Structural (`clustering/structural_pass.py`)** — always runs, no LLM.
   Weighted-Jaccard similarity (`clustering/similarity.py`) over every
   candidate application's distinct step 3 signal names; connected
   components at `threshold_strong` (default `0.6`) become candidate
   patterns.
2. **LLM-assisted (`clustering/llm_pass.py`)** — runs only on pass-1
   residue. Groups residue at a looser `threshold_weak` (default `0.35`),
   generates an LLM structural summary per residue application
   (`clustering/llm_client.py`), and asks the model to judge which
   summaries describe the same underlying pattern. Requires
   `ANTHROPIC_API_KEY` in the environment — with no key configured,
   `LlmClient.available` is `False` and this pass is skipped with a
   diagnostic (`LLM_PASS_SKIPPED`), not a hard failure: every residue
   application simply becomes `unclustered`. This is the actual behaviour
   of a dev environment with no LLM credentials, exercised directly by
   `tests/test_main_integration.py`.

Anything left over after both passes becomes a `status: unclustered` row —
a distinct bucket from `candidate_pattern`, never a one-member cluster
masquerading as one (spec Part E).

## Install

```powershell
pip install -r requirements.txt
```

## Run standalone

The script reads a `StepContext` JSON object (see `docs/11-STEP-CONTRACT.md`)
from stdin and writes a `StepResult` JSON object to stdout — nothing else
goes to stdout. Required pieces:

- `parameters.engagement_id` — the engagement to cluster
- `database_url` — a plain `postgresql://user:pass@host:port/db` URL,
  **required** (see above — this is the step's input path, not an optional
  persistence side-effect)
- `output_dir` — where to write `pattern-discovery-clusters.json`
- `config.threshold_strong` / `config.threshold_weak` / `config.category_weights`
  — optional overrides of the defaults in `clustering/similarity.py` and
  `clustering/structural_pass.py`
- `ANTHROPIC_API_KEY` in the environment — optional; enables pass 2

See `sample-context.json` for a filled-in example.

```powershell
Get-Content sample-context.json | python main.py
```

## Tests

```powershell
python -m unittest discover -s tests
```

`test_similarity.py`, `test_structural_pass.py`, `test_assembly.py` and
`test_llm_pass.py` are pure — no database, no network (the LLM pass is
tested against a fake client with the same two-method shape as
`llm_client.LlmClient`). `test_main_integration.py` exercises `run()` end
to end, including persistence, against a real Postgres — set
`DATABASE_URL` (plain `postgresql://` form) in the environment first; it
defaults to the same local dev database the backend uses
(`docker/docker-compose.yml`). It runs with no `ANTHROPIC_API_KEY` set, so
it is also the executable proof of the pass-2-skipped path.

## What's deliberately not here

Per spec Part A, this implementation is the step's own code plus the
`pattern_discovery_clusters` / `pattern_discovery_cluster_members` Alembic
migration only. Not included, and needed before this step can actually be
launched by the engine:

- `backend/app/jobs/phase0-estate-consolidation.yaml` and its
  `all_in_engagement` precondition scope (Part A2).
- Registering `pattern-discovery-clustering` in `wf_step_registrations`.

Both are small, well-scoped follow-ups — see the spec doc's Part A for
exactly what each needs.
