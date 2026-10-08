# `application-fingerprinting` — Application Fingerprinting

## 1. Purpose

`application-fingerprinting` creates a detailed, evidence-backed technical fingerprint for each project or application candidate discovered in `solution-discovery`.

`solution-discovery` answers:

> What solutions and projects exist in each repository?

`application-fingerprinting` answers:

> What technical characteristics does each discovered project exhibit?

`application-fingerprinting` should not assign the final application pattern. It should extract, normalize, and structure the technical evidence that will later be evaluated against the pattern catalog in `pattern-classification`.

```text
solution-discovery — Solution and Project Discovery
        ↓
application-fingerprinting — Application Fingerprinting
        ↓
pattern-classification — Pattern Classification Against Catalog
        ↓
pattern-discovery-clustering — Pattern Discovery and Clustering for Unmatched Applications
```

---

## 2. `application-fingerprinting` Objective

For every discovered project or application candidate, generate a structured fingerprint containing:

- Project metadata
- Framework and assembly references
- Package dependencies
- Source-code constructs
- Entry points
- Endpoints
- Configuration indicators
- Execution-model indicators
- Hosting indicators
- UI indicators
- Data-access indicators
- Messaging and integration indicators
- Scheduling and background-processing indicators
- Testing indicators
- Deployment and packaging indicators
- Evidence locations
- Extraction confidence
- Analysis completeness
- Processing warnings

The fingerprint should describe what was observed without assigning a final application type.

Example:

```text
Observed fingerprint:

- Target framework: .NET Framework 4.7.2
- Output type: Library
- Contains 3 .svc files
- Uses System.ServiceModel
- Contains 4 ServiceContract attributes
- Contains 21 OperationContract attributes
- web.config contains system.serviceModel
- IIS hosting indicators are present
```

`pattern-classification` may later classify this fingerprint as:

```text
Pattern: WCF Service hosted in IIS
Confidence: 96%
```

---

# Part A — What `application-fingerprinting` Should Contain

## 3. Input from `solution-discovery`

`application-fingerprinting` should consume the structural inventory produced in `solution-discovery`.

Typical input fields include:

- Repository identifier and path
- Repository revision or commit
- Solution identifier and path
- Project identifier and path
- Project extension and language
- Project format
- Target framework
- Output type
- Package declarations
- Project references
- Configuration-file locations
- Supporting artifact locations
- `solution-discovery` scan status and warnings

`application-fingerprinting` should normally execute at project level while retaining repository and solution context.

```text
Repository
└── Solution
    └── Project
        └── Application Fingerprint
```

Some fingerprint evidence may exist outside the immediate project directory, including shared configuration, repository-level build files, deployment scripts, scheduler definitions, publish profiles, pipeline files, and shared source folders.

---

## 4. Project Metadata Fingerprint

Capture factual properties directly available from the project definition.

| Attribute | Example |
|---|---|
| Project Format | Legacy MSBuild |
| Project SDK | `Microsoft.NET.Sdk.Web` |
| Language | C# |
| Output Type | Exe, Library, WinExe |
| Target Framework | `net472` |
| Framework Family | .NET Framework |
| Multi-Targeted | Yes / No |
| Assembly Name | `Customer.Service` |
| Root Namespace | `ABC.Customer.Service` |
| Nullable Enabled | Yes / No |
| Implicit Usings | Yes / No |
| Project Reference Count | 7 |
| Package Reference Count | 18 |

These values remain factual metadata. They should not yet be interpreted as an application pattern.

---

## 5. Framework, Assembly, Namespace, and Package Fingerprint

Capture technical references such as:

```text
System.Web
System.Web.Mvc
System.Web.Http
System.ServiceModel
System.ServiceProcess
Microsoft.AspNetCore
Microsoft.AspNetCore.Mvc
Microsoft.NET.Sdk.Web
EntityFramework
Microsoft.EntityFrameworkCore
Quartz
Hangfire
Microsoft.Azure.WebJobs
```

Suggested fields:

| Field | Description |
|---|---|
| Reference Name | Assembly, namespace, framework, or package |
| Reference Type | Framework, package, assembly, or namespace |
| Version | Version where available |
| Source | Project file, configuration, or source code |
| Evidence Path | File containing the reference |
| Occurrence Count | Number of occurrences |
| Extraction Confidence | Confidence in the extracted fact |

`application-fingerprinting` records a signal such as `Uses System.ServiceModel`; it does not yet conclude that the project is a WCF Service.

---

## 6. Source-Code Fingerprint

### 6.1 Entry Points

Detect:

- `Main` methods
- Top-level statements
- `Program.cs`
- `Startup.cs`
- `Global.asax`
- Worker host creation
- Windows Service startup
- Azure Function entry methods
- SSIS execution artifacts

Example:

```text
Entry Point Type: Main Method
File: Program.cs
Class: Program
Method: Main
```

### 6.2 Base Classes and Interfaces

Capture inheritance and implemented interfaces such as:

```text
System.Web.UI.Page
System.Web.Mvc.Controller
System.Web.Http.ApiController
ControllerBase
ServiceBase
BackgroundService
IHostedService
DbContext
Hub
```

Example:

```json
{
  "construct": "BASE_CLASS",
  "name": "System.ServiceProcess.ServiceBase",
  "declaringType": "CustomerPollingService",
  "sourcePath": "Services/CustomerPollingService.cs"
}
```

### 6.3 Attributes and Annotations

Detect framework-relevant attributes such as:

```text
[ServiceContract]
[OperationContract]
[HttpGet]
[HttpPost]
[Route]
[ApiController]
[FunctionName]
[WebMethod]
[TestMethod]
[Fact]
[Test]
```

Capture the attribute name, declaring class or method, source file, line number, occurrence count, and relevant parameters.

### 6.4 Important Invocations and Object Creation

Capture selected framework-related invocations, for example:

- `WebApplication.CreateBuilder`
- `Host.CreateDefaultBuilder`
- `UseEndpoints`
- `MapControllers`
- `AddHostedService`
- `ServiceHost`
- `HttpClient`
- Queue-client creation
- Timer creation
- Database-context construction

This should remain targeted technical fingerprinting, not unrestricted call-graph generation.

---

## 7. File and Folder Indicators

Useful indicators include:

```text
*.svc
*.aspx
*.ascx
*.asmx
*.cshtml
*.razor
*.xaml
Global.asax
Startup.cs
Program.cs
Controllers/
Views/
Pages/
App_Start/
Services/
Jobs/
Tasks/
Functions/
```

Capture the indicator type, relative path, count, owning project, and extraction source.

These remain signals. `pattern-classification` performs the interpretation.

---

## 8. Configuration Fingerprint

Inspect configuration files such as:

- `web.config`
- `app.config`
- `appsettings.json`
- Environment-specific configuration
- Publish profiles
- Scheduler configuration
- Service installation configuration
- SSIS configuration
- Pipeline configuration

### 8.1 Hosting Indicators

Capture elements such as:

```text
system.web
system.webServer
aspNetCore
system.serviceModel
serviceHostingEnvironment
```

### 8.2 Endpoint Indicators

Capture service endpoints, HTTP bindings, SOAP bindings, REST route configuration, base addresses, and endpoint behavior declarations.

### 8.3 Background Execution Indicators

Capture Quartz configuration, Hangfire configuration, Windows Service names, timer configuration, cron expressions, and scheduled-task definitions.

### 8.4 Database Indicators

Capture connection-string names, database providers, Entity Framework providers, ADO.NET provider names, and database driver names.

Sensitive information must not be persisted.

Store:

```text
Connection Name: CustomerDb
Provider: System.Data.SqlClient
```

Do not store server names, usernames, passwords, tokens, or complete connection strings.

### 8.5 Messaging Indicators

Capture queue names, topic names, Service Bus configuration, RabbitMQ configuration, MSMQ configuration, and Kafka configuration. Sensitive values should be masked or excluded.

---

## 9. Endpoint Fingerprint

`application-fingerprinting` should identify endpoint-related evidence without assigning a final application pattern.

| Indicator | Example |
|---|---|
| HTTP Route | `/api/customers/{id}` |
| Controller Method | `GetCustomer` |
| WCF Operation | `GetCustomerDetails` |
| SOAP Binding | `basicHttpBinding` |
| Web Method | `[WebMethod]` |
| Function Trigger | HTTP trigger |
| Message Consumer | Queue listener |
| Scheduled Entry | Cron-triggered method |

For REST-related evidence, capture controller count, route count, HTTP verbs, routing style, and API versioning indicators.

For WCF-related evidence, capture service-contract count, operation-contract count, `.svc` count, binding types, endpoint declarations, and hosting configuration.

---

## 10. Execution-Model Fingerprint

Capture how the component appears to execute.

Possible observed execution models include:

```text
Request-response
Long-running process
Scheduled execution
Message-driven
Event-driven
File-triggered
Database-triggered
Interactive desktop
Library-only
Unknown
```

These should be evidence-backed indicators rather than final classifications.

---

## 11. Hosting Fingerprint

Potential hosting indicators include:

- IIS
- Self-hosted process
- Windows Service
- Console host
- ASP.NET Core Kestrel
- Azure Functions
- Docker container
- SSIS runtime
- Windows Task Scheduler
- External enterprise scheduler
- Unknown

A fingerprint may contain multiple hosting indicators.

---

## 12. Data-Access Fingerprint

Capture observed persistence and database technologies.

Potential indicators:

- ADO.NET
- Entity Framework 6
- Entity Framework Core
- Dapper
- NHibernate
- Stored procedures
- Raw SQL
- SQL files
- Oracle client
- SQL Server client
- MongoDB
- File-based persistence

Suggested attributes:

| Attribute | Example |
|---|---|
| Data-Access Technology | Entity Framework 6 |
| DbContext Count | 4 |
| Repository-Class Count | 12 |
| Stored-Procedure References | 23 |
| Database Provider | SQL Server |
| Raw SQL Usage | Detected |
| Connection Configuration | Present |

---

## 13. Messaging and Integration Fingerprint

Capture evidence of system-to-system integration.

Potential indicators:

- HTTP clients
- SOAP clients
- WCF client proxies
- MSMQ
- RabbitMQ
- Kafka
- Azure Service Bus
- IBM MQ
- File transfer
- FTP/SFTP
- SMTP
- COM integration
- External executable invocation

This indicates integration usage but does not define the primary application pattern.

---

## 14. Scheduling and Background-Processing Fingerprint

Capture indicators such as:

- Quartz jobs
- Hangfire jobs
- Hosted services
- Timers
- Windows scheduled tasks
- Control-M definitions
- Autosys files
- Cron expressions
- Batch files
- PowerShell launchers
- Console entry points
- File watchers

Suggested fields:

```text
Scheduler technology
Job class count
Schedule expression count
Timer usage count
External scheduler artifact count
Batch execution script count
```

---

## 15. UI Fingerprint

Capture user-interface-related evidence.

Potential indicators:

- Web Forms pages
- MVC views
- Razor pages
- Blazor components
- WinForms forms
- WPF windows
- XAML files
- Static web assets
- JavaScript framework files

Suggested attributes:

```text
ASPX page count
ASCX control count
Razor view count
Controller count
WinForms form count
WPF window count
XAML file count
Static asset count
```

---

## 16. Test Fingerprint

Capture:

- Test framework
- Test class count
- Test method count
- Test attributes
- Unit-test indicators
- Integration-test indicators
- Mocking framework
- Coverage configuration
- Test target project references

Possible frameworks include MSTest, NUnit, xUnit, SpecFlow, Moq, NSubstitute, and FakeItEasy.

---

## 17. Deployment and Packaging Fingerprint

Capture evidence from:

- Publish profiles
- MSI projects
- Web Deploy packages
- NuGet packaging
- Dockerfiles
- Kubernetes manifests
- Azure DevOps pipelines
- Jenkinsfiles
- PowerShell deployment scripts
- SSIS deployment manifests
- Windows Service installers

Suggested fields:

```text
Packaging method
Artifact type
Publish target
Container presence
Deployment script count
Pipeline reference count
Installer presence
```

---

## 18. Evidence Model

Every signal should be backed by evidence.

```json
{
  "signalType": "ATTRIBUTE",
  "signalName": "ServiceContract",
  "signalCategory": "FRAMEWORK_ANNOTATION",
  "value": "System.ServiceModel.ServiceContractAttribute",
  "sourceType": "SOURCE_CODE",
  "sourcePath": "Services/ICustomerService.cs",
  "lineStart": 12,
  "lineEnd": 12,
  "occurrenceCount": 1,
  "extractor": "RoslynAttributeExtractor",
  "extractionConfidence": 1.0
}
```

Recommended evidence source types:

```text
PROJECT_FILE
SOURCE_CODE
CONFIGURATION
FILE_STRUCTURE
PACKAGE_REFERENCE
ASSEMBLY_REFERENCE
PIPELINE
DEPLOYMENT_SCRIPT
SOLUTION_METADATA
```

Evidence is required because `pattern-classification` must be able to explain why a pattern matched.

---

## 19. Fingerprint Categories

A practical fingerprint should contain:

```text
Project Metadata
Framework References
Package Dependencies
Source Constructs
File Indicators
Configuration Indicators
Entry Points
Endpoint Indicators
Execution Indicators
Hosting Indicators
UI Indicators
Data-Access Indicators
Messaging Indicators
Scheduling Indicators
Deployment Indicators
Testing Indicators
```

---

## 20. Fingerprint Quality and Status

Every project fingerprint should include a processing status:

```text
COMPLETE
PARTIAL
FAILED
SKIPPED
NOT_SUPPORTED
```

Capture analysis capabilities such as:

- File discovery completed
- Project metadata parsed
- MSBuild evaluation completed
- Source syntax parsed
- Semantic compilation completed
- Configuration parsed
- Deployment artifacts parsed
- Generated code excluded
- Unsupported language constructs found

A partial fingerprint should remain usable.

---

## 21. Example Fingerprint Output

```json
{
  "schemaVersion": "1.0",
  "fingerprintVersion": "1.0",
  "repositoryId": "repo-1024",
  "solutionId": "solution-001",
  "projectId": "project-001",
  "projectName": "Customer.Service",
  "projectPath": "src/Customer.Service/Customer.Service.csproj",
  "projectMetadata": {
    "projectFormat": "LEGACY_MSBUILD",
    "language": "CSHARP",
    "outputType": "LIBRARY",
    "targetFrameworks": [
      {
        "raw": "v4.7.2",
        "family": "DOTNET_FRAMEWORK",
        "version": "4.7.2"
      }
    ]
  },
  "analysisCapabilities": {
    "projectEvaluated": true,
    "syntaxAnalysis": true,
    "semanticAnalysis": false,
    "configurationAnalysis": true
  },
  "fingerprint": {
    "frameworkReferences": [
      "System.ServiceModel",
      "System.Web"
    ],
    "fileIndicators": {
      "svcFiles": 3,
      "aspxFiles": 0,
      "controllers": 0
    },
    "sourceConstructs": {
      "serviceContracts": 4,
      "operationContracts": 21,
      "serviceBaseClasses": 0
    },
    "configurationIndicators": {
      "systemServiceModel": true,
      "serviceEndpoints": 3,
      "basicHttpBindings": 2,
      "wsHttpBindings": 1
    },
    "hostingIndicators": [
      "ASP_NET",
      "IIS_CONFIGURATION"
    ],
    "dataAccessIndicators": {
      "entityFramework6": true,
      "dbContextCount": 2,
      "sqlServerProvider": true
    },
    "integrationIndicators": {
      "wcfClientReferences": 1,
      "httpClientUsage": 0
    }
  },
  "evidenceCount": 39,
  "fingerprintStatus": "PARTIAL",
  "warnings": [
    {
      "code": "SEMANTIC_ANALYSIS_UNAVAILABLE",
      "message": "Semantic analysis could not be completed because dependencies were unavailable."
    }
  ]
}
```

The output must not yet contain an `applicationPattern` field. That belongs to `pattern-classification`.

---

## 22. Dashboard Views for `application-fingerprinting`

### 22.1 Fingerprinting Coverage

Show:

- Total projects eligible for fingerprinting
- Fingerprints completed
- Partial fingerprints
- Failed fingerprints
- Unsupported projects
- Projects with no meaningful fingerprint
- Average evidence count per project

### 22.2 Technical Signal Distribution

Show counts of projects containing HTTP, WCF-related, UI, scheduling, messaging, database, Windows Service, and container indicators.

These must be labelled as technical signals, not application counts.

Correct:

```text
Projects containing WCF-related signals: 145
```

Incorrect for `application-fingerprinting`:

```text
WCF applications: 145
```

### 22.3 Project Fingerprint Detail

```text
Project Fingerprint
├── Project metadata
├── Framework references
├── Package references
├── Entry points
├── Source constructs
├── Endpoint indicators
├── Configuration indicators
├── Hosting indicators
├── Data-access indicators
├── Messaging indicators
├── Scheduling indicators
├── Deployment indicators
├── Test indicators
└── Evidence and warnings
```

---

## 23. Out of Scope for `application-fingerprinting`

The following remain outside `application-fingerprinting`:

- Final application-pattern assignment
- WCF, REST, batch, web, or desktop classification
- Pattern-priority resolution
- Primary versus secondary pattern determination
- Pattern catalog matching
- Classification confidence
- Unknown application grouping
- Clustering unmatched fingerprints
- New-pattern proposal
- Business application identification
- Modernization effort estimation
- Migration-wave planning
- Cloud-readiness assessment

These belong to `pattern-classification` and `pattern-discovery-clustering`.

---

## 24. Boundary Between `application-fingerprinting` and `pattern-classification`

| `application-fingerprinting` — Fingerprinting | `pattern-classification` — Classification |
|---|---|
| Detect `.svc` files | Classify as WCF Service |
| Detect `ApiController` | Classify as REST API |
| Detect `ServiceBase` | Classify as Windows Service |
| Detect Quartz jobs | Classify as Scheduled Batch |
| Detect `.aspx` files | Classify as Web Forms |
| Detect `Microsoft.NET.Sdk.Web` | Evaluate ASP.NET Core patterns |
| Detect `ServiceContract` attributes | Apply WCF catalog rule |
| Detect controller routes | Apply REST application rule |

`application-fingerprinting` captures facts. `pattern-classification` interprets those facts against the catalog.

---

# Part B — Recommended Technology Stack

## 25. Primary Implementation Choice

Recommended implementation:

```text
Language:       C#
Runtime:        Modern .NET LTS
Application:    Console application or worker service
Primary tools:  MSBuild APIs and Roslyn
Output:         Versioned JSON
```

`solution-discovery` can remain in Python. `application-fingerprinting` can be independently implemented in .NET because the architecture is decoupled.

Use .NET for `application-fingerprinting` because it provides native support for Visual Studio solutions, MSBuild projects, C# and VB.NET syntax, semantic symbol resolution, base-class and interface resolution, attribute resolution, and cross-project compilation context.

---

## 26. Core Libraries

### 26.1 MSBuild

Recommended packages:

```text
Microsoft.Build
Microsoft.Build.Framework
Microsoft.Build.Utilities.Core
Microsoft.Build.Locator
```

Use MSBuild for:

- Evaluating project files
- Resolving imported `.props` and `.targets`
- Expanding project properties
- Resolving `Compile`, `Content`, `None`, and `ProjectReference` items
- Reading package references
- Determining output type
- Identifying project SDK
- Resolving conditional project metadata

Raw XML parsing should remain available as a fallback.

Recommended precedence:

```text
MSBuild-evaluated value
        ↓ fallback
Raw project-file value
```

Retain both raw and evaluated values when traceability is useful.

### 26.2 Roslyn

Recommended packages:

```text
Microsoft.CodeAnalysis
Microsoft.CodeAnalysis.CSharp
Microsoft.CodeAnalysis.VisualBasic
Microsoft.CodeAnalysis.Workspaces.MSBuild
```

Use Roslyn for:

- Class and interface discovery
- Base-class detection
- Implemented-interface detection
- Method discovery
- Attribute extraction
- Namespace usage
- Entry-point detection
- Controller detection
- Service-contract detection
- Route detection
- Test-framework detection
- Framework API usage
- Invocation analysis
- Object-creation analysis

#### Syntax Analysis

Syntax analysis should work without successful compilation. It can detect declarations, attributes, base-class names, interface names, invocation names, imports, and literal route values.

#### Semantic Analysis

Semantic analysis resolves the actual types and symbols, such as distinguishing `System.Web.Mvc.Controller` from an unrelated user-defined `Controller` class.

---

## 27. Layered Analysis Strategy

The scanner should not depend on every legacy project building successfully.

### Level 1 — File-System Analysis

Always available. Detect solution files, project files, source files, configuration, deployment files, scripts, and pipeline files.

### Level 2 — Structured-File Parsing

Use:

- `System.Xml.Linq` for XML
- `System.Text.Json` for JSON
- A YAML parser for pipelines
- Solution-file parsing
- Project-file XML fallback

### Level 3 — Roslyn Syntax Analysis

Use syntax trees without requiring successful compilation.

This should work when NuGet restore fails, project references are missing, imported targets are unavailable, the repository is incomplete, or source code contains compile errors.

### Level 4 — Roslyn Semantic Analysis

Use compilation and semantic models when the project can be loaded sufficiently.

This provides fully qualified symbols, resolved inheritance, framework API calls, cross-project symbols, and attribute-type resolution.

Semantic analysis is the richest level, but it should be an enhancement rather than a mandatory prerequisite.

---

## 28. Fallback Model

```text
Try MSBuild solution loading
          │
          ├── Success
          │      └── Run syntax and semantic analysis
          │
          └── Failure
                 ├── Evaluate individual project
                 │      ├── Success → syntax and partial semantics
                 │      └── Failure
                 │             ├── Parse project XML
                 │             └── Parse source files syntactically
                 └── Record warnings and degradation reason
```

The scanner must produce useful partial output instead of failing the entire repository.

---

## 29. Windows and Linux Execution

A mixed .NET estate may require two worker profiles.

### Cross-Platform Worker

Suitable for file discovery, raw project parsing, SDK-style project evaluation, C# syntax analysis, basic semantic analysis, configuration analysis, and JSON generation.

### Windows Legacy Worker

Suitable for full .NET Framework projects, Web Forms, legacy WCF, older Visual Studio project systems, SSIS, COM references, Windows Service installer projects, old MSBuild targets, and projects requiring .NET Framework developer packs.

For the first implementation, a Windows-based worker is the safest starting point because the estate contains legacy .NET Framework, WCF, SSIS, and older web applications.

---

## 30. Extractor-Based Design

Do not place all fingerprinting logic in one scanner class.

```csharp
public interface IFingerprintExtractor
{
    string Name { get; }

    bool CanProcess(ProjectContext context);

    Task<ExtractorResult> ExtractAsync(
        ProjectContext context,
        CancellationToken cancellationToken);
}
```

Possible extractors:

```text
ProjectMetadataExtractor
FrameworkReferenceExtractor
PackageReferenceExtractor
FileIndicatorExtractor
EntryPointExtractor
AttributeExtractor
InheritanceExtractor
EndpointExtractor
WcfConfigurationExtractor
AspNetConfigurationExtractor
DataAccessExtractor
MessagingExtractor
SchedulingExtractor
UiArtifactExtractor
TestIndicatorExtractor
DeploymentArtifactExtractor
```

Each extractor should produce signals and evidence, not final classifications.

---

## 31. Separate Fingerprint Extraction from Pattern Classification

Do not implement `pattern-classification` logic inside `application-fingerprinting`.

Avoid:

```csharp
if (hasSvcFile && hasServiceContract)
{
    project.Pattern = "WCF_SERVICE";
}
```

Instead, `application-fingerprinting` should produce signals:

```json
{
  "signals": [
    { "name": "SVC_FILE", "count": 3 },
    { "name": "SERVICE_CONTRACT_ATTRIBUTE", "count": 4 },
    { "name": "OPERATION_CONTRACT_ATTRIBUTE", "count": 21 },
    { "name": "SYSTEM_SERVICE_MODEL_CONFIG", "count": 1 }
  ]
}
```

`pattern-classification` may later apply configurable rules.

This separation enables reusable fingerprints, reclassification without rescanning, explainability, configurable catalogs, and `pattern-discovery-clustering`.

---

## 32. JSON Output Design

Use strongly typed C# records or classes and serialize with `System.Text.Json`.

Suggested top-level structure:

```json
{
  "schemaVersion": "1.0",
  "scannerVersion": "1.0.0",
  "scanId": "scan-20260818-001",
  "repositoryId": "repo-1024",
  "projects": [],
  "repositorySignals": [],
  "warnings": [],
  "scanSummary": {}
}
```

Every project fingerprint should contain identity, structural metadata, analysis capabilities, fingerprint categories, evidence, status, and warnings.

---

## 33. JSON Schema

Maintain a formal, versioned JSON Schema.

```text
schemas/
├── application-fingerprint-v1.0.schema.json
├── application-fingerprint-v1.1.schema.json
└── fingerprint-signal-v1.0.schema.json
```

The schema should define required fields, enums, nullability, evidence structure, signal categories, status values, and version compatibility.

Validate every output before persistence.

---

## 34. Suggested Solution Structure

```text
DotNetApplicationFingerprinting.sln

src/
├── Fingerprinting.Cli/
├── Fingerprinting.Application/
├── Fingerprinting.Domain/
├── Fingerprinting.MSBuild/
├── Fingerprinting.Roslyn/
├── Fingerprinting.Configuration/
├── Fingerprinting.Extractors/
├── Fingerprinting.Serialization/
└── Fingerprinting.Infrastructure/

tests/
├── Fingerprinting.UnitTests/
├── Fingerprinting.IntegrationTests/
├── Fingerprinting.GoldenFileTests/
└── Fingerprinting.RepositoryFixtures/
```

Recommended responsibilities:

- **Cli:** command-line entry point
- **Application:** scan orchestration and pipeline
- **Domain:** project, signal, evidence, status, and fingerprint models
- **MSBuild:** project evaluation and XML fallback
- **Roslyn:** syntax, semantic, workspace, and symbol utilities
- **Configuration:** XML, JSON, and YAML extractors
- **Extractors:** technical fingerprint modules
- **Serialization:** JSON serialization, schema validation, and versioning
- **Infrastructure:** logging, metrics, persistence, and file storage

---

## 35. Testing Strategy

Golden-file testing is strongly recommended.

Create fixture repositories:

```text
fixtures/
├── legacy-wcf-service/
├── aspnet-webforms/
├── aspnet-mvc/
├── netcore-api/
├── windows-service/
├── console-batch/
├── ssis-project/
├── broken-project-reference/
├── missing-nuget-dependency/
└── mixed-solution/
```

For each fixture, store expected JSON. The test should run the scanner, normalize volatile fields, validate the JSON Schema, and compare the result with the expected output.

Important scenarios:

- Missing solution
- Multiple solutions
- Standalone projects
- Malformed XML
- Conditional target frameworks
- `Directory.Build.props`
- Missing imported targets
- Source code that does not compile
- Duplicate source files
- Generated code
- Very large repositories
- Unsupported project types
- Partial semantic analysis
- Multiple application-related indicators in one project

---

## 36. Operational Stack

| Area | Recommendation |
|---|---|
| Scanner Language | C# |
| Runtime | Modern .NET LTS |
| Project Evaluation | MSBuild APIs |
| Source Analysis | Roslyn |
| XML Parsing | `System.Xml.Linq` |
| JSON Parsing and Serialization | `System.Text.Json` |
| YAML Parsing | Mature YAML library |
| CLI | `System.CommandLine` or equivalent |
| Logging | `Microsoft.Extensions.Logging` |
| Dependency Injection | `Microsoft.Extensions.DependencyInjection` |
| Parallel Processing | TPL or Channels |
| Raw Result Storage | Object storage |
| Inventory Database | PostgreSQL |
| API | ASP.NET Core Web API |
| Dashboard | Existing dashboard technology |
| `pattern-discovery-clustering` | Python |

---

## 37. Role of Python

Python can remain the implementation language for `solution-discovery`.

```text
solution-discovery:
Python
- Repository scanning
- Solution and project discovery
- Structural inventory
- Initial metadata extraction

application-fingerprinting:
C# and .NET
- MSBuild evaluation
- Roslyn syntax analysis
- Roslyn semantic analysis
- Technical fingerprint extraction

pattern-classification:
Configurable classification engine

pattern-discovery-clustering:
Python-based clustering and pattern discovery
```

There is no need to rewrite `solution-discovery` in .NET merely for language consistency.

---

## 38. Implementation Principles

1. **Partial success over total failure** — a broken legacy project should still produce a useful partial fingerprint.
2. **Evidence for every meaningful signal** — every signal should identify where and how it was extracted.
3. **Syntax analysis must work without compilation** — semantic analysis improves accuracy but is not mandatory.
4. **No classification inside fingerprint extraction** — `application-fingerprinting` extracts facts; `pattern-classification` assigns patterns.
5. **Version every schema and scanner output** — fingerprints must remain comparable and reprocessable.
6. **Preserve raw and evaluated values** — MSBuild-evaluated metadata should not silently erase raw values.
7. **Avoid storing secrets** — credentials, tokens, and sensitive configuration must be excluded or masked.
8. **Use modular extractors** — new signals should be addable without changing the core pipeline.
9. **Retain immutable raw output** — raw JSON supports auditability and reclassification.
10. **Make the scanner deterministic** — the same repository revision and scanner version should produce the same normalized fingerprint.

---

# `application-fingerprinting` Outcome

> For every discovered project or application candidate, generate a normalized, versioned, and evidence-backed technical fingerprint describing its framework usage, source constructs, configuration, endpoints, execution model, hosting, integrations, data access, scheduling, testing, and deployment indicators, without yet assigning a final application pattern.

## Recommended Technical Direction

> Implement `application-fingerprinting` as a modular C#/.NET scanner using MSBuild for project evaluation, Roslyn for syntax and semantic analysis, structured configuration parsers for XML/JSON/YAML, layered fallbacks for non-buildable legacy applications, and a versioned JSON Schema for the final fingerprint output.
