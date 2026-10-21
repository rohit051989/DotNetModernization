# 31 — `dependency-and-context-map`: Estate Dependency Graph, Context Map & Endpoint Register

Lifecycle step `dependency-and-context-map`. Owner: **P**. Job: `phase0-estate-consolidation`, engagement-scoped.
Implemented in **Python**, in-process or `process` adapter.

The steps from `repository-ingest` to `risk-scoring-tier-assignment` each see one repository. This step sees the whole engagement, and answers the
questions no single repository can.

---

## Part A — Why this step matters

Four outputs, each impossible from one repository:

| Output | The question it answers |
|---|---|
| **External endpoint register** | Which backend services does the estate depend on, and which need a conversation with another team? |
| **Package estate view** | Which library upgrades recur across many repositories, so they are researched once? |
| **Dependency graph** | Which applications depend on which, including across repositories? |
| **Context map** | What sits outside the estate, and how does the estate reach it? |

The endpoint register is the deliverable. If eight repositories call one SOAP endpoint
over NetTcp, that is **one** backend conversation with one team and one lead time —
invisible from eight separate scans. It is the client's own hardest problem in their
assessment.

---

## Part B — Inputs

### B1. Reads from the database, not artifacts

This step is engagement-scoped but its inputs are per-repository rows produced by a
different job. Artifact resolution works within one job, so it cannot reach them — the
same situation as the former clustering step.

It reads `outbound_invocations`, `package_assessments`, `entry_points`, `projects`,
`project_references` and `project_packages` directly, for every in-scope repository in
the engagement.

To preserve lineage, record per repository the `step_execution_id` of the run whose rows
were read.

### B2. Partial estate

Repositories arrive over time; the step runs on whatever has been scanned. Every output
carries coverage:

```json
"coverage": { "repositoriesInEngagement": 50, "repositoriesIncluded": 12,
              "repositoriesPending": 38, "coverageRatio": 0.24, "partialEstate": true }
```

A register built from 24% of the estate is provisional. The UI must say so on every view,
not only in a summary.

### B3. Only used, resolved facts

- outbound invocations with `usage = used` only. Unused clients are dead code and must not
  appear as dependencies
- unresolved endpoints are counted and listed separately, never merged into a guessed host

---

## Part C — External endpoint register

### C1. Grouping

Primary key: **normalised host**. A host is usually one owning team, so it is the unit of
conversation. Within a host, group by path and contract.

```
soap0.services.client-a.example                         ← one conversation
  /AccountService.svc   IAccountService     called by 6 repositories
  /PaymentService.svc   IPaymentService     called by 3 repositories
```

Port is kept on each entry but does not split the host group — different ports on one host
are almost always the same team.

**Group by the production host.** With one configuration file per environment, one
service has a different host in each, and the raw host would split one service and one
owning team across several rows. The engagement setting `production_environment` names
the environment whose host keys the row (as `outbound-invocation-inventory` names environments from file names:
`appsettings.Production.json` → `Production`). A call with a binding for that environment
is filed under that binding's host, and the other environments' hosts are listed beneath
the row. A call with no production binding — or every call, when the setting is not
made — falls back to the host as found, and the row says so (`groupingNote`).

### C2. Per host

| Field | Meaning |
|---|---|
| `host` | Normalised |
| `services` | Path and contract groups beneath it |
| `calling_repositories` / `calling_projects` | Distinct counts, with the lists |
| `mechanisms` | `soap_client`, `http_client`, `database` and so on |
| `bindings` | For SOAP, every binding seen — read with the security mode and credential, never alone |
| `worst_verdict` | Worst Linux verdict across every call |
| `verdict_by_environment` | Per environment, carried from `outbound-invocation-inventory` |
| `requires_backend_change` | True when a call's platform matrix entry (29 C10) says only the endpoint's owner can fix it (`fix.who: backend_owner`) — a named pipe, MSMQ, an NTLM credential |
| `possible_backend_change_reasons` | Fixes that are ours or the owner's, not yet known which (`we_or_backend_owner`) — a Windows credential, which is Kerberos we may configure on our side. Not counted as a required backend change until a probe in a Kerberos environment says so (endpoint-register 1.4.0) |
| `under_review` | Platform matrix entries a probe contradicts (29 C11). Until a reviewer revises one, its verdict is left out of `worst_verdict` and shown as "contradicted by probe — under review", and its fix is not a backend change. Counted apart in the summary (endpoint-register 1.5.0) |

`requires_backend_change` is the field the register exists for. It separates *"we can fix
this in our code"* from *"another team must change their service first"* — and the second
has a lead time that should start now.

### C3. Internal versus external

A host matching an entry point inventoried in **another repository in the engagement** is an
internal dependency — the estate calling itself. Mark it `internal` and link it to the
serving repository and entry point. Everything else is `external`.

A SOAP call matches a WCF service by contract and path, on any host. A SOAP call to an
**ASMX** service has no WCF contract to match. It matches `entry-point-inventory`'s
`asmx_web_method` entries instead, by the `.asmx` service path (the application may sit in a
virtual directory: `/FundsTransferWS/FundsTransferWS.asmx` is `/FundsTransferWS.asmx`) and by
web method. Every operation the call invokes, with its `Async` suffix stripped, must be one of
the service's web methods. On the WCF sample, `ftmt.corp.example.com` (FundsTransferWS) is
served by `wcf-backend`, so its owner is this migration ("ASMX service path and web
methods").

This matters for wave planning: an internal dependency means both sides migrate in a
coordinated way; an external one means a conversation with someone outside the programme.

### C4. Annotations that survive rescans

The register becomes a working tracker. Humans annotate each host:

`endpoint_annotations` — `engagement_id`, `host`, `owning_team`, `contact`,
`conversation_status` (`not_started`, `in_progress`, `agreed`, `resolved`,
`not_required`), `target_date`, `notes`, `served_by_repository`, `updated_by`, `updated_at`.

`served_by_repository` records which of the engagement's repositories serves the host.
Internal HTTP matching is otherwise restricted to loopback addresses, to avoid false
matches (a real host serving `/api/orders` is far more likely someone else's). When a host
is annotated, HTTP calls to it are matched against that repository's routes, and that
repository's only. Loopback matching is unchanged.

**Keyed by normalised host, never by invocation id.** A rescan regenerates invocations; it
must not discard a human's record that a conversation is under way. Same principle as step
6 cluster decisions surviving rescans.

A host with annotations but no remaining calls is retained and marked `no_longer_called`,
not deleted — the conversation history still matters.

---

## Part D — Package estate view

Aggregates `dependency-assessment`'s `package_assessments` across repositories.

| Field | Meaning |
|---|---|
| `package_id` | |
| `repositories` / `projects` | Who uses it |
| `versions_in_use` | Every version seen across the estate, with counts |
| `estate_drift` | Used at more than one version across the estate |
| `recommended_version` | From `dependency-assessment` |
| `outcomes` | Count by outcome across all uses |
| `breaking_members` | Union of changed members hit anywhere |
| `flags` | Deprecated, vulnerable, not-in-client-feed, anywhere |

The value is *research once, apply everywhere*. A breaking upgrade appearing in 40
repositories is one investigation, one conversion approach, and forty applications of it.
Sort by repository count descending, so the widest-reaching upgrades lead.

Estate drift is distinct from `dependency-assessment`'s per-repository drift: Newtonsoft.Json at 12 in one
repository and 13 in another is estate drift even where each repository is internally
consistent.

---

## Part E — Dependency graph

### E1. Nodes and edges

- **Nodes:** projects across the engagement
- **Intra-repository edges:** from `project_references`
- **Cross-repository edges:** a package reference whose id matches a project's package id or
  assembly name in **another** repository in the engagement. Repository A builds
  `ClientA.Common`; repository B references package `ClientA.Common`; that is an edge from B to A

Packages answered by a client feed (`dependency-assessment` `feed_source: client_feed`) are the likeliest
internal packages, so match those first, but match any package id.

### E2. Shared libraries

A project depended on by projects in two or more repositories is a **shared library**. Record
its consumer count. Shared libraries migrate first, and a breaking change in one ripples into
every consumer — so they carry elevated risk regardless of their own size.

### E3. Cycles

Detect cycles. A cycle across repositories means neither side can migrate first, and wave
planning (`migration-wave-planning`) must treat the cycle as one unit. Report every cycle explicitly.

### E4. Reconciling `entry-point-inventory`'s origin

`entry-point-inventory` decides origin per repository, so a module registered in one repository whose source
lives in another was classified `framework`. With the estate view, that is now knowable.

**Do not rewrite `entry-point-inventory`'s rows.** A step owns its rows, and its next rescan would revert
any correction. Record reconciliations in this step's own table:

`origin_reconciliations` — `entry_point_id`, `original_origin`, `reconciled_origin`,
`declaring_repository_id`, `declaring_project_id`, `reason`.

Consumers read `entry-point-inventory`'s origin with this overlay applied. The UI shows the reconciled value
and notes it was corrected estate-wide.

---

## Part F — Context map

External actors — hosts marked `external` in the register — as nodes, with the estate's
applications, and edges typed by mechanism.

Emitted as **Structurizr DSL** for a C4 System Context view, per the v3 architecture
document: machine-readable, diffable, renders without bespoke tooling.

```
workspace {
  model {
    estate = softwareSystem "Engagement estate"
    wsse0 = softwareSystem "soap0.services.client-a.example" "External" { tags "External" }
    estate -> wsse0 "SOAP over NetTcp — 6 repositories"
  }
  views { systemContext estate { include * autolayout lr } }
}
```

Group the estate's applications by repository so the diagram stays legible at fifty
repositories; detail lives in the register, not the picture.

---

## Part I — Integration edges

The register says *which service* a call reaches. Integration edges say *which operation*:
the unit a migration actually breaks or preserves.

### I1. Edges

Each edge carries:
- the caller's project and call site
- the callee's project and entry point
- the mechanism
- the match method and its confidence

Edges are built by matching `outbound-invocation-inventory`'s invoked operations (29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES Part C9, 1.2.0) to `entry-point-inventory`'s
entry points:
- **SOAP** — by contract and operation; the path as well, when the service's address says
- **HTTP** — by verb and route template, on a loopback host or a host annotated
  `served_by_repository` (C4)
- **gRPC** — by service and method

Same-repository edges are included and flagged as such.

### I2. Per entry point

For each entry point a call can reach, report whether an internal caller was found. **Never
label an entry point "unused"**: an operation with no internal caller may still be called
from outside the estate. The wording is *"no internal caller found"*.

### I3. Integration view

On the Estate tab, for each application: the operations it calls (each with the entry
point it reaches, or why none matched) and its own operations that others call.

---

## Part G — Data model and artifacts

| Table | Holds |
|---|---|
| `endpoint_register` | One row per host per engagement, Part C2 fields. Replaced per run |
| `endpoint_register_services` | Path and contract groups per host |
| `endpoint_annotations` | Human annotations. **Never replaced by a run** |
| `package_estate` | One row per package per engagement, Part D fields |
| `dependency_edges` | `from_project_id`, `to_project_id`, `edge_kind` (`project_reference`, `internal_package`), `cross_repository` |
| `shared_libraries` | Project, consumer counts |
| `dependency_cycles` | Member projects per cycle |
| `origin_reconciliations` | Part E4 |
| `integration_edges` | Part I1, one row per matched operation per call site. Replaced per run |
| `integration_entry_points` | Part I2, per entry point: `internal_caller_found` or `no_internal_caller_found` |

Artifacts, all deterministic, sorted keys, coverage carried:

- `endpoint-register@1.1.0` — 1.1.0 adds production-host grouping (C1) and the served-by
  annotations the run used (C4)
- `package-estate@1.0.0`
- `dependency-graph@1.0.0`
- `context-map@1.0.0` — the Structurizr DSL text
- `integration-map@1.0.0` — Part I

Registration: engagement-scoped, `consumes: []` per Part B1, the six artifacts declared in
`produces`.

---

## Part H — UI

A new **Estate** tab at engagement scope.

**Endpoint register** — hosts as rows, sorted with `requires_backend_change` first, then by
calling-repository count. Each row: host, internal or external, services, repositories
calling, bindings, worst verdict, and the annotation fields editable inline. Expanding a host
shows services, calling projects, and per-environment verdicts.

The conversation status column turns the register into a tracker. A summary strip:
*"9 hosts require backend change — 3 conversations under way, 6 not started."*

**Packages** — packages sorted by repository count, with estate drift flagged and breaking
members expandable.

**Dependencies** — shared libraries and cycles as lists. A rendered graph is optional; at
fifty repositories a list of shared libraries and cycles is more useful than a picture.

**Context** — the C4 view rendered from the DSL, with the DSL downloadable.

Coverage — *"12 of 50 repositories included"* — on every view.

**SOAP compatibility** — Part J's report, with its CSV export.

---

## Part J — SOAP backend compatibility report

The client's question: **for each SOAP backend, will the call still work after the move to
.NET 10?** One artifact, `soap-backend-compatibility` 1.1.0 (step version 1.8.0, with
endpoint-register 1.5.0), built from
the same grouping as the endpoint register (Part C1) — `build_register` hands back the calls
it filed under each row — and from outbound-invocation-inventory 1.5.0's two verdicts, each
resting on a matrix entry (29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md C10, C11).

**Per backend host:** whether an estate repository serves it (the register matched it, or a
person annotated `served_by`) — then its owner is this migration — or another team does, with
the owning team a person annotated. **Per calling application and environment:** the address,
binding, effective security mode and credential type (and whether declared or the binding's
default), the **runtime** verdict with the matrix entry it rests on, the **platform** verdict,
and what must change, each change with who makes it:

| Finding | Change | Who |
|---|---|---|
| Runtime `unsupported`: the mode (Message) | The service must offer the binding with Transport or TransportWithMessageCredential over HTTPS | Backend owner |
| | Then repoint the client to it | We |
| Runtime `unsupported`: the binding has no WCF client | The service must also offer basicHttp, wsHttp or netTcp | Backend owner |
| Runtime `unknown` (no entry, or unresolved) | Read the binding and security by hand | We |
| Runtime or platform `unknown` from an entry: unprobed (matrices 1.1.0, the wildcard rule) | Probe the binding, security mode and credential before relying on it (29 C11) | We |
| Runtime `supported_with_caveat` | Check the caveat | We |
| Platform, not `compatible` | The platform matrix entry's `fix.change` — e.g. a named pipe: offer a binding with a Linux client; NTLM: accept another credential | The entry's `fix.who` — backend owner |
| Platform `requires_change`: a Windows credential | Kerberos configuration on our side, or a credential change by the backend's owner | We or the backend owner, not yet known which (the note is the entry's caveat) |
| Platform `requires_change` (an unqualified host) | Change this environment's configuration | We |
| Scanned before 1.4.0 | Rescan: the runtime verdict was never given (`not_assessed`) | We |

"We" is the calling application's side, inside this migration; "backend owner" is the
service's side, and the note says whether that owner is this migration or another team. No
platform change is a rule in code: it is the fix of the platform matrix entry the verdict rests
on (`platformMatrixEntry`, outbound-invocation-inventory 1.5.0).

**Confirmation and probes are read live.** The run records both matrix entries behind each
environment's verdicts. Whether a person has confirmed each, and the probe results recorded on
it (29 C11), are read from the matrix files when the report is served, so a confirmation or a
probe made after the run counts at once. Each verdict shows its entry, its confirmation and
its probes, each probe once though it is recorded on both entries, and the WCF client
version and runtimes its evidence covers.

- **Under review.** A verdict resting on an entry a probe contradicts reads "contradicted by
  probe — under review", never the entry's unrevised verdict (kept as `unrevisedVerdict` for the
  reviewer). The changes that entry implied are withdrawn; each change records its `source`
  (runtime, platform or configuration), so only that entry's changes go. Every total counts it
  apart (`summary.underReview`, the host's `underReview` and chip, the CSV), and recomputes
  the worst verdicts and backend-change counts without it (`soap_compatibility.review`,
  `summarize`).
- **Evidence and the targeted WCF client.** The engagement's target WCF client version is
  an estate setting (`target_wcf_client_version`), or else the version the matrices record for
  its target framework. An entry whose evidence covers an older WCF client is listed in
  `evidencePredatesTarget` and flagged "re-probe".
- **The run's matrices.** The report reads the matrix versions the run recorded
  (`matrixVersion`, `platformMatrixVersion`) and lists in `newerMatrices` any that a newer file
  supersedes: rescan.

The report is a **draft** (a banner in the UI, `readyForClient: false`, and `-DRAFT` in the
export's file name) until every entry it rests on, runtime and platform, is confirmed, none
is contradicted, none has evidence older than the targeted WCF client, and the run used the
newest matrices.

**Per repository.** The repository page's Surface section shows the same answer for one
repository (`GET /api/repositories/{id}/soap-compatibility`): each used SOAP call, per
environment, with binding, effective security, both verdicts, and the confirmation state of
the matrix entry each rests on (who confirmed it, and the decision). Verdicts under review
read as such there too (`wcf_matrix.live_verdict`). It is read from the repository's own
outbound invocations, so a rescan updates it at once, and each call links to its row in this
report. The report itself is rebuilt only by the estate consolidation. When that has not run
since the repository's last scan, the section says so plainly (`estate_stale`, with both
times), and a call the newest estate run does not have says "not in the estate report: rerun
it".

**Export:** `GET /api/engagements/{id}/estate/soap-compatibility.csv`, one row per backend
host, calling application and environment, each carrying the target framework, matrix
version and source, both matrix entries and their confirmation, the probe results and any
contradiction, what the evidence covers and whether it predates the targeted WCF client, so a
row read alone says what it rests on.

---

## Acceptance criteria

- [ ] Reads per-repository rows across the engagement and records the source execution per
      repository
- [ ] Every output carries coverage; the UI shows it on every view
- [ ] Unused clients are excluded; unresolved endpoints are listed separately
- [ ] The register groups by normalised host, with services beneath
- [ ] `requires_backend_change` is true only where a call's platform matrix entry says the
      backend's owner must change; a Windows credential (Kerberos) is a possible backend
      change, listed apart
- [ ] SOAP callers match ASMX services by `.asmx` path and web methods
- [ ] A host served by an entry point in another engagement repository is marked internal and
      linked to it
- [ ] Annotations survive a rescan; a host with no remaining calls is retained as
      `no_longer_called`
- [ ] Package estate shows repositories per package, versions in use and estate drift
- [ ] Cross-repository edges are found by matching package ids to projects in other
      repositories
- [ ] Shared libraries and cycles are identified and reported
- [ ] Origin reconciliations are recorded in this step's table; `entry-point-inventory`'s rows are untouched
- [ ] The context map emits valid Structurizr DSL
- [ ] Two runs over the same data produce identical artifacts

---

## As implemented (`dependency-and-context-map`, version 1.2.0)

Code: `backend/app/estate/analysis.py` (pure functions, tested in
`backend/tests/test_estate_analysis.py`) and `backend/app/steps/estate_map.py` (the
`python` adapter entry point: loads, writes tables and artifacts). Registered from
`backend/app/steps/dependency-and-context-map.registration.json`; runs in
`phase0-estate-consolidation` v5 between the `unclaimed-signal-report` and `migration-wave-planning` stubs. API:
`GET /api/engagements/{eid}/estate` (the newest run's four artifacts plus live
annotations) and `PUT /api/engagements/{eid}/estate/annotations/{host}`. UI: the
**Estate** tab, which replaces the disabled "Dependencies" placeholder tab.

**Inputs and coverage (B1, B2).** A repository is in the engagement when it is not
deleted and its `retirement_status` is `active`, and included once solution-discovery,
entry-point-inventory, outbound-invocation-inventory and dependency-assessment have each
completed for it. Per included repository, `estate_sources` records the newest completed,
not carried-forward execution of each of those steps — the run whose rows are in the
tables — and every artifact carries the same list.

**Development addresses.** Sample and many real repositories carry `localhost` or
`(localdb)` addresses in their checked-in configuration. A loopback host is not a team, so
it is never one register row for everything: a loopback call served by exactly one
repository of the estate is grouped under that repository (`localhost@wcf`); any other
loopback call is grouped by port (`localhost:5433`), since on a developer machine the port
is all that tells two services apart. Rows are flagged `loopback`, and the UI labels them
"development address": the deployed host comes from each environment's own settings.

**Internal versus external (C3).** Entry points carry no host, so matching uses what they
do carry. A SOAP call matches a WCF service by contract and path (the service's address
templates and `.svc` file names), on any host — a contract name is specific enough to trust
across repositories. An HTTP call matches an HTTP route template only on a loopback address
— a real host serving `/api/orders` is far more likely someone else's. Candidates are
ranked same solution folder, same repository, other repository, and the best rank kept; a
loopback port matched once in a repository carries its server to that repository's other
calls on the same port. A match in the **same** repository counts as internal too (the WCF
sample's TestClient calls services its own repository hosts), flagged `sameRepository` on
the link. Internal targets link to the serving project and entry point (the lowest entry
point id of the contract, stable across rescans).

**`requires_backend_change` (C2).** True when a call uses a binding only the service's
owner can replace (`netTcpBinding`, `netNamedPipeBinding`, `netMsmqBinding`, ...) or
Windows-integrated service security (`clientCredentialType` Windows, Ntlm, Negotiate,
Kerberos). The reasons are recorded. Database integrated authentication is not counted:
that is fixed in the caller's connection string, not by the server's owner.

**Annotations (C4).** `endpoint_annotations` is keyed by the register's host and no run
writes it. A host with an annotation and no remaining calls is written to the register as
`no_longer_called` and listed in the artifact's `noLongerCalled`. Annotation fields are not
in the artifacts — they change independently of any scan — and are merged by the API.

**Package estate (D).** `estateDrift` is any package at more than one version across the
estate, as specified. `crossRepositoryDrift` is added: repositories using different
version sets from each other — the Newtonsoft.Json 12-here, 13-there case that `dependency-assessment`'s
per-repository drift cannot see. A package at several versions inside one repository has
estate drift but not cross-repository drift.

**Dependency graph (E).** Cross-repository edges match a package id to another
repository's project by assembly name or project file name (`solution-discovery` records no
`PackageId`); `client_feed` on the edge says whether `dependency-assessment` found the package on a client
feed. Shared libraries count consumer repositories including the project's own. Cycles are
strongly connected components (Tarjan). Origin reconciliation matches a framework-origin
handler type to another repository's project by the longest root namespace or assembly name
that prefixes it; the entry-point inventory API applies the overlay and reports
`origin_reconciled_from`.

**Context map (F).** A Structurizr `systemLandscape` view: one software system per
repository inside a group named for the engagement, External systems for external hosts
(tagged "Development address" and "Backend change" where they apply), relationships
labelled by mechanism and binding with each caller's own project count. Internal hosts
become repository-to-repository relationships; a repository calling itself is not drawn.
The artifact carries the model (`systems`, `relationships`) beside the DSL so the UI draws
the same picture without parsing DSL.

**1.1.0.** Migration `b8e2d4f61a07`.

**Production-host grouping (C1).**
- `engagements.production_environment` is set with
  `PUT /api/engagements/{eid}/estate/settings`, not the engagement PUT, which
  replaces every field and would clear it. It is returned on the engagement
  and in `GET …/estate` `settings`, beside the environments `outbound-invocation-inventory` found and
  the repository slugs.
- The match is case-insensitive.
- A call's production binding is its first binding for that environment
  that names a host. Its host and port key the row, and every other binding's
  host (and the code's own, when different) is listed in `otherHosts` with
  its environments.
- Each row carries `groupedBy`:
  - `production_environment` when any call in it was filed by its production
    binding
  - `host` otherwise
- `groupingNote` says why a row, or part of it, fell back.
- Loopback grouping (`localhost@wcf`) applies to whichever host was chosen.
- The setting takes effect on the next run. The UI says so when the stored
  setting differs from the one the register was built with.

**Carried annotations (C4, step 1.2.0, endpoint-register 1.2.0).**
- Setting a production environment moves calls from a raw host's row to the
  production host's. Without carrying, the raw host's annotation would become
  "no longer called".
- The run builds the register twice: as found (no production environment) and
  grouped. `carry_annotations` then finds each annotated host that is no
  longer a row but whose calls went under a production row, and carries it to
  that row (to each, if the calls split).
- The row lists it in `annotationCarriedFrom`. The register lists the pairs in
  `carriedAnnotations` and leaves the host out of `noLongerCalled`.
  `endpoint_register.annotation_carried_from` holds the same.
- A carried `served_by_repository` applies to the production row unless that
  row is annotated itself.
- The annotation row is never moved, copied or changed by a run: the UI shows
  the carried annotation on the production row, marked as carried, and an
  edit there saves the production row's own annotation.
- On the samples, with PROD set, the one row the grouping removes is
  `localhost:8090` (the FundsTransfer backend's local address). It would carry
  to `ftmt.corp.example.com`.

**`served_by_repository` (C4).**
- Stored as `endpoint_annotations.served_by_repository_id` (FK repositories,
  `ON DELETE SET NULL`). The API speaks slugs and rejects a slug outside the
  engagement.
- An annotation on a loopback row has no effect: loopback matching is
  unchanged.
- The run lists the annotations it used in `endpoint-register`
  `servedByAnnotations`.
- The annotation PUT replaces every field, so the UI sends
  `served_by_repository` on every save.

**Integration edges (I).** `build_integration` in `analysis.py`.
- **SOAP.** WCF operations match on contract and operation: `contract_operation_and_path`
  (0.95) when the call's path is among the service's addresses, else
  `contract_and_operation` (0.85). A client's `FooAsync` matches operation
  `Foo`. ASMX web methods match on service path and method
  (`service_path_and_method`, 0.9).
- **HTTP.** HTTP actions match on verb and route template:
  `verb_and_route_template` (0.9) on loopback, or
  `verb_and_route_template_on_annotated_host` (0.85) against the annotated
  repository only.
  - −0.2 for a partial path, −0.1 for an `ANY`-verb action or an unread verb.
  - An exact verb is preferred over `ANY`, then the route with the most
    literal segments.
  - Conventional routes (no template) cannot be matched; they are reported
    `matchable: false`.
- **gRPC.** gRPC methods match on service and method (`service_and_method`,
  0.95).
- **Ranking.** Candidates are ranked as in the register (same folder, same
  repository, elsewhere) and only the best rank is kept. Where several entry
  points still answer equally, each edge's confidence is capped at 0.5.
- **Unmatched calls.** An operation with no match is listed in `unmatched`
  with the reason: not resolved statically, a host that is neither loopback
  nor annotated, or no entry point serving it.
- **Per entry point.** Every WCF, ASMX, HTTP-action and gRPC entry point
  carries `internalCaller`: `internal_caller_found` or
  `no_internal_caller_found`. The word "unused" appears nowhere.
- **Integration view.** The tab's Integration view shows per application
  (project) the operations it calls and its operations others call.
  `applications` in the artifact is that view's data.

**1.3.0 (endpoint-register 1.3.0).**
- **Who must change (`backendChangeOwner`).** A host or service that requires a
  backend change records who must make it:
  - `this_migration`: the call matched a service in the estate (internal, including
    `localhost@wcf`). The reason reads "the service (wcf) is inside this migration:
    plan its change with its callers".
  - `another_team`: the call matched nothing in the estate. The reason reads
    "another team owns the service: ask them, and start now".
  - `null`: no change is required.
- **Mixed hosts.** On a host row where calls differ, `another_team` wins, because it is
  the change with the longer lead time.
- **Summary.** The summary adds `requiresChangeByAnotherTeam` and
  `requiresChangeInThisMigration`. The Estate tab splits its count in the same way.
  A row's pill reads "another team must change their service" (red) or "change a
  service in this migration" (amber).
- **Decision coupling.** At the end of a run, after its tables are written, the step
  re-derives the dependent decisions of every architecture decision in the engagement
  (28-ITEM Part U). New integration edges can create a derived decision for an
  internal client, and lost edges can supersede one.
- **Migration.** `d82f5c3e19a4` adds `endpoint_register.annotation_carried_from`, which
  was previously added by an edit to `c4a7e1d93b26`. That edit was reverted (see
  CLAUDE.md rule 4).
- **Impact (1.4.0, 1.5.0).** At the end of each run, after decisions are re-derived:
  `impact-analysis`'s staleness is refreshed, its client impact is added from this run's
  integration edges (1.4.0), and catalog rule conflicts are classified across the estate
  into `impact_rule_conflicts` (1.5.0). See `33-IMPACT-ANALYSIS.md`, As implemented.
