# 24 — Step 4: Pattern Classification Against Catalog

> **Superseded by [28-ITEM-AND-CONVERSION-MODEL.md](28-ITEM-AND-CONVERSION-MODEL.md).** Kept as history; do not build from it. Lifecycle step 6 is now `item-detection` (`backend/app/steps/item_detection.py`); this document's classification engine, scoring, conflicts and role patterns were removed.

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
| `aspnetcore-rest-api-legacy` | Yes | — |
| `fx47-class-library` | Yes | — |
| `fx-aspnet-mvc` | Yes | — |
| `aspnet-webforms` | Verify | Confirm `ASPX_FILE` is registered |
| `wcf-iis-servicemodel` | Yes | — |
| `console-batch-job` | Partly | No scheduling signals |
| `windows-service` | Yes | — |
| `ssis-package` | **Yes, on metadata alone** | Step 3 emits no SSIS signals, but step 2 already derives `structuralType: ssis_project` from the `.dtproj` extension — a metadata-only rule is confident but has no package-internals evidence; see the `matchWarnings` note on it in Part C |

A pattern that cannot yet be expressed is recorded with `rules_status:
awaiting_signals` and a **structured** `required_signals_pending` list (Part B2) —
not free text. That turns a gap into a work queue driving step 3's extractor
priorities, and it surfaces in catalog coverage.

**"What step 3 can see" is not the only source of detection.** `ssis-package` is
`active`, not `awaiting_signals` — a `.dtproj` file's `structuralType: ssis_project`
is step 2 metadata (§10.6, Part C "Metadata conditions"), available today regardless
of what step 3 extracts. Before authoring a pattern as `awaiting_signals`, check
whether step 2 metadata alone gives a usable — if thin — detection; `required_signals_
pending` still tracks the richer signals a future extractor will add, independent of
whether the pattern is already active on metadata. A metadata-only match should
declare a `matchWarnings` entry (Part C) naming the gap, so "confidently detected,
thinly evidenced" is visible on every match rather than looking identical to a
fully-evidenced one.

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
| `anchor_signals` | `JSONB` NOT NULL DEFAULT `'[]'` | Signal names. Intended for an inverted index that was never built — it does **not** gate evaluation, and must not: a metadata-only pattern has none. Read only by coverage reporting today. See Part C, "Candidate selection" |
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

**An undeclared relationship defaults to CONFLICTING, not compatible.** Two patterns
whose relationship is in neither list — the common case, since the seeded patterns
leave both mostly empty — are not silently treated as compatible. Defaulting to
compatible would silently assert a project is two things at once; defaulting to
conflicting forces a human look, and every relationship then gets declared
deliberately as the estate is learned. See Part E's "Conflict rejection" for how this
plays out (`AMBIGUOUS` when the pair scores within the ambiguity margin, the higher
scorer wins otherwise) and the `UNDECLARED_PATTERN_RELATIONSHIP` governance
observation it emits.

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

`blocking: true` means the pattern cannot be evaluated **on signals alone** without
it — not that the pattern is unevaluable outright, if a metadata-only rule (Part A6)
gives it another way in. `ssis-package` is `active` with `SSIS_PACKAGE_FILE` still
listed here, `blocking: true`: true for what it was meant to say (no signal-based
detection works without it) even once metadata makes the pattern evaluable some other
way. Non-blocking entries are enrichment. Catalog coverage groups these by
`expected_extractor` **regardless of `rules_status`** — an `active` pattern's
still-pending signals are as much a work queue entry as an `awaiting_signals`
pattern's — producing a direct answer to "which extractor should we build next".

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
  ],
  "matchWarnings": [
    "Detected structurally; package internals not yet analysed."
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

The `none` group takes **signal conditions only**. A metadata exclusion is
expressed in the `metadata` group instead, with `notEquals` or `notIn` — see
the next section.

### Metadata conditions

From step 2 and step 3 project data rather than signals: `outputType`,
`projectFormat`, `frameworkFamily`, `frameworkVersion`, `projectSdk`,
`structuralType`, `extension`, `fingerprintStatus`. Per §10.6, not everything needs to
become a signal. A pattern detectable from these alone can be `active` with empty
`all`/`any`/`atLeast`/`supporting`/`none` — see `ssis-package` (Part A6) — the base
score of 50 (Part E) still applies with nothing to lift it, so it matches at the bare
pass unless `thresholds.minimumScore` is lowered to admit that.

Positive operators are `equals`, `in`, `startsWith`, `contains`, `regex`. Two
negative operators, `notEquals` and `notIn`, express a metadata **exclusion** —
the `none` group cannot, since it accepts signal conditions only.

Null handling differs between the two kinds, deliberately:

- A **positive** operator on an absent field fails. A project with no recorded
  `outputType` is not known to be `WinExe`, so it does not match a rule
  requiring it.
- A **negative** operator on an absent field passes, for the same reason: not
  known to be `WinExe` is not the same as known to be `WinExe`.

This matters most for **absence-based patterns** — the class of pattern with no
positive signal of its own, which matches by denying everything else
(`fx47-class-library`, `netstandard-modern-library`, `role-library-project`).
Their signal disqualifiers hold only when step 3 actually extracted the signal;
on a `PARTIAL` fingerprint with syntax analysis unavailable they go blind and
co-match whatever they were meant to exclude. Step 2 msbuild metadata is
recorded whether or not syntax analysis ran, so a metadata exclusion holds
where the signal one does not. Both library patterns therefore carry
`outputType notIn ["WinExe", "Exe"]` alongside their entry-point disqualifiers:
belt and braces, and the braces are the ones that survive a degraded scan.

### Framework family discriminates patterns; framework version parameterises accelerators

**`frameworkFamily` is a legitimate pattern discriminator. `frameworkVersion` is
not.** Family — `net-framework` versus `net-core` versus `net-standard` versus `net` —
is a genuine pattern boundary: a WCF service on .NET Framework and a REST API on .NET
Core are different code shapes, hosted differently, migrated differently. Version
within a family is not. Core 2.1 and Core 3.1 REST APIs are structurally identical —
same `Startup.cs`, same controllers, same `Microsoft.AspNetCore.Mvc` — and one
accelerator handles both by reading the version. Splitting on it yields one pattern
per minor release for a single shape, and the catalog stops being a catalog of shapes.

So: no pattern carries a `frameworkVersion` condition. Where one is needed to separate
two shapes, the real discriminator is almost always something else — for
`aspnetcore-rest-api-legacy` it is the **hosting model** (`Startup.cs` plus
`WebHost`/`Host.CreateDefaultBuilder`, and explicitly *not*
`WEB_APPLICATION_CREATE_BUILDER_ENTRY_POINT`, which belongs to the modern patterns).

Version is still recorded, and deliberately: `framework_family` and
`framework_version` are echoed onto `project_classifications` and onto the artifact's
per-project block (Part F), so it is an explicit **pattern parameter** rather than
something implicit that a consumer has to join back to step 2 to recover. Step 10's
risk scoring reads the version, and so does an accelerator deciding which breaking
changes apply. That is the division: **family selects the pattern, version
parameterises whatever acts on it.**

Support lifecycle sits on the version side of that line too. A `netcoreapp3.1` or
`net5.0` project is past end of life and needs a retarget, but "is this still
supported" is a fact about the version, not a different code shape — so it is a
`framework_version` judgement, never a pattern boundary. This is why
`netstandard-modern-library` covers `net-core` alongside `net` and `net-standard`:
the shape is identical, and excluding the out-of-support family left a common real
project matching no library pattern at all and falling through to step 5's discovery
queue.

**Support lifecycle parameterises target-state selection, not pattern detection.**
The out-of-support case is real and must be actionable — it just belongs one level
down, in the target state. Every `ALREADY_MODERN` pattern therefore carries two
options rather than one:

- *"No migration required — supported version"*
- *"Retarget to current LTS — version out of support"*

Same pattern, same code shape, two destinations, and step 14 picks between them from
the classification's `framework_version`. Neither is `is_recommended`: the condition
is in the option names, and recommending either unconditionally would assert a
version fact the catalog cannot know — a .NET 6 web app is `ALREADY_MODERN` today and
approaching end of support regardless. This is the same principle as the family/version
split, applied to the decision rather than the detection: **detection reads the shape,
target-state selection reads the version.**

### The hosting model discriminates ASP.NET Core patterns, not the family

**`frameworkFamily` is only a valid discriminator where the pattern is genuinely
family-bound.** Some patterns are: `wcf-iis-servicemodel` and `windows-service` are
`System.ServiceModel`/`System.ServiceProcess`-based, `aspnet-webforms` and
`fx-aspnet-mvc` are `System.Web`-based, and none of those API surfaces exist outside
.NET Framework. A family condition on those is a real constraint.

**ASP.NET Core patterns are not family-bound, and a family condition on one is a
mistake** — the same error as a version condition, one level up. ASP.NET Core runs on
either family: ASP.NET Core 2.x on .NET Framework 4.6.1 was a supported
configuration, and `eShopPorted.csproj` in the eShopModernizing sample is exactly
that. Its migration path follows the **code shape** — retarget and fix Core breaking
changes — not the TFM. Binding it to `fx-aspnet-mvc` on the strength of its
`net-framework` family would attach a `System.Web.Mvc` accelerator to code that has
no `System.Web.Mvc` in it, and needs a different API surface.

So `aspnetcore-rest-api-legacy` carries **no** metadata condition. Its discriminator
is the hosting model: `STARTUP_CLASS_ENTRY_POINT` plus a host builder
(`WebHost`/`Host.CreateDefaultBuilder`), with
`WEB_APPLICATION_CREATE_BUILDER_ENTRY_POINT` disqualifying — that belongs to the
modern patterns. And the separation is declared from **both** directions:
`fx-aspnet-mvc` disqualifies on `STARTUP_CLASS_ENTRY_POINT` and both host builders,
because a `System.Web.Mvc` application never has them. That is a true exclusion, and
it is what should have separated the two patterns from the start — the family
condition was standing in for it.

The general rule: reach for a `frameworkFamily` condition only when the pattern's
defining API surface cannot exist on the other family. Otherwise find the structural
discriminator — usually the hosting or entry-point model — and declare the exclusion
on both patterns.

### Mutual exclusion must be declared on both patterns

**Where two patterns are mutually exclusive, both must say so.** If A is defined by a
signal that B should never see, then B needs a `none` disqualifier for it — not just
A needing one for B's. Relying on the other pattern scoring higher is **not
separation**: it produces a real match on the wrong pattern, which then depends on
score order, the ambiguity margin and the undeclared-relationship default to come out
right, and it attaches the wrong accelerator the moment any of those shift.

This has now been the same bug three times — `core2-rest-api` had no exclusion against
`fx-aspnet-mvc`, `fx-aspnet-mvc` had none against the ASP.NET Core hosting model, and
`fx47-class-library` had none against either — which makes it a systematic gap in
authoring rather than three accidents.

**Absence-based patterns are the exposed class.** A pattern with no positive signal
condition — `fx47-class-library`, `netstandard-modern-library`, `ssis-package` — is
*defined by* its `none` list plus its metadata conditions. Any project shape missing
from that list is a shape the pattern will claim. When authoring or editing one, the
question is not "does this rule describe a class library" but "which other pattern's
defining signals are absent from my exclusions".

`probe.py --audit` checks this by construction: it builds each active PRIMARY
pattern's canonical project and reports any *other* pattern that also matches it.
Run it after any rule edit. It sweeps `frameworkFamily` for patterns that declare no
family condition, because that is the axis the missed cases lived on.

### Candidate selection

Every non-role pattern in the active catalog is evaluated for every project — a full
scan, deliberately, and it is load-bearing rather than incidental.

Part B1 describes `anchor_signals` as being "for the inverted index", and a
signal-keyed index is the obvious optimisation: evaluate only those patterns whose
anchor signals the project actually emitted. **It has never been built** — nothing
reads `anchor_signals` at evaluation time, only coverage reporting does — and a
metadata-only pattern is exactly what such an index would break. `ssis-package`
detects on `structuralType` alone, so its `anchor_signals` is `[]`; an index keyed on
anchor signals would return it for no project at all and silently drop it from
evaluation, turning every SSIS package back into `NO_PATTERN_MATCHED` with nothing in
the output to explain why.

Every metadata-only pattern therefore depends on candidate selection staying a full
scan. If an index is ever added for throughput, it goes in
`engine/classify.py`'s `candidate_application_patterns()`, which exists to own this
contract, and **a pattern with empty `anchor_signals` must bypass the index and always
be evaluated.** The corpus fixture `synthetic/ssis-metadata-only` fails if this
regresses.

### Match warnings

`matchWarnings` — an array of strings, top-level alongside the rule groups. Shown as a
project-level warning (`code: PATTERN_MATCH_WARNING`, naming the pattern) whenever
this pattern matches. For a pattern whose detection is confident but its evidence is
thin — most often a metadata-only pattern with no signal evidence to show — so that
gap is visible on the match rather than implied by an absence of signal evidence the
reader has to notice on their own.

---

## Part D — Project role determination

A first pass over patterns with `classification_role: PROJECT_ROLE`, using the same
engine. Seed six:

| Pattern id | Value | Primary basis |
|---|---|---|
| `role-test-project` | `TEST` | `TESTING_INDICATOR` signals, test framework packages |
| `role-database-project` | `DATABASE` | `structuralType: sql_database_project` |
| `role-deployment-project` | `DEPLOYMENT` | Out-of-scope structural types from step 2 |
| `role-library-project` | `LIBRARY` | No entry point signals, no IIS-hosted evidence, no test attributes |
| `role-application-project` | `APPLICATION` | Entry point signals, IIS-hosted evidence (`SVC_FILE`, `SYSTEM_SERVICE_MODEL_CONFIG`, `ASPX_FILE`, `ASMX_FILE`, `IHTTP_HANDLER_BASE_CLASS`, `IHTTP_MODULE_BASE_CLASS`), `outputType` Exe/WinExe, or a web SDK |
| `role-unknown` | `UNKNOWN` | Fallback, lowest priority, always matches |

Highest score wins; ties break on `priority`. The result carries its own confidence.

Role gates application-pattern eligibility via `eligibility.excludedProjectRoles`.
This is what stops a test project containing MVC references being classified as an MVC
web application — the failure §11 exists to prevent, and the highest-value guard in
this step.

**Role exclusions apply only to the patterns that declare them.** A `TEST` or
`LIBRARY` project is excluded from application-type patterns but still evaluated for
`SECONDARY` capability patterns. A library using EF Core should record that capability.

**The role pass runs for `SKIPPED` projects too.** It comes before the
`fingerprint_status == SKIPPED` gate, not after it. Role determination rests
mostly on step 2 metadata (`structuralType`, `outputType`), which exists for a
project step 3 declined to fingerprint — a `docker-compose.dcproj` is
recognisably `DEPLOYMENT` whether or not anything was extracted from it. Leaving
`project_role` null on those rows loses information the platform already has,
and makes the estate view report an unknown role for projects whose role is not
in doubt. Application-pattern evaluation still stops at the gate; only the role
survives it.

**Both halves of a mutual exclusion apply here as well** (see "Mutual exclusion
must be declared on both patterns"). `role-library-project` is absence-based and
sits at priority 65, *above* `role-application-project`'s 60 — so any
application evidence it does not explicitly deny wins the role for it instead.
That is how IIS-hosted WCF services (`OutputType: Library`, no `Main`, no
`Global.asax`) were recorded as `LIBRARY` while ASP.NET MVC applications beside
them were `APPLICATION`. Every signal added to `role-application-project`'s `any`
group must be added to `role-library-project`'s `none` group in the same change.

**`role-unknown` always matches and never wins.** It is the specified fallback:
empty rules, base score 50, priority 0. Coverage counting must therefore record
every role pattern that cleared its threshold, not only the winner, or the
always-matching fallback reads as never matched.

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

**"Conflicting" includes the undeclared case.** Two primaries whose relationship
appears in neither pattern's `compatible_with` nor `conflicts_with` (Part B1) are
treated as conflicting by default — this is the case that actually fires on real
legacy repositories, since the seeded patterns leave both lists largely empty and
hybrid applications are common, not edge cases. Each match involved records
`relationship_source`: `"declared"` when the catalog actually says so,
`"defaulted"` when the pattern fell back to the undeclared-conflicting rule — so a
human reading the result can tell a deliberate catalog decision from a default that
still needs one made. A `"defaulted"` outcome also emits a governance observation,
`UNDECLARED_PATTERN_RELATIONSHIP`, naming both pattern ids, so the catalog can be
corrected as the estate is learned. Declaring `compatible_with` explicitly is the only
way two primaries stop competing — silence is never read as compatibility.

### Status resolution

1. Fingerprint `SKIPPED` → `SKIPPED`
2. Role excludes every candidate primary pattern → `NOT_ELIGIBLE`
3. A required capability is missing for every candidate → `INSUFFICIENT_FINGERPRINT`
4. Two or more **conflicting** (declared, or undeclared and therefore defaulted —
   see "Conflict rejection") primaries above threshold within the margin →
   `AMBIGUOUS`
5. Two or more **compatible** primaries above threshold — compatibility must be
   declared; this never happens by default — → `MULTIPLE_MATCHES`
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
`project_role_confidence`, `framework_family`, `framework_version`,
`catalog_revision`, `signal_registry_version`,
`config_version`, `evaluated_pattern_count`, `primary_pattern_id` (FK, nullable),
`warnings` JSONB, `step_execution_id`, `classified_at`.

`framework_family` and `framework_version` are echoed from step 2's `projects` row
(both nullable — step 2 leaves them null for a project with no parseable target
framework) and also appear on the artifact's per-project block, so the artifact is
self-contained and no downstream consumer has to join back to step 2. See Part C,
"Framework family discriminates patterns; framework version parameterises
accelerators".

### `classification_matches`

One row per **evaluated** pattern, matched or not — near-misses are the tuning input.

`id` PK, `project_id` FK, `pattern_id` FK, `pattern_version`, `matched` BOOL,
`classification_role`, `match_score` INT, `confidence` NUMERIC(3,2),
`confidence_level`, `is_primary_selected` BOOL, `rejection_reason` TEXT,
`relationship_source` TEXT (`declared`/`defaulted`, nullable — set only when this
match participated in a conflict/ambiguity determination against another PRIMARY
candidate; see Part E "Conflict rejection"),
`engagement_scope_status` (`active`/`deferred`/`deleted`, per A5),
`matched_rules` JSONB (rule id, signal, required vs actual), `failed_rules` JSONB,
`missing_preferred` JSONB, `negative_triggered` JSONB, `explanation` TEXT.

#### `failed_rules` entries

Each entry carries `group` (`all`/`any`/`atLeast`/`metadata`) and
**`is_disqualifying`**, and the list is **sorted disqualifying-first**.

The distinction is load-bearing, because `failed_rules` holds two different kinds of
thing and conflating them misleads:

- `is_disqualifying: true` — this condition's failure is *why* the pattern did not
  match. For `all` and `metadata`, any single failure. For `any` and `atLeast`, the
  members of a group that failed as a whole.
- `is_disqualifying: false` — an **unsatisfied alternative inside a group that
  passed** on one of its siblings. The pattern was not held back by it. This is
  tuning context, not a reason.

Without the flag, `failed_rules[0]` reads as the cause when it may be neither first
nor a cause: `aspnetcore-rest-api-legacy` on a project with
`WEBHOST_CREATE_DEFAULT_BUILDER_ENTRY_POINT` recorded `host-builder` (the *other*
`any` member, in a group that passed) ahead of the `metadata` condition that actually
disqualified it. Part I makes near-miss failed rules the rule-tuning surface, so the
UI must render the two groups separately rather than as one red list.

**A `none`-disqualified pattern has an empty `failed_rules`.** A `disqualify: true`
condition that fires is recorded in **`negative_triggered`**, not `failed_rules` —
so for that whole class of exclusion (the largest one, now that mutual exclusions are
declared on both sides) the cause is in a different array and `failed_rules` is `[]`.
Both must be read together to answer "why didn't this match"; `explanation` names the
stage (`none-disqualify`) and is the reliable single field. `fx47-class-library` on
`eShopPorted.csproj` is the worked example: `failed_rules` `[]`,
`negative_triggered` `[no-mvc-controller]`.

Unique on `(project_id, pattern_id)`. Index on `(repository_id, matched)` and
`(repository_id, pattern_id)`.

### `catalog_coverage_reports` — per scan, per repository

§18's metrics, plus: patterns awaiting signals grouped by `expected_extractor`, and
the most frequent unmatched signal combinations.

`most_frequent_unmatched_signal_combinations` is the recurring **shapes of
signals present on projects whose status is `NO_PATTERN_MATCHED`** — each entry
a `{signals, project_count}` pair, top five by count. It is the direct input to
step 5's clustering: two projects that matched nothing and carry the same signal
shape are one candidate pattern, not two gaps. A repository with no
`NO_PATTERN_MATCHED` projects therefore reports an empty list, and that is the
correct output rather than a missing metric.

It is **not** a count of failed patterns' `anchor_signals`. Computing it that way
restates `never_matched_pattern_ids` — every entry's count equals the project
count — and gives step 5 nothing to cluster on. The
`corpus/fingerprints/unmatched-cluster/` fixtures pin the intended behaviour
with two unmatched projects sharing a shape, asserted through
`corpus/expected/unmatched-cluster/_coverage.json`; that file is the repo-level
half of the corpus contract, since a per-project expectation cannot express a
property of the repository as a whole.

`patterns_awaiting_signals_by_extractor` is **not** filtered to
`rules_status: awaiting_signals`. A pattern can be `active` on a partial
detection while `required_signals_pending` still names richer signals a future
extractor will supply — `ssis-package` (Part A6) and the two desktop patterns
are all active and all still on an extractor's backlog. The backlog tracks what
`required_signals_pending` says is missing, independent of whether the pattern
can already be evaluated some other way.

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
`required_signals_pending` (later promoted to `active` on a metadata-only rule — see
Part A6 — once it was clear step 2 metadata alone gave a usable detection;
`required_signals_pending` stayed as the extractor backlog for what the rule still
lacks). Gate: every `active` pattern's signals exist; every `awaiting_signals` pattern
declares its pending signals; all validate.

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
- [ ] `ssis-package` is `active` on a metadata-only rule (`structuralType: ssis_project`),
      `thresholds.minimumScore` lowered to the base score, `required_signals_pending`
      still populated for the package-internals signals SsisExtractor will add, and
      every match carries a `matchWarnings` entry saying so
- [ ] Every other `awaiting_signals` pattern has been audited for a step 2
      metadata-only detection before assuming it must wait on step 3 signals
- [ ] No pattern carries a `frameworkVersion` condition; `frameworkFamily`
      conditions remain and every application-type pattern has one
- [ ] `framework_family` and `framework_version` appear on
      `project_classifications` and on the artifact's per-project block
- [ ] Candidate selection evaluates every active non-role pattern, including one
      with empty `anchor_signals`; a metadata-only pattern still matches
- [ ] Corpus covers a metadata-only match and an undeclared-relationship
      `AMBIGUOUS` pair
- [ ] A test project containing MVC signals classifies as role `TEST` with no primary
      application pattern, but still records secondary capabilities
- [ ] A library using EF Core records the capability despite being role `LIBRARY`
- [ ] Scoring matches Part E exactly on a hand-computed fixture
- [ ] A missing **required** capability yields `INSUFFICIENT_FINGERPRINT`, not
      `NO_PATTERN_MATCHED`
- [ ] Conflicting patterns within the margin yield `AMBIGUOUS` with no forced winner
- [ ] Conflicting patterns outside the margin select the higher scorer and record
      `rejection_reason` on the loser
- [ ] Two primaries above threshold whose relationship is declared in neither
      `compatible_with` nor `conflicts_with` default to conflicting — `AMBIGUOUS`
      within the margin, higher-scorer-wins outside it — never `MULTIPLE_MATCHES`
- [ ] Every match involved in a conflict/ambiguity determination records
      `relationship_source` (`declared` or `defaulted`); a `defaulted` outcome emits
      `UNDECLARED_PATTERN_RELATIONSHIP` naming both pattern ids
- [ ] Compatible primaries above threshold, with the relationship explicitly declared
      via `compatible_with`, yield `MULTIPLE_MATCHES`
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
