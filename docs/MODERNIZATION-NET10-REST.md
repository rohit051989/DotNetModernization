# WCF Catalog → .NET 10 REST: Modernization Analysis

| | |
|---|---|
| **Application** | WCF Catalog (`sampleapps\WCF`) |
| **From** | .NET Framework 4.7.2, WCF SOAP (net.tcp, basicHttp, wsHttp) |
| **To** | .NET 10, ASP.NET Core Web API (REST/JSON) |
| **Kept as is** | Business logic, request/response schemas, the outbound SOAP call to FundsTransferWS |
| **Status** | Analysis only. Nothing has been changed or built yet |

All paths below are relative to `sampleapps\WCF\`.

---

## Contents

1. [Summary](#1-summary)
2. [Target shape](#2-target-shape)
3. [REST routes](#3-rest-routes)
4. [Fault → HTTP status mapping](#4-fault--http-status-mapping)
5. [Dead code to skip](#5-dead-code-to-skip)
6. [Files to change](#6-files-to-change)
7. [New files](#7-new-files)
8. [Files to delete](#8-files-to-delete)
9. [Files that do not change](#9-files-that-do-not-change)
10. [Confirm before relying on this](#10-confirm-before-relying-on-this)

---

## 1. Summary

| Bucket | Count |
|---|---|
| Files to change | 23 |
| New files | 20 |
| Files to delete | 27, and the `.vs\` folder |
| Files untouched | 33 |
| Business-logic changes | **0** |

The counts are the tables in sections 6–9, file by file: 23 + 27 + 33 = the 83 files of the
repository, besides this document. Section 6's overview also lists the five files deleted for
reasons it explains (the four host files and `Reference.cs`); they are counted once, as deletes.

Why the service classes still change: .NET 10 has no WCF hosting. The service classes use a
few WCF-only APIs that must be swapped mechanically. Their rules, validation, pricing, stock
handling and the transfer loop do not change.

| WCF-only API inside service classes | Occurrences |
|---|---|
| `throw new FaultException<T>(…)` | 18 |
| `[ServiceBehavior(InstanceContextMode.PerCall)]` | 5 |
| `ServiceSecurityContext.Current` | 1 |
| `ConfigurationManager.AppSettings[…]` | 2 |
| `new FundsTransferWSSoapClient()` (config-based constructor) | 3 |

Three things change beyond the protocol:

- **No admin rights needed.** Kestrel listens without http.sys reservations, so the net.tcp
  workaround and both `netsh` admin scripts become dead.
- **The outbound SOAP client is regenerated.** The call to FundsTransferWS stays SOAP, but on
  .NET 10 the WCF client comes from NuGet and cannot read `<system.serviceModel>` from
  `App.config`. The proxy is regenerated with `dotnet-svcutil`, and the address is passed in
  code from `appsettings.json`.
- **Per-environment config moves to `appsettings.{ENV}.json`.** That replaces Web Deploy's
  `Parameters.xml` and `SetParam.xml`.

---

## 2. Target shape

| Concern | Today (.NET Framework 4.7.2) | Target (.NET 10) |
|---|---|---|
| Hosting | `ServiceHost`, bindings built in code | ASP.NET Core Web API on Kestrel |
| Ports | net.tcp 8101/8102/8201/8202/8203; HTTP 8443/8543 behind an admin step | **8443**: TLS, for Utility and Product<br>**8543**: TLS plus a required client certificate, for Order, Account and FundsTransfer |
| Contracts | `[ServiceContract]` interfaces + `[DataContract]` DTOs | Same interfaces without WCF attributes; DTOs unchanged |
| Services | WCF service classes | Same classes, registered in DI and called by 5 thin controllers |
| Faults | `FaultException<T>` | `ServiceFaultException<T>` (new), mapped to an HTTP status, with the same fault object as the JSON body |
| Caller identity | `ServiceSecurityContext.Current` | TLS client certificate, read through a small `ICallerIdentity` interface |
| Configuration | `App.config` + `Parameters.xml` + `SetParam.xml` | `appsettings.json` + `appsettings.{DEV,SITP,STE,PROD}.json` |
| Outbound SOAP | Visual Studio service reference + config endpoint | `dotnet-svcutil` proxy + address from config. Still SOAP 1.1 over `basicHttpBinding` |
| Contract document | WSDL | OpenAPI |

> **Same schema:** set `PropertyNamingPolicy = null` so JSON keeps the C# property names.
> ASP.NET Core defaults to camelCase. If consumers need the old XML shape instead,
> `AddXmlDataContractSerializerFormatters()` serves the existing `[DataContract]` XML.

---

## 3. REST routes

### Public: port 8443 (TLS)

| # | Operation | Method | Route | Request → Response |
|---|---|---|---|---|
| 1 | `Ping` | GET | `/api/utility/ping` | → `string` |
| 2 | `GetServerTimeUtc` | GET | `/api/utility/time` | → `DateTime` |
| 3 | `GetProduct` | GET | `/api/products/{productId:int}` | → `Product` |
| 4 | `SearchProducts` | POST | `/api/products/search` | `ProductSearchRequest` → `ProductSearchResult` |
| 5 | `CreateProduct` | POST | `/api/products` | `ProductCreateRequest` → `int` |
| 6 | `AdjustStock` | POST | `/api/products/{productId:int}/stock?quantityDelta={n}` | → 204 |

### Secure: port 8543 (TLS + required client certificate)

| # | Operation | Method | Route | Request → Response |
|---|---|---|---|---|
| 7 | `PlaceOrder` | POST | `/api/orders` | `PlaceOrderRequest` → `OrderSummary` |
| 8 | `GetOrder` | GET | `/api/orders/{orderId:guid}` | → `OrderSummary` |
| 9 | `GetOrdersByCustomer` | GET | `/api/orders?customerId={id}` | → `List<OrderSummary>` |
| 10 | `CancelOrder` | POST | `/api/orders/{orderId:guid}/cancel` | → 204 |
| 11 | `GetAccount` | GET | `/api/accounts/{customerId}` | → `Account` |
| 12 | `UpdateContactInfo` | PUT | `/api/accounts/contact` | `AccountContactUpdateRequest` → 204 |
| 13 | `PlaceFundsTransfer` | POST | `/api/funds-transfers` | `FundsTransferRequest` → `FundsTransferResult` |
| 14 | `QueueFundsTransfer` | POST | `/api/funds-transfers/queue` | `FundsTransferRequest` → `int` |
| 15 | `ProcessTransferQueue` | POST | `/api/funds-transfers/queue/process` | → `TransferBatchSummary` |
| 16 | `GetFundsTransferStatus` | GET | `/api/funds-transfers/{orderId}` | → `FundsTransferStatus` |
| 17 | `GetTransferHistory` | GET | `/api/funds-transfers/history` | → `List<TransferHistoryEntry>` |

Operations 13, 15 and 16 still call FundsTransferWS over SOAP. Practice-account transfers are
handled locally and never sent.

---

## 4. Fault → HTTP status mapping

| Fault (the response body) | HTTP status |
|---|---|
| `ValidationFault` | 400 Bad Request |
| `ProductNotFoundFault`, `OrderNotFoundFault`, `AccountNotFoundFault` | 404 Not Found |
| `InsufficientStockFault`, `InvalidOrderStateFault` | 409 Conflict |
| `FundsTransferUnavailableFault` | 503 Service Unavailable |
| Anything else | 500, generic message only, no exception text |

---

## 5. Dead code to skip

Each item was checked by counting references or tracing where values are read.

| # | Item | Where | Evidence | Action |
|---|---|---|---|---|
| X1 | `HostSettings.ClientCertThumbprint` + host key `ClientCertificate.Thumbprint` | `src\Catalog.Host\HostSettings.cs`, `src\Catalog.Host\App.config` | Loaded, never read. Client trust is PeerTrust via the certificate store | Drop |
| X2 | `<system.diagnostics><trace autoflush>` | `src\Catalog.Host\App.config` | No `Trace.` call anywhere | Drop |
| X3 | `TransferQueueItem.QueuedUtc` | `src\Catalog.Services\FundsTransfer\TransferQueueItem.cs` | Written once in `TransferQueueRepository.cs`, never read | Drop the property and the assignment |
| X4 | `OrderStatus.Shipped` / `Pending` never assigned | `OrderStatus.cs`; the `Shipped` check in `OrderService.CancelOrder` | Only `Confirmed` and `Cancelled` are ever assigned | **Keep** the enum values (schema). Treat the `Shipped` branch as dormant |
| X5 | Commented-out `//using …fundstransferws` | `src\Catalog.Services\FundsTransferService.cs` | A comment only | Drop |
| X6 | Proxy members `Ping`, `PingAsync`, `*Async` and their message classes | `Service References\FundsTransferWS\Reference.cs` | The caller uses only `PlaceRealTimeFTOrder` and `RealTimeFTInquiry` | Generated; goes away on regeneration |
| X7 | `.disco`, `Reference.svcmap`, `configuration.svcinfo`, `configuration91.svcinfo`, `.datasource` | `src\Catalog.Services\Service References\FundsTransferWS\` | Visual Studio design-time files, no runtime use | Delete |
| X8 | `BuildBasicHttpsHost`, `BuildWsHttpsHost`, `TryAdd`, `RunHttpSmokeTest`, `CreateBasicHttpsFactory`, `CreateWsHttpsFactory` | Host and TestClient `Program.cs` | Only run when `EnableHttpEndpoints=true`, which is `false` everywhere; never exercised | Do not port |
| X9 | `src\Hosting.Iis\` (7 files) | `src\Hosting.Iis\` | Not in the solution, never built or run; ASP.NET Core cannot use `.svc` | Delete |
| X10 | `Setup-AdminHttpBindings.ps1`, `Remove-AdminHttpBindings.ps1` | `scripts\` | http.sys reservations only; Kestrel needs none | Delete |
| X11 | `.host.pid` (PID 11176, no such process), `.vs\` | Repo root | Leftover runtime and IDE files | Delete / gitignore |
| X12 | `CertificateLocator.cs` exists twice, almost identical | `src\Catalog.Host\`, `src\Catalog.TestClient\` | Only the error text differs | Host copy goes with the migration; TestClient keeps its copy |

> **Looks unused, but keep.** These are API surface for external callers, even though nothing
> in this repo reads them: `FundsTransferResult.HistoryId`, `FundsTransferStatus.IsPractice`,
> `TransferHistoryEntry.Response`, `InvalidOrderStateFault.AttemptedAction`.

---

## 6. Files to change

### Overview

| File | Location | Changes |
|---|---|---|
| `Catalog.Contracts.csproj` | `src\Catalog.Contracts\` | 2 |
| `IUtilityService.cs` | `src\Catalog.Contracts\` | 2 |
| `IProductService.cs` | `src\Catalog.Contracts\` | 2 |
| `IOrderService.cs` | `src\Catalog.Contracts\` | 2 |
| `IAccountService.cs` | `src\Catalog.Contracts\` | 2 |
| `IFundsTransferService.cs` | `src\Catalog.Contracts\` | 2 |
| `Catalog.Services.csproj` | `src\Catalog.Services\` | 4 |
| `Reference.cs` (outbound proxy) | `src\Catalog.Services\Service References\FundsTransferWS\` | delete, regenerated as N11 |
| `AccountService.cs` | `src\Catalog.Services\` | 4 |
| `ProductService.cs` | `src\Catalog.Services\` | 6 |
| `OrderService.cs` | `src\Catalog.Services\` | 9 |
| `UtilityService.cs` | `src\Catalog.Services\` | 1 |
| `FundsTransferService.cs` | `src\Catalog.Services\` | 10 |
| `TransferLogger.cs` | `src\Catalog.Services\FundsTransfer\` | 2 |
| `TransferQueueItem.cs` | `src\Catalog.Services\FundsTransfer\` | 1 |
| `TransferQueueRepository.cs` | `src\Catalog.Services\Repositories\` | 1 |
| `Catalog.Host.csproj` | `src\Catalog.Host\` | 3 |
| `Program.cs` (host) | `src\Catalog.Host\` | 7 |
| `HostSettings.cs` | `src\Catalog.Host\` | delete |
| `CertificateLocator.cs` (host) | `src\Catalog.Host\` | delete |
| `App.config` (host) | `src\Catalog.Host\` | delete |
| `Parameters.xml` | `src\Catalog.Host\` | delete |
| `Catalog.TestClient.csproj` | `src\Catalog.TestClient\` | 2 |
| `Program.cs` (test client) | `src\Catalog.TestClient\` | 12 |
| `ClientSettings.cs` | `src\Catalog.TestClient\` | 1 |
| `App.config` (test client) | `src\Catalog.TestClient\` | 2 |
| `New-DevCertificates.ps1` | `scripts\` | 2 |
| `README.md` | repo root | 1 |

---

### 6.1 Contracts: `src\Catalog.Contracts\`

Why these files: the interfaces carry WCF attributes. They stay as the service interfaces that
the controllers call. The DTOs do not change.

#### `Catalog.Contracts.csproj`

1. Change `<TargetFramework>` from `net472` to `net10.0`.
2. Remove the `System.ServiceModel` and `System.Runtime.Serialization` references.
   `[DataContract]` is built into .NET 10.

#### `IUtilityService.cs`

1. Remove `[ServiceContract]` and the 2 `[OperationContract]` attributes.
2. Remove `using System.ServiceModel;` and fix the doc comment that names basicHttpBinding.

#### `IProductService.cs`

1. Remove `[ServiceContract]`, 4 `[OperationContract]` and 6 `[FaultContract]` attributes.
2. Remove the `using` and fix the doc comment (basicHttpBinding + SSL).

#### `IOrderService.cs`

1. Remove `[ServiceContract]`, 4 `[OperationContract]` and 6 `[FaultContract]` attributes.
2. Remove the `using` and rewrite the doc comment: wsHttp message security becomes TLS client
   certificates.

#### `IAccountService.cs`

1. Remove `[ServiceContract]`, 2 `[OperationContract]` and 3 `[FaultContract]` attributes.
2. Remove the `using` and fix the doc comment.

#### `IFundsTransferService.cs`

1. Remove `[ServiceContract]`, 5 `[OperationContract]` and 4 `[FaultContract]` attributes.
2. Remove the `using` and fix the doc comment (net.tcp / wsHttp).

---

### 6.2 Services: `src\Catalog.Services\`

Why these files: they hold the business logic, plus a handful of WCF-only calls that do not
exist on .NET 10. Only those calls change.

#### `Catalog.Services.csproj`

1. Change `<TargetFramework>` from `net472` to `net10.0`.
2. Remove the 4 framework references: `System.ServiceModel`, `System.Runtime.Serialization`,
   `System.Configuration`, `System.Xml`.
3. Add the .NET WCF client packages for the outbound SOAP call: `System.ServiceModel.Http` and
   `System.ServiceModel.Primitives` (8.x).
4. Remove the Visual Studio service-reference items: `WCFMetadata`, `WCFMetadataStorage`,
   `Compile Update` and the 6 `None` items.

#### `Service References\FundsTransferWS\Reference.cs` (outbound SOAP proxy) — delete

Why: the .NET Framework proxy depends on `App.config`, which .NET 10 does not read. It is
deleted, with the rest of the service-reference folder (section 8), and replaced by a proxy
regenerated into `Connected Services\FundsTransferWS\` (N11):

1. Regenerate the proxy from the saved WSDL, with `--sync` so the calling code stays synchronous:

   ```powershell
   dotnet-svcutil "Service References\FundsTransferWS\FundsTransferWS.wsdl" `
       --namespace "*,WcfCatalog.Services.FundsTransferWS" `
       --sync `
       --outputDir "Connected Services\FundsTransferWS"
   ```

   The new proxy builds its binding in code (`GetBindingForEndpoint`).
2. Delete the old `Reference.cs`, the `.wsdl` once regeneration is done, and the X7 files.
   The regenerated `Reference.cs` and `dotnet-svcutil.params.json` replace them (N11).

#### `AccountService.cs`

1. Remove `[ServiceBehavior(InstanceContextMode.PerCall)]` (the DI lifetime replaces it) and
   `using System.ServiceModel;`.
2. `GetAccount`, account not found: replace
   `throw new FaultException<AccountNotFoundFault>(detail, new FaultReason("…"))` with
   `throw new ServiceFaultException<AccountNotFoundFault>(detail, "…")`.
3. `UpdateContactInfo`, validation: same replacement for `ValidationFault`.
4. `UpdateContactInfo`, account not found: same replacement for `AccountNotFoundFault`.

#### `ProductService.cs`

1. Remove `[ServiceBehavior]` and the `using`.
2. `GetProduct`: replace the `ProductNotFoundFault` throw.
3. `SearchProducts`: replace the `ValidationFault` throw.
4. `CreateProduct`: replace the `ValidationFault` throw.
5. `AdjustStock`: replace the `ProductNotFoundFault` throw.
6. `AdjustStock`: replace the `InsufficientStockFault` throw.

#### `OrderService.cs`

1. Remove `[ServiceBehavior]` and the `using`.
2. `PlaceOrder`: replace the `ValidationFault` throw.
3. `PlaceOrder`: replace the `ProductNotFoundFault` throw.
4. `PlaceOrder`: replace the `InsufficientStockFault` throw (pricing check).
5. `PlaceOrder`: replace the `InsufficientStockFault` throw (stock reservation). The
   `catch { rollback; throw; }` around it is unchanged.
6. `GetOrder`: replace the `OrderNotFoundFault` throw.
7. `CancelOrder`: replace the `OrderNotFoundFault` throw.
8. `CancelOrder`: replace the `InvalidOrderStateFault` throw.
9. Caller identity, because `ServiceSecurityContext` does not exist in ASP.NET Core:
   - add a constructor that takes `ICallerIdentity`;
   - `TryGetCallerCertificateSubject()` returns `_caller.CertificateSubject`.

   The implementation returns `"{Subject}; {Thumbprint}"`, the format WCF produced, so
   `PlacedByCertificateSubject` values do not change.

#### `UtilityService.cs`

1. Remove `[ServiceBehavior]` and the `using`. Both methods are unchanged.

#### `FundsTransferService.cs`

1. Remove `[ServiceBehavior]`. **Keep** `using System.ServiceModel;`: the WCF client package
   still provides `CommunicationException` and `FaultException` for errors from the backend.
2. `PlaceFundsTransfer`: replace the `FundsTransferUnavailableFault` throw.
3. `GetFundsTransferStatus`: replace the `FundsTransferUnavailableFault` throw.
4. `ToQueueItem`: replace the `ValidationFault` throw.
5. `PlaceFundsTransfer`: change `new FundsTransferWSSoapClient()` to
   `new FundsTransferWSSoapClient(FundsTransferWSSoapClient.EndpointConfiguration.FundsTransferWSSoap, _options.FundsTransferWSUrl)`.
6. `ProcessTransferQueue`: same constructor change. The loop, REQ/RES logging, `Action/@id`
   read and Done / Rejected / Abort handling are untouched.
7. `GetFundsTransferStatus`: same constructor change.
8. `ToQueueItem`: read `FundsTransferUserId` from `_options` instead of
   `ConfigurationManager.AppSettings`. The method becomes an instance method.
9. Replace the field initializers `new TransferQueue(…)` and `new TransferLogger()` with
   constructor injection of `FundsTransferOptions`, `TransferQueue` and `TransferLogger`.
10. Remove the commented-out `//using …fundstransferws` line (X5).

#### `FundsTransfer\TransferLogger.cs`

1. The constructor takes the log directory from `FundsTransferOptions` instead of
   `ConfigurationManager.AppSettings["LogDirectory"]`.
2. Optional: `AppDomain.CurrentDomain.BaseDirectory` → `AppContext.BaseDirectory` (both work on
   .NET 10).

#### `FundsTransfer\TransferQueueItem.cs`

1. Remove the `QueuedUtc` property (X3).

#### `Repositories\TransferQueueRepository.cs`

1. Remove `item.QueuedUtc = DateTime.UtcNow;` (X3).

---

### 6.3 Host: `src\Catalog.Host\`

Why these files: hosting is the part that is rewritten, from `ServiceHost` to ASP.NET Core.

#### `Catalog.Host.csproj`

1. Change `Sdk="Microsoft.NET.Sdk"` to `Sdk="Microsoft.NET.Sdk.Web"`, `net472` to `net10.0`,
   and drop `<OutputType>`.
2. Remove the 3 framework `<Reference>` items.
3. Add the `Microsoft.AspNetCore.Authentication.Certificate` and `Microsoft.AspNetCore.OpenApi`
   packages.

#### `Program.cs`

1. Replace all `ServiceHost` code with `WebApplication.CreateBuilder(args)` … `app.Run()`. That
   also replaces the `Console.ReadLine()` shutdown.
2. Kestrel: two endpoints from configuration, with the server certificate from
   `CurrentUser\My` by subject. No admin rights needed.
   - **8443**: `ClientCertificateMode.NoCertificate`
   - **8543**: `ClientCertificateMode.RequireCertificate`
3. `AddAuthentication().AddCertificate(…)`. Its validation callback replaces PeerTrust: accept
   a client certificate present in `CurrentUser\TrustedPeople`, and skip revocation in dev.
   The Order, Account and FundsTransfer controllers require it and are mapped to port 8543 only.
4. Add
   `AddControllers().AddJsonOptions(o => o.JsonSerializerOptions.PropertyNamingPolicy = null)`
   to keep the schema's property names, and register the fault filter (N2).
5. Dependency injection:
   - the 5 services, scoped (matching PerCall);
   - `TransferQueue` and `TransferLogger`;
   - `FundsTransferOptions`, bound from configuration;
   - `ICallerIdentity` → `HttpCallerIdentity`;
   - `AddHttpContextAccessor()`.
6. `AddOpenApi()` / `MapOpenApi()`. The OpenAPI document replaces the WSDL as the contract
   snapshot (lifecycle step 15).
7. Remove `BuildTcpHost`, `BuildBasicHttpsHost`, `BuildWsHttpsHost`, `ApplyDebugBehavior`,
   `TryAdd` and the `EnableHttpEndpoints` branch. Keep the startup banner showing the backend
   URL, now read from configuration.

#### `HostSettings.cs` — delete

Replaced by `appsettings.json` and `FundsTransferOptions`. `ReadClientEndpointAddress` goes too.

#### `CertificateLocator.cs` — delete

Kestrel loads the server certificate from configuration (X12).

#### `App.config` — delete

ASP.NET Core has no `App.config`; the keys move to `appsettings.json` (N6). The X1 and X2
entries and the `<startup>` element are not carried over.

#### `Parameters.xml` — delete

Per-environment values move to `appsettings.{ENV}.json` (N7).

---

### 6.4 Test client: `src\Catalog.TestClient\`

Why these files: `ChannelFactory` cannot call REST, and the faults now arrive as HTTP statuses.

#### `Catalog.TestClient.csproj`

1. Change `net472` to `net10.0` and remove the 3 framework references.
2. Add the `System.Configuration.ConfigurationManager` package, so `ClientSettings` keeps
   reading `App.config`.

#### `Program.cs`

1. Replace `CreateTcpFactory<T>` with creating the typed REST client (N8) on an `HttpClient`
   that carries the client certificate. The `Run*` call sites (`utility.Ping()`,
   `product.GetProduct(id)`, …) **stay the same**.
2. Delete `CreateBasicHttpsFactory`, `CreateWsHttpsFactory`, `RunHttpSmokeTest` and the
   `EnableHttpEndpoints` branch (X8).
3. `CloseChannel<T>` → dispose the `HttpClient`; drop `IClientChannel`.
4. Dev-only server certificate trust through
   `HttpClientHandler.ServerCertificateCustomValidationCallback`, replacing the channel's
   PeerTrust setting.
5. `AdjustStock(-1000)` check: `catch FaultException<InsufficientStockFault>` →
   `catch ServiceFaultException<InsufficientStockFault>`.
6. `GetProduct(999999)` check: same change for `ProductNotFoundFault`.
7. Cancel-twice check: same change for `InvalidOrderStateFault`.
8. `GetOrder(random)` check: same change for `OrderNotFoundFault`.
9. `GetAccount(unknown)` check: same change for `AccountNotFoundFault`.
10. `RunFundsTransfer`: same change for `FundsTransferUnavailableFault`.
11. `PlaceFundsTransfer(invalid)` check: same change for `ValidationFault`.
12. Update the section headers that say "net.tcp", and the `using` lines
    (`System.ServiceModel*` → `System.Net.Http`).

#### `ClientSettings.cs`

1. Replace the 5 `*TcpPort` properties, `EnableHttpEndpoints`, `ProductHttpsPort` and
   `OrderWsHttpsPort` with `PublicBaseUrl` and `SecureBaseUrl`.

#### `App.config`

1. Replace the `Ports.*` keys and `EnableHttpEndpoints` with:
   - `Rest.PublicBaseUrl` = `https://localhost:8443`
   - `Rest.SecureBaseUrl` = `https://localhost:8543`
2. Remove `<startup><supportedRuntime>`.

---

### 6.5 Scripts and docs

#### `scripts\New-DevCertificates.ps1`

1. Stop patching the host `App.config`, which is deleted. The host finds the server
   certificate by subject, so no host patch is needed. Keep the TestClient `App.config` patch.
2. Update the help text (no net.tcp). Certificate creation and `TrustedPeople` stay as they
   are; Kestrel uses them without admin rights.

#### `README.md` (repo root)

1. Rewrite it for .NET 10: the two ports, the route table, the fault → status table,
   `dotnet run`, environments via `ASPNETCORE_ENVIRONMENT`, and the outbound SOAP section.

---

## 7. New files

| # | File | Location | Purpose |
|---|---|---|---|
| N1 | `ServiceFaultException.cs` | `src\Catalog.Contracts\Faults\` | `ServiceFaultException<TDetail> : Exception` with `Detail` and `Reason`. Replaces `FaultException<T>` at the 18 throw sites and the 7 client catch sites |
| N2 | `ServiceFaultExceptionFilter.cs` | `src\Catalog.Host\Errors\` | Maps the detail type to an HTTP status (section 4) and writes the detail as the body. Anything else returns a generic 500 and is logged |
| N3 | `UtilityController.cs` | `src\Catalog.Host\Controllers\` | Routes 1–2. Thin: one action per route, no logic |
| N3 | `ProductsController.cs` | `src\Catalog.Host\Controllers\` | Routes 3–6 |
| N3 | `OrdersController.cs` | `src\Catalog.Host\Controllers\` | Routes 7–10 |
| N3 | `AccountsController.cs` | `src\Catalog.Host\Controllers\` | Routes 11–12 |
| N3 | `FundsTransfersController.cs` | `src\Catalog.Host\Controllers\` | Routes 13–17 |
| N4 | `ICallerIdentity.cs` | `src\Catalog.Services\` | `string CertificateSubject { get; }`, used by `OrderService` |
| N5 | `HttpCallerIdentity.cs` | `src\Catalog.Host\` | Reads `HttpContext.Connection.ClientCertificate` and returns `"{Subject}; {Thumbprint}"` |
| N6 | `appsettings.json` | `src\Catalog.Host\` | Kestrel endpoints and certificate; `FundsTransfer:FundsTransferWSUrl`, `LogDirectory`, `FundsTransferUserId` |
| N6 | `appsettings.Development.json` | `src\Catalog.Host\` | Local values (was `SetParamFiles\DEV\LOCAL`) |
| N7 | `appsettings.DEV.json` | `src\Catalog.Host\` | Values from `SetParamFiles\DEV\SetParam.xml` |
| N7 | `appsettings.SITP.json` | `src\Catalog.Host\` | Values from `SetParamFiles\SITP\SetParam.xml` |
| N7 | `appsettings.STE.json` | `src\Catalog.Host\` | Values from `SetParamFiles\STE\SetParam.xml` |
| N7 | `appsettings.PROD.json` | `src\Catalog.Host\` | Values from `SetParamFiles\PROD\SetParam.xml` |
| N8 | `CatalogRestClient.cs` | `src\Catalog.TestClient\` | Implements the 5 service interfaces over `HttpClient` and turns error responses back into `ServiceFaultException<T>`, so the `Run*` bodies do not change |
| N9 | `FundsTransferOptions.cs` | `src\Catalog.Services\FundsTransfer\` | `FundsTransferWSUrl`, `LogDirectory`, `FundsTransferUserId` |
| N10 | `Properties\launchSettings.json` | `src\Catalog.Host\` | Local profile with `ASPNETCORE_ENVIRONMENT=Development` |
| N11 | `Reference.cs` | `src\Catalog.Services\Connected Services\FundsTransferWS\` | The outbound SOAP proxy, regenerated with `dotnet-svcutil` (6.2). Replaces the old `Service References` proxy |
| N11 | `dotnet-svcutil.params.json` | `src\Catalog.Services\Connected Services\FundsTransferWS\` | The regeneration's parameters, so the proxy can be regenerated again |

> **Bonus:** lifecycle step 5 reads `appsettings.{ENV}.json` per environment. Moving off
> `SetParam.xml` closes the gap where the per-environment backend addresses were invisible
> to it.

---

## 8. Files to delete

| What | Location | Why |
|---|---|---|
| `Account.svc`, `FundsTransfer.svc`, `Order.svc`, `Product.svc`, `Utility.svc`, `Web.config`, `README.md` | `src\Hosting.Iis\` | X9: never built or run; `.svc` is not supported on ASP.NET Core |
| `Setup-AdminHttpBindings.ps1` | `scripts\` | X10: http.sys only |
| `Remove-AdminHttpBindings.ps1` | `scripts\` | X10: http.sys only |
| `Apply-SetParam.ps1` | `scripts\` | `ASPNETCORE_ENVIRONMENT` selects the settings file |
| `SetParam.xml` × 5 (DEV, DEV\LOCAL, SITP, STE, PROD) | `CustomFiles\Catalog.Host\SetParamFiles\` | Moved into N6 / N7 |
| `HostSettings.cs`, `CertificateLocator.cs`, `App.config`, `Parameters.xml` | `src\Catalog.Host\` | See 6.3 |
| `Reference.cs`, `.wsdl`, `.disco`, `Reference.svcmap`, `configuration.svcinfo`, `configuration91.svcinfo`, `.datasource` | `src\Catalog.Services\Service References\FundsTransferWS\` | Replaced by the regenerated proxy (X7) |
| `.host.pid`, `.vs\` | Repo root | X11 |

---

## 9. Files that do not change

| Files | Why |
|---|---|
| 16 × `DataContracts\*.cs` | Plain DTOs. `[DataContract]` compiles on .NET 10, and JSON keeps the same names |
| 7 × `Faults\*.cs` | Become the HTTP error bodies as they are |
| `Namespaces.cs` | Used only for XML namespaces |
| `CatalogData.cs` | Static repository singletons work as they are |
| `Repositories\AccountRepository.cs`, `OrderRepository.cs`, `ProductRepository.cs` | No framework-specific code |
| `FundsTransfer\TransferQueue.cs` | `SecurityElement.Escape` and `StringBuilder` work on .NET 10 |
| `src\Catalog.TestClient\CertificateLocator.cs` | Still loads the client certificate by thumbprint |
| `WcfCatalog.sln` | Same 4 projects |
| `config\nuget_hv2.config` | Unchanged. The Artifactory mirror must now carry `System.ServiceModel.*`, `Microsoft.AspNetCore.Authentication.Certificate` and `Microsoft.AspNetCore.OpenApi` |
| `.github\copilot-instructions.md` | Unrelated to the application |
| Everything in `..\WCF-backend` | The backend stays as it is and is still called over SOAP 1.1 |

---

## 10. Confirm before relying on this

1. **Proxy shape.** The `dotnet-svcutil` proxy for this ASMX WSDL should keep the same
   `PlaceRealTimeFTOrder(string) : string` shape. Its generated binding sets max message sizes
   to `int.MaxValue`, which differs from today's defaults.
2. **Client certificate validation.** On Windows, Kestrel should hand self-signed client
   certificates to the validation callback. If it rejects them before that, the client
   certificate's issuer needs trusting, or the callback mode needs adjusting.
3. **If the target is OpenShift / Linux**, three more changes apply:
   - the `G:\Logs\…` paths in the DEV / SITP / STE / PROD settings;
   - the file-based `TransferLogger` (containers log to stdout);
   - Windows certificate stores (certificates would be mounted from a Secret).

   The outbound SOAP call is fine on Linux: it is `basicHttpBinding` with no Windows security.
