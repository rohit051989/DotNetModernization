# 30 — Step 6: Dependency Upgrade Assessment

New lifecycle step 6. Owner: **P**, with an advisory **S** sub-task. Job:
`phase0-repository-discovery`, after step 5 and **before** item detection.
Implemented in **C# / .NET** in the step 3 solution, invoked via the `process` adapter.

Determines, for every third-party package a project uses, whether it can move to the
engagement's target framework, what version it should move to, and which lines of code
break when it does.

---

## Part A — Why it exists and where it sits

### The gap

Moving to .NET 10 is rarely just a framework retarget. Packages must move too, and a
newer package version frequently renames types, removes members or changes signatures.
So upgrading a library is a version bump **plus** changes to every call site using an
API that moved. For a .NET Framework estate this is often the larger share of the work.

### Placement: before item detection

Inserted as step 6, so `item-detection` becomes step 7 and steps 6–35 renumber to 7–36.
Slugs are unchanged.

The reason it precedes item detection: its findings are emitted as **signals**. Item
detection then matches catalog items against them exactly as it does every other
signal, and dependency upgrades become ordinary occurrences in the work list, flowing to
decisions and conversion with no special handling. Placed after item detection, its
findings would need a parallel pipeline.

This step is therefore registered as a signal **producer**, declaring its emitted
signals alongside the step 3 extractors.

---

## Part B — Deterministic version lookup

### B1. No LLM in the lookup

Finding versions is a factual lookup with one correct answer, and an authoritative source
exists. An LLM's knowledge is dated and it would confidently report stale versions. All
lookup is deterministic, via the NuGet protocol.

The LLM role is confined to explaining breaking changes — Part E.

### B2. Feed resolution — client feeds first

| Situation | Feeds used |
|---|---|
| `NuGet.config` declares package sources | **Those sources**, in declared order |
| No `NuGet.config`, or no sources declared | **nuget.org** as fallback |

Resolve `NuGet.config` the way the NuGet client does: repository-level, then user, then
machine, honouring `<clear/>`.

Record per lookup which feed answered:

- `feed_source`: `client_feed` or `nuget_org_fallback`
- `feed_name`: the source's configured name

**A `<clear/>` is deliberate.** A bank that clears nuget.org and points only at
Artifactory has decided what may be used. Respect it: when client feeds are configured,
they are the authority.

### B3. The client-feed gap

When client feeds are configured, also query nuget.org **for comparison only** — never as
the answer — where network policy allows. If a newer compatible version exists publicly
but not in the client feed, set `not_in_client_feed` with both versions:

> Latest public compatible: 13.0.3 — latest in Artifactory: 12.0.1

That is a governance finding: the version exists, but the client has not approved or
mirrored it. Configurable via `compare_public_feed`, default `true`; skipped cleanly if
nuget.org is unreachable.

### B4. Credentials

Feeds typically require authentication. Use the NuGet client's own credential
resolution — `packageSourceCredentials`, environment variables, credential providers.

**Nothing derived from a feed credential is ever persisted**, the same invariant as
connection strings in docs/21 Part G. Feed URLs are stored with userinfo, query and
fragment stripped, per step 5's normalisation.

### B5. The repository stays read-only

`dotnet restore` writes `obj/` and `project.assets.json` into the repository, which steps
1–7 must never do. So:

- direct dependencies come from step 2's `project_packages` — no restore needed
- metadata and package contents are fetched with NuGet's protocol libraries into a cache
  **outside** the repository
- transitive dependencies, if enabled, are resolved by restoring a **copy** of the project
  file and `NuGet.config` in a scratch directory — never in place

`git status` must be clean after the step.

### B6. Lookup cache and determinism

This step depends on external state: a package published tomorrow changes today's answer.
It cannot be deterministic across time, and pretending otherwise would be wrong.

So determinism is defined **against a lookup cache**:

- a `package_lookup_cache` table keyed by `(feed_url_normalised, package_id)` holding the
  version list, deprecation, vulnerability and target-framework data, with `fetched_at`
- a rescan reuses cache entries younger than `lookup_cache_ttl_hours`, default 24
- **two runs against the same cache produce identical artifacts**
- `force_refresh` bypasses the cache
- the cache snapshot time is recorded in `StepOutput.metadata`, per the volatile-field
  pattern, so a result is always read alongside when it was true

### B7. Unreachable feeds

A feed that cannot be reached yields outcome `unknown` with the reason. Never guess, never
silently substitute another feed.

---

## Part C — Per-package assessment

### C1. Target framework

From the engagement's `target_framework` parameter — `net10.0` for TestClientA and
TestClientB.

### C2. Upgrade outcome — one value

| Outcome | Meaning |
|---|---|
| `current` | Already on the latest version supporting the target |
| `upgrade_safe` | A newer compatible version exists and nothing the code calls changed |
| `upgrade_breaking` | A newer compatible version exists and the code calls a changed API |
| `no_compatible_version` | No version supports the target framework |
| `unknown` | Could not be determined — reason recorded |

The **recommended version** is the latest version that supports the target framework,
from the authoritative feed. Not merely the latest version: a package's newest release
may have dropped a framework the project still needs.

### C3. Flags — orthogonal, may co-occur

| Flag | Meaning |
|---|---|
| `deprecated` | Publisher deprecated it, with any suggested replacement recorded. **Upgrading does not clear this** |
| `vulnerable` | Known advisories against the current version, with severity. Records whether the recommended version resolves them |
| `not_in_client_feed` | A newer compatible version exists publicly but not in the client feed |

A package may be `upgrade_breaking` **and** `vulnerable` **and** `deprecated` at once.
That is why these are flags rather than outcomes.

### C4. Safe versus breaking — two methods

**Semver first pass, always.** A major version change is presumed breaking; minor and
patch presumed safe. Cheap and always available, but a heuristic.

**API comparison, refining it.** Download the current and recommended versions to the
cache, extract each assembly for the relevant target framework, and compare their public
surface. ApiCompat or reflection-based comparison. Produces the precise list of removed
types, removed members and changed signatures.

Then intersect with the code: find call sites of each changed member. Syntax search,
guarded by `using` of the package's namespaces — the same approach as step 3's
`SYSTEM_DRAWING_USAGE`, so confidence below 1.0.

Record `classification_method`: `api_diff` or `semver_heuristic`. An API diff showing no
change to anything the code calls makes a major version `upgrade_safe`; a minor version
whose diff hits a call site becomes `upgrade_breaking`. **The diff overrides the
heuristic.**

When assemblies cannot be obtained, fall back to semver, mark the method, and lower
confidence.

---

## Part D — Signals, items and occurrences

### D1. Emitted signals

| Signal | Type | Evidence |
|---|---|---|
| `PACKAGE_UPGRADE_SAFE` | `PACKAGE` | The `PackageReference` line. Value: `{id} {from} -> {to}` |
| `PACKAGE_UPGRADE_BREAKING` | `API_INVOCATION` | **Each affected call site.** Value: `{id} {from} -> {to}: {member}` |
| `PACKAGE_NO_COMPATIBLE_VERSION` | `PACKAGE` | The `PackageReference` line |
| `PACKAGE_DEPRECATED` | `PACKAGE` | The `PackageReference` line. Value carries the suggested replacement |
| `PACKAGE_VULNERABLE` | `PACKAGE` | The `PackageReference` line. Value carries the highest severity |
| `PACKAGE_NOT_IN_CLIENT_FEED` | `PACKAGE` | The `PackageReference` line. Value carries both versions |

Register them in the signal registry with this step declared as their producer. Bump the
registry version in the same change, per the established rule.

### D2. Catalog items

Generic, parameterised by package — **not** one item per library, which would turn the
catalog into a package index.

| Item | Scope | Detects on | Occurrence |
|---|---|---|---|
| `package-upgrade-safe` | occurrence | `PACKAGE_UPGRADE_SAFE` | One per project per package |
| `package-upgrade-breaking` | occurrence | `PACKAGE_UPGRADE_BREAKING` | One per affected file |
| `package-replacement-required` | occurrence | `PACKAGE_NO_COMPATIBLE_VERSION` or `PACKAGE_DEPRECATED` | One per project per package |
| `package-vulnerable` | occurrence | `PACKAGE_VULNERABLE` | One per project per package |
| `package-not-approved` | occurrence | `PACKAGE_NOT_IN_CLIENT_FEED` | One per project per package |

`occurrence_source` groups by `source_path_and_value`, so two packages needing upgrade in
the same project file are two occurrences.

**Ordering constraint:** `package-upgrade-safe` and `package-upgrade-breaking` for the same
package must run as one unit — bump the version, then fix call sites. Record in both items
and in the docs/28 conversion-ordering section.

**`package-replacement-required` needs a client decision.** An abandoned or deprecated
library is a replacement, not an upgrade, and which replacement to adopt is a genuine
choice. Its resolutions present the options, with the publisher's suggested replacement as
the default where one exists.

### D3. Conversion

A natural fit for `invocation.type: copilot` — the Copilot upgrade agent already bumps
packages and fixes common breaking changes — with platform approaches for the cases it does
not handle. Not built in this step; approaches arrive with steps 19 and 20 (renumbered
from 18 and 19 when this step was inserted at 6).

---

## Part E — Advisory explanation (the S sub-task)

For `upgrade_breaking` packages, optionally summarise the change from release notes and
migration guides:

> `JsonConvert.DefaultSettings` is replaced by `JsonSerializerOptions`. Migration pattern:…

- **Advisory only.** It explains; it never decides an outcome, version or call site
- the deterministic API diff is the authority, and the summary is shown beside it
- failure to produce a summary never fails the step
- sends package names, versions and the diffed member names — **no source code**
- `naming_source` style provenance recorded, with the model version
- disabled by default; `enable_change_explanation` turns it on

---

## Part F — Data model

### `package_assessments`

One row per project per direct package: `id` (derived, stable), `repository_id`,
`project_id`, `package_id`, `current_version`, `recommended_version`, `outcome`,
`classification_method`, `deprecated`, `deprecation_replacement`, `vulnerable`,
`vulnerability_max_severity`, `vulnerabilities_resolved_by_upgrade`,
`not_in_client_feed`, `latest_public_version`, `feed_source`, `feed_name`, `confidence`,
`breaking_members` JSONB, `call_sites` JSONB, `step_execution_id`, `assessed_at`.

### `package_lookup_cache`

`feed_url_normalised`, `package_id`, `versions` JSONB, `metadata` JSONB, `fetched_at`.
Primary key `(feed_url_normalised, package_id)`.

### Artifact

`dependency-assessment@1.0.0`, per project, packages sorted by id. Deterministic against
the cache. Summary per project: count by outcome, count flagged deprecated, vulnerable and
not-approved.

---

## Part G — UI

A **Dependencies** section on the repository page. Packages in a table — current version,
recommended version, outcome badge, flags — with `no_compatible_version` and `vulnerable`
sorted first. Breaking packages expand to the changed members and their call sites, each
linking to source. Where `not_in_client_feed` is set, both versions show side by side.

The feed that answered is visible per package, so it is always clear whether a result came
from the client's Artifactory or the nuget.org fallback.

---

## Part H — Not in this step

- **Estate view.** *"Newtonsoft.Json 12 is used in 40 repositories"* aggregates across the
  engagement and belongs with step 11's consolidation, alongside the endpoint register
- **Transitive vulnerability remediation** beyond reporting — fixing a transitive package
  is a package-reference change best made once the direct upgrades land
- **Non-NuGet dependencies** — npm for the parked React work, vendored DLLs referenced by
  `HintPath`. A `HintPath` reference to a vendored DLL is worth flagging as `unknown`, since
  it has no feed to query

---

## Acceptance criteria

- [ ] Step inserted at 6; item-detection is 7; steps renumbered to 36 with slugs unchanged;
      both job definitions updated and valid
- [ ] Registered as a signal producer; its signals in the registry; registry version bumped
- [ ] With a `NuGet.config` declaring sources, those feeds answer and `feed_source` is
      `client_feed`
- [ ] With no `NuGet.config`, nuget.org answers and `feed_source` is `nuget_org_fallback`
- [ ] `<clear/>` is honoured: nuget.org is never used as the answer when client feeds exist
- [ ] A version present publicly but absent from the client feed sets
      `not_in_client_feed` with both versions
- [ ] An unreachable feed yields `unknown` with a reason, never a substituted answer
- [ ] Recommended version is the latest supporting the target framework, not merely latest
- [ ] Deprecated and vulnerable are flags that co-occur with any outcome
- [ ] API diff overrides the semver heuristic in both directions, and
      `classification_method` records which applied
- [ ] Breaking packages record affected call sites
- [ ] The five generic catalog items exist and detect via item-detection with no special
      handling; occurrences appear in the work list
- [ ] No feed credential is persisted; feed URLs are normalised
- [ ] `git status` is clean in every scanned repository; nothing is restored in place
- [ ] Two runs against the same lookup cache produce identical artifacts; cache time is in
      metadata
- [ ] The advisory explanation, when enabled, never alters an outcome and sends no source

---

## As implemented (step 6, scanner 1.1.0, artifact `dependency-assessment@1.1.0`)

Code: `steps/step-003-fingerprinting/src/Fingerprinting.Dependencies` (pipeline) and
`Fingerprinting.Dependencies.Cli` (`DependencyAssessment.Cli.exe`), sharing
`Fingerprinting.Analysis` and `Fingerprinting.StepHost` with steps 3 to 5. Tests in
`tests/Fingerprinting.Dependencies.Tests`, offline: feeds are local folders of packages built
in the test, their assemblies compiled with Roslyn. NuGet's own libraries do the feed work:
`NuGet.Protocol` and `NuGet.Credentials` 7.9.0.

**Which feed is the client's (B2).** NuGet resolves the sources for each project
(`Settings.LoadDefaultSettings` from the project directory, so `<clear/>` and the declared
order are NuGet's own). A source is a **client feed** when it is not nuget.org and is
declared in a repository-level `NuGet.config`, or is an http(s) source declared at user or
machine level. A *local folder* declared only at user or machine level is tooling, not a
client feed — Visual Studio's machine-wide "Microsoft Visual Studio Offline Packages" is the
case on every developer machine — and is recorded with role `ignored`. With client feeds,
every one must answer: an unreachable one makes the package `unknown` (B7), and nuget.org is
consulted for the B3 comparison only. With none, nuget.org answers as
`nuget_org_fallback`.

**Versions.** Step 2's version text, with central package management resolved from the
nearest `Directory.Packages.props`, and `$(Property)` versions expanded from unconditional
literal properties in the project file and the `Directory.Packages.props` /
`Directory.Build.props` files up to the repository root (nearer wins). A version that still
cannot be read is `unknown` with the reason. The project's **current framework** comes from
step 2 only — including a framework set in `Directory.Build.props` or
`Directory.Packages.props` (solution-project-inventory 2.1.0, `target_framework_source`) —
so step 6 and item detection see one answer for the same project.

**Compatibility.** A version supports the target when a dependency group is compatible with
it; when the groups say no, the newest version's own lib/ref folders get a second opinion,
since an MSBuild-targets package can declare a net472 group and still install anywhere.

**Package kind (1.1.0).** `runtime | build | tools | analyzer | content`, from the package's
own files: real `.dll`s under `lib/` or `ref/` (not `_._` placeholders) make it runtime;
otherwise analyzers, then build (`build/`, `buildTransitive/`, `buildMultiTargeting/`), then
tools, then content (`content/`, `contentFiles/`, `staticwebassets/`). A package with no
assets is runtime if it has dependencies, build if not. **Only a runtime package can be
`upgrade_breaking`.** A build, tools or analyzer package with a newer compatible version is
`upgrade_safe` with `classification_method: package_kind`, whatever the version jump. A
content package (bootstrap, jQuery) is also `upgrade_safe`, but a major jump sets
`content_breaking_possible`: markup and CSS may break, which the call-site model cannot see.
Known limit: a meta-package with only a props file and dependencies (Swashbuckle.AspNetCore)
classifies as build; its API lives in its dependencies, which are not direct references and
are not diffed. Its reason says so.

**Safe versus breaking (C4).** For a runtime package: semver presumes, the API diff
overrides. The diff reads the current version's lib (or ref) group nearest the project's
framework — the target's when the framework is unknown — against the recommended version's
group nearest the target, with System.Reflection.Metadata. Source compatibility is the test,
since callers are recompiled: a removed override (calls bind to the base) and an added
optional parameter are not changes. Call sites are matched by syntax, guarded by the type's
namespace and argument count.

**Call-site certainty (1.1.0).** A call site is `ambiguous` when an *unchanged* overload of
the same name accepts the same number of arguments — `Assert.AreEqual(a, b)` when MSTest 4
removed the `IEquatable<T>` overload but kept the generic one — and `confirmed` otherwise.
Ambiguous sites carry confidence 0.4, confirmed 0.7. `breaking_evidence` says what an
`upgrade_breaking` outcome rests on: `confirmed_call_sites`,
`ambiguous_call_sites_only` (the outcome reason starts "possibly breaking"), or
`semver_presumed`.

**Version drift (1.1.0).** A package id referenced at more than one version across the
repository's projects sets `version_drift` on each reference and counts once in
`summary.versionDriftCount`. The Dependencies view groups references by package and version
and shows drifting versions together under the package.

**Determinism and the cache (B6).** The lookup cache (`package_lookup_cache` in the engine,
a JSON file standalone) holds each feed's answer, and also what was read from packages
(lib/ref frameworks, package kind), so a rerun against the same cache reads nothing new. No
fetch time appears in the artifact; `lookup_cache_snapshot_at` is in the step output's
metadata. Packages are downloaded to `%LOCALAPPDATA%\ModernizationPlatform\dependency-cache`
and restores for transitive resolution run in a scratch copy under `%TEMP%`, never in the
repository.

**Items (D2).** `package-replacement-required` matches either signal and locates
occurrences from both with `occurrence_source.also` (28-ITEM-AND-CONVERSION-MODEL.md Part E),
so a package that is both deprecated and without a compatible version is one occurrence.
