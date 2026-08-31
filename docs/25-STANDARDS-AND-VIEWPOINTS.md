# 25 — Standards Conformance & Architecture Viewpoints

Amends `11-STEP-CONTRACT.md`, `02-DATA-MODEL.md`, `10-ENGINE-CONCEPTS.md`,
`17-LIFECYCLE-STEPS.md`, `21-STEP-003-FINGERPRINTING.md` and
`24-STEP-004-CLASSIFICATION.md`.

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

### A3. SARIF export from step 3

Additive — the native artifact stays. Emit `application-fingerprint.sarif` alongside
it as a second declared output, `artifact_type: fingerprint-sarif`, version `2.1.0`
tracking the SARIF spec version.

Mapping:

| Fingerprint | SARIF |
|---|---|
| Signal registry entry | `tool.driver.rules[]` — `reportingDescriptor` with `id`, `name`, `shortDescription`, `properties.category` |
| Signal instance | `results[]` with `ruleId`, `level: "none"` (these are observations, not defects) |
| Evidence span | `locations[].physicalLocation.region.startLine` / `endLine` |
| Source path | `physicalLocation.artifactLocation.uri`, repository-relative |
| `occurrence_count`, `extraction_confidence` | `properties` bag |
| Signal categories | `taxonomies[]` |
| Scanner version | `tool.driver.version` |
| Project | one `run` per project, or `partialFingerprints` — prefer one run per project |

Follow the SARIF specification's normative guidance on deterministic output: stable
array ordering, no absolute paths, no embedded timestamps. Our existing determinism
rules already satisfy most of it.

Validate against the published SARIF 2.1.0 JSON schema before writing. A validation
failure is a step failure.

Note in the step 3 README that a colleague contributing an extractor may deliver
SARIF directly rather than the native signal format, since Roslyn analyzers emit it
natively — that is the point of adopting it.

---

## Part B — Spec-only changes to unimplemented steps

### B1. Step 7 — context map (the capability gap)

Step 7 currently builds a dependency graph of applications and libraries. Extend its
scope to also produce the **Context viewpoint**: which systems call which, including
parties outside the estate.

This is not documentation. The engagement's defining constraint is minimal consumer
impact, and open question 2 in the architecture document — *"are any WCF endpoints
consumed by external clients who cannot change their contract?"* — is currently
answered by asking humans in a workshop. Much of it is derivable.

**Second artifact from step 7: `context-map@1.0.0`.**

Nodes: applications from step 2, plus **external actors** — systems referenced but
not present in the estate.

Edges typed by integration mechanism: `HTTP_CLIENT`, `SOAP_CLIENT`, `GRPC_CLIENT`,
`DATABASE`, `MESSAGE_QUEUE`, `FILE_SHARE`, `SCHEDULED_TRIGGER`, `EMAIL`, `UNKNOWN`.
Each edge carries direction, confidence, and the signals that evidenced it.

**This requires new step 3 signals**, which do not exist in batch 1. Add an
`IntegrationExtractor` to a later extractor batch covering: `HttpClient` and
`WebClient` base addresses, WCF client proxies and `ChannelFactory` usage, generated
service reference clients, connection strings pointing at hosts not in the estate,
`System.Messaging` and `ServiceBus` queue and topic names, SMTP configuration, and
file share paths.

Until those signals exist, step 7 emits a context map containing internal edges only,
with a governance observation naming the missing extractor. Same honesty rule as
`ssis-package` in the catalog: declare the gap, don't fake the output.

Also emit a **C4 System Context view** from the context map, and a **C4 Container
view** per wave from step 12. Structurizr DSL is machine-readable and renders without
bespoke tooling.

### B2. Step 7 — CycloneDX

Emit the external dependency inventory as CycloneDX alongside the native artifact.
Often already a client requirement, and free once the data exists.

### B3. Steps 19 and 32 — OpenAPI and WSDL natively

Step 19 currently specifies "OpenAPI or route table". Make it definite: **emit OpenAPI
3.1 for REST and WSDL 1.1 for SOAP**, never a proprietary snapshot. Step 32 then diffs
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
genuinely earns its keep, and it is what the reserved `S` in steps 3 and 4 owner codes
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
- [ ] Step 3 emits `fingerprint-sarif@2.1.0` as a second output, validating against
      the SARIF 2.1.0 schema before write
- [ ] Two runs produce identical SARIF checksums
- [ ] The SARIF file opens in a SARIF viewer with rules and locations resolving
- [ ] Specs 19, 32 and the step 7 entry in docs/17 updated per Part B
- [ ] `docs/17-LIFECYCLE-STEPS.md` gains a viewpoint column
