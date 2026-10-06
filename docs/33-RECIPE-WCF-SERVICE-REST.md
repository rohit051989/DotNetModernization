# 33 — Worked Recipe: `wcf-service` → REST on .NET 10

**Status: Draft, document only.** No approach in this recipe is built, and nothing has been
converted. This document is the first worked example of `32-CONVERSION-ARCHITECTURE.md`,
and the specification its approaches will be built and certified against.

| | |
|---|---|
| **Recipe** | `wcf-service-rest` v0.1.0 |
| **Binds** | item `wcf-service`, resolution `wcf-service-rest-rewrite` (`backend/app/seed/data/catalog_items.yaml`) |
| **Coupled recipe** | `wcf-client-to-rest` for `wcf-nettcp-client` / `migrate-to-service-protocol` (Part F) |
| **Layouts** | `side_by_side` (worked here), `in_place` |
| **Fixture** | `sampleapps\WCF` (WCF Catalog, .NET Framework 4.7.2, 5 services, 17 operations) |
| **Oracle** | `sampleapps\WCF\MODERNIZATION-NET10-REST.md`, the hand analysis of the same conversion. A certified recipe must reproduce it (Part I) |

---

## Section index

| Part | Covers |
|---|---|
| A | Scenario and scope |
| B | Inputs and preconditions |
| C | Supporting items |
| D | Resolution parameters and target contract |
| E | Recipe steps |
| F | Coupled recipe: the internal client |
| G | Plan on the fixture: slices and units |
| H | Equivalence on the fixture |
| I | Certification on the fixture |
| J | What this recipe does not automate |
| K | Open points |

---

## Part A — Scenario and scope

The client keeps the legacy SOAP service in production unchanged. A new .NET 10 REST service
is built **alongside** it, and clients move to REST over time. So:

- **Layout:** `side_by_side`. Legacy is read-only (32 B7). The target is a new solution root.
- **Converted:** the inbound protocol (SOAP → REST) and the runtime (.NET Framework 4.7.2 →
  .NET 10).
- **Not converted:** business logic, request and response schemas, and **outbound SOAP
  calls**. The call to FundsTransferWS stays SOAP 1.1 over `basicHttpBinding`; only its
  client code is regenerated, because .NET 10 cannot read `<system.serviceModel>` from
  `App.config`.
- **Derived decisions** (28 Part U), already declared on the resolution:

  | Item | Effect |
  |---|---|
  | `wcf-service-host` | Derived → `wcf-host-aspnetcore-web-host`. Carried out by this recipe's step F08 |
  | `fx47-class-library` | Subsumed. Retargeting is step F02 |
  | `wcf-nettcp-client` (internal clients) | Derived → `migrate-to-service-protocol`. Carried out by the coupled recipe (Part F) |

---

## Part B — Inputs and preconditions

### B1. Discovery outputs consumed

| From | Used for |
|---|---|
| Step 2 projects | Retarget targets, project roles |
| Step 4 entry points | Slices: one per service contract; the operations each slice owns |
| Step 5 outbound invocations, **with deploy-time configuration** (32 Part L) | The outbound SOAP client to keep, and its per-environment addresses from `SetParam.xml` |
| Step 7 occurrences of the supporting items (Part C), **with anchors** | Unit targets |
| `reachability-analysis` (32 Part L) | Dead code excluded from the scaffold or removed by F10 |
| Step 15 contract snapshot | Source contract for the mapping |
| `target-contract-design`, signed off at gate 18 | Routes, verbs, fault → status rows (Part D) |
| `behaviour-baseline-capture` | Replay cases per operation (Part H) |

### B2. Blockers

The recipe stops at planning if any of these items is found on the service project:

| Blocker item | Why REST conversion cannot be mechanical |
|---|---|
| `wcf-duplex-contract` | Callbacks have no REST equivalent |
| `wcf-session-instancing` | `PerSession`/`Single` instancing holds per-client state |
| `wcf-message-contract` | Message headers and body members need a per-operation design |
| `wcf-known-type-hierarchy` | Polymorphic payloads need explicit JSON type mapping |
| `wcf-transaction-flow` | Distributed transactions do not cross REST |
| `wcf-message-signing-required` | The client requires WS-Security message signing to be preserved, not replaced by transport security |
| `msmq-usage` (exists) | Queued transport |

**On the fixture: none present.** The secure group's `TransportWithMessageCredential` is not a
blocker: replacing it with transport mTLS is an engagement decision (Part D), not a code
shape.

### B3. Preconditions (32 Part E)

- Step 14: legacy builds and its tests pass at `legacy_commit`.
- Every slice has baseline cases (Part H).
- Every supporting item is `ready` (two-state readiness, 28 Part C). **Today none are**: their
  signals do not exist yet (Part C). The recipe stays `draft` until they do.

---

## Part C — Supporting items

Each is a catalog item with `kind: supporting`, `parent_item: wcf-service`. They are detected
by step 7 and take their decision from the parent (32 C2).

| Supporting item | Scope | Detects | Signal (proposed) | Fixture count |
|---|---|---|---|---|
| `wcf-service-contract-decl` | occurrence | An interface carrying `[ServiceContract]` | `WCF_SERVICE_CONTRACT_DECL` | 5 |
| `wcf-service-behavior-attr` | occurrence | `[ServiceBehavior]` on a service class | `WCF_SERVICE_BEHAVIOR_ATTR` | 5 |
| `wcf-fault-throw` | occurrence | `throw new FaultException<T>(…)` | `WCF_FAULT_THROW` | 18 |
| `wcf-security-context-read` | occurrence | `ServiceSecurityContext.Current` / `OperationContext.Current` | `WCF_SECURITY_CONTEXT_READ` | 1 |
| `configmanager-appsettings-read` | occurrence | `ConfigurationManager.AppSettings[...]` in library code | `CONFIGMANAGER_APPSETTINGS_READ` | 2 |
| `wcf-client-config-construction` | occurrence | `new XClient()` where `XClient : ClientBase<T>` and the address comes from config | `WCF_CLIENT_CONFIG_CONSTRUCTION` | 3 |
| `wcf-service-reference` | application | A `Service References\` folder with `Reference.svcmap` | `WCF_SERVICE_REFERENCE` | 1 |
| `webdeploy-parameters` | application | `Parameters.xml` plus `SetParam.xml` files that target the project's config | `WEBDEPLOY_PARAMETERS` | 1 (6 files) |
| `dead-code` | occurrence | Unreachable members, write-only fields, config keys nothing reads, unbuilt folders | `UNREACHABLE_MEMBER`, `WRITE_ONLY_MEMBER`, `UNREAD_CONFIG_KEY`, `UNBUILT_SOURCE_FOLDER` | 12 findings (X1–X12) |

**Readiness today: all `not_ready`.** None of these signals exists in the registry. Only
`EXPOSES_WCF_SERVICE` and `WCF_SERVICE_HOSTING`, used by `wcf-service` itself, do.
`WCF_SERVICE_CONTRACT_DECL` may duplicate an existing step 3/4 signal under another name;
confirm before adding. Each signal needs an extractor claim and **anchors** (32 C3).

---

## Part D — Resolution parameters and target contract

### D1. Resolution parameters

Client choices, passed to every approach as data (28 Part L).

| Parameter | Fixture value | Meaning |
|---|---|---|
| `target_framework` | `net10.0` | |
| `public_port` / `secure_port` | `8443` / `8543` | Kestrel endpoints |
| `secure_contracts` | `IOrderService`, `IAccountService`, `IFundsTransferService` | Served only on the secure port |
| `secure_group_auth` | `mtls` | Replaces wsHttp `TransportWithMessageCredential` + X.509. **An engagement decision, recorded with its rationale** |
| `client_cert_trust` | `trusted_people_store` | PeerTrust equivalent; `allowlist` and `chain` are the alternatives |
| `server_cert_subject` | `CN=WcfCatalogDev-Server` | Loaded by Kestrel from `CurrentUser\My` |
| `caller_identity_format` | `"{Subject}; {Thumbprint}"` | Keeps `PlacedByCertificateSubject` values as WCF produced them |
| `json_naming` | `as_declared` | `PropertyNamingPolicy = null` |
| `fault_status_map` | engagement conventions (32 Part G) | |
| `outbound_soap` | `keep` | Regenerate the proxy with `--sync`; address from config |

### D2. Target contract (output of `target-contract-design`, signed off at gate 18)

| # | Operation | Verb | Route | Port | Faults → status |
|---|---|---|---|---|---|
| 1 | `IUtilityService.Ping` | GET | `/api/v1/utility/ping` | public | — |
| 2 | `IUtilityService.GetServerTimeUtc` | GET | `/api/v1/utility/time` | public | — |
| 3 | `IProductService.GetProduct` | GET | `/api/v1/products/{productId:int}` | public | ProductNotFound 404 |
| 4 | `IProductService.SearchProducts` | POST | `/api/v1/products/search` | public | Validation 400 |
| 5 | `IProductService.CreateProduct` | POST | `/api/v1/products` | public | Validation 400 |
| 6 | `IProductService.AdjustStock` | POST | `/api/v1/products/{productId:int}/stock?quantityDelta=` | public | ProductNotFound 404, InsufficientStock 409 |
| 7 | `IOrderService.PlaceOrder` | POST | `/api/v1/orders` | secure | Validation 400, ProductNotFound 404, InsufficientStock 409 |
| 8 | `IOrderService.GetOrder` | GET | `/api/v1/orders/{orderId:guid}` | secure | OrderNotFound 404 |
| 9 | `IOrderService.GetOrdersByCustomer` | GET | `/api/v1/orders?customerId=` | secure | — |
| 10 | `IOrderService.CancelOrder` | POST | `/api/v1/orders/{orderId:guid}/cancel` | secure | OrderNotFound 404, InvalidOrderState 409 |
| 11 | `IAccountService.GetAccount` | GET | `/api/v1/accounts/{customerId}` | secure | AccountNotFound 404 |
| 12 | `IAccountService.UpdateContactInfo` | PUT | `/api/v1/accounts/contact` | secure | Validation 400, AccountNotFound 404 |
| 13 | `IFundsTransferService.PlaceFundsTransfer` | POST | `/api/v1/funds-transfers` | secure | Validation 400, FundsTransferUnavailable 503 |
| 14 | `IFundsTransferService.QueueFundsTransfer` | POST | `/api/v1/funds-transfers/queue` | secure | Validation 400 |
| 15 | `IFundsTransferService.ProcessTransferQueue` | POST | `/api/v1/funds-transfers/queue/process` | secure | — |
| 16 | `IFundsTransferService.GetFundsTransferStatus` | GET | `/api/v1/funds-transfers/{orderId}` | secure | FundsTransferUnavailable 503 |
| 17 | `IFundsTransferService.GetTransferHistory` | GET | `/api/v1/funds-transfers/history` | secure | — |

Request and response bodies are the existing data contracts, unchanged. **Exceptions list on
the fixture: empty.** Every operation maps by convention. The routes add the `/v1` segment
the conventions require; the hand analysis omitted it.

---

## Part E — Recipe steps

Paths in `allowed_paths` are relative to the **target root**. Every step also carries the
side-by-side guard `no_writes_under: {legacy_root}` (32 B7). Unless noted, verification is
`dotnet build` of the step's project, then targeted replay (32 Part E).

### E1. Foundation steps

| Step | Approach | Targets | Class | Does | `allowed_paths` | Post-checks |
|---|---|---|---|---|---|---|
| F01 | `scaffold-side-by-side` | project set | deterministic | Copies the legacy source at `legacy_commit` into the target root, **excluding** folders and files reachability marked dead or unbuilt (X9 `Hosting.Iis`, X10 admin scripts, X11 `.host.pid`/`.vs`). Records the copy manifest used by drift reconciliation | `**` (empty target only) | Manifest matches legacy minus exclusions |
| F02 | `retarget-sdk-net10` | each non-host project (3) | deterministic | `TargetFramework` → `net10.0`; removes framework `<Reference>` items now in-box or replaced (`System.ServiceModel`, `System.Runtime.Serialization`, `System.Configuration`, `System.Xml`) | `**/*.csproj` | `xml_parses`; no `net4*` TFM |
| F03 | `add-wcf-client-packages` | projects with `wcf-service-reference` (1) | deterministic | Adds `System.ServiceModel.Http` and `System.ServiceModel.Primitives` from the engagement's approved feed | `**/*.csproj` | Packages resolve from `nuget_hv2.config` feeds |
| F04 | `regenerate-outbound-proxy` | `wcf-service-reference` (1) | deterministic (`process`) | `dotnet-svcutil {saved .wsdl} --namespace "*,{existing namespace}" --sync`. Removes `Reference.cs` and the VS design-time files (X6, X7). The namespace and the synchronous methods are kept, so calling code compiles unchanged | `**/Service References/**`, `**/Connected Services/**`, `**/*.csproj` | Generated client exposes every operation the caller uses (`PlaceRealTimeFTOrder`, `RealTimeFTInquiry`) with the same signatures |
| F05 | `configmanager-to-options` | `configmanager-appsettings-read` anchors **outside** every slice (1: `TransferLogger`) | deterministic | Creates the options class (`FundsTransferOptions`) and replaces the read with a constructor-injected value | `src/**/*.cs` | `signal_absent: CONFIGMANAGER_APPSETTINGS_READ` at those anchors |
| F06 | `add-service-fault-exception` | project (Contracts) | deterministic (template) | Adds `ServiceFaultException<TDetail>` (`Detail`, `Reason`) | `src/*Contracts*/Faults/*.cs` | File compiles |
| F07 | `add-caller-identity-abstraction` | project (Services) | deterministic (template) | Adds `ICallerIdentity` | `src/*Services*/*.cs` | — |
| F08 | `aspnetcore-host` | project with `wcf-service-host` (1) | deterministic (template) | Replaces the host: `Sdk.Web`, `Program.cs` from the template filled with D1 parameters (Kestrel ports, certificate, mTLS, trust mode, JSON naming, fault filter, OpenAPI, empty DI and controller regions), `HttpCallerIdentity`, `ServiceFaultExceptionFilter`. Deletes `HostSettings.cs`, the host's `CertificateLocator.cs` (X12), `App.config` (X1, X2) and the `ServiceHost` builders (X8 host part) | `src/*Host*/**` | Host starts; both ports listen; `/openapi/v1.json` served; no `System.ServiceModel` in the host project |
| F09 | `webdeploy-params-to-appsettings` | `webdeploy-parameters` (1) | deterministic | Reads `Parameters.xml` match paths and every `SetParam.xml`, writes `appsettings.json` (defaults), `appsettings.Development.json` (`DEV\LOCAL`) and `appsettings.{ENV}.json` per environment folder. Moves the outbound address from `<client><endpoint>` to `FundsTransfer:FundsTransferWSUrl` | `src/*Host*/appsettings*.json` | **Config equivalence**: for every environment, every key resolves to the value legacy resolved |
| F10 | `drop-dead-code` | `dead-code` anchors not already removed by F01, F04, F08 or S04 (1 on the fixture: X3 `QueuedUtc`, the property and its one write) | deterministic | Removes the member or key and its writes | `src/**` | `signal_absent` on those anchors |

### E2. Slice steps (run once per operation slice)

| Step | Approach | Targets (within the slice) | Class | Does | Post-checks |
|---|---|---|---|---|---|
| S01 | `strip-wcf-contract-attributes` | `wcf-service-contract-decl` | deterministic | Removes `[ServiceContract]`, `[OperationContract]`, `[FaultContract]` and `using System.ServiceModel;`; rewrites binding words in the doc comment | `signal_absent: WCF_SERVICE_CONTRACT_DECL` |
| S02 | `remove-service-behavior` | `wcf-service-behavior-attr` | deterministic | Removes `[ServiceBehavior]`; instancing becomes the DI lifetime (`PerCall` → scoped) registered by S06 | `signal_absent` |
| S03 | `fault-throw-to-service-fault` | `wcf-fault-throw`, `batching: per_file` | deterministic | `new FaultException<T>(detail, new FaultReason(r))` → `new ServiceFaultException<T>(detail, r)`. **Downgrade to assisted** when the fault is built in a helper or the reason is not a `FaultReason` literal or interpolation | `signal_absent: WCF_FAULT_THROW` |
| S04 | `slice-specific` | identity, config and client-construction anchors in the slice | deterministic | Order: `ServiceSecurityContext.Current` → `_caller.CertificateSubject` via constructor injection. FundsTransfer: `ConfigurationManager` read → options; 3 × `new FundsTransferWSSoapClient()` → `new FundsTransferWSSoapClient(EndpointConfiguration.FundsTransferWSSoap, _options.FundsTransferWSUrl)`; field initializers → constructor injection; X5 comment removed | `signal_absent` per anchor kind |
| S05 | `generate-controller` | the slice's contract and its D2 rows | deterministic (generator) | One controller, one action per mapped operation, calling the injected service interface. No logic | Routes in OpenAPI equal the slice's D2 rows |
| S06 | `register-slice` | host DI region | deterministic | Registers the service (scoped) and its controller; maps secure contracts to `secure_port` | Host starts; slice routes answer |

S04 is written as one step with per-slice variants so the recipe stays readable. When built,
each variant is its own approach (`wcf-security-context-to-caller-identity`,
`client-config-construction-to-explicit-endpoint`, `field-init-to-ctor-injection`), because
each is reusable on other WCF services.

---

## Part F — Coupled recipe: the internal client

`Catalog.TestClient` carries `wcf-nettcp-client`. Step 11's integration edges show it calling
`Catalog.Services`, so its decision is derived as `migrate-to-service-protocol`
(rule `internal-client-follows-service`). Recipe `wcf-client-to-rest` runs **in the same plan
and the same slices**, so each slice is proven from both sides.

| Step | Approach | Targets | Does |
|---|---|---|---|
| C01 | `rest-client-base` | client project (foundation) | Adds `CatalogRestClient` base: `HttpClient` with client certificate and dev-only server validation; turns error statuses back into `ServiceFaultException<T>` using the D2 fault rows |
| C02 | `client-settings-to-base-urls` | client settings (foundation) | `Ports.*Tcp`, `EnableHttpEndpoints`, HTTPS ports → `Rest.PublicBaseUrl`, `Rest.SecureBaseUrl`; drops `<startup>` |
| CS1 | `rest-client-for-contract` | per slice | Implements the slice's interface over the base client, so existing call sites stay unchanged; replaces that slice's `CreateTcpFactory<T>` use |
| CS2 | `fault-catch-to-service-fault` | per slice, `per_file` | `catch (FaultException<T>)` → `catch (ServiceFaultException<T>)` |

`RunHttpSmokeTest` and the HTTP factory methods (X8 client part) are dead and excluded by
F01 when reachability marks them; otherwise C02 removes them.

---

## Part G — Plan on the fixture: slices and units

Slice order: low risk first; the slice with writes and an outbound dependency last.

| Order | Slice | Operations | Units: recipe | Units: coupled client | Total |
|---|---|---|---|---|---|
| 0 | **Foundation** | — | 12 (F01 1, F02 3, F03–F09 1 each, F10 1) | 2 (C01, C02) | **14** |
| 1 | Utility | 2 | 4 (S01, S02, S05, S06; S03 `not_applicable`: no throws) | 1 (CS1; CS2 `not_applicable`) | **5** |
| 2 | Product | 4 | 5 (S01, S02, S03 × 5 anchors in 1 file, S05, S06) | 2 | **7** |
| 3 | Account | 2 | 5 (S03 × 3 anchors) | 2 | **7** |
| 4 | Order | 4 | 6 (S03 × 7 anchors, S04 identity) | 2 | **8** |
| 5 | FundsTransfer | 5 | 9 (S03 × 3 anchors, S04 × 4: options, client construction × 3 anchors, constructor injection, X5) | 2 | **11** |
| | **Total** | **17** | | | **52 units** |

**Automation mix on the fixture: 52 deterministic, 0 assisted, 0 manual.** A certified recipe
must plan the fixture with no assisted units (Part I). A client repository that produces
assisted units is showing shapes the fixture does not cover. That is useful information,
not a failure.

**Anchors covered:** 18 fault throws, 5 behaviour attributes, 5 contract declarations,
1 identity read, 2 config reads, 3 client constructions, 1 service reference and 1 deploy
parameter set, each by exactly one unit.

**Dead-code findings:** 11 of the 12 are removed. X4 (`OrderStatus.Shipped`/`Pending`) is
reported and kept, because the enum values are part of the schema.

| Finding | Removed by |
|---|---|
| X1, X2, X12, X8 (host part) | F08, with the host files they live in |
| X3 | F10 |
| X5 | S04 (FundsTransfer) |
| X6, X7 | F04 |
| X8 (client part) | F01 exclusion, or C02 |
| X9, X10, X11 | F01 exclusion |

---

## Part H — Equivalence on the fixture

### H1. Baseline cases (from `behaviour-baseline-capture`)

The fixture has no production traffic, so cases are generated, plus the scenarios
`Catalog.TestClient` already exercises.

| Slice | Cases (minimum) |
|---|---|
| Utility | `Ping`; `GetServerTimeUtc` |
| Product | Get existing; get `999999` → ProductNotFound; search with paging, filter and sort; search invalid page → Validation; create valid; create invalid → Validation; adjust −5; adjust −1000 → InsufficientStock; adjust on missing product → ProductNotFound |
| Account | Get existing; get unknown → AccountNotFound; update valid; update bad email → Validation; update unknown → AccountNotFound |
| Order | Place valid (checks `PlacedByCertificateSubject`); place with no items → Validation; unknown product → ProductNotFound; over stock → InsufficientStock; get; get random → OrderNotFound; by customer; cancel; cancel twice → InvalidOrderState |
| FundsTransfer | Place accepted; place GBP → Rejected without id; place invalid → Validation; practice account; status of accepted; status of practice; queue + process with 5 seeded records (Done/Rejected mix); queue to `999-99999` → Abort, later records stay pending; history |

### H2. Normalisation rules

| Field | Rule |
|---|---|
| `OrderSummary.OrderId`, `InvalidOrderStateFault.OrderId` | Present, valid GUID; compared by position in the case sequence |
| `*CreatedUtc`, `StartedUtc`, `CompletedUtc`, `SubmittedUtc`, `GetServerTimeUtc` result | Within 5 s of the call |
| `FundsTransferResult.OrderId` (`FT…`, `PRAC…`) | Pattern match; compared by sequence because both stacks call identical backend instances |
| `TransferHistoryEntry.Response` | Compared as XML |
| Collections | Ordered as returned. Repositories order explicitly, so order is contractual here |

### H3. Downstream and side effects

- **FundsTransferWS** is the only downstream. For each run, legacy and target each get a
  **fresh** backend instance (`WCF-backend`, IIS Express), so transfer-id sequences match.
  Recorded backend exchanges can replace it once they exist.
- **Outbound payload check:** the `REQ:` XML sent to `PlaceRealTimeFTOrder` must be
  **byte-identical** between legacy and target for every FundsTransfer case. This is the
  strongest single check in the recipe: the backend never changes, so any difference is a
  defect.
- **State:** all state is in memory (`CatalogData`). Each comparison starts both stacks fresh
  and compares the state reachable through read operations after each write case.
- **Production parallel run (client estate, not the fixture):** only reads are mirrored. Rows
  13–15 of D2 move money and are proven in pre-production only.

### H4. Fixture-specific checks

- **Caller identity:** the target's `PlacedByCertificateSubject` must equal legacy's for the
  same client certificate. The legacy value comes from a WCF X.509 identity, the target value
  from `HttpCallerIdentity` with `caller_identity_format`.
- **Configuration:** for each of `DEV\LOCAL`, `DEV`, `SITP`, `STE`, `PROD`, the target's
  resolved `FundsTransfer:FundsTransferWSUrl`, `LogDirectory` and `FundsTransferUserId` equal
  the legacy values resolved from `App.config` + that environment's `SetParam.xml`.

---

## Part I — Certification on the fixture

`wcf-service-rest` and `wcf-client-to-rest` move from `draft` to `certified` only when a run on
`sampleapps\WCF` meets every property assertion below (32 Part J). Property assertions, not a
golden diff.

### Plan

- [ ] Plans exactly the 6 slices and 52 units of Part G, all `deterministic`
- [ ] Every non-dead-code anchor listed in Part G is covered by exactly one unit
- [ ] Every dead-code finding except X4 is removed by the unit or exclusion Part G names; X4 is reported, not removed
- [ ] No blocker found (B2)

### Execution

- [ ] All 52 units `committed`, each in its own commit, none red
- [ ] No file under the legacy root changed (the legacy repository's `git status` is clean)
- [ ] Solution builds on `net10.0` with zero `System.ServiceModel` references outside the outbound proxy and `FundsTransferService.cs`
- [ ] Zero `FaultException<` throws, zero `[ServiceBehavior]`, zero `ServiceSecurityContext`, zero `ConfigurationManager` in `Catalog.Services`
- [ ] The excluded and deleted files match `MODERNIZATION-NET10-REST.md` §8, minus the items that layout makes unnecessary to delete (side by side copies only what is needed)

### Evidence

- [ ] OpenAPI has exactly the 17 routes of D2, with the D2 fault statuses
- [ ] Every H1 case is equivalent under H2, with no approved known differences
- [ ] Every FundsTransfer case's outbound `REQ:` XML is byte-identical
- [ ] Configuration equivalence passes for all 5 environments
- [ ] `PlacedByCertificateSubject` matches

### Oracle agreement

- [ ] Every change listed in `MODERNIZATION-NET10-REST.md` §6 is made by some unit, or is listed here as intentionally different (the `/v1` route segment; slice-based ordering)

**A second fixture is needed before `active`.** One fixture proves the recipe can work; it
does not prove it generalises. Candidates: an IIS-hosted `.svc` service with `web.config`
bindings (no self-host), and a service whose faults are built in helper methods, to exercise
the S03 downgrade path.

---

## Part J — What this recipe does not automate

| Item | Owner |
|---|---|
| The security model change (message credentials → mTLS) | Engagement decision, recorded with rationale (D1 `secure_group_auth`) |
| The target contract | Generated, then signed off by humans at gate 18 |
| Production traffic and backend recordings | Supplied by the client under the ingestion contract (32 Part O, question 3) |
| Linux-specific changes (`G:\Logs\…` paths, file logging, Windows certificate stores) | Separate catalog items (`hardcoded-windows-path`, logging items), decided on their own |
| Consumer migration and legacy retirement | Out of scope: the client retires legacy once all callers have moved |

---

## Part K — Open points

| # | Point | Proposal |
|---|---|---|
| 1 | `WCF_SERVICE_CONTRACT_DECL` may duplicate an existing signal | Check step 3/4's signal vocabulary first; reuse if equivalent |
| 2 | S05 depends on the signed-off mapping being machine-readable | `target-contract-design` emits the mapping as an artifact (`contract-mapping` 1.0.0), not only a document |
| 3 | F08's template encodes hosting choices (two ports, mTLS) | Template parameters come only from D1, so other engagements reuse the approach with different choices |
| 4 | The fixture's in-memory state makes side-effect comparison easy; real services use databases | Database side-effect comparison (snapshot and diff per case) is specified with the equivalence step, not per recipe |
| 5 | Should Utility, a two-operation slice, be merged into the foundation? | No. Keeping it as the first slice exercises the slice machinery on the lowest-risk code |
