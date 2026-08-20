# 24 — Step 4: Pattern Classification Against Catalog

Lifecycle step 4. Owner: **P + S**. Job: `phase0-repository-discovery`, after step 3.
Implemented in **Python**, invoked via the `process` adapter.

Read `step-4-pattern-classification-against-catalog.md` alongside this. That document
is the authority on **classification design**; this spec is the authority on how it
integrates with the existing catalog, engine and UI, and **overrides it** where they
disagree.

**Sections superseded in the requirements document:** §8 and §9 (rule structure — use
Part C), §11 (role determination — use Part D), §15 (scoring — use Part E, which pins
what §15 leaves illustrative), §21 (migration — use Part B and Part K), §22 (registry
validation — use Part B3).

---

## Part A — Decisions that override the requirements document

### A1. Catalog reshaping is a prerequisite phase

§21 treats migrating the eight seeded patterns as a task inside step 4. It is larger:
the catalog is a live database with a structured rules editor, master/client scoping,
engagement overlays and decision records referencing patterns. Reshaping
`detection_rules` means new columns, a new schema, signal validation on write, a
rebuilt editor, re-authored seed data and a revised export format.

**Build and verify it before writing any classification code.** Part K sequences this.

### A2. Python, not .NET

Rule evaluation over JSON with database access. No code parsing, no Roslyn. The
regression corpus means re-running classification constantly while tuning rules, so
fast iteration matters more than throughput.

### A3. Pattern versioning stays integer

The document uses semver `patternVersion: 2.0.0`. The `patterns` table already has an
integer `version`. Keep it. Reproducibility comes from **catalog revision** (Part H),
not per-pattern semver.

### A4. Project role determination lives in the catalog

§11 recommends implementing role rules separately, which conflicts with §28.4 —
classification logic belongs in the catalog. Role rules **are** catalog patterns in a
`PROJECT_ROLE` family, evaluated in a first pass using the same rule engine. One
engine, one authoring surface, and role rules stay editable. Part D.

### A5. Engagement scope annotates results, it does not filter them

Classify against **every active master pattern**, then annotate each match with its
engagement scope status. If a client deferred Web Forms and a project matches it, that
is a finding they need. Exclude nothing; label everything.

### A6. Only classify what step 3 can see, and make the gap actionable

Coverage across the eight seeded patterns is uneven with batch 1 extractors:

| Pattern | Classifiable now | Blocking gap |
|---|---|---|
| `core2-rest-api` | Yes | — |
| `fx47-class-library` | Yes | — |
| `fx-aspnet-mvc` | Yes | — |
| `aspnet-webforms` | Verify | Confirm `ASPX_FILE` is registered |
| `wcf-iis-servicemodel` | Yes | — |
| `console-batch-job` | Partly | No scheduling signals |
| `windows-service` | Yes | — |
| `ssis-package` | **No** | Step 3 emits no SSIS signals at all |

A pattern that cannot yet be expressed is recorded with `rules_status:
awaiting_signals` and a **structured** `required_signals_pending` list (Part B2) —
not free text. That turns a gap into a work queue driving step 3's extractor
priorities, and it surfaces in catalog coverage.

### A7. Deterministic scoring

§15's worked example is illustrative. Part E pins the formula exactly. Same
fingerprint plus same catalog revision must always yield the same score, or the
regression corpus is worthless.

### A8. Repository-scoped patterns are deferred

The `scope` column exists for future use, but **v1 evaluates `PROJECT` scope only**.
A `REPOSITORY`-scoped pattern is skipped with a governance observation. Repository
signals from step 3 are retained but unused here. Revisit when a real
repository-scoped pattern appears.

---

## Part B — Catalog schema migration

### B1. New columns on `patterns`

| Column | Type | Notes |
|---|---|---|
| `classification_role` | `TEXT` NOT NULL DEFAULT `'PRIMARY'` | CHECK IN (`PRIMARY`, `SECONDARY`, `PROJECT_ROLE`) |
| `classification_family` | `TEXT` | `APPLICATION_TYPE`, `WEB_APPLICATION`, `CAPABILITY`, `PROJECT_ROLE` |
| `classification_value` | `TEXT` | `REST_API`, `WCF_SERVICE`, `TEST` |
| `scope` | `TEXT` NOT NULL DEFAULT `'PROJECT'` | CHECK IN (`PROJECT`, `REPOSITORY`). See A8 |
| `priority` | `INTEGER` NOT NULL DEFAULT 50 | Conflict tiebreak, higher wins |
| `compatible_with` | `JSONB` NOT NULL DEFAULT `'[]'` | Array of **pattern ids** |
| `conflicts_with` | `JSONB` NOT NULL DEFAULT `'[]'` | Array of **pattern ids** |
| `anchor_signals` | `JSONB` NOT NULL DEFAULT `'[]'` | Signal names, for the inverted index |
| `eligibility` | `JSONB` | Fingerprint statuses, excluded project roles |
| `analysis_requirements` | `JSONB` | `{required: {...}, preferred: {...}}` |
| `thresholds` | `JSONB` NOT NULL | `{minimumScore, highConfidenceScore}` |
| `rules_status` | `TEXT` NOT NULL DEFAULT `'draft'` | CHECK IN (`active`, `awaiting_signals`, `draft`) |
| `required_signals_pending` | `JSONB` NOT NULL DEFAULT `'[]'` | See B2 |
| `detection_rules_legacy` | `JSONB` | Preserves pre-migration values. Dropped after J2 is verified |

`compatible_with` and `conflicts_with` hold **pattern ids**, not classification
values. §12's example uses values; ids are unambiguous and referentially checkable.
Validate that a pattern does not appear in both lists, and that every referenced id
exists.

### B2. `required_signals_pending`

Structured, so the gap is actionable rather than a note:

```json
[
  {
    "signal_name": "SSIS_PACKAGE_FILE",
    "purpose": "Anchor signal — identifies a .dtsx package",
    "expected_extractor": "SsisExtractor",
    "blocking": true
  },
  {
    "signal_name": "SSIS_CONNECTION_MANAGER",
    "purpose": "Supporting evidence for connection topology",
    "expected_extractor": "SsisExtractor",
    "blocking": false
  }
]
```

`blocking: true` means the pattern cannot be evaluated at all without it. Non-blocking
entries are enrichment. Catalog coverage groups these by `expected_extractor`,
producing a direct answer to "which extractor should we build next".

### B3. Signal validation on write — resolving the contradiction

Validation depends on `rules_status`:

| `rules_status` | Behaviour |
|---|---|
| `active` | Every signal referenced in `detection_rules` and `anchor_signals` **must** exist in the active registry. Unknown signal → **422** naming it |
| `awaiting_signals` | Unregistered signals are **permitted**, and each must appear in `required_signals_pending`. A referenced-but-not-declared unknown signal → 422 |
| `draft` | Unregistered signals permitted, warned not rejected. Draft patterns are never evaluated |

Only `active` patterns are evaluated by step 4. This lets you author the intended SSIS
rules today, declare exactly which signals they await, and have them start working the
moment the extractor lands — with a governance report telling you that.

When a signal is later registered, re-validate every `awaiting_signals` pattern and
report which ones are now promotable to `active`. Promotion stays a human action.

### B4. Editor rebuild

The current tag-input editor for frameworks, namespaces, globs and packages becomes
obsolete. Replace with a rule builder covering: anchor signals (warning when a weak
signal per §7 is the only anchor), rule groups, the signal condition editor,
classification fields, compatibility multi-selects, eligibility, analysis requirements,
thresholds, `rules_status` with its pending-signals editor, and a validated raw-JSON
escape hatch. Every signal select shows its registry description.

### B5. Export

`GET /api/catalog/export` gains the new fields, stays deterministic and sorted, and
bumps `catalog_version` to `2.0`. Include `catalog_revision` in the envelope.

---

## Part C — Detection rule schema

Stored in `detection_rules` JSONB. `schema: "signal-rules/1.0"`.

```json
{
  "schema": "signal-rules/1.0",
  "all": [
    { "id": "wcf-contract", "signal": { "name": "SERVICE_CONTRACT_ATTRIBUTE", "minimumOccurrences": 1 } }
  ],
  "any": [
    { "id": "svc-host", "signal": { "name": "SVC_FILE", "minimumOccurrences": 1 } },
    { "id": "svc-config", "signal": { "name": "SYSTEM_SERVICE_MODEL_CONFIG" } }
  ],
  "atLeast": [
    { "id": "razor-evidence", "count": 2,
      "of": [
        { "id": "razor-file", "signal": { "name": "RAZOR_FILE" } },
        { "id": "pages-folder", "signal": { "name": "PAGES_FOLDER" } }
      ] }
  ],
  "supporting": [
    { "id": "operation-contract", "signal": { "name": "OPERATION_CONTRACT_ATTRIBUTE" }, "weight": 15 }
  ],
  "none": [
    { "id": "is-test", "signal": { "name": "FACT_ATTRIBUTE", "minimumOccurrences": 1 }, "disqualify": true },
    { "id": "weak-test-hint", "signal": { "name": "TEST_METHOD_ATTRIBUTE" }, "penalty": 20 }
  ],
  "metadata": [
    { "id": "is-library", "field": "outputType", "equals": "Library" }
  ]
}
```

### Rule ids

Every condition carries an **`id`**, referenced in `matched_rules` and `failed_rules`
so explanations and regression diffs are stable. Author-supplied ids are required on
`active` patterns; the API generates a positional fallback (`all[0]`) and warns if
omitted. Ids must be unique within a pattern. Renaming an id is a material change and
bumps `version` — it breaks corpus comparisons otherwise.

### Signal condition fields

`name` (required, registry-checked), plus optional `category`, `type`, `sourceType`,
`value` (`equals`, `in`, `startsWith`, `contains`, `regex`), `minimumOccurrences`,
`maximumOccurrences`, `minimumDistinctValues`, `minimumDistinctSourceFiles`,
`minimumExtractionConfidence`.

Prefer `equals`, `in` and `startsWith`. A `regex` must be anchored and is checked for
catastrophic backtracking at save time.

### Negative conditions

Two distinct behaviours the requirements document conflates:

- `disqualify: true` — pattern cannot match, regardless of score
- `penalty: <n>` — subtract from the score

Use `disqualify` for genuine exclusions, `penalty` for weak counter-evidence.

### Metadata conditions

From step 2 and step 3 project data rather than signals: `outputType`,
`projectFormat`, `frameworkFamily`, `frameworkVersion`, `projectSdk`,
`structuralType`, `extension`, `fingerprintStatus`. Per §10.6, not everything needs to
become a signal.

---

## Part D — Project role determination

A first pass over patterns with `classification_role: PROJECT_ROLE`, using the same
engine. Seed six:

| Pattern id | Value | Primary basis |
|---|---|---|
| `role-test-project` | `TEST` | `TESTING_INDICATOR` signals, test framework packages |
| `role-database-project` | `DATABASE` | `structuralType: sql_database_project` |
| `role-deployment-project` | `DEPLOYMENT` | Out-of-scope structural types from step 2 |
| `role-library-project` | `LIBRARY` | `outputType: Library`, no entry point signals |
| `role-application-project` | `APPLICATION` | Entry point signals, `outputType` Exe/WinExe, or a web SDK |
| `role-unknown` | `UNKNOWN` | Fallback, lowest priority, always matches |

Highest score wins; ties break on `priority`. The result carries its own confidence.

Role gates application-pattern eligibility via `eligibility.excludedProjectRoles`.
This is what stops a test project containing MVC references being classified as an MVC
web application — the failure §11 exists to prevent, and the highest-value guard in
this step.

**Role exclusions apply only to the patterns that declare them.** A `TEST` or
`LIBRARY` project is excluded from application-type patterns but still evaluated for
`SECONDARY` capability patterns. A library using EF Core should record that capability.

---

## Part E — Scoring and resolution, pinned

### Match score

```
1. `all`      — any failure       → NOT MATCHED, score 0
2. `any`      — none pass         → NOT MATCHED, score 0
3. `atLeast`  — any group short   → NOT MATCHED, score 0
4. `metadata` — any failure       → NOT MATCHED, score 0
5. `none`     — disqualify fires  → NOT MATCHED, score 0
                penalty fires     → accumulate
6. base_score       = 50
7. supporting_score = min(50, sum of matched supporting weights)
8. match_score      = clamp(base_score + supporting_score − penalties, 0, 100)
9. matched if match_score >= thresholds.minimumScore
```

Base 50 means required conditions alone are a bare pass; supporting evidence lifts a
pattern past a typical threshold of 70. Tune thresholds per pattern, not the base.

### Confidence

```
confidence = (match_score / 100)
           × completeness_factor
           × extraction_factor
           × capability_factor
           × ambiguity_factor
```

| Factor | Value |
|---|---|
| `completeness_factor` | `COMPLETE` 1.0, `PARTIAL` 0.85 |
| `extraction_factor` | Mean `extraction_confidence` of signals that matched conditions |
| `capability_factor` | **0 if any `required` capability is absent** — the pattern cannot be evaluated. 0.9 if a `preferred` capability is absent. Otherwise 1.0 |
| `ambiguity_factor` | 0.8 when a **conflicting** pattern scored within `ambiguity_margin` (default 10), else 1.0 |

Levels: `HIGH` ≥ 0.85, `MEDIUM` ≥ 0.60, `LOW` ≥ 0.40, else `VERY_LOW`.

All coefficients live in
`steps/step-004-classification/config/classification-config-1.0.0.json`, versioned in
git and recorded in every classification output. Never hardcoded.

### Primary versus secondary

They resolve differently, and the requirements document does not separate them:

- **`PRIMARY` patterns compete.** Conflicts, ambiguity and selection apply. At most
  one is marked `is_primary_selected`.
- **`SECONDARY` patterns do not compete.** Every one above threshold is recorded. A
  project can hold many capabilities simultaneously.

`classification_status` describes the **primary** outcome only. Secondary capabilities
are always listed regardless of status.

### Conflict rejection

When two conflicting primaries are both above threshold but **outside** the ambiguity
margin, the higher scorer wins and the loser is recorded with `matched: true`,
`is_primary_selected: false`, and a `rejection_reason` naming the winner and the score
gap. §20 requires explaining why a conflicting pattern was rejected — this is where
that lives.

### Status resolution

1. Fingerprint `SKIPPED` → `SKIPPED`
2. Role excludes every candidate primary pattern → `NOT_ELIGIBLE`
3. A required capability is missing for every candidate → `INSUFFICIENT_FINGERPRINT`
4. Two or more **conflicting** primaries above threshold within the margin → `AMBIGUOUS`
5. Two or more **compatible** primaries above threshold → `MULTIPLE_MATCHES`
6. Exactly one primary above threshold → `MATCHED`
7. None above threshold, fingerprint sufficient → `NO_PATTERN_MATCHED`
8. Engine error → `CLASSIFICATION_FAILED`

`INSUFFICIENT_FINGERPRINT` versus `NO_PATTERN_MATCHED` matters most — only the latter
is a step 5 candidate. Clustering projects that failed to match because analysis was
incomplete would poison pattern discovery.

---

## Part F — Data model

Replaced wholesale per repository on rescan.

### `project_classifications` — 1:1 with `projects`

`project_id` PK FK, `repository_id`, `classification_status`, `project_role`,
`project_role_confidence`, `catalog_revision`, `signal_registry_version`,
`config_version`, `evaluated_pattern_count`, `primary_pattern_id` (FK, nullable),
`warnings` JSONB, `step_execution_id`, `classified_at`.

### `classification_matches`

One row per **evaluated** pattern, matched or not — near-misses are the tuning input.

`id` PK, `project_id` FK, `pattern_id` FK, `pattern_version`, `matched` BOOL,
`classification_role`, `match_score` INT, `confidence` NUMERIC(3,2),
`confidence_level`, `is_primary_selected` BOOL, `rejection_reason` TEXT,
`engagement_scope_status` (`active`/`deferred`/`deleted`, per A5),
`matched_rules` JSONB (rule id, signal, required vs actual), `failed_rules` JSONB,
`missing_preferred` JSONB, `negative_triggered` JSONB, `explanation` TEXT.

Unique on `(project_id, pattern_id)`. Index on `(repository_id, matched)` and
`(repository_id, pattern_id)`.

### `catalog_coverage_reports` — per scan, per repository

§18's metrics, plus: patterns awaiting signals grouped by `expected_extractor`, and
the most frequent unmatched signal combinations.

---

## Part G — Artifact and step registration

```yaml
step_name: pattern-classification
lifecycle_step_no: 4
display_name: "Pattern classification against catalog"
owner_code: P + S
version: "1.0.0"
implementation_status: implemented

consumes:
  - artifact_type: application-fingerprint
    version_range: "^1.0.0"
    optional: false

produces:
  - artifact_type: application-classification
    artifact_version: "1.0.0"

adapter_type: process
adapter_config:
  command: ["steps/step-004-classification/.venv/Scripts/python.exe",
            "steps/step-004-classification/main.py"]
  timeout_seconds: 1800
```

Own virtualenv, per the convention from step 2. Artifact follows §19's per-project
structure with a repository envelope and governance summary, deterministic — sorted
keys, volatile fields in `StepOutput.metadata`.

The `S` in the owner code is reserved. **v1 calls no LLM**, per §26.

---

## Part H — Catalog revision and regression corpus

### Catalog revision

A `catalog_revisions` table with a monotonic integer, incremented on any insert,
update or soft delete of `patterns` or `target_state_options`. Recorded on every
classification. This is what makes a classification reproducible.

### Regression corpus

§23.4 is the highest-value testing idea in the document — it lets rules be tuned
without rescanning repositories.

```
steps/step-004-classification/corpus/
  fingerprints/<repo-slug>/<project-slug>.json
  expected/<repo-slug>/<project-slug>.json
```

`--corpus` mode runs across the corpus and diffs against expected.

**Comparison ignores volatile fields** — `catalog_revision`, `config_version`,
timestamps — and compares: `classification_status`, `project_role`,
`primary_pattern_id`, the set of matched pattern ids, and `match_score` within a
tolerance of ±2. Without this, every catalog edit would invalidate every expected file
and the corpus would be abandoned within a week.

Report per project: status changes, newly ambiguous, newly unmatched, score deltas
beyond tolerance. Seed from the two sample repositories.

---

## Part I — API and UI

```
GET /api/repositories/{id}/classification-summary
GET /api/repositories/{id}/classifications        ?status=&pattern_id=&role=
GET /api/projects/{project_id}/classification     full detail incl. failed matches
GET /api/engagements/{eid}/pattern-distribution
GET /api/engagements/{eid}/catalog-coverage
GET /api/catalog/pending-signals                  awaiting_signals grouped by extractor
```

### Repository detail — Classification section

§25.1 counts, then a project table with role, primary pattern, confidence level and
status, expanding to the §25.4 detail tree.

### Project classification detail

Matched patterns with score, confidence and explanation, then **near-miss patterns
with their failed rules** — what makes tuning possible. Every matched rule links to
its step 3 signal and evidence, satisfying §20's traceability requirement.

### Dashboard

**The Patterns card becomes real.** Applications stays `—` until deployable
application aggregation exists, which §26 places outside step 4.

Label honestly: *"Projects classified as WCF Service: 12"*, never *"WCF applications: 12"*.

### Catalog coverage — master view

In Workflow Administration: registered versus referenced signals, unused signals,
patterns never matched, **patterns awaiting signals grouped by expected extractor**,
and the most frequent unmatched signal combinations. The middle one is your step 3
extractor backlog; the last is the direct input to step 5.

---

## Part J — Build sequencing

Four prompts. Do not merge them.

**J1 — Catalog schema migration.** B1 through B3 and B5, plus `catalog_revisions`. No
UI rule builder, no re-authored patterns, no classification. Gate: the eight existing
patterns survive with `detection_rules_legacy` populated, the catalog UI still loads,
and decision records are intact.

**J2 — Re-author patterns.** The eight seeded patterns plus six role patterns, using
real registry signal names. `ssis-package` marked `awaiting_signals` with structured
`required_signals_pending`. Gate: every `active` pattern's signals exist; every
`awaiting_signals` pattern declares its pending signals; all validate.

**J3 — Classification engine.** Script, tables, artifact, registration, corpus mode.
Gate: runs on both samples, `phase0-repository-discovery` validates with no YAML
change, two runs produce identical checksums.

**J4 — UI.** Rule builder replacing the old editor, classification views, dashboard,
coverage. Gate: a rule edited in the UI changes classification on re-run without a
rescan.

---

## Acceptance criteria

- [ ] Patterns gain all B1 columns; `detection_rules_legacy` preserves prior values
- [ ] An `active` pattern referencing an unregistered signal returns 422 naming it
- [ ] An `awaiting_signals` pattern may reference unregistered signals, but only those
      declared in `required_signals_pending`; an undeclared one returns 422
- [ ] Registering a new signal reports which `awaiting_signals` patterns are now
      promotable, and promotion remains a human action
- [ ] A pattern appearing in both `compatible_with` and `conflicts_with` is rejected
- [ ] All eight patterns re-authored; six role patterns seeded
- [ ] `ssis-package` is `awaiting_signals` with structured pending signals, excluded
      from evaluation with a governance observation
- [ ] A test project containing MVC signals classifies as role `TEST` with no primary
      application pattern, but still records secondary capabilities
- [ ] A library using EF Core records the capability despite being role `LIBRARY`
- [ ] Scoring matches Part E exactly on a hand-computed fixture
- [ ] A missing **required** capability yields `INSUFFICIENT_FINGERPRINT`, not
      `NO_PATTERN_MATCHED`
- [ ] Conflicting patterns within the margin yield `AMBIGUOUS` with no forced winner
- [ ] Conflicting patterns outside the margin select the higher scorer and record
      `rejection_reason` on the loser
- [ ] Compatible primaries above threshold yield `MULTIPLE_MATCHES`
- [ ] Multiple secondary capabilities coexist without competing
- [ ] `disqualify` and `penalty` behave differently and are both exercised
- [ ] A pattern deferred for an engagement still classifies, annotated `deferred`
- [ ] Failed matches persist with their failed rules and stable rule ids
- [ ] Every matched rule links to its step 3 signal and evidence
- [ ] `catalog_revision` increments on a pattern edit and is recorded
- [ ] Corpus mode ignores volatile fields and reports score deltas beyond ±2
- [ ] Re-running classification after a rule change requires no rescan
- [ ] Two runs over unchanged input produce identical artifact checksums
- [ ] `REPOSITORY`-scoped patterns are skipped with a governance observation
- [ ] Dashboard Patterns card is real; Applications still shows `—`
- [ ] Catalog coverage groups pending signals by expected extractor
