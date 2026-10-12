# 33 — Impact Analysis (`impact-analysis`)

New lifecycle step `impact-analysis`. Owner: **P**. Job: `phase0-repository-discovery`, after test coverage
and before risk scoring. Implemented in **C# / .NET** in the `application-fingerprinting` solution, `process`
adapter.

For each work item, the full set of files its conversion will touch — and what happens to
each — not merely the file where its signal was found.

---

## Part A — The gap this closes

Today the work list shows **where a signal was found**. That is the evidence, not the blast
radius.

Converting a WCF service to REST does not touch one file. It touches the service contract
interfaces, every implementation, the data contracts used in operation signatures, the `.svc`
files, the `system.serviceModel` configuration, the WSDL, the tests, and every client. Some are
updated, some deleted, some rewritten, and some files are created that do not yet exist.

Knowing that set, per work item, is what makes conversion plannable: effort scales with the
impacted files, not the signal files; conversion ordering needs it; and two work items that both
touch a file must be visible before either converts it.

---

## Part B — Placement and renumbering

Inserted as **step 9**, between test coverage and risk scoring:

| Step | Why here |
|---|---|
| 8 Test coverage | Its source-to-test mapping supplies impacted test files |
| **9 Impact analysis** | |
| 10 Risk scoring | Blast radius is a risk factor |

`risk-scoring-tier-assignment` moves from 9 to 10; every later step moves up by one; the
lifecycle becomes 37 steps. **Slugs are unchanged.** Update `17-LIFECYCLE-STEPS.md` to v2.3,
including every cross-reference in step notes that names a renumbered step.

### Structural impact here, client impact at `dependency-and-context-map`

Integration edges — which code calls which service — are built by
`dependency-and-context-map` in the estate job,
which runs after the per-repository job. That includes same-repository edges such as
`Catalog.TestClient` calling `Catalog.Services`.

So the work splits:

- **`impact-analysis`** computes **structural** impact by traversing the repository's own code
- **`dependency-and-context-map`** adds **client** impact at the end of each run, from its integration edges, intra-
  and cross-repository — the same post-step pattern derivations already use

A work item's impact view shows both, labelled by source.

---

## Part C — Impact depends on the resolution

The same item has a different blast radius under each resolution. CoreWCF keeps contracts and
implementations largely intact; a REST rewrite replaces them. So impact rules are **per
resolution**.

### Which resolutions are computed

| Situation | Computed |
|---|---|
| No decision | The **default** resolution |
| Decision made | The **chosen** resolution, and the **default** |
| Every other resolution | Not computed. Shown as pending |

The default is always computed, so a chosen resolution can be compared with the lift-and-shift
baseline: *"your choice touches 40 files; the default touches 12."*

The UI states this plainly: *"Impact is analysed for the default resolution and the chosen one.
Other resolutions are not analysed."*

### When the decision changes

A changed decision means the chosen resolution's impact may not have been computed. Mark that
work item's impact `stale`, naming the resolution, and recompute on the next scan. Stale impact
is shown as stale — never presented as current.

---

## Part D — Impact rules are catalog data

Rules live on each resolution in `catalog_items.yaml`, are seeded through the never-overwrite
path, and are included in the catalog export — the same treatment as derivations. When the
delivery team learns that a resolution touches more than the rules say, they correct the data,
not the code.

### Rule format

```yaml
impact:
  - id: impl
    from: seed
    select: self
    action: rewrite
    reason: "Service implementation becomes REST controller logic"

  - id: contracts
    from: impl
    traverse: implemented_interfaces
    filter: { has_attribute: ServiceContract }
    action: delete
    reason: "WCF service contract is replaced by controller routes"

  - id: data-contracts
    from: contracts
    traverse: signature_types
    filter: { has_attribute: DataContract }
    action: update
    reason: "Remove DataContract attributes; keep as request and response models"

  - id: svc
    from: impl
    traverse: convention_files
    kind: svc
    action: delete

  - id: service-config
    from: impl
    traverse: config_elements
    path: system.serviceModel/services
    action: delete

  - id: tests
    from: [impl, contracts]
    traverse: referencing_tests
    action: update

  - id: controllers
    create: "REST controller per service contract"
    for_each: contracts
    proposed_path: "{project.dir}/Controllers/{type.name}Controller.cs"
    action: create
```

Each rule starts `from` the seed or an earlier rule, applies one primitive, optionally filters, and
assigns an action. Rules compose; ids let later rules build on earlier ones.

### The default rule

An item or resolution with no explicit rules gets one: `from: seed`, `select: self`,
`action: update`. Every work item therefore has at least its own evidence files as impact — never
an empty set.

---

## Part E — Traversal primitives

Deterministic, built on Roslyn syntax and file inspection:

| Primitive | Returns |
|---|---|
| `self` | The seed's evidence files |
| `implemented_interfaces` | Interfaces the given types implement |
| `implementations_of` | Types implementing the given interfaces |
| `signature_types` | Types used in parameters and return values of the given types' members |
| `declaring_files` | Files declaring the given types |
| `referencing_files` | Files referencing the given types |
| `config_elements` | Config files and elements at a path, or naming the given types |
| `convention_files` | Files tied by convention — `.svc`, `.asmx`, `Reference.cs`, WSDL |
| `referencing_tests` | Test files mapped to the given types, from `test-coverage-assessment` |
| `project_file` | The project's `.csproj` |
| `entry_points` | `entry-point-inventory` entry points of the given types |

Filters: `has_attribute`, `in_project`, `namespace_prefix`, `excludes_generated`.

Traversal never leaves the repository in `impact-analysis`. Cross-repository reach is `dependency-and-context-map`'s.

---

## Part F — Actions and certainty

### Actions

| Action | Meaning |
|---|---|
| `update` | Edited in place |
| `rewrite` | Substantially replaced, logic preserved |
| `delete` | Removed |
| `create` | A new file, recorded with a description and proposed path |
| `review` | May need change; a person should check |

### One action per file per work item

Where several rules reach the same file within one work item, keep the strongest action —
`delete`, then `rewrite`, then `update`, then `review` — and record every reason. A file is
listed once.

### Certainty

| Certainty | When |
|---|---|
| `confirmed` | Reached by a deterministic primitive through resolved references |
| `possible` | Reached through a name-based match, an ambiguous type resolution, or a convention that could not be verified |

Reflection and string-based wiring are invisible to syntax. Impact the traversal cannot see is not
claimed. Where an untraceable path is detected, the work item records it as a known limit rather
than implying the set is complete.

### Traceability

Every impacted file records its **traversal path**: *"data contract `PlaceOrderRequest`, used in
`IOrderService.PlaceOrder`, contract of `OrderService`."* Any entry can be explained back to its
seed.

---

## Part G — Overlaps across work items

Impacted files are shared across work items. That is information, not noise.

### Effective resolution

For overlap purposes each work item uses its **effective** resolution: the chosen one where
decided, otherwise the default. That is what will actually be done.

### Hotspots

A file impacted by three or more work items is a hotspot. Converting it is a coordination point.

### Conflicts

| Combination on one file | Result |
|---|---|
| `delete` with any non-`delete` action | **Conflict** |
| `create` with `create` at the same path | **Conflict** |
| `rewrite` with `update` | Not a conflict; ordering matters |
| `update` with `update` | Not a conflict; ordering may matter |

Conflicts are reported per file, naming both work items and their actions. They feed conversion
ordering in Track A.

---

## Part H — LLM residue, deferred

An LLM could surface impacts the traversal misses — reflection, string configuration, convention
wiring — always as `possible`. It depends on the shared provider in
`32-TEST-COVERAGE-ASSESSMENT.md` Part G, which is not yet built.

**`impact-analysis` ships deterministic only.** Confirmed impacts are also the more credible result to put in
front of a client.

---

## Part I — Data model and artifact

| Table | Holds |
|---|---|
| `work_item_impacts` | Work item, resolution, file path (null for create), action, reasons, certainty, rule id, traversal path, source (`structural` or `client`) |
| `impact_summaries` | Per work item per resolution: counts by action, confirmed and possible counts, stale flag |
| `file_impact_rollup` | Per file: impacting work items with effective resolution and action, hotspot, conflicts |

Artifact `impact-analysis@2.1.0` (1.0.0 before the three figures, 2.0.0 before rule ids on the rollup; see As
implemented), deterministic
for given code and decisions.

---

## Part J — UI

### Work item impact

On a work item, its impacted files grouped by action, each with reason, certainty and traversal
path. Where both the default and the chosen resolution are computed, show them **side by side**:

| | Default — CoreWCF | Chosen — REST rewrite |
|---|---|---|
| Rewrite | 1 | 4 |
| Update | 9 | 6 |
| Delete | 2 | 11 |
| Create | 0 | 5 |
| **Files** | **12** | **26** |

Then the file lists beneath, expandable. Other resolutions show the pending note.

### Repository impact summary

Total impacted files by action, hotspots, and conflicts, with each conflict naming its work items.

### Per-file view

For any file, every work item that touches it, with action and resolution.

---

## Part K — Initial rules

Seed explicit rules for the items with impact beyond their own evidence. Everything else takes the
default rule.

| Item | Resolutions with explicit rules |
|---|---|
| `wcf-service` | REST rewrite, CoreWCF, gRPC rewrite, remain Windows-hosted |
| `wcf-service-host` | ASP.NET Core web host |
| `wcf-nettcp-client` | Migrate to the service's new protocol, call HTTP binding |
| `asmx-service` | Its resolutions |
| `aspnet-webforms` | Its resolutions |
| `package-upgrade-breaking` | `self` plus `project_file` — the call sites and the `.csproj` |

`remain Windows-hosted` resolutions impact nothing structural; give them `select: self`,
`action: review`, so the work item is still visible without implying edits.

These are reasonable defaults, not truths. They are catalog data so the delivery team tunes them as
conversions teach them what a resolution really touches.

---

## Acceptance criteria

- [ ] Step inserted at 9; risk scoring at 10; docs/17 at v2.3 with every cross-reference corrected;
      both jobs valid
- [ ] Impact rules are per resolution, in the catalog, seeded through the never-overwrite path and
      included in the catalog export
- [ ] With no decision, only the default is computed; with a decision, the chosen and the default
- [ ] Other resolutions show as pending with the explanatory note
- [ ] A changed decision marks impact stale until the next scan
- [ ] Every work item has at least its own evidence files as impact
- [ ] One action per file per work item, strongest kept, all reasons recorded
- [ ] Every impacted file carries a traversal path back to its seed
- [ ] `create` entries carry a description and proposed path
- [ ] Hotspots and conflicts computed from effective resolutions
- [ ] Client impact added at the end of `dependency-and-context-map`, labelled `client`
- [ ] Two runs over unchanged code and decisions produce identical artifacts
- [ ] The WCF repository's `wcf-service` work item shows REST rewrite and CoreWCF side by side

---

## As implemented

**Step numbers.** This document was written calling the estate step that builds integration
edges "step 11". Inserting this step renumbered it: `dependency-and-context-map` is **step 12**
(`17-LIFECYCLE-STEPS.md` v2.3), and the references above name it by slug.

**Code.** `steps/step-003-fingerprinting/src/Fingerprinting.Impact` (code index, rule engine,
pipeline, rollup) and `Fingerprinting.Impact.Cli` (assembly `ImpactAnalysis.Cli`, published to
`publish/impact-analysis/`), sharing `Fingerprinting.Analysis` and `Fingerprinting.StepHost`.
Registration `registration/impact-analysis.json` (2.1.0). Schema
`schemas/impact-analysis-2.1.0.schema.json`, written by `make_impact_schema_2_1_0.py`
(1.0.0, 2.0.0 and their generators stay for artifacts already written).
`phase0-repository-discovery` (v13 on) wires all four inputs, each required:
`solution-project-inventory` ^2.0.0, `entry-point-inventory` ^2.0.0, `item-occurrences` ^1.0.0,
`test-coverage` ^1.0.0. Decisions and the impact rules are read from the database at run time.

**Work items and seeds.** A work item is a found item on a project, from `item-detection`'s
occurrences. Its seeds are each occurrence's file and every evidence `source_path`
(repository-level evidence excluded). An item matched on project metadata only
(`fx47-class-library`: framework family and output type) is seeded with its `.csproj`, so every
work item has at least its own evidence as impact.

**Resolutions (Part C).** Every active item has exactly one default resolution, enforced by
the database (`trg_item_resolutions_one_default`, CLAUDE.md rule 13). `aspnet-webforms` and
`ssis-package` had none; their factory defaults are `aspnetcore-mvc-rewrite` and
`csharp-sql-pushdown` (`DEFAULT_AMENDMENTS` in `app/items/pattern_migration.py`). The
*presumptive* fallback (lowest consumer impact, labelled so) remains in the code for an item
whose default cannot be read, but no active item reaches it. A decision means a live decision
with a chosen resolution; a pending decision with none counts as no decision.

**Rules (Part D).** `item_resolutions.impact_rules` (JSONB, empty means the default rule),
authored as `impact:` in `catalog_items.yaml`, validated by `backend/app/items/impact_rules.py`
on seed and on import, seeded through `app/items/baseline.py`, and exported. The field is
optional in the baseline: empty rules are left out of the content hash and the export, so
adding it changed no existing baseline or exported file. Primitives beyond Part E: a
`client_call_sites` primitive, which `impact-analysis` records as deferred and `dependency-and-context-map` evaluates; and
`create` rules with `for_each` and `proposed_path` placeholders `{project.dir}`,
`{type.name}` and `{type.base_name}` (`IOrderService` → `OrderService`). The Web Forms rules
live with the pattern migration's resolution amendments (`app/items/pattern_migration.py`),
since those resolutions come from it.

**Certainty and limits (Part F).** Confirmed: reached through a type resolved uniquely (in the
referencing type's namespace or its usings), a `.svc`/`.asmx`/markup directive or a config
element naming the type by full name, a config section in the same project, or a `test-coverage-assessment`
mapping by type reference at confidence 0.8 or more. Possible: an ambiguous type, a match by
simple name only, and svcutil proxies or WSDL that mention the name. A file in the result containing `Type.GetType`,
`Activator.CreateInstance`, `Assembly.Load(From)`, `GetMethod` or `InvokeMember` adds a known
limit naming it. Traversal paths are rendered seed-last, joined by ` ← `.

**An action describes what happens to the file.** `delete` means the whole file goes.
- A config element is part of a file: removing or editing one is an `update` of the file,
  with the element (`element <service> at system.serviceModel/services, line 31`) in the
  entry's `details`. The rule validator refuses `delete` on `config_elements`; the engine
  also turns one into an update if it ever reaches it. Several work items editing one config
  file (`wcf-service`, `sensitive-config-key`, `hardcoded-windows-path`) are therefore
  ordering, not a conflict.
- A type-based `delete` (a contract interface) deletes the file only if every top-level type
  it declares is deleted by that rule; otherwise the file is updated, its details naming the
  type removed and the types it keeps.
- The rule's own action stays in each reason, so the details and the reason together say
  what was asked and what it means for the file.

**Being an item's evidence does not mean its conversion edits that file.** Evidence can be
code the conversion rewrites or a file it makes obsolete, so a `select: self` rule names the
kind of file it acts on with the `extension` filter. `wcf-service-host` → ASP.NET Core web
host: `.cs` evidence (a self-hosted ServiceHost's `Program.cs`) is rewritten; `.svc` evidence
(IIS activation) is deleted, and the ASP.NET Core entry point is *created* at
`{project.dir}/Program.cs`, once per `.svc`-hosted project; the project file is updated.
The same mistake was corrected in `aspnet-webforms` (code-behind rewrite on `.cs` only;
markup evidence deleted) and `asmx-service` (code-behind on `.cs`; `.asmx` evidence deleted).
A `create` whose proposed path names no type creates one file per project; a proposed file
that already exists is recorded as an update of it, with a detail saying so. Two work items
deleting one file agree: not a conflict.

**Conflicts grouped by the rules that produce them** (`backend/app/impact/conflicts.py`).
Each rollup work item carries the rule ids that put it on the file (artifact 2.1.0). A
conflict is keyed by its kind and both sides' item, resolution and rule ids. A key seen on
more than one pair of work items is a **catalog rule conflict**, reported once — "1 rule
conflict affecting N work items" — for catalog authors to fix in the rules; a key seen on
one pair of work items only is a **work-item conflict**, reported individually for a person
to decide (two files where the same two work items conflict by the same rules are still one
pair: one instance cannot show a recurring pattern).

**Classification is estate-wide.** The common case is one instance of a pattern per
repository across many repositories, which no single repository can recognise. So
`impact-analysis` records each conflict per repository with its rule ids, and at the end of
each estate-consolidation run `dependency-and-context-map` (1.5.0) aggregates the keys
across every repository in the engagement (`apply_estate`) into `impact_rule_conflicts`
(migration `c5f8a1d3e7b2`): one row per key seen on more than one pair of work items
anywhere in the estate — "1 rule conflict affecting N work items across M repositories".
The repository summary classifies its own conflicts against that table, so a conflict that
occurs once in a repository is labelled a catalog rule conflict, naming how many
repositories it appears in, when its rule pair recurs elsewhere. A key the last estate run
has not seen is classified from the repository alone (`classified_by: repository`) until the
next run. The engagement's rule conflicts are on the Estate tab (`GET
/api/engagements/{id}/impact/rule-conflicts`, every instance by repository) and, across
engagements, in the master catalog's Rule conflicts tab (`GET
/api/catalog/impact-rule-conflicts`, counts per engagement only — the files are each
engagement's own data).

Before the host rule was corrected, eShopModernizing's two NTier copies showed the pattern
within one repository: `wcf-service` [svc] delete against `wcf-service-host` [host] rewrite
on each copy's `CatalogService.svc`. With the rule corrected, 0 conflicts across the estate.

**Copies of one codebase.** A repository can hold two copies of the same code (eShopModernizing's
Legacy and Modernized NTier solutions) declaring identical full names. A `.svc`/`.asmx`/markup
directive, a config element or a type reference then binds to the copy nearest it by path,
so each copy's work item reaches its own files only. Declarations in one directory (a partial
class across `Default.aspx.cs` and `Default.aspx.designer.cs`) are one copy. A simple-name
match is not taken when the directive's full name is declared by another type.

**Three figures, never added together.** Per resolution: `changed` (update, rewrite, delete
of existing files — the headline), `created` (new files) and `toReview` (files a person should
check). Review is never counted as change: CoreWCF on the WCF repository's `wcf-service` is
16 changed and 13 to review, the REST rewrite 29 changed and 5 new. Client files are counted
the same way (`client_changed`, `client_review`). The repository summary reconciles:
`changes` (one per file per work item) = rewrite + update + delete, across `filesChanged`
distinct files; creates at `newFiles` distinct paths; `filesToReview` counts files with review
marks and no change. Hotspots and conflicts are over every action, review included, per
Part G.

**Tables (Part I).** `work_item_impacts`, `impact_summaries`, `file_impact_rollup` (migrations
`fb29977e6d01`, and `a7d4e2c9b1f3` for the three figures and `details`). `impact-analysis` replaces the repository's rows, client rows included; the next estate
run adds client rows back. A summary records the decision it was computed for
(`decision_resolution_id`).

**Stale (Part C).** `backend/app/impact/stale.py`, engagement-wide and idempotent, runs after
every decision write and supersede, and in `dependency-and-context-map` after decisions are re-derived. A summary
whose recorded decision differs from the live one is stale, with a reason naming both
resolutions; a decision changed back clears it.

**Client impact (Part B).** `backend/app/impact/client.py`, at the end of each
`dependency-and-context-map` run (its version 1.4.0). For each computed resolution with a
`client_call_sites` rule, every integration edge whose entry point is handled in a file the
resolution structurally impacts gives the call-site file the rule's action, one row per caller
file, with a traversal path per call. Confidence 0.8 and above is confirmed. A caller file the
work item already impacts structurally stays structural. The rollup is then recomputed in
Python (`backend/app/impact/rollup.py`) for every repository involved, identical to the .NET
rollup where there are no client rows. Client rows belong to the caller's repository's rollup.

**API and UI (Part J).** `GET /api/repositories/{id}/impact` (totals, hotspots, conflicts, work
items, files; 409 before `impact-analysis` has run) and `GET /api/repositories/{id}/impact/work-item`
(`item_id`, `project_path`): the computed resolutions, default or presumptive first, with
entries grouped by action, and the pending note. The repository page's Impact section shows
the summary, hotspots and conflicts naming their work items, the work item list with the
side-by-side and expandable file lists, and a filterable per-file view.

**Calibration against a hand analysis** (`backend/app/impact/calibration.py`). The rules are
measured against an oracle: `sampleapps/WCF/MODERNIZATION-NET10-REST.md` (sections 6–8),
encoded file by file in `backend/tests/fixtures/impact_oracle/wcf-net10-rest.yaml` with the
scenario's decisions. `impact-analysis` runs in its standalone mode on frozen inputs (the
WCF repository's upstream artifacts and integration edges, beside the oracle) with the
rules from the catalog export; client impact is added from the frozen edges as
`dependency-and-context-map` adds it. Actions fold to the oracle's words (delete, change,
new).

- **Review is an abstention**: never found, never claimed, never agreement. Recall counts
  the oracle's files impact-analysis claims; precision, of the files it claims, those the
  oracle lists; the review rate, the files it only reviews among all it lists, is held under
  a ceiling so a rule cannot gain by reviewing.
- **Every disagreement is classified** in the oracle — `rule_missing`, `rule_wrong`,
  `oracle_wrong`, `scope`, `vocabulary` — and **tagged with the work expected to resolve
  it**: `reachability-analysis`, a supporting item or recipe of
  `35-RECIPE-WCF-SERVICE-REST.md` (`supporting-item:<id>`, `recipe:<id>`), or `out-of-scope`.
  The report projects recall per tag, so each discovery pick's effect is measured as it
  lands. Recall in scope leaves out the files tagged `out-of-scope`.
- `tests/test_impact_calibration.py` holds recall, recall in scope and precision to the
  floors and the review rate to the ceiling recorded in the oracle, and fails on an
  unclassified or untagged disagreement.

| | Recall | Precision | Review |
|---|---|---|---|
| Before calibration | 27/68 = 39.7% | 27/45 = 60.0% | — |
| First calibration (rules) | 32/68 = 47.1% | 32/37 = 86.5% | 13 = 26.0% |
| `deploy_parameter_files`, `hosting_project` | **43/70 = 61.4%** (in scope 43/67 = 64.2%) | **43/44 = 97.7%** | 13 = 22.8% |

The oracle grew from 68 to 70 files when the hand analysis was corrected (Reference.cs settled
as deleted, its regenerated proxy listed as new). Remaining disagreements by the work
expected to resolve them, with recall if each landed: `supporting-item:wcf-service-reference`
9 (74.3%), `supporting-item:dead-code` 5, `recipe:wcf-client-to-rest` 3,
`reachability-analysis` 2, `supporting-item:configmanager-appsettings-read` 2,
`supporting-item:wcf-security-context-read` 2, `supporting-item:webdeploy-parameters` 1,
`out-of-scope` 3.

Calibration corrected `wcf-service` → REST rewrite (service classes and contract interfaces
are updated and kept; data contracts are review; the contracts project and a fault exception
type beside the contracts are added; controllers and the fault filter are created in the
project hosting each contract) and `wcf-service-host` → ASP.NET Core web host (`App.config`,
`Parameters.xml` and the Web Deploy SetParam files deleted; `appsettings.json`, one
`appsettings.{Environment}.json` per SetParam environment and a launch profile created).

Engine additions it brought:

- `project_files` — files in the work item's project matching a name;
- `hosting_project` — the project hosting a contract, from entry-point-inventory's
  `HOSTS_WCF_SERVICE` link, nearest copy where copies of a codebase host one contract name;
- `deploy_parameter_files` — the SetParam / SetParameters files outbound-invocation-inventory
  found for a project, with their environment (LOCAL becomes ASP.NET Core's Development).
  `outbound-invocation-inventory` ^1.3.0 is a fifth required input (step 2.2.0,
  `phase0-repository-discovery` v15);
- placeholders `{node.project.dir}`, `{node.environment}` and `{type.resource}` (IOrderService
  → Orders);
- action `none`, for a traversal later rules build on and that touches nothing itself.

The host's deletion of the SetParam files collides with `hardcoded-windows-path` and
`unqualified-hostname`, which edit them: a conversion ordering constraint
(`28-ITEM-AND-CONVERSION-MODEL.md`, conversion ordering). On one application the pair is a
work-item conflict; recurring across the estate it is one catalog rule conflict.

**Not built.** The LLM residue (Part H).
