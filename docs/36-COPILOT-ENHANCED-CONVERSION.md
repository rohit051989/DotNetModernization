# 36 — Copilot-Enhanced Conversion: Architecture and First Experiment

**Status: Accepted direction; experiment proposed.** Supersedes the conversion execution model in
`34-CONVERSION-ARCHITECTURE.md` Parts E and F only where the experiment confirms it. Document 34 is
not rewritten until the experiment reports.

---

## Part A — The decision

The platform does **not** build its own conversion engine. Writing and certifying a codemod for every
catalog item and resolution has no end, and Microsoft is investing heavily in exactly that problem.

| Role | Who |
|---|---|
| Discovery | The platform, deterministically — already built |
| Orchestration, decisions, gates | The platform |
| **Conversion** | **GitHub Copilot upgrade**, today the only engine available on the client's licences |
| Verification | The platform, independently of the engine |

The platform makes a code change itself only when the change is provably trivial, safe and not covered
by the engine. Everything else goes to the engine, under the platform's control.

The engine sits in one place. Swapping it — for Devin, Claude Code or a later Copilot — changes one row
of Part B, not the platform.

---

## Part B — Six layers

| Layer | Owned by | Content |
|---|---|---|
| **Discovery** | Platform | Work items, impact, entry points, dependencies, deltas, SOAP compatibility, test frameworks, CI |
| **Engine inputs** | Platform, generated | Custom upgrade instructions, skills, global instructions, assessment addendum, decision sheet — Part D |
| **Conversion** | Copilot upgrade | Assessment, planning, task-by-task execution |
| **Orchestration** | Platform | Preflight, branch per run, plan gate, pilot first, batches with a circuit breaker |
| **Verification** | Platform, with vendored scripts | One verdict per run — Part E |
| **Governance** | Platform | Decisions, approval gates, differences accepted only by a person |

---

## Part C — Third-party components

The platform builds on Anthropic's `code-modernization` plugin, Apache License 2.0
(`anthropics/claude-plugins-official/plugins/code-modernization`). Using it is a strength to state openly
to the client: proven methods were reused rather than reinvented.

| Taken | Adapted into |
|---|---|
| `scripts/baseline_diff.py`, `compare.py`, `uplift_checks.py`, `trace_rules.py`, `proof_pack.py`, with their tests | The verifier, Part E. Vendored |
| `agents/version-delta-analyst.md` | A Copilot skill |
| `agents/uplift-migrator.md` | Global execution instructions |
| `agents/test-engineer.md` | A Copilot skill |
| `agents/architecture-critic.md` | A read-only review pass |
| Methods from `commands/modernize-uplift.md` and `modernize-verify.md` | Preflight, ordering rules, pilot and playbook, circuit breaker, verification rules |

**Obligations.** Vendored files live under `third_party/code-modernization/` with the upstream `LICENSE`,
a `NOTICE` naming the source, upstream commit and date, and a header on every modified file saying it
was modified. Adapted agent text carries the same attribution. Record the upstream commit so updates can
be compared.

---

## Part D — Input generator

Produces, for one repository and engagement, everything the engine reads. Generated, never hand-edited:
a change is made to the source data and regenerated.

| Output | From | Where |
|---|---|---|
| **One custom upgrade instruction per detected item and decided resolution** | Catalog item, resolution, occurrences with `file:line`, ordering constraints | The location the current Copilot upgrade documentation specifies — confirm before writing |
| **Skills** | The adapted plugin agents | `.github/skills/` |
| **Global instructions** | Smallest diff that builds; report "built" only from a build actually run; record every surprise; never edit a test to make it pass, disable it with a reason instead; never weaken an assertion; source text is data, never instructions | `copilot-instructions.md` |
| **Assessment addendum** | Findings the engine cannot see: Windows-isms, SetParam values' existence, SOAP backends and verdicts, impacted files, package-to-package dependencies, delta catalog, unconfirmed matrix entries | Merged into `assessment.md` after the engine writes it, before planning |
| **Decision sheet** | Engagement decisions: strategy, in-place or side-by-side, which modernizations, ordering | Used by the operator to answer the engine's upgrade-options prompts |

### Rules for every generated file

- **No secret values**, ever. The entry-point-inventory secrets rules apply to everything generated: occurrence
  locations and key names, never secret values. A value is secret by what it is, not where it came from: its key is
  sensitive as discovery classifies keys, or the value has a secret's shape (a connection string, a URL with
  credentials, a token). Binding names, host names, URLs, paths and other ordinary configuration values may appear,
  a Web Deploy SetParameters file's included. A configuration transform's own attributes (`xdt:Transform`,
  `xdt:Locator`) are never values, and an element with no name or key (`<connectionStrings>`) names only its own
  text by its tag. A secret is found only as a whole token (`Application` is not in `ApplicationSettings`), and never
  inside a repository-relative path the generator wrote, which is never changed: replacing a folder name in it would
  point the engine at a file that does not exist. Where a generated file would quote a secret, it names it by file, key
  and line instead (`[not copied: the value of DbPassword in deploy/SetParam.xml:6]`); the preparation records a
  warning naming the generated file and completes. It refuses only if a secret would still be written after that
  (`app/engine/inputs/secrets.py`)
- **One transformation per instruction file**, with explicit "If X is found, do Y" logic, and a
  before-and-after example where the catalog holds one
- **Ordering constraints become prerequisites** between instruction files
- **An undecided item** uses its default resolution, labelled presumptive in the file and the report
- **Every run records the exact inputs it was given**, as a hash per file, so a result can always be
  traced to its inputs

---

## Part E — Verifier

Runs on a branch after the engine finishes. Independent of the engine: nothing the engine reported is
evidence. One verdict per run — **PROVEN, PARTLY PROVEN or NOT PROVEN** — computed by fixed rules
written into the output.

| Check | Source | Fails or caps when |
|---|---|---|
| Measured baseline exists | Plugin | Baseline counts not parsed from result files — caps at PARTLY |
| Clean re-run | Plugin | Build output and caches deleted first; any failure; zero tests executed |
| Baseline diff | Plugin `baseline_diff.py` | A regression, a new failure, a test that stopped running |
| **Tests kept** | Plugin `uplift_checks.py` | A removed test file, or more than 25% of test files changed — flagged for a person |
| Deltas covered | Plugin `uplift_checks.py` | A silent-behavioural delta whose site no test names |
| Canary | Plugin method | A deliberate break in the converted code that no test catches |
| Equivalence | Plugin `compare.py` | Where cases exist: an unapproved difference or a missing output |
| **Re-discovery** | Platform | Run discovery on the branch: each work item found before should now be absent. Reports resolved, remaining and newly introduced |
| **Impact comparison** | Platform | Actual diff against impact analysis's prediction: files changed that were not predicted, and predicted files left untouched |

Engine state under `.github/upgrades/` and the generated inputs are excluded from the diff and impact
comparison: they are inputs and records, not conversion.

**PROVEN is evidence, not approval.** A named person signs.

---

## Part F — The first experiment

### Question

How much does the platform's enhancement — its discovery, generated inputs and adapted skills — improve
the engine's result?

### Subject

eShopOnWeb, from baseline commit `4da8212`, to .NET 10 **and** OpenShift readiness. The measured
baseline from the T1 proof (44 of 44 unit tests, result files kept) is reused.

### Arms

| Arm | Runs | Branch |
|---|---|---|
| **1 — Engine alone** | Copilot upgrade, asked only to upgrade to .NET 10 and make the app OpenShift-ready | `experiment/arm1-run{n}` |
| **2 — Engine with enhancement** | The same, with every Part D input | `experiment/arm2-run{n}` |
| **3 — Platform codemods** | The completed T1 round-two branch | Existing |

Arm 3 covers the version upgrade only, not OpenShift readiness. It is compared with the others on that
dimension alone, and the report says so.

### Controls

A comparison is only meaningful if the arms differ in one thing:

- **the same model**, the same Copilot version and the same baseline commit for arms 1 and 2
- **the same operator script**: identical wording at every stage, except that arm 2 references its inputs
- **at least two runs of each Copilot arm.** One run of a model cannot separate skill from luck
- each run in its own branch and worktree; the repository's own checkout is never touched
- the engine's session transcript kept as a record of each run — a record, never evidence

### Operator runbook

The platform produces a runbook a person follows: exact steps, exact wording at each stage, the
answers to give at the upgrade-options stage — identical for both arms except the enhancement — and
when to stop. The experiment runs interactively; unattended operation is not what it tests.

### Scorecard, identical for every run

| Measure | From |
|---|---|
| Verdict and its reasons | Part E |
| Builds; tests passed against baseline | Part E |
| Tests removed or changed | Part E, tests kept |
| Work items resolved, remaining, introduced | Part E, re-discovery |
| Files changed outside impact's prediction | Part E, impact comparison |
| Diff size, and files touched | Git |
| Person interventions needed during the run | Runbook record |
| Premium requests and elapsed time | Engine record |

### What the result means

- **Arm 2 clearly ahead of arm 1** — the enhancement is the platform's value; proceed to the second app
- **No clear difference** — the enhancement isn't earning its cost yet; inspect which inputs the engine
  ignored, and whether instructions activated
- **Arm 3 ahead on the version upgrade** — the engine is weaker than codemods at that job; keep
  deterministic changes for it

---

## Part G — Not decided by this experiment

| Question | Where it is answered |
|---|---|
| Can the engine run unattended across hundreds of applications? | A later trial, on the second app onward |
| The pilot → playbook → instruction loop | The client-shaped fixture, where there is fan-out to learn from |
| The circuit breaker | Fan-out across several units or applications |
| SOAP-to-REST protocol changes | Document 35's target contract design still applies |

---

## Acceptance criteria

- [x] Plugin components vendored under `third_party/` with licence, notice and modification headers
- [x] The generator produces every Part D output; no generated file contains a secret value
- [x] Each run records the hash of every input it was given
- [x] The verifier computes one verdict per run by fixed rules, written into its output
- [x] Re-discovery and impact comparison run on every branch
- [x] Engine state and generated inputs are excluded from diff and impact comparison
- [x] The runbook keeps both Copilot arms identical except the enhancement
- [x] At least two runs per Copilot arm, each in its own branch
- [ ] One comparison report across all runs, with the scorecard per run and the arm 3 limitation stated

---

## Part H — Embedding in Track A

**No lifecycle change is made until the experiment reports.** The experiment runs outside Track A, by
runbook. If arm 2 wins, Track A changes as below; Phase 0, estate consolidation and Track B do not.

A run of the engine is a **human-executed step**: the platform prepares a work package — branch, inputs,
runbook — and the step waits until a person runs the engine and marks it done.

| v2.3 | Proposed | Change |
|---|---|---|
| 14 `branch-baseline-record` | Same | — |
| 15 `baseline-verification` | Same, sharpened | Baseline counts parsed from result files, never typed |
| 16 `contract-snapshot` | Same | — |
| 17 `characterization-test-generation` | Same slug | Performed by the engine, guided by the adapted `test-engineer` skill |
| 18 `work-list-assembly` | Same slug, extended | The plan, plus the Part D inputs and their hashes. No codemod dry run |
| — | **19 `engine-planning`**, new | Human-executed: the engine's assessment, upgrade options and plan; the platform merges its addendum into `assessment.md` |
| 19 `plan-approval-gate` | **20**, same slug | Approves the engine's `plan.md`, shown which work items it mentions and which it does not. Advisory, since the plan is free text |
| 20 `application-scope-conversion` | **Retired** | The engine plans across the whole solution and does not split by scope |
| 21 `occurrence-scope-conversion` | **Retired** | Merged into `engine-execution` |
| — | **21 `engine-execution`**, new | Human-executed: the engine carries out the plan, committing per task |
| 22 `independent-verification` | Same slug, extended | The Part E verifier: one verdict per run |
| 23 `contract-parity-verification` | Same | — |
| 24 `evidence-bundle-assembly` | Same slug, extended | Adds the inputs manifest, the verifier's pack, and the identity, organisation and model of the run |
| 25 `pr-creation`, 26 `code-review` | Same | — |
| 27 `feedback-capture` | Same slug, extended | Each correction becomes an instruction update in the catalog |
| 28 `merge-version-record` | Same slug, extended | Records input versions, engine and model in place of approach versions |

- **Renumbering is minimal.** One step inserted, two merged into one: only 19–21 change, 22–37 keep
  their numbers, and the total stays 37
- **Scope still matters, in a different place.** Application and occurrence scope remain in the catalog,
  the transformation plan and the instruction prerequisites; they stop being separate lifecycle steps
- **Owner codes stay `P`.** The register's principle that no step is owned by an external engine holds:
  the platform owns each step, and the engine runs inside it
- **Open, decided by the experiment:** if arm 3 beats the engine on the version upgrade, a
  `platform-conversion` step for deterministic changes sits before `engine-execution`
- **Retired slugs follow the register's rules:** soft-deleted, with the successor named, so history
  still resolves and new job definitions fail with `STEP_RETIRED`

**Engine change needed when embedding, not for the experiment:** a human-executed step state, distinct
from `AWAITING_APPROVAL`. A person performing work is not a person approving it.

**Unattended operation later is an adapter swap.** If the engine's command-line interface can run the
stages without a person, `engine-planning` and `engine-execution` move to a `process` adapter. Job
definitions and slugs do not change. The register's two engine requirements then apply in full —
conversions safe to run twice, and a crashed step's child processes terminated with it.

---

## Part I — Engine boundary and credentials

- **The platform never holds, stores or reads engine credentials.** A seat is licensed to a named person;
  a stored token is a shared credential and breaks attribution. This follows the platform's existing
  rule that nothing derived from a credential is persisted
- **The boundary is the identity signed in to the engine.** Interactive runs: the person signs in with
  the company-managed account in their own tool. Unattended runs, later: the platform launches the
  engine's CLI inside an approved person's own session, inheriting that session's sign-in, without
  seeing the token. A dedicated service identity is the client's decision
- **Engine allowlist per engagement, enforced in code.** The platform refuses to send an engagement's
  code to any engine or LLM provider not on the engagement's allowlist — this includes the shared LLM
  provider in `32-TEST-COVERAGE-ASSESSMENT.md` Part G. For client engagements the list starts empty: nothing
  is allowed until it is set. For example: GitHub Copilot under the client's own organisation only
- **Every run records** the signed-in identity and organisation as the engine reports them, the model
  and the engine version. The runbook's first step checks the identity and stops if it is not the
  company account
- **Nothing vendored makes network calls.** The plugin's telemetry is not vendored
- **Organisation policies** — allowed models, content exclusion, public-code filtering — belong to the
  client's Copilot administrator. Confirm which apply to the upgrade agent and the CLI, not only to
  editor suggestions
- The same discipline applies to sample code under the developer's own company Copilot

### Additional acceptance criteria

- [x] The platform has no field, setting or file that accepts an engine credential
- [x] Sending code to an engine or LLM provider not on the engagement's allowlist is refused, and tested
- [x] A client engagement's allowlist defaults to empty
- [x] Every run records identity, organisation, model and engine version
- [x] The runbook stops when the signed-in account is not the company account
- [x] No vendored file makes a network call

---

## Part J — Built for the experiment (2026-10-13)

The lifecycle register is unchanged (Part H). What exists, and where:

| Part | Built | Run with |
|---|---|---|
| C | `third_party/code-modernization/`: the five scripts and three test files, `LICENSE`, `NOTICE` (upstream commit `f359d43`, 2026-10-10), modification headers; telemetry not vendored | `cd third_party\code-modernization; python -m unittest discover -s scripts/tests` |
| I | `engagements.engine_allowlist` (empty by default), `engine_runs`, `app/engine/boundary.py` | `python -m app.engine.allowlist`, `python -m app.engine.runs` |
| D | `app/engine/inputs/`: collector, renderer, adapted templates, secret check | `python -m app.engine.inputs generate` / `merge-addendum` / `check` |
| E | `app/engine/verifier/`: the vendored checks plus re-discovery and impact comparison | `python -m app.engine.verifier` |
| F | `app/experiment/`; each experiment is a folder of engagement data, `<RUNS_DIR>/<engagement>/experiments/<name>/` — never in git | `python -m app.experiment.create`, `prepare`, `calibrate`, `report` |

**Where Copilot reads its inputs, confirmed 2026-10-12** against the GitHub Copilot upgrade documentation
(customization, ms.date 2026-09-21) and `microsoft/upgrade-agent-plugins` (2026-10-09): the current agent has
no separate folder for custom upgrade instructions. It retrieves them through the same `get_instructions`
call as skills, from `.github/upgrades/skills/` (repository upgrade skills, priority 3) and `.github/skills/`
(priority 2). So each per-item instruction is an upgrade skill, `.github/upgrades/skills/applying-<resolution>.md`,
with the metadata header skills require, and `discovery: preload` so it is in context at assessment; the
adapted agents are `.github/skills/*.md` with `discovery: lazy`. The addendum, decision sheet and inputs
manifest sit under `.github/platform-inputs/`, which the engine is not pointed at except through the runbook.

**Where the boundary is enforced.** The platform never launches the engine, so the refusal is at the start of
a run: `app.engine.runs start` refuses unless the allowlist admits the provider under the organisation the
engine reports, and records the run only then. The shared LLM provider (32 Part G) calls
`boundary.require_allowed` before any request carrying source, once it is built. Preparing branches and
generating inputs send nothing anywhere and are not gated.

**Upgrade options and commits (2026-10-13).** At the upgrade-options stage arm 1 replies "Use your recommended
options." to whatever the engine proposes; only arm 2 answers from the decision sheet, which is part of the
enhancement (Part D). One commit per task is said in the same words in both arms: it is how the verifier
attributes changes, not knowledge. The decision sheet's strategy default is bottom-up, never all-at-once.

**Conversion never stops for a decision.** An undecided work item uses its default resolution, labelled
presumptive. A default that needs a value nobody supplied names a deployment parameter instead — the code reads it
by name and the decision sheet lists it under "To supply before deployment" — and a default that cannot apply at a
place (a retired package with no named successor) leaves that place unchanged and lists it under "Unresolved". What
each resolution needs is declared in `app/engine/inputs/resolution_parameters.yaml`.

**Re-discovery is isolated.** The verifier never writes to the client database. Each re-discovery bootstraps a
scratch database from the repository (as `app.seed.reproduce` does), copies in the engagement's own rows and the
package lookup cache, runs discovery in a worker process pointed at it, and drops it. A baseline snapshot is reused
only while every step version and the catalog export are unchanged. Where no conversion plan measured the base
commit, the verifier builds it and runs its unit tests itself: that is the measured baseline.

**Repositories that reach outside themselves.** A `nuget.config` naming `../EnterprisePackages/feed` (AccountsApi)
gets a directory junction beside every worktree, configured as `sibling_links`; a junction is removed as a link,
never recursed into. Verifier worktrees are named `wt` to keep deep repository paths under 260 characters.

**Verdict rules as built.** Two checks not in the Part E table are part of the fixed rules: *something
converted* (no change outside engine state and generated inputs fails the run — the baseline must read as
nothing converted) and, within re-discovery, *a project not on the engagement's target framework* (caps at
PARTLY). Re-discovery's remaining or introduced work items cap at PARTLY; the impact comparison and diff
size are reported, never judged. The canary is configured per repository in the experiment configuration.

**Every experiment file is produced by the platform, with no AI involved (2026-10-13).** Each experiment is a
self-contained folder, `<RUNS_DIR>/<engagement>/experiments/<name>/`, engagement data outside git:

| File | Produced by | From |
|---|---|---|
| `experiment.yaml` | `python -m app.experiment.create` | `app/experiment/templates/experiment.yaml.tmpl`, filled with the values a person passes on the command line; the command is recorded in the file's header, in Windows PowerShell form, so it can be run again with changed values (`--force` replaces the file) |
| `RUNBOOK.md` | `python -m app.experiment.prepare --config ...` | `experiment.yaml` and what prepare created: branches, worktrees, arm 2 inputs. Code-rendered (`render_runbook`), absolute paths |
| `CALIBRATION.md` | `python -m app.experiment.calibrate --config ...` | the verifier's own `verification.json` for the baseline commit and, where an arm has a `ref`, arm 3. `--render-only` re-renders without re-verifying |
| `REPORT.md` | `python -m app.experiment.report --config ...` | each run's `verification.json` and engine run record; one scorecard per run |

A new generation (`generation: N`) is a new set of branches and worktrees, `experiment/vN/...` in
`<repository>/experiment-vN/`; the files of an earlier generation are kept in the folder's `generation-<N>/`.
No step edits an existing worktree: prepare refuses when arm 2 inputs are out of date and says which generation to
set.

**Pinned instrument (2026-10-13).** An experiment is measured with one platform commit
(`app/experiment/instrument.py`). `create` records it in `experiment.yaml` as `platform_commit` and refuses while
the platform's working tree has uncommitted changes. `prepare` refuses at any other commit. Every verification
records the commit it ran at and whether the tree was clean (`platform` in `verification.json`, a line in
`VERIFICATION.md`). `report` marks a run verified at another commit or from a changed tree "instrument differs" and
lists it, and `calibrate` does the same for a calibration.

**Reproducing every experiment file.** Each command can write its file to another folder, so a regenerated file can
be compared with the one in use without touching it: `create --out <folder>` (the recorded command leaves out
`--out` and `--force`), `prepare --render-only --out <folder>` (reads the existing worktrees; makes no branch,
worktree, junction or commit), `calibrate --render-only --out <folder>`, and `report --out <folder>`. The engine
inputs are reproduced the same way with `python -m app.engine.inputs generate --out <folder>`.

## Part K — Engine-facing text, self-contained (2026-10-14)

The experiment's first check found `applying-ocp4-secret-injection.md` quoting its catalog item's whole
description into a Copilot instruction: a reference to `docs/21 Part G`, and notes written for catalog
authors ("strong candidate for fully deterministic conversion", "conversion ordering resolves the
overlap"). Copilot reads only the branch: a platform document is a reference to nothing, and an author's
note is noise it may act on.

**Two audiences, two fields.** Catalog items and resolutions carry `engine_guidance` beside their
author-facing `description` (28-ITEM-AND-CONVERSION-MODEL Parts D and F). The item's says what the change
is and why it matters on the target platform; the resolution's says what to do, in steps. Self-contained:
no platform documents, lifecycle step names, catalog or signal vocabulary, or internal notes. Factory
defaults are in `backend/app/seed/data/engine_guidance.yaml`, seeded through the never-overwrite path and
exported with the catalog. Written for every item detected in the three experiment applications (19
items, 42 resolutions); the file's header lists the 22 items still to write.

**The generator uses only engine-facing text.** `collect` reads `engine_guidance` and names, never a
description, target description or note; an item's description is parsed only for its ordering rules,
which the renderer writes as prerequisites in its own words. An item without guidance is emitted from its
resolution's guidance alone. A resolution without guidance cannot be applied: no instruction is written,
and its places go to the decision sheet's "Unresolved", to be left unchanged. Both are listed, outside
the branch: `generate` prints them and the runbook has a "Changes without engine-facing guidance" section.
The generator's own wording avoids the platform's vocabulary too: "change" and "approach" rather than
item and resolution, "default" rather than presumptive. The manifest names only the generator version,
the commit and each file's hash.

**The self-containedness check** (`app/engine/inputs/selfcontained.py`) runs in `build`, after the secret
check and before anything is written, over every generated file including the manifest. It checks only terms
specific to the platform, and never refuses an ordinary word on its own (catalog, resolution, signal, discovery,
step): those are the client's words too, in its project names and its prose. It fails on:

| Check | Fails on |
|---|---|
| platform document | `docs/...`, a spec file name, a `Part X` citation |
| platform path | `backend/`, `steps/`, `catalog/`, `third_party/` ..., a platform module (`app.engine`), `RUNS_DIR` |
| absolute local path | a Windows drive or UNC path, or a home or temp directory, unless the repository's own files hold it (the path the instruction is about) |
| lifecycle step | a lifecycle step's slug |
| platform vocabulary | any catalog item or resolution id, any signal name, an internal field name (`detection_state`, `engine_guidance` ...), the platform's own name |

Item ids, resolution ids, signal names and step names come from the database (`vocabulary` in the
collected model). Every name that comes from the repository itself is allowed wherever it appears: a file or
folder name, a file's name without its extension (a project's, `Catalog.Host`), a path it has, a namespace its
code declares. Also allowed: a skill's name (`applying-<id>`), Copilot's `discovery: preload|lazy` key, and the
attribution paragraph crediting the plugin a template was adapted from. The adapted templates' notices
still credit the plugin and say they were modified, without naming platform documents or paths.

Proof: `tests/test_engine_inputs.py` `SelfContained` plants each kind of violation and checks it is
refused and named, with nothing written; `RealRepository` generates the three experiment applications
clean. Over the inputs generated before this change, the check finds 413, 476 and 550 findings
(AccountsApi.Net10, AccountsApi.Net8, eShopOnWeb); over the regenerated inputs, none.

## Part L — Frozen package lookups (2026-10-14)

The pinned commit fixes the platform but not the package feeds. eShopOnWeb arm 3 resolved 16 work items at
generation 2 and 14 at generation 3 only because nuget.org published System.Text.Json and System.Net.Http.Json
10.0.13 in between: the verifier's throwaway database copied the live lookup cache, and discovery refreshed entries
older than the 24-hour TTL. Package changes are most of each application's work items, so a release between two
verifications would shift the comparison with nothing about the runs differing.

**The snapshot.** `python -m app.experiment.lookups freeze --engagement E --repository R --name N` writes
`package-lookups.json` into the experiment's folder: every lookup cache row for the packages the repository's
dependency assessment covers, and for their dependencies (the planner reads those to couple moves). That is every
answer the experiment's inputs were built from. It refuses, naming each, when an answer is no longer the one the
assessment used (a row fetched after the assessment ran, or a feed answer the cache no longer holds): it never
substitutes a newer one. The file is deterministic (sorted keys, one format) and never replaced without `--force`.
`create` refuses without it and records its sha256 in experiment.yaml as `package_lookups.sha256`.

**Verification answers from it only.** When experiment.yaml names a snapshot, the verifier checks the file against
that sha256 (a mismatch stops it), loads its rows, and nothing of the live cache, into the throwaway database, and
launches discovery there with the job parameter `lookup_offline` (phase0-repository-discovery v16), which
dependency-assessment 1.4.1 reads: answers come from the cache whatever their age, a package the snapshot does not
hold is reported as not answered, and no package file is downloaded. The baseline's cached re-discovery is keyed on
the snapshot too. Each verification records `packageLookups` (`source: snapshot`, its sha256 and row count, or
`source: live`), and `report` and `calibrate` mark any verification not made against the experiment's snapshot,
including one answered from live feeds.

**One key per local feed.** A local folder feed is keyed by its path, and AccountsApi's `../EnterprisePackages/feed`
resolves, in a verifier's worktree, through the junction beside it, to a path under `runs/`, so no frozen answer
matched it, and every AccountsApi package went unanswered. Live, this had stayed hidden: the verifier simply looked
the feed up again under the new key. dependency-assessment 1.4.2 resolves junctions and links in a local feed's path,
so every checkout names the folder by one key.

**What it does not freeze.** Package files (`.nupkg`) already downloaded are used as they are: a version's content
never changes. The restore that builds and tests each branch still uses the machine's package folders and feeds, as
any build does; it decides whether the branch builds, not which work items remain.

## Part M — What the pilot run found (2026-10-14)

AccountsApi.Net10 arm 2 run 1 of generation 3 was the first Copilot run. It is the **pilot**: kept, verified as a
dress rehearsal, and excluded from the comparison (`python -m app.engine.runs mark-pilot`; the run record's `role`).

**Inputs.** A sensitive key is named by its leaf (`EnterpriseAuthentication:Token:SigningKey`, not the section), and a
key holding an Enterprise.Vault reference is a vault reference, handled by `enterprise-vault-secret-reference`, not a
secret in the file (21-APPLICATION-FINGERPRINTING, registry 1.12.0). A deployment parameter for a path is named after
the configuration key the code reads (`FileContent__FilePath`, `resolution_parameters.yaml` `{KEY}`), one per key at
every place it is set; a literal in code, which has no key yet, takes the old value-based name.

**Discovery gaps.** Four items: Enterprise.Vault references, configuration files that cannot be parsed (the two
utilities' `appsettings.json` had unescaped backslashes, so nothing in them was seen), custom logging providers that
write files, and build and pipeline files that assume Windows.

**What the platform writes into a client repository.** Every commit the platform makes goes through
`gitops.platform_commit`: its message passes the self-containedness check (the inputs commit had cited this document)
and carries no co-author trailer; otherwise nothing is committed. The conversion runner's messages no longer name the
approach (a catalog id) or say "occurrence". Generated files are written with the line endings the repository's git
settings expect in the working tree (`eol` and `text` attributes, then `core.autocrlf`, then `core.eol`), so opening
them never shows them modified; the committed text, and the manifest's hashes, are the same either way.

**The runbook.** Copilot skipped the assessment, options and planning stages (the goal asked for no framework change),
never committed as it worked, and its terminal hung for over an hour on a multi-line PowerShell here-string. So the
opening message now carries everything: both arms, identically, are told to edit files with file-editing tools, keep
every terminal command on one line, stay on the current branch, and commit after each change with a message naming it;
arm 2 adds its instructions, skills, assessment addendum and decision sheet. The merge-addendum step is gone. If the
stages appear, the runbook answers them as before. A stuck terminal (`>>`, or five minutes with no output) gets
Ctrl+C, the same in both arms, recorded as a **protocol action** (`runs protocol`), never an intervention; the report
counts them apart.

**The verifier.** An engine run looks up live feeds and may take a release newer than the frozen snapshot. Such a
package is upgraded (dependency-assessment 1.4.3, outcome current), its work item resolved, and it is listed apart as
"newer than snapshot" in the verification and the report, never as unresolved or unknown.

## Part N — One conversion at a time (2026-10-14)

The work moves from comparing arms to converting one application at a time. The goal is a converted application that
builds, passes its tests and starts, verified independently. The experiment machinery (Parts F, J, L, M:
`app.experiment`) stays in place, unused.

**Prepare.** `python -m app.engine.convert prepare --engagement <e> --repository <r>` makes the next conversion: branch
`conversion/<n>` from the baseline, in the worktree `<RUNS_DIR>/<engagement>/<repository>/conversions/<n>/wt`, with
the generated inputs committed as the platform (`gitops.platform_commit`). It writes `RUNBOOK.md` and
`conversion.json` beside the worktree. It records the platform commit it ran at and pins nothing. There are no arms,
generations or frozen lookups. The baseline, goal, sibling links and canaries are given once and default to the previous
conversion's. If the latest conversion has not been run, preparing again refreshes its inputs in place. Otherwise it
makes the next conversion. So fixing an instruction and preparing again needs nothing more.

**Not run, one definition** (`app.engine.convert.not_run_because`, used by preparation, `status()` and the Conversion
tab alike): the branch is the baseline plus only the platform's commits (its package, scope and inputs commits), and no
tracked file is modified or staged. That is exactly what a refresh's `git reset --hard` could not throw away. An
untracked file, ignored or not, does not count against it: the reset leaves it as it is, `conversion.json` lists it
(`untracked`), and the platform never commits it (its inputs commit stages exactly the files it generated, by path).
Only one where the new inputs, `in-scope.sln` or a scope note would be written stops a refresh: it is refused before
anything changes, naming each file (`files_in_the_way`; a file the platform wrote earlier, by its inputs manifest or its
text, is not one). A kept conversion says its real cause, in the result, in `last-prepare.json` (`keptBecause`,
`message`, the files in `details`) and on the Conversion tab: commits beyond its inputs, uncommitted changes to tracked
files (named), or the untracked files in the way (named).

**The runbook** is one page, from `backend/app/engine/templates/conversion-runbook.md`. It covers: open the
worktree; send the opening message; the standard replies; the stuck-terminal step; when the agent reports done, commit;
then verify.

**The opening message** carries everything the agent needs, including what done means. Before it reports done, the
agent builds the solution with 0 errors and runs every test, and every test passes (none weakened, skipped or deleted;
a test file changed only where the code it tests moved, each change listed with its reason). It confirms every JSON and
XML configuration file parses. It starts the application without blocking the terminal, waits until it listens or
fails, then stops it. A failure only for want of a secret, vault or external service is reported, not worked around in
code. Anything that fails is fixed and all four checks repeated, at most three times; then the agent reports what still
fails. Each result is given with its command and a summary of the output. The global instructions add two rules: several
changes to one configuration file are made in a single edit, and a JSON or XML configuration file is re-read and
confirmed to parse after every edit. They no longer offer skipping a failing test.

**Verify.** `python -m app.engine.convert verify --engagement <e> --repository <r> --branch <b>` runs the verifier on a
branch against its baseline, with no experiment configuration. The baseline, sibling links and canaries come from the
branch's conversion record, or from the repository's latest record for any other branch (then `--base` is needed).
Package lookups are answered live.

**Verifier 1.1.0.** Two corrections, both found by the pilot, whose `appsettings.json` was left unparseable while every
test passed:

- **Configuration files parse**: every JSON and XML configuration file on the branch is parsed (JSON as .NET
  configuration reads it, comments and trailing commas allowed: `app.engine.configfiles`), and each failure is named
  with its line, never its text. A file that parsed at the base commit (or is new) and does not on the branch caps the
  verdict at NOT PROVEN. One that did not parse at the base commit either is a gap.
- **Not checked**: a work item gone from the branch that had a place in a file that does not parse there is *not
  checked*, never resolved, and is a gap. Discovery cannot read inside that file, so the item's absence proves
  nothing.

**Verifier 1.2.0: package upgrades against what was asked.** On the simple path, re-discovery looks packages up live,
so it suggests today's newest release. A package-upgrade place (`package-upgrade-safe`, `package-upgrade-breaking`) is
met when the package is at or above the version the conversion's inputs asked for. Those versions are read back from
the platform's inputs commit on the branch, made when the conversion was prepared (`app.engine.verifier.packages`). A
release published since then is listed as information, "released since the conversion was prepared", and is never a
remaining work item. A package the inputs never named (one the conversion added) has no asked version and is judged
against today's releases. `package-vulnerable` is always judged against today's advisories, because a new advisory is
a real finding.

**Successors and fixes are requested versions; prepare checks advisories.** An instruction that replaces a retired
package with its successor names the successor's version (dependency-assessment 1.5.0: its newest release that
supports the target and has no known advisory). A vulnerability names the version that fixes it, or says plainly that
no release without a known advisory exists yet, and then asks for nothing. Both are read back as requested versions
(`render.package_targets`), so the verifier judges a successor like any other upgrade: in the pilot, the agent chose
`Asp.Versioning.Mvc.ApiExplorer 8.1.0` with no version to judge it against. Before `prepare` changes anything, every
version the inputs ask for is checked against the package lookups (`convert.check_advisories`). None may carry a known
advisory, every one must be known to the lookups, and the lookups must be less than a day old. Otherwise prepare
refuses and says to run discovery again. The versions checked are recorded in `conversion.json`.

**What conversion 1 found (2026-10-14).**

- *Every instruction names its files.* The agent's file search failed, so it worked blind. It reported no `Build/`
  folder when `Build/` holds nine files, created a root `Dockerfile` duplicating `deploy/docker/Dockerfile`, and
  pointed CI at a `Build/validate-config.sh` that does not exist. Every instruction now has a **Files** section
  (`render.concerned_files`, from the repository's file list at the discovered commit). It lists the files of its
  places and impact and the project files of its projects. A package instruction adds the project settings
  (`Directory.*.props`, `nuget.config`, `global.json`); every other instruction adds all container, build, CI and
  deployment files. The opening message and the global instructions say: open the files the instructions name; do
  not search for them; never create a file the instructions say already exists.
- *Never hide a warning or an error.* Conversion 1 built with `-nowarn:NU1902,NU1903`, hiding the vulnerability
  warnings. The opening message and the global instructions forbid suppressing a warning or an error to make a check
  pass.
- *The stuck terminal.* If Ctrl+C does not clear `>>`, close the Copilot terminal: it reopens and retries the command.
- *Package changes applied by the platform.* Conversion 1 applied none of its package changes. Now `prepare` applies
  those that need no code before the agent's inputs are generated, on the conversion branch, with the conversion unit
  loop (34-CONVERSION-ARCHITECTURE Part E). Each is one commit that builds and passes the baseline's tests: safe
  upgrades (a vulnerability's fix is its package's upgrade) and removals of framework-provided packages (recipe
  `remove-framework-provided-package`, approach `remove-package-reference`). There is no retarget unit when the
  projects already target the engagement's framework. A change that does not go green is not committed, is reported
  by prepare, and stays in the agent's instructions. The agent is left what needs code: breaking upgrades, a retired
  package's successor, and any package change that did not go green. The verifier reads the package commits' versions
  as requested versions (`packages.applied_by_platform`), and the inputs commit is the platform commit that writes
  the instructions.
- *Tests kept counted a settings file.* The plugin's test-name rule includes Java's integration-test suffix
  `IT.<ext>`, which `appsettings.SIT.json` matches. The verifier now counts .NET test files only: in a test project's
  folder, or source code (`verifier.is_test_file`). VERIFICATION.md lists every test file changed, added or removed.
- *Resolved by a deployment file* (verifier 1.3.0, `app.engine.verifier.deployment`). A `console-batch-job` occurrence
  is resolved when a CronJob manifest on the branch names the project. An `enterprise-vault-secret-reference`
  occurrence is resolved when a Vault Agent `agent-inject-secret-<name>` annotation delivers the secret its reference
  names. VERIFICATION.md lists each with the file that carries it.

**What conversion 2 found (2026-10-15).**

- *A fast package step, inside prepare* (`app.conversion.batch`). The plan's deterministic units (safe upgrades, each
  also fixing its package's vulnerability; framework-provided removals; and, where the framework changes, the
  retarget and the framework-delta fixes) are applied together in one working copy, then built and tested once.
  Green: one commit, listing every change, one line each (`- P a -> b (project)`, read back by the verifier as a
  requested version). Red: the working copy is reset with git to the branch's tip and the units are split in halves,
  each settled the same way, until each failing unit is alone. What passes is committed, and each failing unit is
  recorded with its error. Conversion 2's unit loop took 20 cycles for 20 changes; the batch takes one when all are
  green. `conversion.json` records the step's duration, its build-and-test cycles and its flaky tests.
- *Flaky tests.* A test that passed at the baseline and fails is rerun once, alone (`dotnet.rerun`). If it passes, it
  is flaky: reported by prepare and in VERIFICATION.md, never counted as a failure, and never silent. The verifier
  applies the same rule. It names every test by its class and method (`Ns.Class#Method`, the vendored baseline_diff,
  which reads a TRX result's class from its test definition: MSTest and NUnit give only the method as its name), so
  tests with the same method name in different classes or projects are counted apart; it reruns a failing test by
  that name (`FullyQualifiedName~Ns.Class.Method`) and reads the rerun the same way, so a passing namesake never
  stands in for it. An approved removal names the test, or its method as an earlier verification named it. A method
  name alone (an approval recorded before 2026-11-23) applies only when it is unambiguous in the repository's tests,
  the baseline's and the clean run's: when tests of several classes share it, it applies to none of them, the
  baseline diff names the tests not approved, and VERIFICATION.md lists the approval under "Approvals to renew",
  with the classes, for a person to approve again by the test's full name (2026-11-24).
  `NormalizedKeys_RoundTripThroughEnterpriseEncryptor`, run 50 times at AccountsApi.Net10's
  baseline, failed 2 times (4%), both with an RSA parameter-length `CryptographicException` from
  `Enterprise.Cryptography`.
- *No instruction conflicts with the global rules.* Every instruction names the tests that exercise the code it
  touches (test-coverage-assessment's mapping), under **Tests that use this code**: keep them, and the code they
  use. The default resolution of `custom-file-logger-provider` is now `unregister-file-logger-provider`: unregister
  the provider, keep the class and its tests. `remove-file-logger-provider` removes them, and only a decision
  chooses it.
- *Existing deployment assets are kept* (`app.engine.deployment_assets`). An existing vault delivery mechanism is
  detected in the repository's YAML: an init container, Vault Agent annotations, a CSI secrets store or an
  external-secrets sync. When one exists, the vault item's resolution is `keep-existing-vault-delivery`, unless a
  decision chose another, and the instruction names the mechanism. The verifier counts a vault reference as carried
  when any such mechanism on the branch names its secret. The global instructions, the opening message and every
  instruction that lists deployment or build files say: change existing mechanisms in place or add beside them;
  never replace or remove one unless a decision says so.
- *Windows build files stay.* `linux-build-pipeline` adds a shell script beside each batch script, and Linux jobs
  beside the Windows ones; it never deletes a Windows script. Every new shell script has LF line endings, enforced
  by a `*.sh text eol=lf` rule in `.gitattributes`, and the executable bit set in git.
- *The opening message.* "Done" means every check passed on the final state: when anything changes after a check,
  all the checks are run again, and only the final results are reported. The agent is no longer asked to commit
  after each change; one commit is fine. The runbook adds: if the agent stops without its done report, send
  `Continue.`
- *Verifier 1.4.0.*
  - It attributes each changed file to the instructions whose Files section names it, and reports each instruction
    as changed, partly changed or untouched, plus the changed files no instruction names.
  - It checks that every new or changed shell script has LF line endings, the executable bit and an `eol=lf` rule.
    Any that fails makes the verdict NOT PROVEN.
  - A person may approve a removed test, with a reason (`python -m app.engine.convert approve-removal`). The
    approval is recorded in the verification and does not fail the verdict; an unapproved removal still does.
  - Tests kept counts source code only. A test project's `.csproj` or settings file, or a name ending in `IT`, is
    configuration, and is listed apart.

**Automatic preparation and verification from the UI (2026-10-15).**

- *Prepared after discovery.* Preparation is the last step of the per-repository discovery job, `conversion-preparation`
  (17-LIFECYCLE-STEPS v2.4). Registering or rescanning a repository runs discovery, then prepares a conversion: the
  branch and worktree, the package step, the inputs under `.github`, and the runbook. Nobody runs a command.
  - **A conversion starts from the commit discovery scanned** (`repositories.ingest_commit_sha`), so its package
    step, instructions and runbook are about the code that was analysed. Never from an earlier conversion's
    baseline: when the repository gains commits, the next conversion starts from the newest one scanned. Its record
    says so (`baseline`, `baselineFrom`, `scannedAt`).
  - **A rescan** refreshes a conversion not run yet, in place, moving it onto the commit just scanned. A conversion
    counts as run by the one definition under **Prepare** (commits beyond its inputs that are not the platform's, or
    uncommitted changes to tracked files; never an untracked file); then the rescan leaves it, saying why, and a person
    starts the
    next one from the UI ("Start the next conversion", which runs discovery with `new_conversion`). That always
    prepares a new conversion on a new branch, and changes no existing one; no engine runs.
  - **A failed baseline**, or a repository the planner cannot plan, still gets a conversion. The package step is
    skipped, the reason recorded, and the package changes go to the engine as instructions.
  - **Creating a conversion is all or nothing.** If creating its worktree, or any later part, fails, everything that
    creation made is removed: the branch, the worktree, the conversion's folder with any partial record and runbook,
    and its plan. The next preparation starts clean, never on "a branch that exists without its conversion record".
    A refresh of an existing conversion keeps it.
  - **Preparation never fails a discovery run.** What happened is in `conversions/last-prepare.json`, shown in the
    Conversion section: a problem as a short summary (what was refused, and in how many files) with the full list
    behind a "details" toggle; secret values named by reference instead of quoted, as a warning on a preparation
    that completed.
  - **Package lookups** older than their limit are refreshed, never refused: a stand-alone `prepare` runs discovery
    first.
  - **Sibling folders** a repository's `nuget.config` reaches by relative path are detected (`siblings.detect`).
- *The Conversion section* of the repository page lists every conversion, newest first (`GET
  /api/repositories/{id}/conversions`): number, branch, status (prepared, run or verified), and the verdict once
  verified. Each entry has:
  - the commit it starts from, the worktree, the runbook, and the opening message with a copy button;
  - what the package step did, what is left for the engine, and the package step's plan with its units and tests.
    Plans of earlier preparations of the same conversion, replaced by a refresh, are marked superseded and hidden
    until asked for;
  - **Verify**, on any conversion that has been run, and its verification with VERIFICATION.md.

  "Start the next conversion" asks for confirmation first. It names the new branch and the commit it will start
  from, and says it prepares fresh package changes, instructions and a runbook, changes no existing conversion, and
  runs no engine.
- *Verify* runs the verifier as the job `conversion-verification` (step `independent-verification`). It refuses, saying
  why, when the worktree has uncommitted changes or the branch has nothing beyond its inputs. For the second it reads
  "NOT PROVEN, nothing converted": the verifier's fixed rules fail an unconverted branch, so the verdict is known
  without a run. Otherwise the conversion's entry then shows the verdict, its reasons and the full VERIFICATION.md.


### Never on a mix of new and older results (2026-11-19)

A discovery run that fails stops at the failed step: the steps before it have stored new results, about the commit it
scanned (and `repositories.ingest_commit_sha` has moved to that commit), while the failed step and every step after it
still hold an earlier run's. Before this change the discovery job's own conversion-preparation step never ran after a
failure (the job halts), but `python -m app.engine.convert prepare` did: it read the newest stored result of each kind
and prepared a conversion from that mix, the package step and the work items from the older run against the newer
commit. `convert.prepare` now refuses (`ResultsMixed`) whenever the repository's latest discovery run failed, was stopped
or abandoned (`app.results.last_scan.refusal`): "The latest discovery run failed at <step> on <when> UTC, so the results
of <steps> are from an earlier run while the others are new. A conversion is not prepared on a mix of new and older
results: fix the failure and rescan the repository first (its Activity tab has the failure)." Nothing is created. The
command line prints it and exits; inside a discovery job it is recorded as the last preparation's message, in full. The
UI's ways to prepare (Start the next conversion, an engine or scope change) run discovery first, so they prepare only
after a run that completes. Both engines alike: this decides whether inputs are prepared, not what they say (rule 20).

## Part O — Conversion scope (2026-11-02)

A scope step before preparation: the dev team chooses which of a repository's solutions and projects its conversions
cover, and the rest are left untouched (backend `app.scope`; the repository page's Scope tab).

**The rules.**

- **The project is the unit of scope.** Selecting or deselecting a solution is a shortcut for its projects:
  deselecting one deselects each of its projects, except a project that another still-selected solution contains.
  That project stays selected, shown as "kept by" that solution. Individual projects can be selected or deselected
  too. A solution's own checkbox shows whether all, some or none of its projects are selected.
- **Every project is in scope until someone saves a scope**, so a repository nobody has reviewed converts exactly as
  before. Only exclusions are stored (`conversion_scopes`, by path relative to the repository), so:
  - a rescan keeps the scope;
  - a project discovered after the save is in scope by default, flagged "new since scope was set";
  - an excluded project that no longer exists drops out.

**Editing and saving.**

- **Editing is a draft.** People tick and untick freely, with Select all, Deselect all and Discard changes (back to
  the last saved scope). Problems show as warnings; nothing is refused while editing. Leaving the tab with unsaved
  changes asks first.
- **Save checks the whole selection** and is refused, with every problem listed together, until there are none:
  - every kept project's dependencies (solution-discovery's project references) must also be kept, directly or
    through other projects. Each problem names the kept project and the excluded dependency, and offers to keep the
    dependency or to exclude the project too;
  - at least one project must be kept.

  The server checks again, in the same words (422 `SCOPE_INVALID`, one item per problem).
- **Before saving**, a summary shows the change: the projects being excluded and re-included, and the work items
  moving out of and back into scope, with an optional reason.
- **Save records** who, from which machine, when and the reason (and an activity record), and carries a version
  check: if someone else saved first, it is refused (409 `STALE_COPY`) with an offer to reload. Only the repository's
  owner or an admin can save, from the machine it was registered on (`PUT /api/repositories/{id}/scope`).

**What happens to an excluded project.** The only choice now is "Leave untouched". The UI also shows "Retire — remove
as dead code", disabled and marked "coming later". Left untouched means:

- **Preparation commits, as the platform, before the package step** (`app.scope.files`):
  - an `OUT-OF-SCOPE.md` in each excluded project's folder, never over a file already there. It says the project is
    outside this conversion's scope and left as it was, who decided, when, the reason if one was given, and that it is
    not part of the converted build;
  - the conversion's own solution, `in-scope.sln` at the repository's root, for every conversion since 2026-11-23
    (with a full scope too), listing exactly the kept .NET projects (`.csproj`, `.vbproj`), never an SSIS `.dtproj` or
    any other project, which are listed as not converted by this track instead (see the 2026-11-23 addendum):
    wherever they live, whichever solutions list them (each shared project once), and those no solution lists. A kept
    project keeps the GUID, type and Debug/Release configuration the first solution listing it gives it (by solution
    path); one no solution lists gets a GUID made from its path and Debug/Release on Any CPU. It is named in the
    conversion's record (`scope.build`). A repository with many solutions sharing projects spreads its kept projects
    across several of them, so no one solution, or filter of one, holds them all; this one does, so every kept project
    is built, tested and verified.
- **The package step** plans and builds only the kept projects: their packages, framework declarations, framework
  deltas and unit tests (`planner.create(excluded_projects=..., solution=...)`), building the conversion's solution,
  which holds every kept unit test project. Its baseline builds the same file, copied into the baseline commit's
  working copy.
- **The instructions** cover only the kept projects:
  - their findings, packages, deltas and tests; no work item names a file of an excluded project (its Dockerfile, a
    build script in its folder), whatever kind of file it is;
  - the top-level instructions' "Conversion scope" section, for both engines (Part Q), where the agent reads first and
    not only in `OUT-OF-SCOPE.md` files it may never open: build and test only the conversion's solution; every
    excluded project by name and path, with who excluded them, when and the reason; never change, retarget or fix
    one; if a change seems to need one, stop and say so;
  - the decision sheet's and RUNBOOK.md's "Conversion scope" section, the same list;
  - Claude Code's settings, which deny edits inside each excluded project's folder (only its project file when its
    folder also holds a kept project, or is the repository's root);
  - the Linux build-pipeline instruction, which builds the conversion's solution too;
  - the addendum, which lists the projects left out.
- **The work list** marks excluded findings "out of scope": kept visible, never deleted. Its counts say how many are
  out of scope.
- **The verifier**:
  - reports any change inside an excluded project, other than its `OUT-OF-SCOPE.md`, as a scope violation, naming the
    files (check "Scope kept"): a branch with one is NOT PROVEN;
  - builds and tests the conversion's solution, at the base commit (the same file, copied beside it) and on the branch;
  - treats an excluded project's tests as out of scope, not as removals or failures, and leaves them out of the
    baseline;
  - leaves excluded findings out of what re-discovery counts as remaining, and excluded projects out of "not on the
    target framework";
  - does not count the scope's own files as conversion;
  - says in VERIFICATION.md how many projects were left out.
- **The conversion's record** keeps the scope it was prepared with (`scope` in `conversion.json`).

**Saving a changed scope** prepares a conversion that has not been run yet again, through the same discovery run a
rescan starts. A conversion already run keeps the scope it was prepared with; the new scope applies to the next one.

**Backlog**, not built:

- **Excluding entry points.** An application's entry points (an endpoint, a job) cannot be left out on their own.
  That needs reachability analysis: which code only an excluded entry point reaches.
- **Retire.** Remove an excluded project as dead code instead of leaving it untouched, with its solution entries and
  references.
- **Hints.** Suggest which projects look dead: no entry point, nothing referencing them, no recent commits.

## Part P — Can this machine run the baseline? (2026-11-03)

A conversion's baseline builds and tests the repository on its own frameworks, before anything is converted, on the
machine it is registered on. That machine needs the runtimes and build tools those frameworks require. Without them
the package step used to be skipped with a reason found deep inside preparation, such as a .NET 8 test project on a
machine whose platform .NET had only the .NET 10 runtime. Now the platform checks first and says so plainly
(`app.toolchain`).

**What a repository needs.** Its projects in scope (Part O), with their target frameworks from solution-discovery and
their test projects (recognised by what they reference, below):

| Project | To build | To run its unit tests |
|---|---|---|
| modern (`netX.Y`, `netcoreappX.Y`) | a .NET SDK of version X or later | the .NET X.Y runtime (`Microsoft.NETCore.App`, the same major, that minor or later) in the architecture of the platform's dotnet; the ASP.NET Core or Windows Desktop runtime of the same version when it, or a project it references, uses the Web or Windows Desktop SDK |
| SDK-style on .NET Framework | a .NET SDK (its reference assemblies come from NuGet with the restore) | that .NET Framework runtime |
| legacy (non-SDK-style) on .NET Framework | that version's reference assemblies (its Developer Pack); a web application project (its project file imports `Microsoft.WebApplication.targets`) also needs those targets where `dotnet build` finds them | that .NET Framework runtime (3.5 for 3.5 and older) |

A `netstandard` project needs nothing beyond an SDK.

**What this machine has** (`app.toolchain.machine`), read from folders, the dotnet executable's header and the
registry, never by running anything:
- the .NET the platform builds and tests with: the `dotnet` first on `PATH`, which is `DOTNET_ROOT`'s when
  `backend\.env` sets it. Its architecture, SDKs and shared runtimes. `dotnet test` starts its test host from this
  install only, so a runtime elsewhere does not count;
- the machine's other .NET installs (machine-wide x64 and x86, the per-user one), named only to say where a missing
  runtime is after all;
- the .NET Framework reference assemblies, the .NET Framework 4.x release, and whether 3.5 is turned on;
- `Microsoft.WebApplication.targets` under the platform's SDK, where `dotnet build` looks, and under Visual Studio,
  which `dotnet build` does not use.

**The result** is one summary, and each missing or present item with what it is for (build or test), the projects
that need it, and what the machine has instead. For example: "Baseline tests cannot run here: needs the .NET 8 runtime
(x64)", with "`dotnet test` starts the test host from C:\MP\tools\dotnet (x64) only, which has .NET 10.0.7;
C:\Program Files\dotnet (x64) has 8.0.29. DOTNET_ROOT (backend\.env) points the platform at the install without it".
"The baseline cannot build here: needs ..." when the build itself cannot run.

**Where it runs and shows:**
- **After discovery**, the conversion-preparation step checks and records it (`toolchain_checks`, one row per
  repository) before it prepares anything.
- **The repository's page** (`GET /api/repositories/{id}/toolchain`): on its own machine, checked now and recorded
  when it changed; elsewhere, what its machine last recorded, saying so. When the machine cannot run the baseline, the
  page header says so on every tab, and the Conversion tab says so beside "Start the next conversion", with what is
  missing and that a conversion prepared now gets no package step.
- **The package step** checks before planning, and is skipped at once with the summary as its reason: "no package
  step: Baseline tests cannot run here: needs ...". The conversion is still prepared, and its package changes go to
  the agent as instructions.
- **Preflight** lists, across every registered repository, what this machine lacks and which repositories need it, as
  `WARNING`, never a failure (`python -m app.toolchain report`).

## Part Q — Two conversion engines: GitHub Copilot and Claude Code (2026-11-19)

GitHub Copilot is not available on every client's machines; Claude Code may be. Both stay fully working, behind the
same boundary (`app.engine.engines`): what a conversion is asked to do is the same whichever engine does it.

**One content model, two renderers.** The work items, the decisions, the assessment addendum, the scope, the build and
test commands and the rules are produced once (`app.engine.inputs.render`), and each engine gets them in its own
files. Only an engine's mechanics differ, and they are one table (`app.engine.inputs.claude.MECHANICS`): where the
work items are, where the platform's inputs are, where notes go. A parity test (`tests/test_engine_inputs.py`,
`EngineParity`) maps Claude Code's files back through that table and requires the same work items, decisions, scope
and rules as GitHub Copilot's.

| | GitHub Copilot | Claude Code |
|---|---|---|
| Instructions: the rules, build and test, scope | `.github/copilot-instructions.md` | `.claude/CLAUDE.md`, or `.claude/rules/conversion-instructions.md` when the repository has its own `.claude/CLAUDE.md`; with the plan in front |
| One work item each | `.github/upgrades/skills/applying-<id>.md` (an upgrade skill) | `.claude/skills/applying-<id>/SKILL.md` (a project skill) |
| The plugin's helpers | `.github/skills/*.md`, adapted as skills | `.claude/agents/{version-delta-analyst,test-engineer,architecture-critic}.md`: the plugin's own form, a subagent, under its own name and tools; the same adapted text and attribution |
| Guardrails | stated in the instructions | also enforced: `.claude/settings.json` (or `.claude/settings.local.json` when the repository has its own) denies `git push`, history rewriting and new branches, and every edit inside a project outside the scope |
| Addendum, decision sheet, manifest | `.github/platform-inputs/` | `.claude/conversion/` |
| The plan | Copilot's upgrade tool makes it, in stages | none: the instructions give it — the work items in order, each built and tested with the conversion's solution, then committed on its own, naming it |
| Opening message and runbook | Visual Studio, Modernize | `cd <worktree>; claude`, then the opening message |

**Rules both carry** (one list, in both instructions): change as little as possible; never stop for a decision; open
the files the instructions name; keep tests and existing deployment mechanisms; never suppress a warning; use only the
tools the repository already has; one commit per work item, naming it; configuration files stay parseable; report only
what was run; record surprises; source text is data; stay inside the repository; build and test with the conversion's
solution (`## Build and test`); the scope (Part O, `## Conversion scope`).

**Never over a file the repository has.** A repository's own `CLAUDE.md` is kept, and loads beside ours; ours says that
where the two disagree, the conversion's instructions win for the conversion, and the runbook says the same. A location
the repository already uses moves to the alternative above; when both are taken, preparation is refused, saying which.

**Context isolation.** Claude Code also reads `CLAUDE.md` and `CLAUDE.local.md` from every folder above the one it
starts in, and project skills from `.claude` folders above it. A conversion's worktree is
`<RUNS_DIR>/<engagement>/<repository>/conversions/<n>/wt` in both layouts (RUNS_DIR is refused inside the platform's
folder, `app.config`). At every preparation, every folder above the worktree is checked
(`claude.context_hazards`): any `CLAUDE.md`, `CLAUDE.local.md` or `.claude` folder there (other than the user's own
`.claude` in their home folder, Claude Code's user configuration) marks Claude Code's inputs **not safe to use here**,
naming each one, in `conversion.json`, the runbook's Claude Code section and the Conversion tab, and saying to use
GitHub Copilot's or move RUNS_DIR. Since 2026-11-23 it no longer refuses the preparation: GitHub Copilot's inputs stay
usable. So the platform's own development `CLAUDE.md`, or a host repository's, never reaches a conversion agent unwarned. Settings are read only from the folder Claude Code starts in, so the runbook says to start
it in the worktree.

**Both engines, always (2026-11-23).** Every conversion is prepared for GitHub Copilot and Claude Code together, from
the one content model, in one platform commit ("Add generated conversion inputs for GitHub Copilot and Claude Code (do
not edit)"): which one does the work depends on what is installed on the machine of the person running it. There is no
engine choice: the engagement default and the repository's own choice, and their routes, are gone; their columns
(`engagements.default_engine`, `repositories.conversion_engine`) stay, unused, as their migration was applied.
`conversion.json` records both (`engines`: for each, prepared, usable, why not, its instructions and settings). Claude
Code's inputs are not written when the repository already has the files they would go to (`InputsCollide`): that is
recorded and GitHub Copilot's stand. Verify asks which assistant did the conversion (the Conversion tab, defaulting to
the one being viewed; `--assistant` on the command line); `conversion.json` (`assistant`) and VERIFICATION.md
("Conversion done with") record it, and the verifier reads that assistant's instructions only, never both copies. A
record from before has `engine` (GitHub Copilot when absent) and only that engine's inputs. Nothing prepares it again
on its own, and no discovery run starts when a backend starts: an unrun one gains the other engine's inputs at its next
rescan or prepare, and a run one is left as it is (the next conversion has both). Until then the Conversion tab says
"Prepared for one engine only" and how to add the other.

**Everything that holds for Copilot's inputs holds for Claude Code's:** the self-containedness and secret checks, the
inputs manifest (`.claude/conversion/inputs-manifest.json`), exclusion from the diff, impact comparison and
re-discovery (`.claude/` is engine state, like `.github/upgrades/`), and the attribution of changed files to the
instruction that names them (`## Files` in each `SKILL.md`).

**Changing conversion inputs** says, for each engine, that the change was applied there or why it does not apply
(CLAUDE.md).

## Part Q addendum — Not-applicable items and the utc-everywhere resolution (2026-11-23)

Rule 20, for each engine:

- **An item the engagement decided is not applicable** (`28-ITEM-AND-CONVERSION-MODEL.md` Part F, "Not applicable")
  is absent from the content model both engines' inputs are rendered from (`collect()` sets it aside), so it is absent
  from GitHub Copilot's and Claude Code's inputs alike: no work item, no line in the decision sheet, the addendum or
  the runbook. Applied to both; nothing engine-specific.
- **The resolution `utc-everywhere`** of `datetime-now-usage` ("UTC everywhere, independent of the host's time zone")
  is a catalog resolution like any other: its `engine_guidance` is the work item's "What to do" for GitHub Copilot and,
  through `claude.MECHANICS`' substitutions only, for Claude Code. It asks the agent to report two kinds of place in the
  task's notes: a genuine local-time need, converted with a named zone; and every stored or compared time, left
  unchanged and listed under "Stored times for a decision". Applied to both; nothing engine-specific.

## Part Q addendum — Both engines, in-scope.sln for every conversion, and the runbook (2026-11-23)

Rule 20, for each engine:

- **in-scope.sln for every conversion.** With a full scope it lists every convertible project; with a reduced scope,
  exactly the kept ones; only `.csproj` and `.vbproj` (`app.scope.service.CONVERTIBLE`). Both engines' instructions
  build and test it (`dotnet build in-scope.sln`, `dotnet test in-scope.sln`; the first message's done checks name it),
  and the verifier builds and tests this one solution. Applied to both.
- **Not converted by this track.** Every project that is not one of those (an SSIS `.dtproj`, a database `.sqlproj`, ...)
  is never in in-scope.sln; both engines' instructions and RUNBOOK.md list them by path under "Not converted by this
  track" (`render.not_converted_lines`). Applied to both.
- **RUNBOOK.md** has a shared header naming the full path of in-scope.sln, then a complete section for each engine:
  GitHub Copilot (open the full path in Visual Studio, the modernization agent, the first message verbatim, replies,
  done, Verify choosing GitHub Copilot) and Claude Code (a terminal at the worktree's root, by full path, or that
  folder in VS Code with the Claude Code extension; the first message verbatim; permission prompts; continuing an
  interrupted session with `claude --continue`; checking that each work item was committed; Verify choosing Claude
  Code). No solution is opened for Claude Code; its instructions say to build and test in-scope.sln. The Conversion tab
  shows the header and one section, for the engine chosen in its dropdown (remembered per browser). Applied to both:
  each section is that engine's mechanics only.

## Part Q addendum — Not run, one definition; refreshes and untracked files; test projects (2026-11-23)

A conversion prepared for GitHub Copilot alone, with one untracked file a person's tool left in its worktree, was kept
at every rescan as "has been run": preparation counted the untracked file, while the Conversion tab counted only
commits, so the tab said "prepared" and nothing was refreshed or said.

- **One definition of not run** (Part N, **Prepare**): preparation, `status()` and the tab use the same check, and an
  untracked file does not count. A refresh never overwrites a person's untracked file at a path it would write: it is
  refused before anything changes, naming the files. The inputs commit stages exactly the generated files, by path.
  A kept conversion says its real cause, on the tab and in `last-prepare.json`.
- **No discovery run at backend start.** A conversion prepared for one engine gains the other's inputs at its next
  rescan or prepare; the tab says "Prepared for one engine only" and how to add the other until then.
- **Test projects by what they are** (`app.conversion.testprojects`): a project is a test project when it references
  a test framework (Microsoft.NET.Test.Sdk, xunit, NUnit or MSTest packages, `IsTestProject`, the MSTest.Sdk project
  SDK; in a legacy project, packages.config or a `<Reference>` to a test framework assembly), whatever its name. The
  package step's baseline and the verifier run those, less any whose tests test-coverage-assessment classified as
  integration, functional or smoke only; before, they ran only projects whose test classes were classified "unit",
  which needed a `*.UnitTests`-style name, a category or a mocking library, so `*.Tests`, `*Test` and plainly named
  test projects were not run. The verifier runs those in in-scope.sln; when it lists none, the clean re-run fails
  saying so plainly, so a branch whose tests were not found is never PROVEN.

Rule 20, for each engine: all of this applies to GitHub Copilot and Claude Code alike, and changes no conversion
input. What a conversion is told (the work items, rules, decision sheet, addendum, scope, build and test commands,
first message and runbook) is the same text as before for both; when a refresh happens, and what it may touch, is the
same for both engines' files.

## Part Q addendum — .NET Framework sources, old-style projects and failed preparations (2026-11-24)

A repository descoped to a few projects, all on .NET Framework 4.7, failed its preparation with "target v4.7 is not a
.NET (5+) framework": the engine inputs' model computes package moves and couplings when the in-scope projects share one
framework, and the framework rules knew only .NET (5+) targets. The step completed, as it always does, and the
Conversion tab went on showing the earlier conversion with no sign of the failure.

- **.NET Framework sources** (34-CONVERSION-ARCHITECTURE "As built", "A .NET Framework source"): package support and
  dependency minimums follow NuGet for a .NET Framework project, in both spellings (`v4.7`, `net472`). A framework the
  rules do not cover is recorded as not known, never an error that stops a preparation.
- **Old-style projects are retargeted by the engine, not the package step.** The package step's retarget edits a
  `TargetFramework(s)` element; an old-style project declares `TargetFrameworkVersion` instead (and usually
  packages.config), which the package step does not edit. A repository with one gets no package step, recorded as
  "no package step: `<project>` is an old-style project (TargetFrameworkVersion v4.7): old-style projects are
  retargeted by the conversion engine, not the package step", and its package changes go to the engine as
  instructions, as for any repository without a package step. The package step's behaviour is unchanged; only the
  message is plain (before: "declares no TargetFramework(s), though solution-discovery says it does").
- **A failed preparation is visible.** The step still never fails the discovery run. The repository header's
  failed-scan notice covers it: "The latest scan ... completed, but its conversion-preparation failed: <message>",
  read from the attempt the owner's machine published for that same run (`app.results.last_scan.failed_preparation`),
  so it is the same on every machine. It never refuses a preparation: the next rescan prepares again. The Conversion
  tab shows the failure's message and labels the conversion it still shows "older: the last preparation failed".

Rule 20, for each engine: the model is shared, so the fix applies to GitHub Copilot and Claude Code alike. No
conversion input text changes for either beyond package couplings now being reported for .NET Framework sources (the
addendum's and decision sheet's package rows, and the work items that name a package's coupling).

## Part Q addendum — Design questions before converting (2026-11-24)

Some resolutions change the design, not only the code: a SOAP service becomes a REST API, a UI is rewritten, a Windows
service becomes a CronJob. How to implement them (logging, an API description, input validation) is the developer's
call, and the inputs alone cannot make it. Such a resolution is flagged in the catalog, and the engine asks first.

- **The flag** (`item_resolutions.confirm_design`, 28-ITEM-AND-CONVERSION-MODEL): "Confirm the design before
  implementing", set on the factory resolutions that change the design or the architecture
  (`backend/app/seed/data/confirm_design.yaml`), unset on the rest, editable by admins. An installation whose catalog
  is its database's own gets the flags at its bootstrap from the export, for the items holding a flagged resolution
  (`catalog_source.design_flag_items`, as the release's wording corrections): an unedited resolution takes the flag, an
  edited one is left as it is and reported as a conflict.
- **The rule, not the questions** (`render.design_section`): when a work item's chosen resolution is flagged, the
  instructions get a section, "Design questions before converting", listing those work items by name, with the rule:
  at the start of the conversion, before changing any code, ask the developer 3 to 5 questions for each listed work
  item, all in one message, one round; the questions are the engine's to choose, from the code and the work item, about
  how to implement the change, each naming the default it will use; never about anything the instructions, a work item
  or the decision sheet already decide; "Use the defaults" accepts every default; then every work item is worked
  through without stopping again for these questions. It is the one exception to "Never stop for a decision". No
  question is written into the inputs.
- **The record** (`CONVERSION-DECISIONS.md` at the worktree's root, `paths.DESIGN_DECISIONS`): a section per work item
  (`## <work item name>`) with a table `| Question | Default | Answer |`, committed with the first work item. It is a
  record, not a change: excluded from the diff, impact and re-discovery comparison like the inputs.
- **The verifier** (`verifier.design_check`) reads the flagged work items from the instructions at the inputs commit. A
  flagged work item the branch changed (a file its instruction names, or a commit named after it) with no answer
  recorded is a gap ("Design questions answered"), so the branch is at best PARTLY PROVEN. VERIFICATION.md has a
  "Design decisions" section with every question, default and answer.
- **The runbook** opens with one line pointing each engine's users to their section (A: GitHub Copilot, B: Claude
  Code), and each section, after its first message, says to expect the questions first, naming the work items, and to
  answer them or reply `Use the defaults.`

Rule 20, for each engine:

- **GitHub Copilot**: applied. The section is in `.github/copilot-instructions.md`, sent with every request, so the
  modernization agent asks before its plan's first code change; runbook section A says to expect it and how to answer.
- **Claude Code**: applied. The same section is in its instructions (`.claude/CLAUDE.md`), through the mechanics table
  (the work item names are the same for both), and its plan, "How to run this conversion", puts the questions before
  the first work item; runbook section B says to expect them.
- The decisions file, its format and the verifier's check are the same for both. The parity test
  (`tests/test_engine_claude.py`) passes unchanged.

## Part Q addendum — A descoped, old-style repository's inputs (2026-11-24)

A repository descoped to three old-style projects of 172 showed three gaps in what both engines are told.

**The scope reaches every section** (`collect._in_scope_entry`). The addendum's Windows-only, deploy parameter and SOAP
sections read every outbound invocation of the repository, so they named configuration files of dozens of projects
outside the scope, which the engine must not touch and the verifier's "Scope kept" check then penalised it for. Now a
binding is listed only when its configuration file is in scope, and an entry only when it has an in-scope binding or an
in-scope call site; one with neither, as a project left out has, is dropped. An unscoped repository is unchanged. The
other sections already followed the scope (items, packages, framework deltas, tests, the work items' Files); the decision
sheet's deployment parameters come from the items, which follow it.

**Restored package folders are not the repository's own.** A work item's Files listed a package's vendored scripts
(`packages/<id>.<version>/tools/*.ps1`), because the build files it names come from the whole repository's file list. No
instruction names a file in a restored package folder now (`paths.restored_package`, `render.concerned_files`), and the
two backend walks that read deployment YAML skip them too (`deployment_assets`, `verifier.deployment`). Discovery never
detects an item there, only in the repository's own files:

- application-fingerprinting, entry-point-inventory, outbound-invocation-inventory, test-coverage-assessment and
  impact-analysis walk files through one C# walk (`FileSystemWalk`), which already skips every folder named `packages`
  (case-insensitively): unchanged;
- item-detection reads only what fingerprinting recorded, so it inherits that: unchanged;
- solution-discovery skipped `packages` case-sensitively, so a restored `Packages\` folder on Windows was walked for
  project files: it now compares folder names case-insensitively, as the C# walk does;
- dependency-assessment and dependency-hierarchy do not walk the tree (they read project files and restored assets):
  unchanged.

A real scan proves it (`tests.test_descoped_inputs.RestoredPackageFolders`): a project file, a C# file using
`DateTime.Now` and a script inside `packages/Vendor.Lib.1.0.0/` are not recorded; the repository's own are.

**Changes without an instruction.** A change a person decided to make, whose chosen resolution has no engine guidance,
was told "Instruction: none: leave unchanged": a wrong instruction, not a missing one. Now:

- The addendum's Changes table says "no instruction yet: do not change; a person supplies it", with a line telling the
  engine not to make such a change nor choose an approach for it; the decision sheet's Unresolved row says the same.
  "Leave unchanged" stays only where an approach with an instruction cannot apply at a place
  (`resolution_parameters.yaml`).
- A default answer of the decision sheet that would keep something that cannot work on the target is reported the same
  way instead of given: "Package management: keep the current arrangement" for an in-scope project on packages.config
  heading to .NET 5 and later, which cannot restore it, becomes "No instruction yet" with why, status "no instruction
  yet".
- Preparation names each one (`render.incomplete`): the record's `withoutGuidance` and `incompleteInputs`,
  last-prepare.json's `incomplete`, shown on the Conversion tab as "Inputs incomplete", so the person preparing the
  conversion sees the inputs are incomplete before running it. Never a failure.
- Admins write engine guidance in the catalog's item and resolution editors, with the item's version check; every change
  is in the activity record. Guidance that names a platform document, path, step or the platform's own ids is refused
  as a field error, by the same check every generated input passes (`selfcontained`).

No new engine guidance was written for the items still without it.

**Assembly references no package declares.** Old-style projects reference most third-party code as a `<Reference>`
with a `HintPath`, which no package assessment sees, so the inputs said "No package upgrade is recommended" while a
Windows-only assembly would not load in the container. The addendum now has a section, "Assembly references no package
declares", from dependency-hierarchy's assembly references (`collect.assembly_references`). A framework assembly, one a
declared package stands for, and a project outside the scope's are not listed. It states:

- each in-scope project's format (old-style or SDK-style) and whether it uses packages.config;
- each reference: name, version, where it points (a repository DLL, a packages folder without a declaration, the GAC, or
  outside the repository), whether the file exists, and a verdict. A `HintPath` into `packages/<id>.<version>/` is that
  NuGet package, undeclared: declare it as a package reference, with what dependency-assessment's lookups already know
  of its support for the target (`package_lookup_cache`, read only). An assembly on the Windows-only list
  (`backend/app/compatibility/windows_only_assemblies.yaml`, data: the SSIS runtime and the SAP (Sybase) ASE ADO.NET
  provider to start with) "needs a replacement on Linux: a person decides it before the conversion". Anything else is
  "unknown: check it builds and loads on Linux".

A reference to a Windows-only assembly raises a catalog item, `windows-only-assembly-reference` (application scope):
item-detection matches it on a project metadata field, `windowsOnlyAssemblies`, read from the hierarchy (unknown, so not
checked, for a repository without one). Its default resolution is "Decide the replacement before converting", with no
engine guidance: the engine is told not to change the reference, and preparation's warning says "no decision recorded;
a person decides the replacement before the conversion is run" until an engagement decision chooses another resolution
("Replace it with a library that loads on Linux", "Keep the project on Windows"). The package step does not declare an
undeclared package from a packages folder: the projects that reference one this way are old-style, which get no package
step. The engine is told to declare it.

**A conversion with no test project is verified.** The verifier used to fail its "Clean re-run" when in-scope.sln held
no test project, and the baseline diff then failed for want of results. Now every other check runs and is reported: the
clean re-run is a gap, "no test project found in in-scope.sln ... Every other check below was run", the first reason
whatever else is said; the baseline diff and the canary are not applicable. The verdict is at most PARTLY PROVEN.

Rule 20, for each engine:

- **GitHub Copilot**: applied. The scoped outbound sections, the assembly section and the "no instruction yet" wording
  are in its addendum and decision sheet.
- **Claude Code**: applied. The same addendum and decision sheet, through the mechanics table
  (`.claude/conversion/assessment-addendum.md`); nothing here is engine-specific.
- The preparation warning, the catalog item and the verifier's check are the same for both. The parity test
  (`tests/test_engine_claude.py`) passes unchanged. Rule 21: no step artifact gains a field or an enum value (the new
  item is catalog data, and item-detection's metadata evidence already has this shape), so no schema version changes.

## Part Q addendum — Engine guidance written, frameworks by role, the project file, the allow-list (2026-11-24)

The changes a descoped .NET Framework repository's conversion met with "no instruction yet" now have engine guidance
(`backend/app/seed/data/engine_guidance.yaml`, seeded through `baseline.py`, exported to `catalog/items/`): SSIS
packages, .NET Framework class libraries, WCF services and their hosts, ASMX services and the Windows-only assembly
reference, the item and every resolution; and the identity provider claims, explicit legacy code page and incremental
ASP.NET Core resolutions. The first pilot run's lessons are in the text: the .NET Standard bridge multi-targets the
current framework and `netstandard2.0` and keeps the assembly's identity; the C# worker treats the `.dtsx` as its
specification, null handling and statement order included; the REST rewrite keeps each operation's data and maps
faults to status codes with problem details.

- **Frameworks by role.** Guidance never names a framework version: it says "the target framework" and "the project's
  current framework". Each work item has a "Frameworks" section (`render.frameworks_section`) with the real values: the
  target framework of this upgrade, and each concerned project's current framework, with its SDK-style short form
  (`v4.7` is `net47` in an SDK-style project file).
- **The project file.** Two catalog items, detected from solution-discovery's project metadata: an old-style project
  file (`legacy-project-format`: convert it to an SDK-style project, keeping `RootNamespace`, `AssemblyName`, the
  strong-name key and the compiled files, `GenerateAssemblyInfo=false` when `Properties/AssemblyInfo.cs` exists) and
  packages.config (`packages-config`: move to PackageReference, the same packages and versions, transitive ones dropped
  unless the code uses them, `HintPath` references into `packages` removed). The second runs as one unit with the
  first, and the first before a class library's retarget. With the packages.config item's instruction present, the
  decision sheet's Package management answer points to it; the fixed "missing guidance" answer stays only for a
  repository scanned before the item existed.
- **Decisions first.** The Windows-only assembly item's default now has guidance (leave the references unchanged), and
  preparation still names it as a decision a person makes first until one is recorded. Choosing a replacement library
  is a design decision: "Replace it with a library that loads on Linux" is flagged "Confirm the design before
  implementing".
- **The allow-list.** Every active resolution has guidance or is on `engine_guidance_allowlist.yaml` with a reason
  (`tests/test_engine_guidance_allowlist.py` fails otherwise, and for a stale entry). Preparation's warning repeats the
  reason for an allow-listed resolution a conversion chose.
- **Existing installations.** The bootstrap takes the new text from the export for every item that has guidance
  (`catalog_source.guidance_items`), into rows not edited since they were seeded; a row an admin edited is kept and
  reported as a conflict (rule 10).

Rule 20, for each engine:

- **GitHub Copilot**: applied. The guidance reaches its work items (`.github/upgrades/skills/`), each with the
  Frameworks section; the decision sheet's Package management answer changes.
- **Claude Code**: applied. The same work items through the mechanics table (`.claude/skills/*/SKILL.md`), the same
  decision sheet; nothing is engine-specific. The parity test passes unchanged.
- Proved on a made-up repository scanned by the real job (`tests/fixtures/guidance_repository.py`,
  `tests/test_guidance_fixtures.py`): each item detected on its project; each resolution, chosen in turn, carried to
  both engines with no gap; preparation end to end with the defaults and with the alternatives.

`docs/REVIEWING-A-PREPARATION.md` says what a correct preparation contains, for whoever reviews one before it is run.
