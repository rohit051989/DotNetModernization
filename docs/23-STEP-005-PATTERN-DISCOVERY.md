# 23 — Step 005: Pattern Discovery Clustering

Contract for lifecycle step 5, `pattern-discovery-clustering` (`17-LIFECYCLE-STEPS.md`).
Owner `P + S`. Member of `phase0-estate-consolidation`, engagement-scoped, alongside
steps 6, 7, 11, 12.

This document assumes the discovery-based approach already confirmed: step 5 finds
groups of structurally similar applications that step 4 cannot confidently explain
against the Master Pattern Catalog, and hands **candidates** — never catalog writes —
to step 6 for human validation. It does not re-litigate that approach; it pins down
the parts that were still open: the similarity formula, the LLM-timing question, the
singleton bucket, and the two infrastructure gaps that block this step from being
invocable at all.

---

## Part A — Prerequisites (blocking, not this step's job to fix, but recorded here)

Two gaps exist below the level of this contract. Neither is a flaw in the clustering
design; both must be closed before step 5 can run, and both belong to whoever defines
`phase0-estate-consolidation`, not to step 5's own implementation.

### A1. The job itself does not exist

`12-JOB-DEFINITION-FORMAT.md` and `15-REPOSITORY-INGEST-UI.md` are explicit:
`phase0-estate-consolidation` is **not defined yet** — steps 5, 6, 7, 11, 12 are all
stubs. Its precondition, once defined, is documented in both places as: *"every
in-scope, non-deleted repository has a completed `phase0-repository-discovery`
execution."*

### A2. That precondition is a small extension, not a new subsystem

`12-JOB-DEFINITION-FORMAT.md`'s job-to-job dependency section already supports scoped
completion checks — `trackB-wave` gates on `trackA-application` with
`type: job_completed, scope: all_in_wave`. `phase0-estate-consolidation` needs the
same mechanism with a new scope value, e.g.:

```yaml
job_name: phase0-estate-consolidation
version: 1

preconditions:
  - type: job_completed
    job_name: phase0-repository-discovery
    scope: all_in_engagement
    description: "Every in-scope, non-deleted repository must have a completed phase0-repository-discovery execution"
```

This is one new supported `scope` value on an existing precondition type, not a design
gap in the precondition system itself.

### A3. The real gap: cross-execution artifact resolution

This is the one worth flagging loudly, because it's easy to miss until implementation
starts. `phase0-repository-discovery` runs **once per repository** — a separate job
execution each time. Step 5 needs the `application-fingerprint` artifact (and step 4's
classification result — see A4) from **every** one of those executions across the
whole engagement, at once.

Every input-resolution mechanism in `12-JOB-DEFINITION-FORMAT.md` — `${steps...}`,
`${external...}`, `${artifacts...}`, and `partition` — resolves **within one job
execution's own step graph**. None of them reach across job executions. There is
currently no documented way to express "the latest completed artifact of type X, for
every repository in this engagement, across N separate job executions."

Two ways to close this, in order of preference:

1. **Step 5 queries the database directly for this, bypassing envelope input
   resolution for its primary inputs.** The step already receives `database_url`
   (`11-STEP-CONTRACT.md`'s StepContext), and steps 1–3 already write their own rows
   directly. Step 5 would enumerate the engagement's in-scope repositories, find each
   one's latest completed `phase0-repository-discovery` execution, and read the
   `application-fingerprint` and pattern-classification rows from there. No engine
   change required. The step's declared `consumes` becomes documentation of what it
   depends on for precondition/dependency-graph purposes, not its literal read path —
   worth stating explicitly in the step's README so a future reader doesn't go looking
   for an `inputs:` wiring that isn't there.
2. **Add a new `external_inputs` source kind** — something like
   `engagement_artifacts: { artifact_type: application-fingerprint, scope: all_in_engagement }`
   — that the engine resolves at launch into a list of artifact references. Cleaner
   long-term, but it's new engine surface for a need only step 5 has today.

Recommend (1) for v1, consistent with the "boring, dependency-light" bias already
established for steps 1–3, and revisit (2) only if a second estate-wide step needs the
same fan-in.

### A4. Step 4 has no spec or artifact schema yet either

`pattern-classification` is registered in `17-LIFECYCLE-STEPS.md` but has no
`docs/NN-STEP-004-*.md` and no artifact schema under a `schemas/` directory. Step 5
does not need step 4 fully specified to have its own contract written, but it does
need step 4 to eventually produce, per project, at minimum:

```json
{ "project_id": "<uuid, matches step 3's projectId>", "match_status": "unmatched" }
```

alongside whatever it produces for `matched`/`ambiguous`. Step 5 rebuilds the
structural signature itself from step 3's output (per the confirmed design — "we
should not rescan"), so it does not need anything richer than the project id and its
match status from step 4. If step 4 ends up producing `ambiguous` as a third status
(distinct from `unmatched`), step 5 should treat it as in-scope input the same as
`unmatched` — a low-confidence match is exactly the residue this step exists to
examine — but that's step 4's call to confirm when it's written.

---

## Part B — Unit of work

**One execution per engagement**, not per repository — this is what makes step 5
genuinely different from steps 1–4. Input is the union of unmatched/ambiguous
projects across every in-scope repository in the engagement, drawn from A3's
resolution path. A repository contributing zero unmatched projects is a no-op
contributor, not an error.

---

## Part C — Similarity model

Deterministic, auditable, no embeddings for v1 — consistent with the confirmed
design. Defined now, because `"similarity_score": 0.89"` cannot stay undefined once
implementation starts.

**Weighted Jaccard over signal names.** For an application, its signal set is the
distinct `signal.name` values across all of its step 3 signals (project-level plus
any repository-level signals attributed to it) — not the full signal objects, since
`occurrenceCount` and `evidence` are expected to differ between two apps of the same
underlying shape and would only add noise.

```
sim(A, B) = Σ_{s ∈ SigA ∩ SigB} weight(category(s))  /  Σ_{s ∈ SigA ∪ SigB} weight(category(s))
```

Category weights, keyed off step 3's `signalCategory` enum
(`application-fingerprint-1.0.0.schema.json`) — higher weight means more diagnostic of
"what kind of application this is":

| Weight | Categories |
|---|---|
| 2.0 | `HOSTING_INDICATOR`, `ENTRY_POINT`, `FRAMEWORK_REFERENCE`, `ENDPOINT_INDICATOR` |
| 1.0 | `PROJECT_METADATA`, `SOURCE_CONSTRUCT`, `DATA_ACCESS_INDICATOR`, `MESSAGING_INDICATOR`, `SCHEDULING_INDICATOR`, `EXECUTION_INDICATOR`, `UI_INDICATOR` |
| 0.75 | `PACKAGE_DEPENDENCY`, `CONFIGURATION_INDICATOR`, `FILE_INDICATOR`, `DEPLOYMENT_INDICATOR` |
| 0.25 | `TESTING_INDICATOR` |

`TESTING_INDICATOR` is weighted lowest deliberately: xUnit-plus-Moq shows up on
almost everything and says nothing about the application's shape. Weights live in
step config (see Part F), not hardcoded, so they can be tuned per engagement without a
code change — but the default table above ships as the config default and every
change to it should be logged the same way a detection-rule change is.

Record the method name (`weighted_jaccard_v1`) alongside every score produced, so a
future embeddings-based `similarity_method` can be introduced additively rather than
silently changing what an old `similarity_score` meant.

---

## Part D — Clustering algorithm (hybrid, structural-first)

Reconsidering the original flow's ordering: generating an LLM summary for *every*
unmatched application before clustering catches "same underlying pattern, different
structural signature" cases, but pays one LLM call per unmatched app regardless of
whether it ends up clustering with anything — expensive at the hundreds-of-apps,
50+-repository scale the estate-wide split exists for. Run the free, deterministic
pass first; spend LLM calls only on what it couldn't resolve.

**Pass 1 — structural (always runs, no LLM).**
Build a similarity graph over every unmatched/ambiguous application in the
engagement using Part C's formula. Connect an edge wherever
`sim(A, B) >= threshold_strong` (config default `0.6`). Take connected components as
clusters. Every component with 2+ members becomes a `status: candidate_pattern` row
with `formation_method: structural`.

**Residue after pass 1** = applications with no edge at `threshold_strong` — either
true singletons or members of a weak component (edges only below `threshold_strong`
but above a lower noise floor, `threshold_weak`, config default `0.35`).

**Pass 2 — LLM-assisted (residue only).**
For each residue application, generate the LLM structural summary the original design
described (application type, technology and hosting characteristics, modernization
characteristics — never the final pattern decision). Within each weak group from pass
1 (and among true singletons whose summaries look related on a coarse pre-filter —
e.g. same primary `HOSTING_INDICATOR`), ask the LLM to judge same-underlying-pattern
membership. A group the LLM affirms becomes a `status: candidate_pattern` row with
`formation_method: llm_assisted`, `llm_summary_used: true`. This is the semantic
catch-net the original ordering was reaching for, paid for only on the fraction of
applications that reach pass 2.

**Final residue** — no structural cluster, no LLM-affirmed group — becomes
`status: unclustered` (Part E), one row per leftover application, not silently
dropped.

---

## Part E — Data model

Two tables, engagement-scoped, written by this step directly (Part A3).
`common_signals` is the **intersection** of member signal-name sets, not the union or
one representative's signals — that's what actually characterizes the candidate,
consistent with how `common_signals` should read.

### `pattern_discovery_clusters`

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT` PK | `CAND-{engagement_id}-{seq:04d}`, deterministic per engagement |
| `engagement_id` | `TEXT` NOT NULL FK → `engagements.id` | |
| `status` | `TEXT` NOT NULL | `candidate_pattern` \| `unclustered` |
| `formation_method` | `TEXT` NOT NULL | `structural` \| `llm_assisted`; null for `unclustered` |
| `member_count` | `INTEGER` NOT NULL | 1 for `unclustered`, ≥2 for `candidate_pattern` |
| `common_signals` | `JSONB` NOT NULL | Array of `{ name, category }`, the intersection across members |
| `similarity_score` | `NUMERIC` NULL | **Minimum** pairwise similarity within the cluster, not the average — the score reflects the weakest link, which is the conservative, auditable choice. Null for `unclustered` (no pairwise score exists for n=1) |
| `similarity_method` | `TEXT` NOT NULL | `weighted_jaccard_v1` (Part C) |
| `review_priority` | `TEXT` NOT NULL DEFAULT `'standard'` | `standard` \| `high`. Replaces the original `requires_human_validation` flag — redundant given step 6 is unconditionally human per the confirmed design, so repurposed as a queue-ordering signal instead of dropped outright. `high` when `member_count >= 5` (bigger potential accelerator payoff) or `similarity_score` falls in the ambiguous band `[threshold_weak, threshold_strong)` (borderline call, worth a reviewer's attention first) |
| `source_job_execution_id` | `UUID` NOT NULL | Provenance |
| `created_at` | `TIMESTAMPTZ` NOT NULL | |

### `pattern_discovery_cluster_members`

| Column | Type | Notes |
|---|---|---|
| `cluster_id` | `TEXT` NOT NULL FK → `pattern_discovery_clusters.id` | |
| `project_id` | `UUID` NOT NULL | Matches step 3's `projectId` |
| `repository_id` | `UUID` NOT NULL | |
| `similarity_to_cluster` | `NUMERIC` NULL | This member's minimum pairwise similarity to every other member; null for `unclustered` |

Unique on `(cluster_id, project_id)`.

`status: unclustered` rows are what the strategy doc's "long tail is handled as
human-led one-off migration rather than forced into an accelerator" is describing in
data-model terms — they surface to step 6, but as a distinct triage queue, not
disguised as a one-member candidate pattern.

---

## Part F — Artifact `pattern-discovery-clusters@1.0.0`

Payload layer, evolves independently of the envelope per `11-STEP-CONTRACT.md`.
snake_case, mirroring the DB rows above (unlike step 3's camelCase
`application-fingerprint` artifact — payload casing is a per-artifact choice, not a
platform-wide rule, and this artifact exists mainly to checksum what the step wrote to
the tables above, so matching the table shape wins over matching step 3's).

```json
{
  "artifact_type": "pattern-discovery-clusters",
  "artifact_version": "1.0.0",
  "engagement_id": "client-a-ocp4",
  "similarity_method": "weighted_jaccard_v1",
  "config": {
    "threshold_strong": 0.6,
    "threshold_weak": 0.35,
    "category_weights": { "HOSTING_INDICATOR": 2.0, "TESTING_INDICATOR": 0.25 }
  },
  "clusters": [
    {
      "candidate_id": "CAND-client-a-ocp4-0001",
      "status": "candidate_pattern",
      "formation_method": "structural",
      "applications": ["APP-001", "APP-007", "APP-013"],
      "common_signals": [
        { "name": "IIS_HOSTED_ASPX", "category": "HOSTING_INDICATOR" },
        { "name": "WEBFORMS_PAGE_BASE", "category": "SOURCE_CONSTRUCT" }
      ],
      "similarity_score": 0.72,
      "review_priority": "standard"
    },
    {
      "candidate_id": "CAND-client-a-ocp4-0002",
      "status": "unclustered",
      "formation_method": null,
      "applications": ["APP-041"],
      "common_signals": [],
      "similarity_score": null,
      "review_priority": "standard"
    }
  ],
  "summary": {
    "unmatched_input_count": 47,
    "candidate_pattern_count": 9,
    "unclustered_count": 6,
    "structural_cluster_count": 6,
    "llm_assisted_cluster_count": 3
  }
}
```

Additive fields (a new optional key on a cluster, a new `summary` counter) are a
minor bump. Changing `similarity_score`'s meaning (e.g. min → average) or removing
`common_signals`'s intersection semantics is a major bump, per the artifact-versioning
rule in `11-STEP-CONTRACT.md` — the bump happens in the same change as the schema
edit.

---

## Part G — Boundaries (carried forward, unchanged)

Step 5 does **not**:

- Rebuild the step 3 scanner, or rescan repositories — it reads step 3's artifacts.
- Act as another known-pattern classifier — that's step 4's job, run first.
- Automatically create or modify Master Pattern Catalog (`patterns`,
  `target_state_options`) entries. `pattern_discovery_clusters` is a separate table
  tree; nothing here writes to the master catalog. Consistent with `CLAUDE.md`'s
  "client-scoped operations must never mutate master catalog tables" — this step is
  engagement-scoped by definition.
- Decide the final modernization target, or perform migration.
- Introduce embeddings. Structural signature plus category-weighted Jaccard is v1;
  revisit only if clustering quality against real engagement data shows the structural
  and LLM-assisted passes aren't separating genuinely distinct shapes.

Step 5's purpose, unchanged from the confirmed design:

> Find groups of structurally similar applications that step 4 cannot confidently
> explain using the current Master Pattern Catalog, and hand them to step 6 as
> candidates — never as catalog writes.

---

## Acceptance criteria

- [ ] `phase0-estate-consolidation.yaml` exists with the `scope: all_in_engagement`
      precondition (Part A2) — blocks this step from being launchable at all until done
- [ ] Step 5 resolves its cross-execution inputs per Part A3(1) — direct DB query
      against every in-scope repository's latest completed
      `phase0-repository-discovery` execution — and documents this as a deliberate
      deviation from envelope input wiring
- [ ] `sim(A, B)` implements the weighted-Jaccard formula in Part C exactly, with
      category weights read from step config, defaulting to the table in Part C
- [ ] Pass 1 (structural) runs unconditionally; pass 2 (LLM) runs only on pass-1
      residue — an engagement with zero weak/singleton residue after pass 1 makes zero
      LLM calls
- [ ] `common_signals` on every `candidate_pattern` row is verified to equal the
      intersection of its members' signal-name sets, not the union
- [ ] `similarity_score` on a multi-member cluster equals the **minimum**, not
      average, pairwise similarity among its members
- [ ] An application with no structural or LLM-affirmed cluster produces a
      `status: unclustered` row, never a `member_count: 1` `candidate_pattern` row
- [ ] `review_priority` is `high` exactly when `member_count >= 5` or
      `similarity_score` falls in `[threshold_weak, threshold_strong)`
- [ ] Re-running step 5 against unchanged step 3/4 output is idempotent — same
      `candidate_id` assignments, same cluster membership (obligation 1,
      `11-STEP-CONTRACT.md`)
- [ ] Nothing under this step writes to `patterns` or `target_state_options`
- [ ] `pattern-discovery-clusters@1.0.0` validates against a JSON Schema mirroring
      Part F, and its `checksum` is verified by the engine per `11-STEP-CONTRACT.md`
