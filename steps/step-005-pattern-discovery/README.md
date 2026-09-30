# Step 5 — pattern discovery clustering

Groups projects step 4 could not classify into candidate patterns, so a human at step 6
can decide whether each is a new catalog pattern, an extension of an existing one, or out
of scope. Spec: `docs/26-STEP-005-PATTERN-DISCOVERY.md`.

## Running it

```powershell
Get-Content sample-context.json | .venv\Scripts\python.exe main.py
```

Regression corpus — synthetic fixtures, no database:

```powershell
.venv\Scripts\python.exe main.py --corpus
```

`--write-expected` reseeds `corpus/expected/`. Do that only when a change to the expected
output is the point of the change; otherwise a real regression writes itself into the
baseline.

## The corpus is load-bearing here

With current samples step 5 finds almost nothing — eShopModernizing has zero unmatched
projects and eShopOnWeb has three single-project shapes. **Synthetic fixtures are the
only real test until a client estate exists**, so they carry more weight than in previous
steps. `--corpus` also runs two check suites that are not per-fixture:

- **determinism** — two runs produce identical bytes, *and* the clusters artifact is
  byte-identical with narration on and off.
- **rereview** — the multiplier, the floor, flag persistence and coverage-independence of
  the re-review trigger, table-driven at the boundaries.

## Narration

Optional, LLM-produced, and kept off the verification path. It runs after the
deterministic artifact is serialised and checksummed, writes a separate file, and no
narration value is an input to `build_clusters_artifact()`.

`enable_narration: false` in `config/discovery-config-*.json` skips it entirely. That is
the switch to reach for when debugging determinism — but note the corpus already asserts
narration cannot affect the clusters artifact, so if a checksum moved, narration is not
why.

Narration failures never fail the step. A missing CLI, a timeout, a bad model, an
unparseable response or a cluster the model skipped all degrade to
`naming_source: "none"` plus a `diagnostics` warning, with the clusters artifact
unchanged. To verify that by hand, point `narration.command` at a binary that does not
exist and confirm the step still exits `COMPLETED` with the same checksum.

**What the model is allowed to see is an allowlist**, in `_cluster_payload()`. Adding a
field to the cluster dict elsewhere in this step does not silently start sending it. If
you extend that payload, the question to answer first is whether the new field is a
classification — `similar_patterns` is withheld for exactly that reason, and the
reasoning is in `narration.py` and in the spec's Part E.

## Things that look like bugs and are not

- **A singleton is still a cluster.** A one-off is not a pattern, but it is something a
  human should see, and it keeps its `cluster_id` if it gains members later.
- **A chained cluster has low cohesion rather than being split.** Connected components
  chains by design; Part C's decision is to record the weakness where the human can see
  it, not to hide it behind a stricter linkage.
- **Clusters are never deleted.** A cluster whose members all disappear is retained with
  `member_count` 0 and `is_stale: true`, because the step 6 decision attached to it is
  history worth keeping — and when members disappear because the projects finally
  classified, the disappearance is the success.
- **`cluster_id` repeats across unrelated fixtures.** It is a hash of the shape, not of
  the membership. Two fixtures with the same signals and facets *should* produce the same
  id; that is the accumulation mechanism working.
