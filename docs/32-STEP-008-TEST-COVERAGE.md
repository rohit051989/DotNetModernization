# 32 — Step 8: Test Coverage & CI Maturity

Lifecycle step 8. Owner: **P**, with an LLM veto as a safety sub-task.
Job: `phase0-repository-discovery`, after item detection.
Implemented in **C# / .NET** in the step 3 solution, `process` adapter.

Answers, per source file: is there a test, which test file covers it, what percentage is
covered, and is that unit or integration coverage. Feeds risk scoring and gates
characterization test generation.

This spec also defines the **shared LLM provider** (Part G), which every LLM use in the
platform adopts. Step 8 is its first consumer.

> Step 9, impact analysis, is inserted after this step in a later change. Step 8 keeps its
> number.

---

## Part A — What it produces

| Question | Answered by |
|---|---|
| Do tests exist? | Test discovery, Part B |
| Which test file covers which source file? | Mapping, Part C |
| Has tests, missing, or nothing to test? | Buckets, Part D |
| What percentage is covered? | Coverage sources, Part E |
| Unit or integration coverage? | Classification, Part B, and Part E |
| Is CI mature? | Part H |

---

## Part B — Test discovery and classification

### B1. Finding tests

A test project references a test framework — xUnit, NUnit, MSTest — or a test SDK. A test
class carries test attributes: `[Fact]`, `[Theory]`, `[Test]`, `[TestMethod]`, `[TestCase]`.
Step 3 already emits most of these signals; reuse them.

### B2. Classifying test type

Deterministic first:

| Evidence | Indicates |
|---|---|
| Project name `*.UnitTests`, `*.Tests.Unit` | Unit, strong |
| Project name `*.IntegrationTests`, `*.FunctionalTests`, `*.SmokeTests`, `*.E2E` | Integration / functional / smoke, strong |
| `[Trait("Category", …)]`, `[TestCategory(…)]`, NUnit `[Category(…)]` | As declared, strong |
| `WebApplicationFactory`, `TestServer`, Testcontainers, `Microsoft.AspNetCore.Mvc.Testing` | Integration |
| Real connection strings or service URLs in test code or test config | Integration |
| Only mocking libraries — Moq, NSubstitute, FakeItEasy — and no infrastructure | Unit, supporting |

Types: `unit`, `integration`, `functional`, `smoke`, `unclassified`. Classification is per
test **class**, since one project can mix them. Where evidence conflicts or is absent, the
result is `unclassified` — never guessed.

**Classification is not permission to execute.** A class classified `unit` is still subject
to the two-key isolation check in Part F before anything runs.

---

## Part C — Mapping source files to test files

### C1. Type references — primary

A test class that references a production type is testing it: instantiates it, mocks its
interface, calls its statics, or passes it to an assertion. Resolve each reference to the
source file declaring the type. Syntax-only, so confidence below 1.0 where a type name is
ambiguous across namespaces.

### C2. Naming convention — supporting

`OrderService.cs` ↔ `OrderServiceTests.cs`, and namespace mirroring. Raises confidence where
it agrees with a type reference; alone it gives a low-confidence mapping, marked as such.

A source file may map to several test files, and a test file to several source files.

---

## Part D — Three buckets

Every non-generated source file in a non-test project falls into exactly one:

| Bucket | Meaning |
|---|---|
| `has_tests` | At least one test file maps to it |
| `missing_tests` | Has testable logic, no test maps to it |
| `no_testable_logic` | Nothing to test — a DTO, an enum, auto-properties only |

A file has testable logic when it declares at least one member with a non-trivial body:
methods, constructors with logic, non-auto property accessors. Without the third bucket, every
data class would count as a gap and send someone writing pointless tests.

---

## Part E — Coverage percentages

### E1. Three sources, best available, always labelled

| Source | Exact | When |
|---|---|---|
| `existing_report` | Measured | A Cobertura, OpenCover or lcov report exists in the repository or a configured CI output location |
| `executed` | Measured | Part F approved and ran the test classes |
| `not_measured` | — | Neither applies. The reason is always recorded |

Every percentage carries its source. A `not_measured` file never shows `0%` — it shows the
reason, such as *"isolation not proven"* or *"build failed"*. Zero means measured and
uncovered; not measured means unknown. The same principle as `not_checked`.

### E2. Unit versus integration

- **Unit coverage** — from an existing report, or from executing approved unit test classes
- **Integration, functional and smoke coverage** — from existing reports **only**. Never
  executed during discovery, since these tests reach real systems by design
- **Combined** — the union where both are measured

Where integration coverage has no report, it shows *"not measured — integration tests are not
executed during discovery"*. The asymmetry is honest, not a gap to hide.

### E3. Per-file figures

Line and branch percentage per source file, from Cobertura's per-class data mapped to files.

---

## Part F — Execution safety: two keys

Unit tests may be executed only when **both** keys turn. Either can stop it.

### F1. Key one — deterministic isolation proof

A test class is isolated when nothing it exercises can reach a real system. Proved using data
the platform already has:

| Check | Fails when |
|---|---|
| Outbound reachability | A production type the test exercises has an outbound call site, from step 5, reachable from the exercised members, and that dependency is not mocked |
| Entry-point reachability | The test calls an entry point, from step 4, that the step 4–5 linkage shows reaching a backend, unmocked |
| Infrastructure in the test | Connection strings, service URLs, file paths outside the scratch area, `Process.Start`, network APIs |
| Untraceable paths | Reflection, dependency injection the syntax cannot resolve, a base-class helper outside the traced set |

**Untraceable means not proven, so not run.** A trace that cannot be followed fails safe.

### F2. Key two — LLM veto

The LLM reads the test class and the production code it exercises, and answers one question:
*is there any indication this test reaches real infrastructure?*

- it can only **block**. It never grants permission key one withheld
- **it fails closed**: unavailable, timed out, or an invalid response counts as a veto
- it runs only where key one has already passed, so it reviews a small set
- requires the engagement's `llm_may_receive_source_code` setting. If off, key two cannot turn,
  and nothing executes

### F3. Defences if both keys are wrong

- **scratch copy** — build and run in a copy outside the repository, never in place, so `obj/`
  and `bin/` never touch the repository
- **clean environment** — the test process inherits no environment variables carrying
  connection strings, service URLs or credentials
- **network denied** to the test process where Windows permits, as defence in depth
- **filtered execution** — run only approved classes, via `dotnet test --filter`. Unapproved
  classes in the same project never run
- **time limit** per project, with the run killed and recorded on expiry

### F4. Opt-in

Execution is off by default, enabled per engagement by `execute_unit_tests`. Off, the step
produces mapping, buckets and existing-report coverage only.

### F5. Audit

Every test class records its decision: key one result and reason, key two result and reason,
executed or not, and why. A reviewer can see exactly why any test did or did not run.

---

## Part G — Shared LLM provider

Every LLM use in the platform goes through one provider. Step 8 is the first consumer; step 6's
advisory explanation, step 9's impact residue and Track A's skills adopt it later.

### G1. Configurable per environment

| Provider | Typical environment |
|---|---|
| `claude-code` | Local development — headless `claude -p` with structured output |
| `devin` | Client VDI |
| `none` | No LLM available. Every LLM use degrades per its failure mode |
| `fake` | Tests. Deterministic canned responses, so tests never call a real model |

Selected by environment configuration, overridable per engagement. Switching provider is a
configuration change, never a code change.

### G2. The contract

A request names a **purpose**, a **prompt**, a **JSON Schema** for the response, and inputs.
The adapter returns a response that validates against the schema, or a failure. A response that
does not validate **is** a failure.

Prompts are provider-neutral. Anything provider-specific — invocation, output flags, parsing —
lives in the adapter. Both providers receive the same request and must satisfy the same schema,
which is how "a similar structured response from both" is guaranteed rather than hoped for.

**Batching:** a request may carry many items — several test classes in one call — with the
schema returning one result per item. Required for providers where each call carries real
latency or cost.

The Devin adapter's interaction model is to be verified against Devin's API in the client
environment. This contract defines what the adapter must satisfy, not how Devin achieves it.

### G3. Failure mode is declared per use

| Kind | On failure | Example |
|---|---|---|
| `safety` | **Fail closed** — treat as a block | Step 8 veto |
| `advisory` | **Fail open** — omit the advisory output | Step 6 breaking-change explanation |

Every LLM use declares its kind. A provider outage on the VDI must never silently switch off a
safety check.

### G4. Source code consent

`llm_may_receive_source_code`, per engagement, default **false**. Uses that need source — the
step 8 veto — cannot run while it is false. Uses that send only names and signals are unaffected.

### G5. Audit

Every call records: purpose, provider, model and version, prompt hash, item count, response,
outcome — accepted, invalid or failed — and latency. A veto is always traceable to the provider
and model that made it.

---

## Part H — CI maturity

Per repository, from pipeline definitions — Azure Pipelines, GitHub Actions, Jenkinsfile, TeamCity:

| Fact | Meaning |
|---|---|
| `has_pipeline` | A CI definition exists |
| `runs_tests` | It runs a test step |
| `collects_coverage` | It produces a coverage report |
| `publishes_coverage` | It publishes that report as an artifact |
| `enforces_coverage_gate` | It fails below a threshold |

Feeds risk scoring, and tells Track B what CI work each repository needs.

---

## Part I — Caching

Coverage only changes when code changes. Cache results by **repository commit SHA**: a rescan at
the same commit reuses mapping, buckets and coverage. Static analysis always reruns cheaply;
execution never reruns at an unchanged commit.

---

## Part J — Data model and artifact

| Table | Holds |
|---|---|
| `test_classes` | Project, file, class, test type, classification evidence, test count |
| `test_mappings` | Source file, production type, test class, method, confidence |
| `source_file_coverage` | Source file, bucket, line %, branch %, coverage source, not-measured reason |
| `test_execution_decisions` | Test class, key one result and reason, key two result and reason, executed, reason |
| `ci_maturity` | Per repository, Part H |
| `coverage_scans` | Per repository: commit SHA, cache state, report sources found |
| `llm_calls` | Part G5 audit |

Artifact `test-coverage@1.0.0`, deterministic for a given commit and cache.

---

## Part K — UI

A **Tests** section on the repository page.

**Per source file**

| Source file | Test file(s) | Test type | Line % | Branch % | Coverage source |
|---|---|---|---|---|---|

**Per project**

| Project | Files | Has tests | Missing | No testable logic | Unit % | Integration % |
|---|---|---|---|---|---|---|

**Execution decisions** — why each test class ran or did not, with both keys' reasons. Collapsed
by default.

**CI maturity** — the five facts as a strip.

`not_measured` cells show their reason, never `0%`.

---

## Part L — Build in three phases

| Phase | Scope |
|---|---|
| **1 — Static** | Discovery, classification, mapping, buckets, existing reports, CI maturity. No LLM, no execution |
| **2 — LLM provider** | Part G in full: `claude-code`, `none` and `fake` adapters, the contract, failure modes, consent, audit. Devin adapter stubbed against the contract |
| **3 — Execution** | Part F: both keys, defences, filtering, opt-in, audit |

Each phase lands and is verified before the next. Phase 3 depends on both earlier phases.

---

## Acceptance criteria

**Phase 1**
- [ ] Test classes found and classified; conflicting or absent evidence yields `unclassified`
- [ ] Source files mapped to test files by type reference, with naming as supporting evidence
- [ ] Every source file in exactly one bucket; DTO-only files are `no_testable_logic`
- [ ] Existing coverage reports parsed into per-file line and branch percentages
- [ ] `not_measured` always carries a reason and never displays as `0%`
- [ ] CI maturity's five facts per repository
- [ ] A rescan at an unchanged commit reuses the cache

**Phase 2**
- [ ] Provider selected by configuration; switching is a configuration change only
- [ ] A response that fails schema validation is treated as a failure
- [ ] A `safety` use fails closed; an `advisory` use fails open
- [ ] With consent false, source-sending uses do not run
- [ ] Batch requests return one result per item
- [ ] Tests use the `fake` provider and never call a real model
- [ ] Every call is audited

**Phase 3**
- [ ] Execution off by default; enabled per engagement
- [ ] A test exercising an unmocked type with a reachable outbound call is not run
- [ ] A test calling an entry point that reaches a backend is not run
- [ ] An untraceable path is not run
- [ ] A veto blocks; an unavailable LLM blocks
- [ ] Only approved classes execute, via filter
- [ ] Execution runs in a scratch copy with a clean environment; the repository is untouched
- [ ] Every class records why it did or did not run

---

## As implemented — phase 1 (step 1.0.0, artifact `test-coverage@1.0.0`)

**Code.** `steps/step-003-fingerprinting`:
- `src/Fingerprinting.TestCoverage` holds the analysis: `TestDiscovery`, `TestMapper`,
  `TestableLogic`, `CoverageReports`, `CiMaturityScanner` and `TestCoveragePipeline`.
- `src/Fingerprinting.TestCoverage.Cli` holds the envelope, the database and the cache. It
  shares `Fingerprinting.Analysis` and `Fingerprinting.StepHost` with steps 3 to 6, and is
  published to `publish/test-coverage-assessment/`.

**Registration and job.**
- Registration: `registration/test-coverage-assessment.json`.
- Job: `phase0-repository-discovery` v11 wires both inputs as required, step 2's
  `solution-project-inventory` and step 3's `application-fingerprint`.
- Config: `coverage_report_locations` (CI output directories to search, default none).
- Schema: `schemas/test-coverage-1.0.0.schema.json`, generated by
  `make_test_coverage_schema_1_0_0.py`.

**No LLM and no test execution.** Execution decisions are not recorded yet. The Tests
section says no test is executed. `llm_calls` and `test_execution_decisions` arrive with
phases 2 and 3.

**B — discovery and classification.**
- **Test projects** are those with a test package (xunit, nunit, mstest,
  Microsoft.NET.Test.Sdk) or one of step 3's test signals.
- **Test classes** declare at least one `[Fact]`, `[Theory]`, `[Test]`, `[TestMethod]`,
  `[TestCase]`, `[DataTestMethod]` or `[TestCaseSource]` method. This is syntax, so a
  commented-out class is not a test class.
- **Evidence:**
  - *strong*: the project name, matched as a case-insensitive suffix (so eShopOnWeb's
    `PublicApiIntegrationTests` is integration), and declared categories;
  - *indicative* of integration: WebApplicationFactory, TestServer, Testcontainers, a
    connection-string literal, or a URL to a non-loopback, non-example host, in the class
    or the test project's configuration;
  - *supporting* unit: Moq, NSubstitute or FakeItEasy and no infrastructure.
- **Unclassified** means two strong types disagree, methods declare different categories,
  a declared unit class uses infrastructure, or there is no evidence.

**C — mapping.**
- **Confidence.** Every simple name in the test class that names a production type, except
  as a member name, maps to the file declaring it:
  - 0.90 when the name is unique;
  - 0.80 when ambiguous but the test file's usings pick one;
  - 0.40 to every candidate when still ambiguous.
- **Naming.** Class name, file name or namespace segment minus a test suffix, and namespace
  mirroring with test segments removed. Each adds 0.05, to at most 0.95, and the method
  becomes `type_reference+naming`. Naming alone maps at 0.30 (`naming_only`).
- **Test methods.** Each mapping records the test methods that reference the type; a
  class-level reference counts for all of them.

**D — buckets.**
- **What counts as logic.** A member has testable logic when its body is more than plain
  wiring. Wiring is an empty body, assignments of a name, member chain, literal or
  parameterless `new()`, and a return of one. Top-level statements count as logic.
- **Precedence.** A file without testable logic is `no_testable_logic` even if a test
  references it: a test instantiating a DTO is not a test of it.
- **Ownership.** Each file belongs to the deepest project directory holding it.

**E — existing reports.**
- **Where.** Candidates are named as coverage tools write them. They are found in the
  repository (bin, obj and node_modules skipped) and, in full, in each configured location.
- **Formats.** The format is decided by content: Cobertura per-class lines and
  condition-coverage; OpenCover sequence and branch points; lcov `DA` and `BRDA`.
- **Path matching.** Each report path maps to the longest repository path it ends with. An
  ambiguous or unknown path is listed unmatched, never guessed.
- **Attribution.** A report counts as unit or integration when its test project's classes
  are all of one kind, or when its path names the kind. Otherwise it counts toward the
  combined figure only.
- **Not measured.** A `not_measured` figure has no percentage and always a reason.
  `source_file_coverage` enforces this with check constraints, so 0 can never stand in for
  unknown.

**H — CI maturity.** Covers GitHub Actions, Azure Pipelines, Jenkins and TeamCity. Each
fact is a line-level match recorded as evidence with file and line, and the UI shows it.

**I — cache.**
- **Key.** The repository's commit (`repositories.ingest_commit_sha`) and a key over the
  step version, each project's path, packages and test signals, and the configured
  locations.
- **Reuse.** A run at a computed commit with the same key reuses the stored result: no
  analysis reruns.
- **Not reused** when `git --no-optional-locks status` shows uncommitted changes to
  source, projects, coverage reports or pipelines, or when there is no git history
  (`no_commit`). `--no-optional-locks` means the repository's index is never written.

**J — tables.** Migration `07cbc5eb5298` creates:
- `test_classes`, `test_mappings`, `source_file_coverage` and `ci_maturity`, all replaced
  per repository;
- `coverage_scans`, one row per run, holding the result on every row that computed it. A
  reused row holds none and points at its source; only a `computed` row is ever reused.

**K — UI and API.**
- **API:** `GET /api/repositories/{id}/tests`, 409 until step 8 has run.
- **Tests section** on the repository page:
  - the commit and cache state;
  - the five CI facts, with their evidence;
  - test projects and classes by type, and why each class is classified;
  - the per-project table, and the per-source-file table filterable by bucket;
  - the phase 1 execution note.
- **Not measured** shows as "not measured" with a numbered note, and the reasons are
  listed below the table, readable on a phone.

