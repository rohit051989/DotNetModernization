# 26 — Step 5: Pattern Discovery Clustering

Lifecycle step 5. Owner: **P + S**. Job: `phase0-estate-consolidation`.
Implemented in **Python**, invoked via the `process` adapter.

Groups projects the catalog could not classify into candidate patterns, so a human at
step 6 can decide whether each is a new catalog pattern, an extension of an existing
one, or out of scope.

---

## Part A — Design decisions

### A1. Engagement-wide clustering, per-repository distribution recorded

Clustering runs across **every in-scope repository in the engagement**, not per
repository.

A pattern is by definition recurring. Clustering per repository means a client-specific
framework appearing once in each of fifty repositories produces fifty single-member
groups and discovers nothing — and that case is the highest-value discovery available.
Migration execution being repository-scoped is a separate concern: you act on a
pattern, and patterns live in a client-agnostic catalog.

Every cluster records `repository_distribution` — member count per repository — so the
repo-by-repo view survives. A cluster spanning many repositories is a stronger pattern
candidate than one concentrated in a single repository, and that should be visible.

Config `clustering_scope` accepts `engagement` (default) or `repository` if this needs
revisiting.

### A2. Two artifacts: deterministic clusters, separate narration

Clustering is deterministic. Naming is not. They must not share a checksum.

- **`pattern-candidate-clusters@1.0.0`** — clusters, members, signatures, cohesion.
  Fully deterministic, checksum-asserted.
- **`pattern-candidate-narration@1.0.0`** — suggested names and descriptions keyed by
  cluster id. LLM-produced, **not** checksum-asserted.

This keeps the verification-path principle intact and matches the split already used
for step 7's graph versus context map: different reliability profiles, different
artifacts, different status.

#### "Not checksum-asserted" does not mean "no checksum"

**The narration artifact carries a checksum, and `metadata.deterministic: false`
alongside it. Do not "correct" this back to omitting the checksum.** That reading of the
sentence above was tried and it does not work: `StepOutput.checksum` is a required field
with `extra="forbid"`, so a step returning an output without one fails validation and the
whole job fails. It reproduces in one line against the contract model:

```
1 validation error for StepResult
outputs.1.checksum
  Field required [type=missing, ...]
```

That is the whole job `FAILED`, not a warning. The step execution never records its
outputs, so the deterministic clusters artifact is lost along with it — over a field that
costs nothing to populate.

Weakening the contract to make `checksum` optional would be the wrong repair. It is
required for good reason on every other artifact in the platform, and a step-5 detail is
no justification for making a platform-wide guarantee optional.

The distinction the split actually protects is **what a verifier does with the checksum**,
not whether one exists:

| | clusters | narration |
|---|---|---|
| Checksum | present | present |
| `metadata.deterministic` | absent (true by default) | `false` |
| A change means | the artifact was tampered with, or the clustering genuinely changed | the model worded a suggestion differently — expected, not a finding |

Recording the hash of a file is ordinary provenance: it tells you *which* narration you
are looking at. What must never happen is the two artifacts sharing a checksum, because
then a reworded suggestion would invalidate the deterministic artifact — and that is the
whole reason these are two artifacts rather than one. `metadata.deterministic: false` is
the flag a verifier reads to tell the two apart.

Narration is optional. With it disabled, clusters carry no names and step 6 shows
signatures instead. Nothing downstream depends on a name.

### A3. Reads from the database, declares no `consumes`

Step 5 is engagement-scoped but its inputs are per-repository artifacts produced by a
*different job*. The `${artifacts.x}` mechanism resolves within one job, so it cannot
reach them.

Step 5 therefore declares no `consumes` and reads `project_classifications`,
`fingerprint_signals` and `projects` directly, which spec 11 already permits. It reads
whatever classification data exists at the moment it runs, and reports what that was
(A5).

To preserve lineage, record in the output the `step_execution_id` of the classification
run that produced each member's status. Provenance survives even though artifact
resolution does not apply.

### A4. Eligibility

| Status | Eligible | Why |
|---|---|---|
| `NO_PATTERN_MATCHED` | **Yes** | The core discovery queue |
| `AMBIGUOUS` | **Yes** | Recurring ambiguity usually means a missing discriminating pattern, not a tie |
| `INSUFFICIENT_FINGERPRINT` | **No** | Analysis failed. Clustering broken scans invents phantom patterns |
| `MULTIPLE_MATCHES` | **No** | Working as designed — the project genuinely holds two patterns |
| `MATCHED`, `NOT_ELIGIBLE`, `SKIPPED`, `CLASSIFICATION_FAILED` | **No** | |

The `INSUFFICIENT_FINGERPRINT` exclusion is the one that matters. It is why step 4
separates that status from `NO_PATTERN_MATCHED` at all.

### A5. Clustering runs on a partial estate; it does not wait for a complete one

**There is no precondition that every in-scope repository has completed discovery.**
An earlier draft required one. At fleet scale it is not a condition that can be met:
repositories are registered over weeks, rescans run continuously, and at any instant
some repository is mid-discovery or failed. A precondition of estate completeness makes
step 5 unlaunchable in exactly the estates it exists for, and the one estate where it
*would* be satisfiable — three repositories, all scanned this morning — is the estate
with nothing to discover.

Clustering degrades gracefully instead. A pattern is a recurring shape; seeing it in six
of fifty repositories still tells you it recurs. More repositories sharpen the evidence,
they do not change its kind.

So step 5 runs whenever it is launched, over whatever has classification results, and is
**honest in the artifact about what it saw**. Every clusters artifact carries a coverage
block in its summary:

| Field | Meaning |
|---|---|
| `repositoriesInEngagement` | In-scope, non-deleted repositories in the engagement |
| `repositoriesIncluded` | Those with classification results this run could read |
| `repositoriesPending` | The remainder — never discovered, mid-discovery, or failed |
| `coverageRatio` | `repositoriesIncluded / repositoriesInEngagement`, 3 dp |
| `partialEstate` | `true` when `repositoriesPending > 0` |

`partialEstate: true` is not a warning state. It is the expected state, and it is
recorded so that a human at step 6 — and the re-review trigger below — can tell how much
of the estate a cluster was measured against. A cluster of three members at coverage 0.10
and one at coverage 1.00 are different pieces of evidence, and the artifact must not
flatten that distinction.

When `repositoriesIncluded` is 0 the step is `NOOP`, with a message naming the pending
repositories rather than a generic empty result.

---

## Part B — Structural signature

### Core signature

The **sorted set of distinct signal names** present on the project. Presence, not
occurrence count — a project with three `HTTP_GET_ATTRIBUTE` occurrences and one with
twenty are the same shape.

Signals with `extraction_confidence` below `min_signal_confidence` (default 0.5) are
excluded, so low-confidence noise does not drive clustering.

### Facets

Recorded alongside, and used as grouping constraints:

| Facet | Source |
|---|---|
| `project_role` | Step 4 |
| `framework_family` | Step 2 |
| `output_type` | Step 2 |
| `structural_type` | Step 2 |

Framework **version** is deliberately excluded, per the established principle: family
discriminates, version parameterises. Two projects differing only in patch version are
the same shape.

`facet_mode` config: `strict` (default — all facets must agree for two projects to
cluster) or `signals_only`.

### Cluster identity

```
cluster_id = sha256(canonical_signature)[:12]
canonical_signature = json({facets, signals}, sorted keys, sorted arrays)
```

Derived from the **shape**, not from membership. So the same shape in a later scan
yields the same id, and a cluster can be tracked across runs as repositories are added.
This is what lets step 6's decisions persist rather than being re-asked every scan.

For similarity clusters, canonical signature is the **intersection** of member signal
sets — the shape they share.

---

## Part C — Clustering

Two passes, both deterministic.

### Pass 1 — exact grouping

Group projects with identical core signature and identical facets. Cheap, exact,
always computed. `cluster_method: "exact"`, cohesion 1.0.

### Pass 2 — similarity grouping

Exact grouping only finds identical shapes, and real estates are messy — two WinForms
apps where one also touches MSMQ land in separate groups, fragmenting a real pattern.

Similarity uses **Jaccard** on signal name sets:

```
J(A,B) = |A ∩ B| / |A ∪ B|
```

Deterministic, no vectors, no ML, and directly explainable to a human: *"these two
projects share 8 of 11 signals."*

Algorithm: build a graph over eligible projects, edge where `J >= similarity_threshold`
(default 0.70) **and** facets agree under `facet_mode`. Take connected components.

Connected components is fully deterministic and order-independent. Its weakness is
chaining — A similar to B, B to C, A not to C, all in one cluster. Rather than adopt a
more restrictive linkage, **record it**: each cluster carries `cohesion`, the minimum
pairwise Jaccard among its members. Low cohesion is visible to the human at step 6
rather than hidden by the algorithm.

Exact groups are collapsed into similarity clusters where they qualify; a cluster
records `cluster_method: "exact" | "similarity"`.

### Singletons

Projects in no cluster of size ≥ `min_cluster_size` (default 2) are recorded as
clusters with `is_singleton: true`. A one-off is not a pattern, but it is still
something a human should see — and a singleton today may gain members when the next
repository is scanned.

### Existing-pattern proximity

For every cluster, compute Jaccard between its signature and the signal set referenced
by each **active** catalog pattern. Report the top three above
`proximity_threshold` (default 0.40) as `similar_patterns`.

This directly feeds step 6's "merge into existing pattern" action — the human sees
*"this cluster is 0.62 similar to `console-batch-job`"* rather than deciding blind. It
also surfaces the case where a cluster exists only because an existing pattern is
slightly too narrow, which is the most common real cause.

---

## Part D — Data model

**Not replaced wholesale per run.** Clusters accumulate — see "Cluster accumulation
across runs" below. Membership and counts are refreshed; identity, history and step 6's
decisions survive.

### `pattern_candidate_clusters`

| Column | Type | Notes |
|---|---|---|
| `cluster_id` | `TEXT` PK | Deterministic hash of canonical signature |
| `engagement_id` | `TEXT` NOT NULL FK | |
| `cluster_method` | `TEXT` NOT NULL | CHECK IN (`exact`, `similarity`) |
| `canonical_signature` | `JSONB` NOT NULL | Facets plus shared signal names |
| `signal_count` | `INTEGER` NOT NULL | |
| `member_count` | `INTEGER` NOT NULL | |
| `repository_count` | `INTEGER` NOT NULL | |
| `repository_distribution` | `JSONB` NOT NULL | `{repository_slug: member_count}` |
| `cohesion` | `NUMERIC(4,3)` | Minimum pairwise Jaccard. 1.0 for exact |
| `is_singleton` | `BOOLEAN` NOT NULL DEFAULT false | |
| `similar_patterns` | `JSONB` | Top proximity matches with scores |
| `status` | `TEXT` NOT NULL DEFAULT `'candidate'` | CHECK IN (`candidate`, `validated_new`, `merged`, `rejected`) — set by step 6 |
| `resolved_pattern_id` | `TEXT` FK → `patterns.id` | Set when validated or merged |
| `resolution_note` | `TEXT` | |
| `decided_at_coverage` | `NUMERIC(4,3)` | `coverageRatio` at the moment step 6 resolved this cluster |
| `decided_at_member_count` | `INTEGER` | `member_count` at that same moment |
| `needs_rereview` | `BOOLEAN` NOT NULL DEFAULT false | Set by step 5 when the evidence has materially grown |
| `rereview_reason` | `TEXT` | Why, in words, naming both counts |
| `is_stale` | `BOOLEAN` NOT NULL DEFAULT false | Every member has disappeared; `member_count` is 0 |
| `first_seen_at` / `last_seen_at` | `TIMESTAMPTZ` | Preserve `first_seen_at` across runs |
| `step_execution_id` | `UUID` | The run that last refreshed this row |

**Step 6 decisions persist across runs.** A cluster whose `status` is `rejected` stays
rejected when the same shape reappears — otherwise every rescan re-asks questions a
human already answered. Membership and counts refresh; status and resolution do not.

### `pattern_candidate_members`

`cluster_id` FK, `project_id` FK, `repository_id` FK, `classification_status`,
`similarity_to_signature` NUMERIC(4,3), `signal_count`,
`classification_step_execution_id` UUID (lineage per A3).

Unique on `(cluster_id, project_id)`.

### Cluster accumulation across runs

`cluster_id` derives from the **shape**, not from membership (Part B). That is the whole
mechanism: the same shape in a later run hashes to the same id, resolves to the same row,
and inherits everything that row already carries.

Each run, per cluster:

| | |
|---|---|
| **Refreshed** | `membership`, `member_count`, `repository_count`, `repository_distribution`, `cohesion`, `similar_patterns`, `signal_count`, `last_seen_at`, `step_execution_id` |
| **Preserved** | `first_seen_at`, `status`, `resolved_pattern_id`, `resolution_note`, `decided_at_coverage`, `decided_at_member_count` |

Upsert on `cluster_id`, never delete-then-insert. `pattern_candidate_members` *is*
replaced per cluster per run, since membership is a snapshot; the cluster row is not.

**A cluster whose members all disappear is retained, not deleted.** Set `member_count` to
0, clear the distribution, and set `is_stale: true`. Members disappear for ordinary
reasons — a repository was deregistered, or the projects finally classified because
someone added the pattern step 6 asked for — and in the second case the disappearance is
the *success*. Deleting the row would discard the step 6 decision that caused it, and a
`rejected` shape that reappears next quarter would be re-asked as if new. A stale cluster
is history, and history is the point of persisting decisions at all.

A stale cluster that regains members clears `is_stale` on the run that finds them, and
keeps its original `first_seen_at`.

### Decision context and re-review

Decisions at step 6 are made on partial evidence — that is A5's whole premise, so it has
to be handled rather than regretted. Record what the human could see at the time:
`decided_at_coverage` and `decided_at_member_count`, both written by step 6 when it sets
`status`.

Every subsequent run re-checks resolved clusters:

```
needs_rereview = member_count > max(decided_at_member_count * 3, min_rereview_members)
```

`min_rereview_members` defaults to 5. The floor exists because the multiplier alone is
useless at the bottom of the range: a singleton rejected at `member_count` 1 would trip
re-review at 4 members, which for a rejected one-off is noise. The multiplier handles
clusters that were already substantial; the floor handles the ones that were not.

`rereview_reason` states it plainly — *"rejected at 2 members, coverage 0.21; now 9
members across 6 repositories at coverage 0.68."*

**This is not automatic reversal, and must never be implemented as one.** The human
decided correctly on the information available; nothing about that decision has become
wrong. What has changed is the information. The system's only job here is to say so, and
to say it once per material change rather than nagging every run — clearing
`needs_rereview` is step 6's action, and re-deciding rewrites `decided_at_*` so the next
trigger is measured from the new baseline.

A cluster still at `status: candidate` is not re-reviewed; it was never decided, so there
is nothing to revisit.

---

## Part E — Narration

Separate, optional, LLM-produced.

Invoked via Claude Code headless with structured output. Per cluster, given the
signature, facets, a sample of member project paths and the proximity matches, it
returns:

```json
{
  "cluster_id": "a1b2c3d4e5f6",
  "suggested_name": "MSMQ integration library",
  "suggested_description": "Class libraries using System.Messaging to read and write MSMQ queues, with connection strings in app.config.",
  "suggested_pattern_id": "msmq-integration-library",
  "confidence": "medium",
  "naming_source": "claude-code",
  "model_version": "…"
}
```

Constraints:

- **Never sees, and never proposes, a classification.** It names a shape. Deciding
  whether that shape is a catalog pattern is step 6's job.
- Output is advisory. Step 6's UI must show it as a suggestion with an edit control,
  never pre-committed.
- `suggested_pattern_id` is a slug proposal only; step 6 validates it.
- Failure to narrate is **not** a step failure — emit the clusters artifact, warn, and
  set `naming_source: "none"`.
- Sends signal names, facets and paths. **No source code.**

Config `enable_narration`, default true. With it false the step is fully deterministic.

### How each constraint is enforced

Implemented in `steps/step-005-pattern-discovery/engine/narration.py`. Each constraint
above is a property of the code rather than a request made of the model, because a
constraint the model is merely *asked* to honour is not a constraint:

| Constraint | Mechanism |
|---|---|
| Never sees a classification | `_cluster_payload()` is an **allowlist** — the payload is assembled field by field, so a field added to the cluster dict elsewhere never starts being sent. `similar_patterns` is present on the cluster and deliberately withheld. |
| Never proposes a classification | The prompt forbids saying whether the shape should become a pattern, how it should be modernized, or what anyone should do; the response schema has no field that could carry one. |
| Advisory only | Narration runs **after** the clusters artifact is serialised and checksummed, writes a different file, and no narration value is an input to `build_clusters_artifact()`. |
| Failure warns | `narrate()` has no raise path. Every failure mode degrades to `naming_source: "none"` plus a `diagnostics` entry, and the step still exits `COMPLETED`. |
| No source code | Only signal names, facets and project **paths** are sent; no file is read. The CLI is additionally invoked with `--allowedTools ""`, so even if a path in the payload were read as an instruction to open a file, there is no tool to do it with. |
| `enable_narration: false` is deterministic | The caller skips the module entirely. |

**`similar_patterns` is withheld deliberately**, and the reason is worth stating because
it looks like useful context. Telling the model "this shape is 0.62 similar to
`console-batch-job`" is handing it a classification, which the first constraint forbids;
it would also bias the naming toward the existing catalog, defeating the point of
discovery. The cluster exists *because* the catalog did not cover it.

Everything the model returns is untrusted input. `_redact()` validates and coerces each
field — a bad `confidence` falls back to `"low"`, a malformed slug is re-derived from the
name, and a response missing a name or description is dropped to `naming_source: "none"`
for that cluster alone rather than failing the batch.

Narration failures surface as `diagnostics` (level `warning`), not as a bespoke
`warnings` field: `StepResult` forbids unknown fields, and `Diagnostic` is already
defined as "a per-item problem that should not halt the whole step — surfaces in the UI
without failing it", which is exactly this. A diagnostic is the right *contract* field
and is still not sufficient on its own, which is what the next section is about.

### `narration_status` — the run-level outcome

A step diagnostic alone is not enough. At fleet scale it is easy to miss, and a human
arriving at step 6 sees unnamed clusters with no indication why — which reads as *"the
platform has nothing to say about this shape"* when the truth may be *"the narrator could
not be reached"*. Those call for completely different actions, so the outcome is recorded
on the run and rendered beside the clusters.

| Status | Meaning |
|---|---|
| `succeeded` | Every cluster named. The quiet case; the UI shows no banner. |
| `partial` | Some named, some not. The narrator was reachable, so the reason is about the response rather than the connection. |
| `failed` | Narration ran and named nothing. |
| `disabled` | Switched off in config. Not a failure — the step is fully deterministic and step 6 shows signatures. |

`narration_reason` is null only when the status is `succeeded`; every other status owes
the human an explanation, enforced by a CHECK constraint on `pattern_discovery_runs`. It
is surfaced in four places, because the person who needs it is not always in the same
place:

- the step's `exit_message`, so a run that named nothing does not read as unqualified
  success in the workflow log
- `StepOutput.metadata` on the clusters output — **not** in the artifact body, see below
- `pattern_discovery_runs`, which is what the UI reads
- the narration artifact's own summary

**The status does not go in the clusters artifact summary, and must not.** It is not a
property of the clustering and it is not deterministic: a run with narration disabled and
one where it succeeded must still produce byte-identical clusters artifacts. Putting the
status in the summary would break that on the first narration failure, which is precisely
the invariant Part A2 exists to protect. `StepOutput.metadata` is where Part F already
says volatile fields go, and it is not part of the hashed content.

### Retry

`POST /api/engagements/{id}/pattern-candidates/retry-narration`, or
`main.py --retry-narration <engagement_id> --database-url <url>`.

Re-runs **narration only**, against the clusters already in the database. It cannot
change the clusters artifact or its checksum, because narration is not an input to it —
that independence is exactly what makes this safe to offer as a button rather than a
re-run of the step.

Re-clustering instead would be actively wrong: the estate may have been rescanned since,
so it could produce a *different* clustering and silently renumber shapes a human is
mid-review on. To re-cluster, launch `phase0-estate-consolidation`.

Retry deliberately ignores `enable_narration`. Asking for narration and being told it is
disabled in a config file you cannot see from the UI is not a useful answer.

A cluster whose `naming_source` is `human` is never overwritten by a later machine run,
whether from retry or from a fresh step 5. Once a person has named a shape, their words
stand.

### Where step 6 picks this up

`GET /api/engagements/{id}/pattern-candidates` returns every non-stale cluster with its
members, its advisory name and the run-level narration status. The **Pattern Candidates**
tab renders it: a banner carrying the status and reason whenever narration did not fully
succeed, with the retry action beside it, and each name badged `suggested` with its
confidence so it never reads as settled. Step 6 adds the decision actions to that same
surface; the review context is already there.

---

## Part F — Artifacts

### `pattern-candidate-clusters@1.0.0`

Deterministic: sorted keys, clusters sorted by `cluster_id`, members by project path,
volatile fields in `StepOutput.metadata`.

```json
{
  "artifactType": "pattern-candidate-clusters",
  "artifactVersion": "1.0.0",
  "engagementId": "client-a-ocp4",
  "catalogRevision": 291,
  "signalRegistryVersion": "1.3.0",
  "config": {
    "clusteringScope": "engagement",
    "similarityThreshold": 0.70,
    "minClusterSize": 2,
    "facetMode": "strict",
    "minSignalConfidence": 0.5,
    "minRereviewMembers": 5
  },
  "summary": {
    "coverage": {
      "repositoriesInEngagement": 12,
      "repositoriesIncluded": 5,
      "repositoriesPending": 7,
      "coverageRatio": 0.417,
      "partialEstate": true
    },
    "projectsTotal": 32,
    "projectsEligible": 6,
    "projectsClustered": 4,
    "projectsSingleton": 2,
    "clusterCount": 2,
    "singletonCount": 2,
    "largestClusterSize": 3,
    "staleClusterCount": 1,
    "needsRereviewCount": 1,
    "eligibilityBreakdown": { "NO_PATTERN_MATCHED": 5, "AMBIGUOUS": 1 }
  },
  "clusters": [
    {
      "clusterId": "a1b2c3d4e5f6",
      "clusterMethod": "exact",
      "canonicalSignature": {
        "facets": { "projectRole": "LIBRARY", "frameworkFamily": "net-framework",
                    "outputType": "Library", "structuralType": "csharp_project" },
        "signals": ["CONNECTION_STRING_CONFIG", "SYSTEM_MESSAGING_ASSEMBLY",
                    "SYSTEM_MESSAGING_NAMESPACE"]
      },
      "memberCount": 3,
      "repositoryCount": 2,
      "repositoryDistribution": { "legacy-orders": 2, "legacy-billing": 1 },
      "cohesion": 1.0,
      "isSingleton": false,
      "similarPatterns": [
        { "patternId": "fx47-class-library", "similarity": 0.43 }
      ],
      "members": [
        { "projectId": "…", "repositorySlug": "legacy-orders",
          "projectPath": "src/Integration/Integration.csproj",
          "classificationStatus": "NO_PATTERN_MATCHED",
          "similarityToSignature": 1.0, "signalCount": 3 }
      ]
    }
  ]
}
```

### `pattern-candidate-narration@1.0.0`

Keyed by `cluster_id`, **excluded from checksum assertion**, with `naming_source` and
model version recorded per entry.

---

## Part G — Step registration

```yaml
step_name: pattern-discovery-clustering
lifecycle_step_no: 5
display_name: "Pattern discovery clustering for unmatched applications"
owner_code: P + S
version: "1.0.0"
implementation_status: implemented

consumes: []

produces:
  - artifact_type: pattern-candidate-clusters
    artifact_version: "1.0.0"
  - artifact_type: pattern-candidate-narration
    artifact_version: "1.0.0"

adapter_type: process
adapter_config:
  command: ["steps/step-005-pattern-discovery/.venv/Scripts/python.exe",
            "steps/step-005-pattern-discovery/main.py"]
  timeout_seconds: 1800
```

Own virtualenv. Exit statuses: `COMPLETED` normally; `NOOP` with a clear message when
no eligible projects exist — a fully classified estate is a valid outcome, not a
failure; `FAILED` only on a genuine error. There are two distinct `NOOP` cases and they
say different things: no repository has classification results yet (the message names the
pending repositories), versus repositories were read and nothing in them was unmatched.

Narration failure is **not** among the `FAILED` cases. A run that clustered correctly and
named nothing is `COMPLETED` with `narration_status: failed` — see Part E.

Registered and running. It is the first implemented step of
`phase0-estate-consolidation`; the other four remain stubs, which is why that job keeps
`stub_policy: continue`.

---

## Part H — Testing

With current samples step 5 will find almost nothing — eShopModernizing has zero
unmatched projects and eShopOnWeb has two single-project shapes. **Synthetic fixtures
are the only real test until a client estate exists**, so they carry more weight here
than in previous steps.

Build a corpus with at least:

- Three projects sharing an identical signature across two repositories → one exact
  cluster, `repositoryCount: 2`
- Two projects at Jaccard ≈ 0.75 → one similarity cluster, cohesion below 1.0
- Two projects at Jaccard ≈ 0.45 → **two** singletons, proving the threshold holds
- A chaining case: A~B, B~C, A≁C → one cluster with visibly low cohesion
- Same signals, different `project_role` → two clusters under `facet_mode: strict`
- One `INSUFFICIENT_FINGERPRINT` project that must be **excluded**
- One cluster whose signature is close to an existing pattern → populated
  `similarPatterns`
- Zero eligible projects → `NOOP`

Accumulation and partial-estate cases, which no single-run fixture can cover:

- Run twice with a repository added between runs → same `cluster_id`, refreshed
  `member_count` and `repository_distribution`, `first_seen_at` unchanged
- Resolve a cluster `rejected`, then re-run with the same shape → still `rejected`
- Remove every member of a resolved cluster → row retained, `member_count` 0,
  `is_stale: true`, status intact
- Restore those members on a later run → `is_stale` cleared, `first_seen_at` still the
  original
- A cluster rejected at 2 members that grows to 9 → `needs_rereview: true` with a reason
  naming both counts; a singleton rejected at 1 that grows to 4 → **not** triggered
  (`min_rereview_members` floor)
- One repository in the engagement with no classification results → `repositoriesPending`
  1, `partialEstate: true`, clustering proceeds over the rest
- No repository with classification results → `NOOP` naming the pending repositories

Assert determinism: two runs over unchanged data, identical `pattern-candidate-clusters`
checksum, and identical `cluster_id` values. Coverage counts are part of the artifact and
therefore part of the checksum — unchanged data means unchanged coverage.

---

## Acceptance criteria

- [x] `phase0-estate-consolidation` defined and engagement-scoped, with **no**
      estate-completeness precondition
- [x] The clusters artifact summary carries the coverage block, and `partialEstate` is
      `true` whenever any in-scope repository has no classification results
- [x] No repository with classification results yields `NOOP` naming the pending ones
- [x] Step 5 registers with `consumes: []` and two declared outputs
- [x] Reads classification and signal data from the database; each member records its
      source classification `step_execution_id`
- [x] Only `NO_PATTERN_MATCHED` and `AMBIGUOUS` projects are eligible;
      `INSUFFICIENT_FINGERPRINT` is excluded and the exclusion count is reported
- [x] Exact grouping produces cohesion 1.0
- [x] Similarity grouping respects the threshold; a pair below it stays separate
- [x] Chaining produces one cluster with low cohesion, not a hidden merge
- [x] Facet disagreement separates clusters under `strict`
- [x] `cluster_id` is derived from shape and is stable across runs
- [x] Step 6 decisions persist: a `rejected` cluster stays rejected when the same shape
      reappears with refreshed membership
- [x] Clusters are upserted, never delete-then-inserted; `first_seen_at` survives
- [x] `needs_rereview` fires at `member_count > max(decided_at_member_count * 3,
      min_rereview_members)` with a reason naming both counts, and never reverses the
      decision itself
- [x] The clusters artifact is **byte-identical with narration on and off**, and
      unchanged when narration fails
- [x] `narration_status` is recorded per run as succeeded/partial/failed/disabled, with
      a reason on everything but `succeeded`
- [x] The status reaches the step message, the clusters output's `StepOutput.metadata`,
      the database and the narration artifact — and **not** the clusters artifact body
- [x] Unnamed clusters are shown with the reason they are unnamed, not silently
- [x] Retry re-runs narration against existing clusters without re-clustering, and
      leaves the clusters artifact checksum untouched
- [x] A `human` naming_source survives a later machine narration run
- [ ] Step 6 records `decided_at_coverage` and `decided_at_member_count` when it resolves
      a cluster — *pending step 6; the columns, the constraint requiring them on any
      resolved cluster, and step 5's use of them are in place*
- [ ] A cluster losing every member is retained with `member_count` 0 and
      `is_stale: true`, not deleted; regaining members clears the flag — *implemented in
      `db.upsert_clusters`, not yet exercised against a real estate*
- [x] `repositoryDistribution` is populated and a cross-repository cluster is visible
      as such
- [x] `similarPatterns` populated where a cluster resembles an active pattern
- [x] Narration is advisory, editable at step 6, and its failure warns rather than
      fails the step
- [x] With `enable_narration: false` the step is fully deterministic
- [x] No source code is sent to the model — signal names, facets and paths only
- [x] Two runs produce identical clusters-artifact checksums
- [x] Zero eligible projects yields `NOOP`
