# 27 — Step 6: Pattern Validation

> **Superseded by [28-ITEM-AND-CONVERSION-MODEL.md](28-ITEM-AND-CONVERSION-MODEL.md).** Kept as history; do not build from it. Pattern validation is no longer a gate; the validation_queue infrastructure it introduced is kept for lifecycle steps 17, 24 and 34.

Lifecycle step 6. Owner: **H**. Job: `phase0-estate-consolidation`, after step 5.

A human decides what each candidate cluster is: a new catalog pattern, an extension of
an existing one, or out of scope.

**This is the platform's first genuine human gate**, and the machinery it establishes —
`AWAITING_APPROVAL`, the validation queue, resume-by-approval — is inherited by steps
22 (plan approval), 38 (code review) and 50 (release approval). Build it as shared
infrastructure with step 6 as its first consumer, not as a one-off.

---

## Part A — The gate model

### Why a gate is not just a slow step

Human decisions here take days. Target-state approval waits on a client architect;
code review waits on a reviewer's queue. A step that blocks a worker for three days is
unusable at 600 applications.

So a gate step **ends its execution cleanly** rather than waiting:

1. Step runs, finds work needing a decision, writes queue items
2. Returns `AWAITING_APPROVAL`; the job execution ends with `batch_status: STOPPED`
3. Humans decide, over whatever period they need
4. A resume creates a **new job execution** continuing from the gate
5. On resume the step re-evaluates: all items decided → `COMPLETED`; some still open →
   `AWAITING_APPROVAL` again

Step 5 in the same job is `COMPLETED` and carried forward, so a resume does not
re-cluster. That property already exists in the runtime and this is its first real use.

### Generic queue, typed payloads

One `validation_queue` table serving all four gate steps. Item **type** varies; the
lifecycle — open, decided, expired, superseded — does not.

Resisting a per-step queue matters. Four bespoke queues means four notification paths,
four "what is waiting on me" views, and four sets of bugs. One queue with typed
payloads means step 22 inherits a working surface.

---

## Part B — Data model

### `validation_queue`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `engagement_id` | `TEXT` NOT NULL FK | |
| `job_execution_id` | `UUID` NOT NULL FK | The execution that raised it |
| `step_execution_id` | `UUID` NOT NULL FK | |
| `step_name` | `TEXT` NOT NULL | `pattern-validation`, later `plan-approval-gate` etc. |
| `item_type` | `TEXT` NOT NULL | CHECK IN (`pattern_candidate`, `target_state_selection`, `migration_plan`, `code_review`, `release_approval`) |
| `item_key` | `TEXT` NOT NULL | Natural key of the subject — here the `cluster_id` |
| `title` | `TEXT` NOT NULL | Rendered in the queue list |
| `payload` | `JSONB` NOT NULL | Type-specific detail for the UI |
| `status` | `TEXT` NOT NULL DEFAULT `'open'` | CHECK IN (`open`, `decided`, `superseded`, `withdrawn`) |
| `outcome` | `TEXT` | Type-specific decision value |
| `outcome_detail` | `JSONB` | Structured decision data |
| `decision_note` | `TEXT` | |
| `decided_by` | `TEXT` | Free text until auth exists |
| `decided_at` | `TIMESTAMPTZ` | |
| `priority` | `INTEGER` NOT NULL DEFAULT 50 | Ordering hint |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |

Partial unique on `(engagement_id, step_name, item_key) WHERE status = 'open'` — one
open item per subject. A re-run finds the existing open item rather than duplicating.

Indexes on `(engagement_id, status)`, `(job_execution_id)`, `(status, priority)`.

**`superseded`** covers a re-run where the subject changed materially — the old item is
superseded and a new one raised, so the stale question is not answered by accident.
**`withdrawn`** covers the subject disappearing entirely, such as a cluster whose
members all vanished.

### Step 6 payload

```json
{
  "cluster_id": "6189a9508df2",
  "cluster_method": "exact",
  "member_count": 7,
  "repository_count": 3,
  "repository_distribution": { "legacy-orders": 4, "legacy-billing": 2, "legacy-web": 1 },
  "cohesion": 1.0,
  "is_singleton": false,
  "canonical_signature": {
    "facets": { "projectRole": "LIBRARY", "frameworkFamily": "net-framework" },
    "signals": ["CONNECTION_STRING_CONFIG", "SYSTEM_MESSAGING_ASSEMBLY", "SYSTEM_MESSAGING_NAMESPACE"]
  },
  "similar_patterns": [ { "pattern_id": "fx47-class-library", "similarity": 0.43 } ],
  "suggested_name": "MSMQ integration library",
  "suggested_description": "…",
  "naming_source": "claude-code",
  "sample_members": [
    { "project_path": "src/Integration/Integration.csproj", "repository_slug": "legacy-orders" }
  ],
  "coverage_at_raise": { "repositories_included": 12, "repositories_pending": 38, "coverage_ratio": 0.24 },
  "is_rereview": false,
  "previous_decision": null
}
```

`coverage_at_raise` is what makes a decision on a partial estate defensible. A reviewer
seeing a two-member cluster at 24% coverage should treat it differently from the same
cluster at 90%, and the UI must say so.

`similar_patterns` **is** shown here, unlike to the narrator. A human deciding whether
to merge needs it; a model naming a shape would be biased by it.

---

## Part C — Decision outcomes

Four, per §6.2 of the architecture document plus one the incremental model requires.

| Outcome | Meaning | Effect |
|---|---|---|
| `create_pattern` | A genuine new pattern | Opens the rule builder pre-populated from the signature. Cluster → `validated_new`, `resolved_pattern_id` set |
| `merge_into_pattern` | An existing pattern is too narrow | Cluster → `merged`, `resolved_pattern_id` set. **Does not silently edit the pattern** — see below |
| `reject` | Not in modernization scope | Cluster → `rejected`. Reason mandatory |
| `defer` | Insufficient evidence to decide | Item stays `open`, cluster stays `candidate`, a `deferred_until_coverage` threshold is recorded |

`defer` is the one my earlier framing missed, and the incremental model makes it
necessary. At 24% coverage the honest answer to a thin cluster is often "ask me again
later." Without it, a reviewer is forced into a premature reject that the re-review
trigger then has to undo.

A deferred item is hidden from the default queue until coverage passes the recorded
threshold or member count grows, then resurfaces automatically.

**A deferred item does not block its gate.** The spec above says the item stays `open`,
and Part D says open items mean `AWAITING_APPROVAL`; read together those would hold the
job open indefinitely on a cluster someone consciously set aside, which is exactly the
premature-reject pressure `defer` exists to remove. So the blocking test is *open and not
deferred*. The gate completes; the deferral resurfaces later through the same reopen path
a re-review uses. This is what "reopen" in Part D's execution logic means — clearing the
deferral, not changing `status`, which never left `open`.

A deferral must name a threshold. One with neither `until_coverage` nor
`until_member_count` is indefinite silence rather than a decision about timing, so the
API rejects it (422) and a CHECK constraint refuses it in the database.

### Merge does not auto-edit

`merge_into_pattern` records the decision and links the cluster. It **does not**
modify the target pattern's rules automatically.

Widening a pattern to absorb a cluster changes classification for every project
already matching it, across every engagement — the pattern is master-catalog, client-agnostic. That is a catalog edit deserving its own review, not a side effect of a
queue action.

Instead, merge produces a **proposed rule amendment**: the signals present in the
cluster but absent from the pattern's current rules, rendered as a suggested diff in
the rule builder, which the human applies explicitly. The cluster is marked `merged`
either way, since the decision about *what it is* has been made.

### Create pattern

Pre-populate the rule builder from the cluster:

- `anchor_signals` — the signature's signals, ranked by how rarely they appear
  elsewhere in the engagement. A signal on 90% of projects is a poor anchor
- `all` group — signals present on **every** member
- `supporting` — signals present on some members, weight scaled by prevalence
- `metadata` — facet values from the signature
- `thresholds` — **derived, not a fixed default.** Part E scores a match as base 50
  plus supporting weight capped at 50, so a draft whose signals are all universal has
  an empty `supporting` group and can never score above 50. Defaulting `minimumScore`
  to 70 emits a pattern that is structurally incapable of matching anything —
  including the cluster it came from, which is the one thing it is guaranteed to
  describe. The draft therefore sets `minimumScore` to `min(70, achievable)` and says
  so in its notes. Every single-member cluster hits this, and so does any cluster whose
  members happen to share their whole signature
- `rules_status` — `draft`, never `active`. It must be reviewed and promoted
  deliberately

After creation, offer to re-run classification for the engagement so the reviewer sees
immediately whether the new pattern captures its cluster. This is the loop that makes
discovery converge, and it needs no rescan — classification reads stored fingerprints.

---

## Part D — Step behaviour

### Registration

```yaml
step_name: pattern-validation
lifecycle_step_no: 6
display_name: "Pattern validation"
owner_code: H
version: "1.0.0"
implementation_status: implemented

consumes:
  - artifact_type: pattern-candidate-clusters
    version_range: "^1.0.0"
    optional: true
  - artifact_type: pattern-candidate-narration
    version_range: "^1.0.0"
    optional: true

produces:
  - artifact_type: pattern-validation-decisions
    artifact_version: "1.0.0"

adapter_type: python
adapter_config:
  entrypoint: "app.steps.pattern_validation:run"

gate:
  type: api
  resume_trigger: "validation_queue_cleared"

restart:
  allow_start_if_complete: true
  start_limit: 20
```

Both inputs `optional: true` — this is what makes step 5 genuinely skippable. With
step 5 stubbed or disabled by policy, step 6 finds no clusters and returns `NOOP`.

That required a runtime change, because `optional` was honoured only by the *validator*
(rule 9 lets an optional entry go unwired) and ignored by the resolver: a wired input
that failed to resolve raised `StepInvocationError` regardless. An optional input that
cannot survive its producer being stubbed is not optional. The resolver now omits it from
`inputs` and records the miss in `inputs_resolved` with `resolved: false` and a reason —
"we looked for it and it was not there" is exactly the evidence docs/20 Part A wants
visible, and is very different from the input never having been wired.

Step 6 reads cluster *state* from the database rather than from the artifact, because
status, `needs_rereview` and `is_stale` are authoritative there and the artifact is a
snapshot. The artifact's absence is the signal that step 5 did not run; the absence of
clusters is what makes the step a `NOOP`. Both can be true at once, and a run where the
artifact is absent but clusters remain from an earlier run still applies any decisions
made in the meantime.

`allow_start_if_complete: true` with a high `start_limit`: a gate may be resumed many
times as decisions trickle in.

In-process `python` adapter, unlike steps 2, 4 and 5 — it reads and writes platform
tables and does no analysis, so a separate process buys nothing.

**A gate step runs inside the engine's transaction.** It writes `validation_queue` rows
that foreign-key `wf_job_executions` and `wf_step_executions` — rows the engine has
flushed but not committed. From a separate session those do not exist yet and the insert
fails on the foreign key, which is what happened the first time this ran. The `python`
adapter therefore hands its step the engine's own `Session` when the entrypoint declares
a `session` parameter; steps that open their own session, like `repository-ingest`, are
untouched because they only write already-committed rows.

The corollary is that **a gate step must never commit**. The engine owns the transaction
boundary, and committing mid-job would publish a partially-run execution. It is also the
better semantics: if a later step fails, the questions this step raised roll back with
it, rather than stranding a queue pointing at an execution nobody can see.

This applies to steps 22, 38 and 50 equally — every gate raises items keyed to its own
execution.

### Execution logic

```
1. Resolve the clusters artifact. Absent or empty  → NOOP
2. For each cluster with status 'candidate' or needs_rereview:
     - open item exists                             → leave it
     - decided item exists, subject unchanged       → skip
     - decided item exists, subject materially changed
       (member_count crossed the re-review trigger) → supersede, raise new
                                                       with is_rereview true and
                                                       previous_decision populated
     - deferred, threshold now met                  → reopen
     - no item                                      → raise
3. Withdraw open items whose cluster is now stale (member_count 0)
4. Apply decided outcomes to pattern_candidate_clusters, recording
   decided_at_coverage and decided_at_member_count
5. Emit pattern-validation-decisions
6. Open items remain → AWAITING_APPROVAL
   Otherwise                                        → COMPLETED
```

Step 6 **applies** decisions to the cluster table rather than the UI writing them
directly. The queue records the human's answer; the step is what acts on it. That keeps
the decision auditable to a specific job execution and means a decision made while no
execution is running is picked up on the next resume.

### Artifact

`pattern-validation-decisions@1.0.0` — deterministic: cluster id, outcome, resolved
pattern, decided by, decided at, coverage at decision, whether it was a re-review. It
is the audit record of what a human decided and on what evidence.

Decision timestamps and reviewer names are content, not volatile — the artifact is
*about* them. Two runs with no new decisions produce identical checksums.

---

## Part E — API

Generic across gate types:

```
GET   /api/engagements/{eid}/validation-queue     ?status=&item_type=&step_name=
GET   /api/validation-queue/{id}
POST  /api/validation-queue/{id}/decide           { outcome, outcome_detail, note, decided_by }
POST  /api/validation-queue/{id}/defer            { until_coverage, until_member_count, note }
GET   /api/engagements/{eid}/validation-queue/summary
```

Step 6 specific:

```
POST /api/engagements/{eid}/pattern-candidates/{cluster_id}/create-pattern
POST /api/engagements/{eid}/pattern-candidates/{cluster_id}/merge-proposal
```

`create-pattern` returns a pre-populated **draft** pattern for the rule builder, not a
persisted pattern. `merge-proposal` returns the suggested rule diff.

Deciding an item does **not** resume the job — resume is explicit, via the existing
execution endpoint, or automatic when the queue empties if
`gate.resume_trigger` is wired. Keep them separate so a reviewer working through
twenty items does not trigger twenty resumes.

---

## Part F — UI

Two surfaces, because two different people need them.

### Pending approvals — Workflow tab

The cross-cutting queue. Every open item across all gate types, grouped by step, with
item type, title, age, priority, and the job execution it blocks. Steps 22, 38 and 50
appear here later with no further work.

An execution in `STOPPED / AWAITING_APPROVAL` shows how many items block it and links
through.

### Pattern Candidates tab

Extend the existing tab from the step 5 work with decision actions.

Per cluster card: suggested name with its `suggested · confidence` badge, or
"Unnamed shape" with the signature; member and repository counts with the distribution;
cohesion, shown as a warning below ~0.6; the signature as signal chips; similar
patterns with their scores; sample member paths linking to project detail.

**Coverage context is mandatory on every card**, not tucked in a detail panel:

> Decided on partial evidence — 12 of 50 repositories scanned (24%)

Four actions: Create pattern, Merge into existing, Reject, Defer. Reject and defer
require a note. Merge requires selecting the target pattern, defaulting to the top
proximity match.

Re-review items render distinctly, showing the previous decision, the evidence then,
and the evidence now:

> Previously rejected at 24% coverage with 2 members. Now 30 members across 15
> repositories.

Singletons collapse into a separate "Single-occurrence shapes" section, expanded on
demand. They are not patterns yet and should not dominate the view.

### As built

Pending approvals sits **above** the jobs list on the Workflow tab, not below the
execution history: a held gate is the one thing on that page that needs a person, and
burying it is how it gets missed at fleet scale. Its labels cover all five gate item
types, including the three whose steps do not exist yet — a label table that only knew
about step 6 would quietly undo Part A's "steps 22, 38 and 50 appear here with no
further work".

The merge-target selector excludes `PROJECT_ROLE` and deprecated patterns. A discovered
application shape cannot merge into `role-library-project`, and offering it is offering
a choice that cannot be right. This needed `classification_role` on `PatternSummary`,
which the list endpoint did not previously return — filtering on an `id` prefix would
have been a convention masquerading as a rule.

Coverage is rendered from the item's `coverage_at_raise`, not from today's coverage.
The reviewer needs to know what the evidence looked like for *this* question; a card
that silently updated to current coverage would misrepresent what was being decided on.

---

## Part G — Acceptance criteria

- [x] `validation_queue` is generic across item types, with the partial unique index
      on open items
- [x] Step 6 returns `AWAITING_APPROVAL` with open items; execution ends `STOPPED`
- [x] Resume creates a new execution; step 5 is carried forward and does not re-cluster
- [x] All items decided → resume completes the step
- [x] Some items decided → resume returns `AWAITING_APPROVAL` again
- [x] Both inputs optional: with step 5 stubbed, step 6 returns `NOOP`
- [x] With step 5 disabled by engagement policy, step 6 still returns `NOOP` — step 5
      records `SKIPPED` with `skip_reason: POLICY_DISABLED_ENGAGEMENT`
- [x] `create_pattern` pre-populates the rule builder with anchors ranked by rarity,
      an `all` group of universal signals, weighted supporting signals, and
      `rules_status: draft`
- [x] A created pattern is never auto-activated
- [x] Re-running classification after creating a pattern captures its cluster, with no
      repository rescan — demonstrated end to end: draft → persist → promote → step 4
      alone → the cluster's member matched the new pattern
- [x] `merge_into_pattern` marks the cluster merged and produces a rule diff **without**
      modifying the target pattern
- [x] `reject` requires a reason and persists across re-runs
- [x] `defer` hides the item until its coverage or member threshold is met, then
      resurfaces it
- [x] A decided cluster crossing the re-review trigger supersedes its item and raises a
      new one with `is_rereview` and `previous_decision`
- [x] A cluster whose members all disappear withdraws its open item
- [x] `decided_at_coverage` and `decided_at_member_count` are recorded on decision
- [x] Coverage context appears on every card, not only in detail
- [x] Cohesion below 0.6 renders as a warning
- [x] Deciding an item does not implicitly resume the job
- [x] Pending approvals lists items across gate types and links to blocked executions
- [x] Two runs with no new decisions produce identical decisions-artifact checksums
- [x] Re-review items render the previous decision, the evidence then and the evidence now
- [x] Singletons collapse into their own section rather than dominating the view
- [x] The merge-target selector offers only patterns a cluster could actually merge into
- [x] A draft's `minimumScore` is reachable by the rules it generates
