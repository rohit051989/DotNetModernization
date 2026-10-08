# 25 — Standards Conformance & Architecture Viewpoints

Amends `11-STEP-CONTRACT.md`, `02-DATA-MODEL.md`, `10-ENGINE-CONCEPTS.md`,
`17-LIFECYCLE-STEPS.md`, `21-APPLICATION-FINGERPRINTING.md` and
`24-PATTERN-CLASSIFICATION.md`.

Two changes, in decreasing order of urgency:

1. **Adopt interchange standards** where one exists, instead of proprietary formats.
2. **Adopt the Rozanski & Woods viewpoint frame** as a completeness lens, which
   exposes one genuine capability gap.

Most of this lands on unimplemented steps and is therefore spec-only. Part A covers
the three changes that touch working code and should be made now.

---

## Part A — Changes to implemented code

### A1. Forcing perspective on decision records

`decision_records.forcing_factor` is free text today. Read against the perspective
framework it is obvious what it actually records: **a quality concern asserting
itself over the lift-and-shift default.** Both seeded examples confirm it — CoreWCF
rejected because WS-Security bindings are unsupported and the security team mandated
removal (Security), and a client standards mandate for minimal APIs (Evolution).

Free text cannot be aggregated. Tagged, it answers a programme-level question:
*"of 47 patterns deviating from lift-and-shift, 31 were security-driven and 12
regulatory."*

**New column on `decision_records`:**

| Column | Type | Notes |
|---|---|---|
| `forcing_perspective` | `TEXT` | CHECK IN (`SECURITY`, `EVOLUTION`, `REGULATION`, `PERFORMANCE_SCALABILITY`, `AVAILABILITY_RESILIENCE`, `LOCATION`, `DEVELOPMENT_RESOURCE`) |

Rename `forcing_factor` to `forcing_rationale` for clarity — it holds the narrative,
the perspective holds the classification.

Validation, extending the rule in `02-DATA-MODEL.md`: when a decision selects an
option that is not the lowest `consumer_impact` among its candidates, **both**
`forcing_perspective` and `forcing_rationale` are required. The existing 422 message
should name both.

Seed data: tag the Reference Engagement B WCF record `SECURITY` and its core2 record
`EVOLUTION`.

UI: the decision form gains a perspective select above the rationale textarea, and
the decision panel displays it as a badge. Add a perspective breakdown to the
engagement coverage endpoint and surface it in the catalog's decision summary — that
rollup is the reason for doing this at all.

Update `docs/02-DATA-MODEL.md`, `docs/03-BACKEND-SPEC.md` and the Appendix B template
reference in the architecture document.

### A2. Viewpoint on step registrations

Cheap, additive, and it lets the platform report assessment coverage rather than
someone maintaining a spreadsheet.

**New column on `wf_step_registrations`:**

| Column | Type | Notes |
|---|---|---|
| `viewpoint` | `TEXT` | CHECK IN (`CONTEXT`, `FUNCTIONAL`, `INFORMATION`, `CONCURRENCY`, `DEVELOPMENT`, `DEPLOYMENT`, `OPERATIONAL`, `NONE`). Nullable — governance and orchestration steps map to no viewpoint |

Populate from the Appendix F mapping. Then:

```
GET /api/engagements/{eid}/viewpoint-coverage
```

Returns, per viewpoint: contributing steps, how many are implemented, how many ran
for this engagement, and a coverage label of `strong`, `partial`, `thin` or `none`
derived from implemented-versus-total. Surface it in Workflow Administration beside
the step registry, and in the engagement dashboard.

The value is honest scoping. "This assessment covers Development and Deployment
fully, addresses Concurrency and Operational partially, and requires stakeholder
input for Context" is a stronger position than implying complete coverage, and it
preempts the question rather than being caught by it.

Update `docs/17-LIFECYCLE-STEPS.md` with a viewpoint column, and
`docs/10-ENGINE-CONCEPTS.md` with the new registration field.

### A3. SARIF export from `application-fingerprinting`

Additive — the native artifact stays. Emit `application-fingerprint.sarif` alongside
it as a second declared output, `artifact_type: fingerprint-sarif`, version `2.1.0`
tracking the SARIF spec version.

**Why this exists — and why it isn't a debugging surface.** SARIF is for external
interoperability: a client's own tooling ingesting our evidence, a contributed
extractor that already speaks SARIF natively (Roslyn analyzers), and standards
conformance the platform can point to in client material. It is **not** an internal
debugging or verification surface — the workflow observability UI (execution detail,
artifact list, step logs) already serves that purpose, is built for this platform's
own data shapes, and doesn't depend on a third-party viewer's own schema-trust
behavior. Do not spend time chasing a viewer-side rendering problem once the file is
independently confirmed correct (schema-valid, every location resolving to a real
file) — see the note below.

Mapping:

| Fingerprint | SARIF |
|---|---|
| Signal registry entry | `tool.driver.rules[]` — `reportingDescriptor` with `id`, `name`, `shortDescription`, `properties.category` |
| Signal instance | `results[]` with `ruleId`, `level: "none"` (these are observations, not defects) |
| Evidence span | `locations[].physicalLocation.region.startLine` / `endLine` |
| Source path, when `evidence_kind: FILE` | `physicalLocation.artifactLocation.uri` (repository-relative) + `uriBaseId: "REPOROOT"` |
| Source path, when `evidence_kind: FOLDER` or `NONE` | no `locations` at all; a `FOLDER` path goes in `properties.folderPath` instead — see the addendum below |
| `occurrence_count`, `extraction_confidence` | `properties` bag |
| Signal categories | `taxonomies[]` |
| Scanner version | `tool.driver.version` |
| Project | one `run` per project, or `partialFingerprints` — prefer one run per project |

Follow the SARIF specification's normative guidance on deterministic output: stable
array ordering, no absolute paths, no embedded timestamps. Our existing determinism
rules already satisfy most of it.

Validate against the published SARIF 2.1.0 JSON schema before writing. A validation
failure is a step failure.

**`uriBaseId` is required, not optional.** A repository-relative `uri` with no
`uriBaseId` resolves, per the SARIF spec, against whatever the *viewer's own*
working directory happens to be — not the scanned repository. In practice this means
a viewer opened anywhere other than the exact scanned root reports every location as
unresolvable (observed: VS Code's SARIF viewer, `"Unable to find
'ConfirmEmail.cshtml.cs'"`). Every `artifactLocation` in `results[].locations` must
carry `uriBaseId: "REPOROOT"`, and the enclosing `run` must declare `REPOROOT` in
`originalUriBaseIds` — the schema requires the id to be declared even when nothing
resolves it.

This creates a determinism conflict: `originalUriBaseIds.REPOROOT.uri` is exactly the
kind of absolute, machine-specific path the "no absolute paths" rule above forbids,
but a real viewer needs *some* absolute path to resolve against. Resolve it with two
files, not one:

1. **The registered, checksummed output** (`application-fingerprint.sarif`,
   `fingerprint-sarif@2.1.0`) declares `originalUriBaseIds: { "REPOROOT": {} }` —
   the id is present so the schema and every `uriBaseId` reference are valid, but its
   `uri` is omitted entirely. No absolute path enters the file, so the determinism
   guarantee (identical checksum for identical input, on any machine) holds.
2. **A local-only sibling** (`application-fingerprint.local.sarif`, same directory)
   is byte-identical except `originalUriBaseIds.REPOROOT.uri` is filled in with this
   machine's actual repository root as an absolute `file://` URI (trailing slash, so
   relative URIs resolve as directory children per RFC 3986). This file is never
   declared as a step output, never checksummed, and gitignored — it exists purely
   so a developer on this machine can open it in a SARIF viewer and have locations
   resolve. Rebuild it on every run alongside the registered file; do not hand-edit it.

A step emitting SARIF should build both from the same in-memory log — everything
except that one field is shared — rather than writing the sibling as a
post-processing patch over the registered file.

Note in the `application-fingerprinting` README that a colleague contributing an extractor may deliver
SARIF directly rather than the native signal format, since Roslyn analyzers emit it
natively — that is the point of adopting it.

**Not every signal's evidence is a location a viewer can open.** SARIF's
`physicalLocation` means a location *within* an artifact — a byte or line range a
viewer can navigate to. A folder-presence signal (`FileIndicatorExtractor`'s
`CONTROLLERS_FOLDER`, `SERVICES_FOLDER`, ... — eight of the ninety-one registered
signals) has a `sourcePath` that is a directory (e.g.
`src/ApplicationCore/Services`), not a file: no line range makes sense for it, and a
viewer that tries to open it as one fails outright.

Fix the mapping table's "source path" row: it undersold this as "repository-relative"
without saying *what kind of thing* — the row is the same regardless of whether the
signal observed a file or a folder, which is exactly the gap that let this ship. The
signal registry now carries an `evidence_kind` field per signal name (`FILE`,
`FOLDER`, or `NONE` for a signal with no navigable source path at all) — audit every
signal type against it, not just the ones a spec author happens to think of; get one
wrong and a viewer breaks on the first repository that has one. The SARIF builder
decides from this field, not from a per-name guess: `evidence_kind != FILE` emits no
`locations` for that result at all (the folder path is still worth keeping — put it
in `properties.folderPath` instead). Two files is still the shape (registered vs.
local, above); this addendum only changes when the "location" half of that shape gets
populated.

**Fix it at the source, not only in the SARIF writer.** The same `sourcePath` is
recorded in the native `application-fingerprint` artifact and in
`fingerprint_signals` — a future consumer of either (`pattern-classification`'s evidence links per
§20/§24, a "view evidence" UI) would hit the identical bug the SARIF viewer did if
`evidence_kind` only existed inside the SARIF builder's head. Stamp
`Signal.evidenceKind` centrally, once, from the registry — the single source of
truth per signal name — onto every signal in the native artifact
(`application-fingerprint@1.1.0`, see `21-APPLICATION-FINGERPRINTING.md` Part F) and the
`fingerprint_signals.evidence_kind` column, not just the SARIF projection.

Add a test asserting every `physicalLocation` in the emitted SARIF resolves to a real
file on disk — never a directory, never a missing path. Run it against a real
repository, not only a synthetic fixture; a folder-evidence bug like this one is
exactly the kind a hand-built two-signal fixture can miss by construction.

**Closed: the VS Code SARIF Viewer blank-panel report.** After the `uriBaseId` and
`evidence_kind` fixes above, a blank panel remained when opening the file directly in
VS Code's SARIF Viewer extension. Independently confirmed correct: schema-valid
against the published SARIF 2.1.0 schema, and every `physicalLocation` resolves to a
real file on disk (the automated test above). The remaining symptom is that
extension's own schema-trust behavior toward a `$schema` URL it doesn't recognize as
one of its pinned trusted dialects — not a defect in this platform's output. Per the
"why this exists" note above, this is not worth further investigation: SARIF here is
for external interoperability, not internal debugging, and the workflow observability
UI is the actual verification surface for this platform's own runs. Do not resume
work on making a third-party viewer render this file.

---

## Part B — Spec-only changes to unimplemented steps

### B1. `dependency-graph-construction` — context map (the capability gap)

`dependency-graph-construction` currently builds a dependency graph of applications and libraries. Extend its
scope to also produce the **Context viewpoint**: which systems call which, including
parties outside the estate.

This is not documentation. The engagement's defining constraint is minimal consumer
impact, and open question 2 in the architecture document — *"are any WCF endpoints
consumed by external clients who cannot change their contract?"* — is currently
answered by asking humans in a workshop. Much of it is derivable.

**Second artifact from `dependency-graph-construction`: `context-map@1.0.0`.**

Nodes: applications from `solution-discovery`, plus **external actors** — systems referenced but
not present in the estate.

Edges typed by integration mechanism: `HTTP_CLIENT`, `SOAP_CLIENT`, `GRPC_CLIENT`,
`DATABASE`, `MESSAGE_QUEUE`, `FILE_SHARE`, `SCHEDULED_TRIGGER`, `EMAIL`, `UNKNOWN`.
Each edge carries direction, confidence, and the signals that evidenced it.

**This requires new `application-fingerprinting` signals**, which do not exist in batch 1. Add an
`IntegrationExtractor` to a later extractor batch covering: `HttpClient` and
`WebClient` base addresses, WCF client proxies and `ChannelFactory` usage, generated
service reference clients, connection strings pointing at hosts not in the estate,
`System.Messaging` and `ServiceBus` queue and topic names, SMTP configuration, and
file share paths.

Until those signals exist, `dependency-graph-construction` emits a context map containing internal edges only,
with a governance observation naming the missing extractor. Same honesty rule as
`ssis-package` in the catalog: declare the gap, don't fake the output.

Also emit a **C4 System Context view** from the context map, and a **C4 Container
view** per wave from `migration-wave-planning`. Structurizr DSL is machine-readable and renders without
bespoke tooling.

### B2. `dependency-graph-construction` — CycloneDX

Emit the external dependency inventory as CycloneDX alongside the native artifact.
Often already a client requirement, and free once the data exists.

### B3. `contract-snapshot` and `contract-parity-verification` — OpenAPI and WSDL natively

`contract-snapshot` currently specifies "OpenAPI or route table". Make it definite: **emit OpenAPI
3.1 for REST and WSDL 1.1 for SOAP**, never a proprietary snapshot. `contract-parity-verification` then diffs
standard artifacts, which means the diff can be done with existing tooling and the
result is meaningful to a client architect without explanation.

This matters more than it looks. The contract-parity spine is the core of the
consumer-impact argument, and "we diff your OpenAPI before and after" is a claim a
client can verify independently.

### B4. Functional viewpoint — business capability mapping

Recorded as a deliberate gap, not scheduled work.

Architecture extraction has standards; **functional building blocks do not**, because
the mapping from code to business capability is not derivable from syntax. What is
standardized is the target taxonomy — APQC's Process Classification Framework
cross-industry, BIAN for banking, eTOM for telecom.

If capability mapping is later required, the approach is: adopt an external reference
taxonomy rather than inventing one, and treat code-to-capability mapping as
LLM-proposed and human-validated. That is the one place in this pipeline where an LLM
genuinely earns its keep, and it is what the reserved `S` in the `application-fingerprinting` and `pattern-classification` owner codes
anticipates. It stays out of the deterministic path.

---

## Part C — Not adopted, and why

| Standard | Decision |
|---|---|
| **OMG KDM / ISO/IEC 19506** | Cite, do not implement. The formal ADM standard, reconfirmed 2025, and conceptually aligned — but only four of seven planned metamodels shipped, tooling is maintained by essentially one vendor, and it assumes QVT transformations we will not write. Adopting it adds modelling ceremony without changing an outcome |
| **UML / XMI** | No. Superseded in practice for this purpose |
| **LSIF / SCIP** | No. Symbol-level code intelligence for navigation, not architecture |
| **Code Property Graph** | No. Security-analysis oriented, not formally standardized |
| **ISO/IEC/IEEE 42010** | Implicitly, via Rozanski & Woods. The standard defines vocabulary; the framework supplies the viewpoints |

State the KDM alignment in client material. It is a genuine credibility marker with
an architecture function, and citing a standard you have consciously chosen not to
implement — with reasons — reads as judgement rather than ignorance.

---

## Acceptance criteria

- [ ] `forcing_perspective` added; `forcing_factor` renamed to `forcing_rationale`
- [ ] A higher-impact selection without both perspective and rationale returns 422
      naming both
- [ ] Seeded Reference Engagement B decisions tagged `SECURITY` and `EVOLUTION`
- [ ] Decision form has a perspective select; the panel shows it as a badge
- [ ] Engagement coverage reports a perspective breakdown
- [ ] `viewpoint` added to step registrations and populated for all 51 steps
- [ ] `GET /api/engagements/{eid}/viewpoint-coverage` returns per-viewpoint coverage
      labels, surfaced in Workflow Administration and the dashboard
- [ ] `application-fingerprinting` emits `fingerprint-sarif@2.1.0` as a second output, validating against
      the SARIF 2.1.0 schema before write
- [ ] Two runs produce identical SARIF checksums
- [ ] Every location carries `uriBaseId: "REPOROOT"`; the registered file declares
      `originalUriBaseIds.REPOROOT` with no `uri`, and a gitignored
      `*.local.sarif` sibling fills it in for local viewing
- [ ] The SARIF file opens in a SARIF viewer with rules and locations resolving
- [ ] The signal registry carries `evidence_kind` (`FILE`/`FOLDER`/`NONE`) per
      signal name; a `FOLDER` or `NONE` signal never emits a SARIF `physicalLocation`
- [ ] `Signal.evidenceKind` is stamped centrally from the registry onto the native
      `application-fingerprint` artifact and `fingerprint_signals.evidence_kind`, not
      only computed inside the SARIF builder
- [ ] A test asserts every emitted `physicalLocation` resolves to a real file on
      disk (never a directory, never a missing path), run against a real repository
- [ ] The `contract-snapshot` and `contract-parity-verification` specs and the
      `dependency-graph-construction` entry in docs/17 updated per Part B
- [ ] `docs/17-LIFECYCLE-STEPS.md` gains a viewpoint column
