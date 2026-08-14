# 17 — Lifecycle Step Register

The canonical list of all 51 lifecycle steps, extracted from the v2 architecture
document sections 6.2 to 6.5. **This file is the source of truth for step names,
numbers and owner codes.** Register steps from here, not from memory.

## Owner codes

| Code | Owner | Meaning |
|---|---|---|
| `P` | Platform (deterministic) | Our code. Reproducible and auditable, no LLM in the path |
| `C` | Copilot engine | Bought capability, invoked headlessly and constrained by our playbook |
| `S` | Custom skill / sub-agent | Our LLM-based capability for judgment work the engine does not cover |
| `H` | Human | Explicit decision or review gate, tier-routed where noted |

Combined codes such as `P + S` mean shared authorship within one step. For
`wf_step_registrations.owner_code`, store the combined string verbatim (`"P + S"`).

## Job assignment

Steps are grouped into jobs. Only `phase0-repository-discovery` is defined today;
jobs marked `*` are deferred until at least one of their steps is ready to build.

| Job | Steps | Scope | Status |
|---|---|---|---|
| `phase0-repository-discovery` | 1, 2, 3, 4, 8, 9, 10 | Per repository | **Defined** |
| `phase0-estate-consolidation` | 5, 6, 7, 11, 12 | Per engagement | Deferred |
| `phase1-target-state-governance` | 13, 14, 15, 16 | Per pattern | Deferred |
| `trackA-application` | 17 – 40 | Per application | Deferred |
| `trackB-wave` | 41 – 51 | Per wave | Deferred |

Phase 0 splits across two jobs because steps 5, 6, 7, 11 and 12 are genuinely
estate-wide — you cannot cluster unmatched patterns, build a cross-repository
dependency graph, or plan waves from a single repository.

## Registration rules

- `step_name` values below are **fixed**. Specs 13, 14 and 15 reference several of
  them directly, and job definition YAML binds to them. Do not re-derive or rename.
- Every step registers as a stub initially: `adapter_type: stub`,
  `exit_status: NOT_IMPLEMENTED`, empty `consumes` and `produces`,
  `implementation_status: stub`.
- Replacing a stub is a registration update only — no job definition change,
  provided `consumes` and `produces` are unchanged.


## Phase 0 — Estate discovery & inventory

| # | step_name | Display name | Owner | Job | Notes |
|---|---|---|---|---|---|
| 1 | `repository-ingest` | Repository estate ingest & inventory creation | `P` | phase0-repository-discovery | Enumerate repositories and create the inventory record set that everything downstream populates |
| 2 | `solution-discovery` | Solution & project discovery per repository | `P` | phase0-repository-discovery | Parse solution and project files; classify application, library, test project |
| 3 | `application-fingerprinting` | Application fingerprinting | `P` | phase0-repository-discovery | Target framework, SDK style, hosting model, namespaces, package references, LOC |
| 4 | `pattern-classification` | Pattern classification against catalog | `P + S` | phase0-repository-discovery | Deterministic rules first; LLM only for ambiguous residue, and its output is a suggestion for human confirmation |
| 5 | `pattern-discovery-clustering` | Pattern discovery clustering for unmatched applications | `P + S` | phase0-estate-consolidation * | Cluster structural signatures into candidate new patterns |
| 6 | `pattern-validation` | Pattern validation | `H` | phase0-estate-consolidation * | Merge into an existing pattern, add as new, or reject as out of scope. Taxonomy errors here propagate into every accelerator |
| 7 | `dependency-graph-construction` | Dependency graph construction | `P` | phase0-estate-consolidation * | Internal and external dependencies, intra- and cross-repository, with shared-library flags |
| 8 | `impact-map-generation` | Impact map generation | `P + S` | phase0-repository-discovery | Region to pattern to scope; LLM narrates regions for human readability |
| 9 | `test-coverage-assessment` | Test coverage & CI maturity assessment | `P` | phase0-repository-discovery | Determines how much characterization testing is needed before automation is safe |
| 10 | `risk-scoring-tier-assignment` | Risk scoring & review tier assignment | `P` | phase0-repository-discovery | Rules over coverage, LOC, shared-library fan-out, external consumers, Windows API count |
| 11 | `inventory-dashboard-population` | Inventory dashboard population | `P` | phase0-estate-consolidation * | Publishes everything above. The program\u2019s single source of truth on progress and blockers |
| 12 | `migration-wave-planning` | Migration wave planning | `P + H` | phase0-estate-consolidation * | Topological grouping from the dependency graph; human confirms wave boundaries |

## Phase 1 — Target state governance

| # | step_name | Display name | Owner | Job | Notes |
|---|---|---|---|---|---|
| 13 | `target-state-options-retrieval` | Target state options retrieval | `P` | phase1-target-state-governance * | Present catalog options for the pattern with consumer-impact and effort ratings |
| 14 | `target-state-approval` | Target state selection & approval | `H` | phase1-target-state-governance * | Client dev team selects from the menu, or explicitly confirms the single available option. Lowest-impact option is presumptive; any deviation requires a recorded forcing factor |
| 15 | `decision-record-capture` | Decision record capture | `P` | phase1-target-state-governance * | Persist decision, rationale, forcing factor, approver and date (Appendix B) |
| 16 | `accelerator-binding` | Accelerator binding | `P` | phase1-target-state-governance * | Bind pattern plus approved target to engine scenario, skills, guardrail playbook and verification oracle |

## Track A — Dev track (per application)

| # | step_name | Display name | Owner | Job | Notes |
|---|---|---|---|---|---|
| 17 | `branch-baseline-record` | Branch creation & baseline SHA record | `P` | trackA-application * | Work never touches the original branch |
| 18 | `baseline-verification` | Baseline verification | `P` | trackA-application * | Does it build and do tests pass today? Without this baseline, later failures cannot be attributed |
| 19 | `api-contract-snapshot` | API contract snapshot | `P` | trackA-application * | Generate OpenAPI or route table pre-migration. The parity baseline for step 32 |
| 20 | `characterization-test-generation` | Characterization test generation | `S` | trackA-application * | Conditional on step 9 falling below the coverage threshold |
| 21 | `guardrail-playbook-generation` | Guardrail playbook generation | `P + S` | trackA-application * | Emit engine playbook and upgrade options for this application: target framework, OCP4 not Azure, lift-and-shift posture. Our primary control lever over the engine |
| 22 | `plan-approval-gate` | Plan approval gate | `H` | trackA-application * | Tier-conditional. Tier 0 and 1 auto-pass; Tier 2 and 3 require sign-off before code is written |
| 23 | `engine-assessment` | Assessment | `C` | trackA-application * | Engine\u2019s own assessment, constrained by step 21 |
| 24 | `plan-validation` | Plan validation | `P + H` | trackA-application * | Auto-reject forbidden actions such as Azure service substitution; human review for Tier 2 and above |
| 25 | `framework-retarget-package-upgrade` | Framework retarget & package upgrade | `C` | trackA-application * | The core transformation |
| 26 | `build-fix-loop` | Build-fix loop | `C` | trackA-application * | Engine\u2019s iterative compile-and-repair cycle |
| 27 | `breaking-change-remediation` | Breaking-change remediation | `C` | trackA-application * | Hosting model, JSON serializer, routing, obsolete API replacement |
| 28 | `windows-to-linux-remediation` | Windows-to-Linux remediation | `S` | trackA-application * | Paths, casing, System.Drawing, registry, certificate stores, encoding. Overrides the engine\u2019s Azure-oriented answers |
| 29 | `configuration-externalization` | Configuration externalization | `P + S` | trackA-application * | Settings to environment variables; prepare ConfigMap and Secret contracts for the DevOps track |
| 30 | `logging-health-endpoint-adaptation` | Logging & health endpoint adaptation | `S` | trackA-application * | stdout structured logging; readiness and liveness endpoints for OCP4 probes |
| 31 | `independent-build-test-verification` | Independent build & test verification | `P` | trackA-application * | Re-run in clean CI. The engine reporting its own success is not verification |
| 32 | `contract-parity-verification` | Contract parity verification | `P` | trackA-application * | Diff post-migration contract against step 19. The evidence for minimal consumer impact |
| 33 | `characterization-test-execution` | Characterization test execution | `P` | trackA-application * | Behaviour parity against the pre-migration baseline |
| 34 | `linux-compatibility-security-scan` | Linux compatibility & security scan | `P` | trackA-application * | Remaining platform-specific API usage, vulnerable packages, hardcoded secrets |
| 35 | `container-build-file-generation` | Container build file generation | `P` | trackA-application * | Dockerfile and ignore file from template: linux-x64, non-root UID, read-only filesystem. The dev track ends here |
| 36 | `evidence-bundle-assembly` | Evidence bundle assembly | `P + S` | trackA-application * | What changed, what was verified, parity results, residual risk. The audit artifact |
| 37 | `pr-creation` | PR creation with structured summary | `P + S` | trackA-application * | Machine-generated summary with the evidence bundle attached |
| 38 | `code-review` | Code review | `H` | trackA-application * | Tier-routed per section 5.8 |
| 39 | `feedback-capture` | Feedback capture | `P` | trackA-application * | Tag corrections by pattern, step and error category |
| 40 | `merge-version-record` | Merge, version record, dashboard update | `P` | trackA-application * | Record which workflow and accelerator versions processed this application |

## Track B — DevOps track (per wave)

| # | step_name | Display name | Owner | Job | Notes |
|---|---|---|---|---|---|
| 41 | `wave-readiness-check` | Wave readiness check | `P` | trackB-wave * | All applications in the wave merged, all shared dependencies migrated, no blocking decisions outstanding |
| 42 | `ocp4-manifest-generation` | OCP4 manifest & Helm chart generation | `P` | trackB-wave * | Deployment, Service, Route, ConfigMap and Secret references, resource limits, probes |
| 43 | `container-image-build-push` | Container image build & registry push | `P` | trackB-wave * | From the step 35 build files, across every application in the wave |
| 44 | `container-smoke-test` | Container smoke test | `P` | trackB-wave * | Run each image; verify startup, health endpoints and a representative live call |
| 45 | `cicd-pipeline-update` | CI/CD pipeline update | `P` | trackB-wave * | Repository pipelines updated to build, push and deploy through the new path |
| 46 | `deploy-non-production-ocp4` | Deploy to non-production OCP4 | `P` | trackB-wave * | Whole wave deployed together so inter-application dependencies resolve |
| 47 | `cross-application-integration-testing` | Cross-application integration testing | `P` | trackB-wave * | The verification that cannot be done per application. Wave-level contract and end-to-end workflow checks |
| 48 | `consumer-regression-verification` | Consumer regression verification | `P` | trackB-wave * | Internal and external consumers of the wave\u2019s endpoints exercised against pre-migration contracts |
| 49 | `performance-resource-baseline` | Performance & resource baseline | `P` | trackB-wave * | Establish OCP4 resource requests and limits against observed behaviour |
| 50 | `release-approval` | Release approval | `H` | trackB-wave * | Wave-level go/no-go, informed by the accumulated evidence bundles |
| 51 | `production-cutover` | Production cutover, parallel run & rollback readiness | `P + H` | trackB-wave * | Cutover plan execution with a defined fallback path; post-deploy verification and dashboard update |

## Verification spine

Steps 18, 19, 32 and 33 form the verification spine: establish a baseline, snapshot
the contract, prove the contract has not moved, prove behaviour has not moved. No
assessed market tool provides any part of it. Treat these four as a unit when
sequencing work.

## Ownership summary

Computed from the table above. Totals to 51.

| Owner | Count | Steps |
|---|---|---|
| `P` | 29 | 1, 2, 3, 7, 9, 10, 11, 13, 15, 16, 17, 18, 19, 31, 32, 33, 34, 35, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49 |
| `P + S` | 7 | 4, 5, 8, 21, 29, 36, 37 |
| `H` | 5 | 6, 14, 22, 38, 50 |
| `C` | 4 | 23, 25, 26, 27 |
| `S` | 3 | 20, 28, 30 |
| `P + H` | 3 | 12, 24, 51 |

The Copilot engine owns **4 steps outright** and shares step 24 — under 10% of the
lifecycle. That figure is the platform thesis and is quoted in the architecture
document; keep it consistent if steps are ever added or renumbered.

Human gates total 5 outright plus 3 shared: taxonomy validation (6), wave boundaries
(12), target state selection (14), plan approval (22), plan validation (24), code
review (38), release approval (50), and production cutover (51).

## Changing this file

Renaming a `step_name` after registration breaks every job definition binding to it.
If a rename is genuinely needed: register the new name, update affected job
definitions, migrate `wf_step_executions` history or accept the discontinuity, then
deprecate the old registration. Do not edit a name in place.
