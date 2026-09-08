# Step 4 — Pattern classification against catalog

Classifies each project in a repository against the active pattern catalog.
Spec: [`docs/24-STEP-004-CLASSIFICATION.md`](../../docs/24-STEP-004-CLASSIFICATION.md).
Python, invoked through the `process` adapter, with its own virtualenv.

The catalog is read **live from the database**, so a rule edit takes effect on the
next run with no rescan.

## Run

Via the engine (normal path) — `StepContext` JSON on stdin, `StepResult` on stdout:

```bash
Get-Content sample-context.json | .venv/Scripts/python.exe main.py
```

Regression corpus, against frozen fingerprint fixtures instead of the database:

```bash
.venv/Scripts/python.exe main.py --corpus
```

## Probing a pattern

**Use `probe.py`. Do not hand-write a signal set.**

Asking "what would match a project shaped like pattern X?" is a common thing to want —
when authoring a rule, when a classification looks wrong, when checking that two
patterns actually separate. The obvious way to do it is wrong in a way that looks
like a catalog bug:

> Required conditions alone score `base_score` **50** (Part E). Most patterns set
> `thresholds.minimumScore` to 60–70. So a hand-built project covering exactly the
> `all`/`any`/`atLeast` conditions scores 50, reports `matched: false`, and the
> project reports `NO_PATTERN_MATCHED` — and the reader concludes the rules are
> broken when the harness was simply under-supplying supporting evidence.

That happened during the eShopPorted investigation and produced three wrong-looking
results in a row. `probe.py` exists so it cannot happen again:

```bash
# One pattern: builds a project that should match it, and explains it if it doesn't
.venv/Scripts/python.exe probe.py aspnetcore-rest-api-legacy

# Every active PRIMARY pattern: reports one-directional exclusions
.venv/Scripts/python.exe probe.py --audit
```

`build_project()` satisfies the required conditions **and** adds supporting
conditions in descending weight until the score clears that pattern's own threshold,
never adding anything from the pattern's own `none` list. The result reports
`projected_score`, what supporting weight it added, and
`supporting_weight_available`.

When the target pattern still does not match, `probe()` names which of four distinct
reasons applies rather than reporting a bare non-match:

| Reason | What it means |
|---|---|
| `disqualified at the '<group>' group by rule '<id>'` | A real rule failure — the interesting case |
| `INSUFFICIENT SUPPORTING WEIGHT, not a rule failure` | Every required condition passed; the score just did not clear the threshold. It also says whether the pattern *can* reach its own threshold from available supporting weight — if not, that is a catalog problem, not a probe problem |
| `role-excluded` | `project_role` is in `eligibility.excludedProjectRoles` |
| `a required analysis capability was unavailable` | `analysis_requirements.required` not met by the fingerprint |

### `--audit`

Builds each active PRIMARY pattern's canonical project and reports any *other*
pattern that also matched it. A co-matcher means the exclusion between the two is
one-directional or absent, which Part C forbids — mutual exclusion must be declared
on both patterns, because relying on one out-scoring the other is not separation.

The audit sweeps `frameworkFamily` across step 2's enum for any pattern that declares
no family condition, since a pattern with no family condition is claiming to be
family-agnostic. This matters: without the sweep the audit is blind to the exact bug
it exists to catch — probing with `frameworkFamily: null` accidentally shields the
project from family-bound poachers like `fx47-class-library`, which requires
`net-framework`. Patterns pinned to a `structuralType` are exempt from the sweep,
because their project type decides what framework they can have at all (an SSIS
`.dtproj` has no `TargetFramework`, so step 2 records a null family for one).

**Run `--audit` after any rule edit.** A clean run is not proof of correctness —
verify the audit still goes red for a bug you reintroduce on purpose before trusting
a green one.

## Layout

```
main.py         process-adapter entry point, artifact writing, persistence
probe.py        pattern probing and the exclusion audit (above)
corpus.py       --corpus mode: frozen fixtures, diffed against expected/
db.py           catalog/project/signal loading, result persistence
engine/
  classify.py   per-project orchestration: role, candidates, conflicts, status
  rules.py      rule-group evaluation and scoring (Part C operators, Part E)
  confidence.py the confidence formula and its factors
  role.py       project-role first pass (Part D)
  coverage.py   catalog governance metrics
  registry.py   active signal-registry resolution
config/         classification-config-*.json — every coefficient, versioned
corpus/
  fingerprints/ frozen per-project inputs, incl. hand-built `synthetic/` cases
  expected/     baselines; refresh with `python corpus.py --write-expected`
```
