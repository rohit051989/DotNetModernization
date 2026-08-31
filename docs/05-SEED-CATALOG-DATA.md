# 05 — Seed Catalog Data

Initial content for the catalog. Load via `python -m app.seed` (idempotent, upsert
by id).

**Totals:** 8 patterns, 16 target state options, 2 engagements, 10 decision records
(5 approved, 1 in review, 2 parked in the primary engagement; 2 approved in the
secondary engagement).

The second engagement exists to demonstrate the core thesis — the same pattern
catalog serving two clients who select different target states. Keep it.

Playbook bodies below are deliberately short. They are realistic placeholders that
look substantive in the UI; they are not finished playbooks.

---

## Patterns and target state options

```yaml
patterns:

  # ---------------------------------------------------------------- 1
  - id: core2-rest-api
    name: ".NET Core 2.x REST API"
    summary: "ASP.NET Core 2.x Web API with Startup-based hosting, running on IIS."
    description: |
      REST API built on ASP.NET Core 2.0-2.2 using the classic `Startup.cs`
      `ConfigureServices` / `Configure` pair and `IWebHostBuilder`. Typically
      hosted in IIS behind the ASP.NET Core Module. Out of support since 2019.
    legacy_stack: ".NET Core 2.0 - 2.2"
    category: web-api
    typical_indicators: "Startup.cs with ConfigureServices/Configure, Program.cs with WebHost.CreateDefaultBuilder, controllers deriving from ControllerBase."
    known_risks: "Default JSON serializer changes from Newtonsoft to System.Text.Json on modern .NET, which can silently alter payload casing, null handling and date formats. Contract snapshot before migration is essential."
    detection_rules:
      target_frameworks: ["netcoreapp2.0", "netcoreapp2.1", "netcoreapp2.2"]
      required_namespaces: ["Microsoft.AspNetCore.Mvc"]
      required_packages: ["Microsoft.AspNetCore.App", "Microsoft.AspNetCore.Mvc"]
      file_globs: ["**/Startup.cs", "**/Controllers/*Controller.cs"]
      forbidden_file_globs: ["**/*.svc", "**/*.aspx"]
      config_markers: []
      confidence_weight: 1.0
      notes: "Highest-confidence pattern in the estate. Simplest migration path and requires no contested target-state decision."
    target_states:
      - id: net10-api-controllers-preserved
        name: ".NET 10 Web API, controllers preserved"
        summary: "Retarget to .NET 10, move to WebApplicationBuilder, keep controller classes and routes exactly as they are."
        target_stack: ".NET 10 + ASP.NET Core, container on OCP4"
        consumer_impact: none
        effort: low
        linux_compatible: true
        container_ready: true
        is_lift_and_shift: true
        prerequisites: "Repository builds cleanly on the current framework. Contract snapshot captured before any change."
        known_limitations: "Pins Newtonsoft.Json explicitly rather than adopting System.Text.Json, to guarantee payload parity. Serializer modernization is deferred to a later pass."
        engine_support:
          engine: github-copilot-app-modernization
          coverage: strong
          scenarios: ["dotnet-upgrade"]
          skills: ["sdk-style-conversion", "aspnetcore-hosting-model"]
          gaps: ["OCP4 containerization", "health endpoint injection", "stdout logging configuration"]
          custom_skills_required: ["ocp4-container-packaging", "linux-remediation"]
        playbook_md: |
          ## Steps
          1. Convert project to SDK-style if not already.
          2. Retarget to `net10.0`.
          3. Replace `WebHost.CreateDefaultBuilder` with `WebApplication.CreateBuilder`,
             folding `Startup.ConfigureServices` and `Startup.Configure` into `Program.cs`.
          4. Pin `Newtonsoft.Json` via `AddNewtonsoftJson()` to preserve payload shape.
          5. Replace `IHostingEnvironment` with `IWebHostEnvironment`.
          6. Move `appsettings` overrides to environment variables.
          7. Add `/healthz` and `/readyz` endpoints for OCP4 probes.
          ## Parity checks
          - OpenAPI diff against the pre-migration snapshot: zero route, verb, status
            code or schema differences.
          - Characterization tests replayed against recorded request/response pairs.

      - id: net10-api-minimal
        name: ".NET 10 Minimal API"
        summary: "Retarget and additionally rewrite controllers as minimal API endpoints."
        target_stack: ".NET 10 + Minimal APIs, container on OCP4"
        consumer_impact: none
        effort: medium
        linux_compatible: true
        container_ready: true
        is_lift_and_shift: false
        prerequisites: "Good test coverage, since endpoint code is restructured rather than retargeted."
        known_limitations: "External contract is unchanged but internal structure churns significantly, enlarging the review surface for no consumer-visible benefit. Not the default choice under a lift-and-shift posture."
        engine_support:
          engine: github-copilot-app-modernization
          coverage: partial
          scenarios: ["dotnet-upgrade"]
          skills: ["sdk-style-conversion"]
          gaps: ["controller-to-minimal-API restructuring", "OCP4 containerization"]
          custom_skills_required: ["minimal-api-restructure", "ocp4-container-packaging"]
        playbook_md: |
          Same retargeting steps as the controllers-preserved option, then convert
          each controller action to a mapped endpoint. Only select this where the
          client explicitly wants the modern idiom and accepts the larger diff.

  # ---------------------------------------------------------------- 2
  - id: fx47-class-library
    name: ".NET Framework 4.7 class library"
    summary: "Shared class library targeting .NET Framework 4.7, consumed by multiple applications."
    description: |
      Non-SDK-style class library on .NET Framework 4.7x. Frequently a shared
      dependency across several applications in the same repository, which makes it
      a coordination point rather than an isolated migration.
    legacy_stack: ".NET Framework 4.7 / 4.7.1 / 4.7.2"
    category: library
    typical_indicators: "Legacy csproj with <TargetFrameworkVersion>, packages.config, AssemblyInfo.cs, OutputType Library."
    known_risks: "Shared libraries fan out. Migrating one can break every consumer simultaneously, so these must be sequenced first within a wave and verified across all dependents."
    detection_rules:
      target_frameworks: ["net47", "net471", "net472"]
      forbidden_namespaces: ["System.Web", "System.ServiceModel", "System.ServiceProcess"]
      file_globs: ["**/Properties/AssemblyInfo.cs"]
      project_properties:
        OutputType: "Library"
      confidence_weight: 0.8
      notes: "Lower confidence weight because many patterns share these markers. Apply after more specific patterns have been matched."
    target_states:
      - id: netstandard20-bridge
        name: ".NET Standard 2.0 bridge"
        summary: "Retarget to .NET Standard 2.0 so both legacy and modern consumers can reference it during a phased migration."
        target_stack: ".NET Standard 2.0"
        consumer_impact: none
        effort: low
        linux_compatible: true
        container_ready: false
        is_lift_and_shift: true
        prerequisites: "No dependency on Framework-only APIs such as System.Web, AppDomain or Windows-specific configuration."
        known_limitations: "Interim state, not a destination. Some Framework APIs have no .NET Standard equivalent. Plan a later move to net10.0 once all consumers are migrated."
        engine_support:
          engine: github-copilot-app-modernization
          coverage: strong
          scenarios: ["dotnet-upgrade", "sdk-style-conversion"]
          skills: ["sdk-style-conversion", "packages-config-to-packagereference"]
          gaps: []
          custom_skills_required: []
        playbook_md: |
          Use where the library has consumers that cannot migrate in the same wave.
          Convert to SDK-style, migrate packages.config to PackageReference,
          retarget to netstandard2.0, remove AssemblyInfo in favour of csproj
          properties. Both old and new consumers keep working.

      - id: net10-class-library
        name: ".NET 10 class library"
        summary: "Retarget directly to .NET 10. Requires all consumers to migrate in the same wave."
        target_stack: ".NET 10"
        consumer_impact: low
        effort: low
        linux_compatible: true
        container_ready: false
        is_lift_and_shift: true
        prerequisites: "All consuming applications scheduled in the same migration wave."
        known_limitations: "Legacy Framework consumers cannot reference a net10.0 library. Sequencing is mandatory, not optional."
        engine_support:
          engine: github-copilot-app-modernization
          coverage: strong
          scenarios: ["dotnet-upgrade"]
          skills: ["sdk-style-conversion", "packages-config-to-packagereference"]
          gaps: ["cross-repository consumer coordination"]
          custom_skills_required: []
        playbook_md: |
          Preferred destination once the dependency graph shows every consumer is in
          the same wave. Otherwise use the .NET Standard 2.0 bridge first.

  # ---------------------------------------------------------------- 3
  - id: fx-aspnet-mvc
    name: "Classic ASP.NET MVC / Web API on .NET Framework"
    summary: "ASP.NET MVC 5 or Web API 2 application on .NET Framework, hosted in IIS."
    description: |
      System.Web-based MVC or Web API application with Global.asax, App_Start
      configuration classes and web.config. Tightly coupled to IIS and the
      System.Web pipeline.
    legacy_stack: ".NET Framework 4.6 - 4.8, ASP.NET MVC 5 / Web API 2"
    category: web-api
    typical_indicators: "Global.asax, App_Start/RouteConfig.cs, App_Start/WebApiConfig.cs, web.config with system.web section, references to System.Web.Mvc."
    known_risks: "HttpContext usage is often pervasive and does not map cleanly. Session state, request-scoped statics and web.config transforms all need deliberate handling."
    detection_rules:
      target_frameworks: ["net46", "net461", "net462", "net47", "net471", "net472", "net48"]
      required_namespaces: ["System.Web.Mvc", "System.Web.Http"]
      forbidden_file_globs: ["**/*.aspx"]
      file_globs: ["**/Global.asax", "**/App_Start/*.cs"]
      config_markers: ["system.web", "system.webServer"]
      confidence_weight: 1.0
      notes: "Distinguish from Web Forms by the absence of .aspx files. An application may contain both, in which case record two impact-map regions."
    target_states:
      - id: aspnetcore-incremental-adapters
        name: "Incremental migration with System.Web adapters"
        summary: "Run ASP.NET Core alongside the existing app using System.Web adapters and a YARP strangler proxy, migrating routes progressively."
        target_stack: ".NET 10 + ASP.NET Core + System.Web adapters + YARP"
        consumer_impact: none
        effort: medium
        linux_compatible: true
        container_ready: true
        is_lift_and_shift: true
        prerequisites: "Ability to run two processes during transition. Route inventory captured up front."
        known_limitations: "Temporarily increases operational complexity by running two applications. Requires a defined end date or the interim state becomes permanent."
        engine_support:
          engine: github-copilot-app-modernization
          coverage: strong
          scenarios: ["aspnet-to-aspnetcore"]
          skills: ["system-web-adapters", "routing-migration", "httpcontext-migration", "global-asax-to-startup", "webconfig-to-appsettings"]
          gaps: ["YARP proxy configuration", "OCP4 containerization"]
          custom_skills_required: ["ocp4-container-packaging", "linux-remediation"]
        playbook_md: |
          ## Steps
          1. Stand up a new ASP.NET Core host alongside the existing application.
          2. Introduce YARP to route unmigrated paths back to the legacy app.
          3. Add System.Web adapters so shared session and HttpContext work across both.
          4. Migrate controllers route group by route group, verifying each.
          5. Retire the legacy host once the route inventory is exhausted.
          ## Parity checks
          - Route inventory diff at each increment: no route may disappear silently.

      - id: aspnetcore-mvc-net10
        name: "Direct migration to ASP.NET Core MVC on .NET 10"
        summary: "Single-pass migration of the whole application to ASP.NET Core MVC."
        target_stack: ".NET 10 + ASP.NET Core MVC, container on OCP4"
        consumer_impact: low
        effort: high
        linux_compatible: true
        container_ready: true
        is_lift_and_shift: false
        prerequisites: "Strong test coverage. Limited HttpContext and session sprawl."
        known_limitations: "Big-bang cutover with a large review surface. Only appropriate for small or well-tested applications."
        engine_support:
          engine: github-copilot-app-modernization
          coverage: strong
          scenarios: ["aspnet-to-aspnetcore"]
          skills: ["routing-migration", "filters-migration", "httpcontext-migration", "global-asax-to-startup", "webconfig-to-appsettings", "bundling-migration"]
          gaps: ["OCP4 containerization", "Windows authentication replacement on Linux"]
          custom_skills_required: ["ocp4-container-packaging", "linux-remediation"]
        playbook_md: |
          Use for smaller applications where the incremental approach adds more
          operational overhead than it removes risk.

  # ---------------------------------------------------------------- 4
  - id: aspnet-webforms
    name: "ASP.NET Web Forms"
    summary: "Server-rendered Web Forms application with .aspx pages and code-behind."
    description: |
      Web Forms application using the page lifecycle, ViewState, server controls
      and code-behind. There is no lift-and-shift path: Web Forms does not exist on
      modern .NET, so any migration is a rewrite by definition.
    legacy_stack: ".NET Framework 4.x, ASP.NET Web Forms"
    category: web-ui
    typical_indicators: ".aspx and .aspx.cs pairs, .ascx user controls, Site.Master, ViewState in rendered output, references to System.Web.UI."
    known_risks: "This is the one pattern where the engagement's lift-and-shift default cannot be honoured. Surface it to the client early rather than discovering it mid-programme. Effort estimates for Web Forms rewrites are routinely underestimated."
    detection_rules:
      target_frameworks: ["net46", "net461", "net462", "net47", "net471", "net472", "net48"]
      required_namespaces: ["System.Web.UI"]
      file_globs: ["**/*.aspx", "**/*.ascx", "**/*.Master"]
      config_markers: ["system.web"]
      confidence_weight: 1.0
      notes: "Presence of .aspx files is decisive. Flag for a mandatory rewrite decision."
    target_states:
      - id: blazor-server-net10
        name: "Blazor Server on .NET 10"
        summary: "Rewrite as a Blazor Server application, the closest conceptual match to the Web Forms component and server-render model."
        target_stack: ".NET 10 + Blazor Server, container on OCP4"
        consumer_impact: high
        effort: high
        linux_compatible: true
        container_ready: true
        is_lift_and_shift: false
        prerequisites: "Screen inventory and behavioural specification captured before starting. Business sign-off on UI change."
        known_limitations: "No automated path preserves ViewState or the page lifecycle. Expect genuine redesign of stateful screens. Requires a persistent connection, which changes load-balancer and session-affinity requirements on OCP4."
        engine_support:
          engine: github-copilot-app-modernization
          coverage: partial
          scenarios: ["webforms-to-blazor"]
          skills: ["webforms-page-conversion", "server-control-mapping"]
          gaps: ["ViewState semantics", "complex page lifecycle logic", "OCP4 session affinity"]
          custom_skills_required: ["ocp4-container-packaging", "webforms-behaviour-capture"]
        playbook_md: |
          ## Before starting
          Capture a screen-by-screen behavioural specification. Automated conversion
          produces a starting point, not a finished screen.
          ## Verification
          Conventional contract parity does not apply. Use screen-level acceptance
          tests derived from the captured specification instead.

      - id: aspnetcore-mvc-rewrite
        name: "ASP.NET Core MVC rewrite"
        summary: "Rewrite as a conventional server-rendered ASP.NET Core MVC application."
        target_stack: ".NET 10 + ASP.NET Core MVC + Razor views, container on OCP4"
        consumer_impact: high
        effort: high
        linux_compatible: true
        container_ready: true
        is_lift_and_shift: false
        prerequisites: "Same as Blazor Server. Preferred where the team's skills favour MVC over Blazor."
        known_limitations: "Requires explicit reimplementation of state that ViewState previously handled implicitly."
        engine_support:
          engine: github-copilot-app-modernization
          coverage: partial
          scenarios: ["aspnet-to-aspnetcore"]
          skills: ["routing-migration", "webconfig-to-appsettings"]
          gaps: ["Web Forms page model has no direct MVC equivalent", "OCP4 containerization"]
          custom_skills_required: ["ocp4-container-packaging", "webforms-behaviour-capture"]
        playbook_md: |
          Choose over Blazor Server where the delivery team is stronger in MVC, or
          where a persistent connection is undesirable in the target topology.

  # ---------------------------------------------------------------- 5
  - id: wcf-iis-servicemodel
    name: "WCF service hosted in IIS"
    summary: "SOAP service built on System.ServiceModel and hosted in IIS via .svc endpoints."
    description: |
      WCF service using ServiceContract and OperationContract attributes, with
      bindings and behaviours configured in web.config, hosted in IIS. Frequently
      consumed by external parties whose contracts cannot change.
    legacy_stack: ".NET Framework 4.x, WCF / System.ServiceModel"
    category: service
    typical_indicators: ".svc files, [ServiceContract] and [OperationContract] attributes, system.serviceModel section in web.config, generated WSDL endpoints."
    known_risks: "External consumers are the dominant constraint. Establish before any decision whether callers can change. A silently altered WSDL is the highest-consequence failure mode in this estate."
    detection_rules:
      target_frameworks: ["net46", "net461", "net462", "net47", "net471", "net472", "net48"]
      required_namespaces: ["System.ServiceModel"]
      file_globs: ["**/*.svc"]
      config_markers: ["system.serviceModel"]
      confidence_weight: 1.0
      notes: "Server-side WCF only. Client-side WCF proxies are a separate concern and are handled as part of the consuming application."
    target_states:
      - id: corewcf-net10
        name: "CoreWCF on .NET 10"
        summary: "Port to CoreWCF, preserving service contracts, bindings and the published WSDL."
        target_stack: ".NET 10 + CoreWCF, container on OCP4"
        consumer_impact: none
        effort: medium
        linux_compatible: true
        container_ready: true
        is_lift_and_shift: true
        prerequisites: "Bindings in use must be supported by CoreWCF. WSDL snapshot captured before migration."
        known_limitations: "CoreWCF does not support every WCF binding. WS-* protocols, MSMQ transport and some Windows-integrated security modes need case-by-case assessment. Windows authentication requires an alternative on Linux."
        engine_support:
          engine: github-copilot-app-modernization
          coverage: strong
          scenarios: ["dotnet-upgrade"]
          skills: ["upgrade-wcf-to-corewcf"]
          gaps: ["OCP4 containerization", "Windows authentication replacement", "WSDL parity verification"]
          custom_skills_required: ["ocp4-container-packaging", "linux-remediation", "wsdl-parity-check"]
        playbook_md: |
          ## Steps
          1. Snapshot the published WSDL and generate a contract baseline.
          2. Retarget to net10.0 and replace System.ServiceModel hosting with CoreWCF.
          3. Translate web.config bindings and behaviours to code-based configuration.
          4. Convert synchronous contracts to Task-based where the engine proposes it,
             verifying the generated WSDL is unchanged.
          5. Replace Windows authentication with the engagement-approved mechanism.
          ## Parity checks
          - WSDL diff against the baseline: must be empty.
          - Recorded SOAP request/response pairs replayed against the new service.

      - id: grpc-net10
        name: "gRPC service on .NET 10"
        summary: "Rewrite as a contract-first gRPC service."
        target_stack: ".NET 10 + gRPC, container on OCP4"
        consumer_impact: high
        effort: high
        linux_compatible: true
        container_ready: true
        is_lift_and_shift: false
        prerequisites: "Every consumer must be able to adopt a gRPC client. Requires HTTP/2 support through the OCP4 ingress path."
        known_limitations: "All callers must change. Only viable where consumers are internal and in scope for coordinated change."
        engine_support:
          engine: github-copilot-app-modernization
          coverage: none
          scenarios: []
          skills: []
          gaps: ["No engine path from WCF contracts to protobuf definitions"]
          custom_skills_required: ["wcf-contract-to-proto", "ocp4-container-packaging"]
        playbook_md: |
          Contract-first. Derive .proto definitions from the existing service
          contracts, then implement against them. Requires a coordinated client
          migration plan before starting.

      - id: rest-net10
        name: "REST API on .NET 10"
        summary: "Rewrite as a conventional REST API, retiring SOAP entirely."
        target_stack: ".NET 10 + ASP.NET Core, container on OCP4"
        consumer_impact: high
        effort: high
        linux_compatible: true
        container_ready: true
        is_lift_and_shift: false
        prerequisites: "All consumers able to change. Resource model designed and agreed."
        known_limitations: "The largest change of the three options. SOAP faults, message-level security and transactional semantics have no direct REST equivalent."
        engine_support:
          engine: github-copilot-app-modernization
          coverage: none
          scenarios: []
          skills: []
          gaps: ["No engine path from WCF to REST resource modelling"]
          custom_skills_required: ["wcf-contract-to-rest", "ocp4-container-packaging"]
        playbook_md: |
          Select only where SOAP retirement is an explicit programme objective and
          every consumer is in scope for coordinated change.

  # ---------------------------------------------------------------- 6
  - id: console-batch-job
    name: "Console batch application"
    summary: "Console executable run on a schedule, typically by Windows Task Scheduler."
    description: |
      Console application with a Main entry point performing batch work — file
      processing, data loads, report generation — invoked on a schedule rather than
      run continuously.
    legacy_stack: ".NET Framework 4.x or .NET Core 2.x console"
    category: batch
    typical_indicators: "OutputType Exe, Main entry point, no web packages, app.config, frequent use of local file paths and drive letters."
    known_risks: "Hardcoded Windows paths, drive-letter mappings, UNC shares and Windows-only scheduling assumptions. Scheduling itself moves out of the application and into the platform, which is a change of operational ownership as much as a code change."
    detection_rules:
      target_frameworks: ["net47", "net471", "net472", "net48", "netcoreapp2.1", "netcoreapp3.1"]
      forbidden_namespaces: ["System.Web", "System.ServiceModel", "System.ServiceProcess"]
      project_properties:
        OutputType: "Exe"
      confidence_weight: 0.9
      notes: "Distinguish from Windows Service by the absence of System.ServiceProcess and ServiceBase."
    target_states:
      - id: ocp4-cronjob-container
        name: "OCP4 CronJob container"
        summary: "Retarget to .NET 10, containerize, and schedule as an OpenShift CronJob."
        target_stack: ".NET 10 console + OCP4 CronJob"
        consumer_impact: low
        effort: medium
        linux_compatible: true
        container_ready: true
        is_lift_and_shift: true
        prerequisites: "Job is idempotent and safe to retry. File paths externalized to configuration."
        known_limitations: "Scheduling moves from Windows Task Scheduler to OpenShift, changing who owns the schedule. Local file dependencies must move to a mounted volume or object storage."
        engine_support:
          engine: github-copilot-app-modernization
          coverage: partial
          scenarios: ["dotnet-upgrade"]
          skills: ["sdk-style-conversion", "configuration-migration"]
          gaps: ["containerization", "CronJob manifest generation", "Windows path remediation"]
          custom_skills_required: ["ocp4-container-packaging", "linux-remediation", "cronjob-manifest-generation"]
        playbook_md: |
          ## Steps
          1. Retarget to net10.0 and convert to SDK-style.
          2. Replace hardcoded paths with configuration; verify path separator and
             case-sensitivity assumptions.
          3. Ensure a non-zero exit code on failure so OpenShift can detect it.
          4. Emit structured logs to stdout.
          5. Generate the CronJob manifest with the schedule previously held in
             Windows Task Scheduler.

      - id: worker-service-container
        name: ".NET Worker Service container"
        summary: "Convert to a long-running Worker Service with an internal scheduler, deployed as a Deployment rather than a CronJob."
        target_stack: ".NET 10 Worker Service + OCP4 Deployment"
        consumer_impact: low
        effort: medium
        linux_compatible: true
        container_ready: true
        is_lift_and_shift: false
        prerequisites: "Job frequency high enough that a persistently running pod is justified."
        known_limitations: "Consumes resources continuously. Scheduling logic moves into the application, which makes it less visible to platform operators than a CronJob."
        engine_support:
          engine: github-copilot-app-modernization
          coverage: partial
          scenarios: ["dotnet-upgrade"]
          skills: ["sdk-style-conversion"]
          gaps: ["console-to-worker restructuring", "containerization"]
          custom_skills_required: ["worker-service-conversion", "ocp4-container-packaging"]
        playbook_md: |
          Prefer the CronJob option unless the job runs very frequently or needs to
          hold warm state between executions.

  # ---------------------------------------------------------------- 7
  - id: windows-service
    name: "Windows Service"
    summary: "Long-running Windows Service built on ServiceBase."
    description: |
      Background service installed on Windows via ServiceBase and InstallUtil,
      running continuously under a service account.
    legacy_stack: ".NET Framework 4.x, System.ServiceProcess"
    category: service
    typical_indicators: "ServiceBase subclass, ProjectInstaller.cs, System.ServiceProcess reference, OnStart/OnStop overrides."
    known_risks: "Service account identity often carries Windows-integrated permissions to file shares and databases. The identity model must be redesigned for Linux, not merely ported."
    detection_rules:
      target_frameworks: ["net47", "net471", "net472", "net48"]
      required_namespaces: ["System.ServiceProcess"]
      project_properties:
        OutputType: "Exe"
      confidence_weight: 1.0
      notes: "ServiceBase inheritance is decisive."
    target_states:
      - id: worker-service-daemon-container
        name: ".NET Worker Service container"
        summary: "Convert ServiceBase to a BackgroundService hosted worker, containerized and deployed as an OCP4 Deployment."
        target_stack: ".NET 10 Worker Service + OCP4 Deployment"
        consumer_impact: low
        effort: medium
        linux_compatible: true
        container_ready: true
        is_lift_and_shift: true
        prerequisites: "Service account permissions mapped to an alternative identity mechanism on OCP4."
        known_limitations: "Windows-integrated authentication to SQL Server or file shares has no direct Linux equivalent. Expect a security-driven forcing factor here rather than a pure lift-and-shift."
        engine_support:
          engine: github-copilot-app-modernization
          coverage: partial
          scenarios: ["dotnet-upgrade"]
          skills: ["sdk-style-conversion"]
          gaps: ["ServiceBase to BackgroundService conversion", "containerization", "Windows authentication replacement"]
          custom_skills_required: ["windows-service-conversion", "ocp4-container-packaging", "linux-remediation"]
        playbook_md: |
          ## Steps
          1. Replace ServiceBase with BackgroundService under the generic host.
          2. Map OnStart/OnStop to ExecuteAsync and StopAsync with cancellation.
          3. Remove the installer project; OpenShift owns lifecycle now.
          4. Replace Windows-integrated authentication with the approved mechanism.
          5. Add liveness and readiness probes.

  # ---------------------------------------------------------------- 8
  - id: ssis-package
    name: "SSIS package"
    summary: "SQL Server Integration Services package performing ETL, defined in a .dtsx file."
    description: |
      Integration Services package with control flow and data flow tasks,
      connection managers, and frequently embedded script tasks containing C# or
      VB.NET. Executed by SQL Server Agent or the SSIS catalog.
    legacy_stack: "SQL Server Integration Services"
    category: data-etl
    typical_indicators: ".dtsx files, .dtproj project files, connection managers, Execute SQL and Data Flow tasks, Script Task components."
    known_risks: "No market tooling covers this conversion. Package XML is highly structured and parseable, which favours a deterministic-first accelerator, but transaction and checkpoint semantics, package variables and expression evaluation carry real behavioural risk. Row-level output equivalence testing is the only credible verification."
    detection_rules:
      file_globs: ["**/*.dtsx", "**/*.dtproj"]
      confidence_weight: 1.0
      notes: "File extension is decisive. Complexity varies enormously between packages, so the impact map should record per-package complexity, not just presence."
    target_states:
      - id: csharp-worker-container
        name: "C# worker with in-process pipeline"
        summary: "Convert the package to a C# worker that reimplements the data flow in code, containerized for OCP4."
        target_stack: ".NET 10 worker + OCP4 CronJob"
        consumer_impact: medium
        effort: high
        linux_compatible: true
        container_ready: true
        is_lift_and_shift: false
        prerequisites: "Source and target schemas documented. Representative input data available for equivalence testing."
        known_limitations: "Complex data flows with many transformations translate poorly to straight-line code. Package-level variables and expression evaluation need explicit reimplementation. Script tasks require porting on their own terms."
        engine_support:
          engine: none
          coverage: none
          scenarios: []
          skills: []
          gaps: ["No market tooling covers SSIS conversion at all"]
          custom_skills_required: ["ssis-inventory-parser", "ssis-dataflow-converter", "ssis-script-task-porter", "ocp4-container-packaging"]
        playbook_md: |
          ## Approach
          Deterministic first: parse the .dtsx XML to inventory components,
          connection managers and script tasks. Template-convert connection managers
          and standard data flow components. Use an LLM sub-agent only for script
          tasks and error-handling semantics.
          ## Verification
          Execute the source package and the generated worker against identical
          input, then diff output tables row by row. This is the strongest
          verification available anywhere in the programme — use it as the reference
          standard for what a verification oracle should look like.

      - id: csharp-sql-pushdown
        name: "C# orchestrator with SQL pushdown"
        summary: "Push set-based transformation logic into SQL and keep a thin C# orchestrator for control flow."
        target_stack: ".NET 10 worker + T-SQL + OCP4 CronJob"
        consumer_impact: medium
        effort: medium
        linux_compatible: true
        container_ready: true
        is_lift_and_shift: false
        prerequisites: "Source and target reside on the same database platform, and the transformation is expressible as set operations."
        known_limitations: "Only applies where transformations are set-based. Row-by-row logic, external service calls and file-based sources still need application code. Moves load onto the database server."
        engine_support:
          engine: none
          coverage: none
          scenarios: []
          skills: []
          gaps: ["No market tooling covers SSIS conversion at all"]
          custom_skills_required: ["ssis-inventory-parser", "ssis-to-sql-translator", "ocp4-container-packaging"]
        playbook_md: |
          Frequently the lower-effort option for straightforward load packages.
          Assess per package during inventory rather than choosing once for the whole
          estate — the two SSIS options are likely to be mixed across several hundred
          packages, and the segmentation rule should be recorded in the decision.
```

---

## Engagements

```yaml
engagements:
  - id: client-a-ocp4
    client_name: "Client A"
    description: "Primary engagement. 50+ repositories, 600+ applications, several hundred SSIS packages. Windows and IIS to Linux on OCP4."
    target_platform: "Linux / OpenShift Container Platform 4"
    default_posture: "lift-and-shift"
    status: active

  - id: reference-engagement-b
    client_name: "Reference Engagement B"
    description: "Illustrative second engagement demonstrating catalog reuse — the same patterns with different approved target states. Retain for demonstration purposes."
    target_platform: "Azure Kubernetes Service"
    default_posture: "lift-and-shift"
    status: active
```

## Decision records

```yaml
decision_records:

  # --- Client A ------------------------------------------------------
  - engagement_id: client-a-ocp4
    pattern_id: core2-rest-api
    candidates_considered: [net10-api-controllers-preserved, net10-api-minimal]
    selected_target_state_id: net10-api-controllers-preserved
    evaluation_notes: "Both options leave the external contract unchanged. Controllers-preserved produces a far smaller diff and a smaller review surface across an estimated 40+ applications matching this pattern."
    rationale: "Lowest consumer impact and lowest effort. No forcing factor to justify restructuring to minimal APIs."
    forcing_perspective: null
    forcing_rationale: null
    approver_name: "TBD"
    approver_role: "Lead Architect, Client A"
    decision_date: "2026-08-01"
    status: approved

  - engagement_id: client-a-ocp4
    pattern_id: fx47-class-library
    candidates_considered: [netstandard20-bridge, net10-class-library]
    selected_target_state_id: netstandard20-bridge
    evaluation_notes: "Dependency graph shows shared libraries consumed by applications scheduled across different waves. A direct net10.0 retarget would break Framework consumers still awaiting migration."
    rationale: "Bridge target keeps both legacy and migrated consumers working during phased waves. Move to net10.0 once all consumers are migrated."
    forcing_perspective: null
    forcing_rationale: null
    approver_name: "TBD"
    approver_role: "Lead Architect, Client A"
    decision_date: "2026-08-01"
    status: approved

  - engagement_id: client-a-ocp4
    pattern_id: fx-aspnet-mvc
    candidates_considered: [aspnetcore-incremental-adapters, aspnetcore-mvc-net10]
    selected_target_state_id: aspnetcore-incremental-adapters
    evaluation_notes: "Applications matching this pattern are large and test coverage is unknown pending assessment. Incremental migration allows route-by-route verification."
    rationale: "Zero consumer impact and progressive verification. Big-bang migration carries unacceptable risk at the observed application size."
    forcing_perspective: null
    forcing_rationale: null
    approver_name: "TBD"
    approver_role: "Lead Architect, Client A"
    decision_date: "2026-08-02"
    status: approved

  - engagement_id: client-a-ocp4
    pattern_id: wcf-iis-servicemodel
    candidates_considered: [corewcf-net10, grpc-net10, rest-net10]
    selected_target_state_id: corewcf-net10
    evaluation_notes: "External consumers confirmed present and unable to change their contracts within the programme timeline. WSDL must remain byte-identical."
    rationale: "Only option with zero consumer impact. gRPC and REST both require every caller to change, which is out of scope."
    forcing_perspective: null
    forcing_rationale: null
    approver_name: "TBD"
    approver_role: "Integration Architect, Client A"
    decision_date: "2026-08-02"
    status: approved

  - engagement_id: client-a-ocp4
    pattern_id: console-batch-job
    candidates_considered: [ocp4-cronjob-container, worker-service-container]
    selected_target_state_id: ocp4-cronjob-container
    evaluation_notes: "Most batch jobs run daily or less frequently. A persistently running pod is not justified for that duty cycle."
    rationale: "Keeps scheduling visible to platform operators and consumes no resources between runs."
    forcing_perspective: null
    forcing_rationale: null
    approver_name: "TBD"
    approver_role: "Platform Architect, Client A"
    decision_date: "2026-08-02"
    status: approved

  - engagement_id: client-a-ocp4
    pattern_id: windows-service
    candidates_considered: [worker-service-daemon-container]
    selected_target_state_id: worker-service-daemon-container
    evaluation_notes: "Only one viable target. Open question remains on replacing Windows-integrated authentication to SQL Server, which is a security-driven change rather than a pure port."
    rationale: "Pending confirmation of the replacement identity mechanism on OCP4."
    forcing_perspective: null
    forcing_rationale: null
    approver_name: null
    approver_role: null
    decision_date: null
    status: in_review

  - engagement_id: client-a-ocp4
    pattern_id: aspnet-webforms
    candidates_considered: [blazor-server-net10, aspnetcore-mvc-rewrite]
    selected_target_state_id: null
    evaluation_notes: "No lift-and-shift option exists — Web Forms has no modern .NET equivalent, so any target is a rewrite. Requires business sign-off on UI change and a screen inventory before a decision can be taken."
    rationale: null
    forcing_perspective: null
    forcing_rationale: null
    approver_name: null
    approver_role: null
    decision_date: null
    status: parked

  - engagement_id: client-a-ocp4
    pattern_id: ssis-package
    candidates_considered: [csharp-worker-container, csharp-sql-pushdown]
    selected_target_state_id: null
    evaluation_notes: "Target runtime and orchestration model on OCP4 not yet agreed. Likely to require a segmentation rule rather than a single choice, since simple load packages and complex data flows suit different targets."
    rationale: null
    forcing_perspective: null
    forcing_rationale: null
    approver_name: null
    approver_role: null
    decision_date: null
    status: parked

  # --- Reference Engagement B — demonstrates catalog reuse -----------
  - engagement_id: reference-engagement-b
    pattern_id: wcf-iis-servicemodel
    candidates_considered: [corewcf-net10, grpc-net10, rest-net10]
    selected_target_state_id: grpc-net10
    evaluation_notes: "All consumers are internal and in scope for coordinated change. Existing WCF bindings rely on WS-Security modes that CoreWCF does not support, so a like-for-like port is not available."
    rationale: "Unsupported bindings rule out CoreWCF. gRPC selected over REST for streaming requirements and internal tooling alignment."
    forcing_perspective: SECURITY
    forcing_rationale: "CoreWCF does not support the WS-Security binding modes currently in use, and the security team has mandated removal of the legacy authentication mechanism. A like-for-like port is therefore not available."
    approver_name: "TBD"
    approver_role: "Chief Architect, Reference Engagement B"
    decision_date: "2026-07-15"
    status: approved

  - engagement_id: reference-engagement-b
    pattern_id: core2-rest-api
    candidates_considered: [net10-api-controllers-preserved, net10-api-minimal]
    selected_target_state_id: net10-api-minimal
    evaluation_notes: "Small application count with strong test coverage. Client explicitly requested adoption of the modern minimal API idiom as part of a wider standards refresh."
    rationale: "Client preference for the modern idiom, accepted because the estate is small and well tested."
    forcing_perspective: EVOLUTION
    forcing_rationale: "Client standards mandate minimal APIs for all new and modernized services. This is a client-directed deviation from the lowest-diff option, not a technical constraint."
    approver_name: "TBD"
    approver_role: "Chief Architect, Reference Engagement B"
    decision_date: "2026-07-15"
    status: approved
```

## Notes for the implementer

- `approver_name: "TBD"` is intentional. These are illustrative records; real
  approvers are captured during the engagement.
- The Reference Engagement B **WCF** record is the one that exercises the
  validation rule in `02-DATA-MODEL.md`: it selects gRPC (`high` impact) over
  CoreWCF (`none`), so both `forcing_perspective` and `forcing_rationale` are
  mandatory — tagged `SECURITY`. Use this record to demonstrate governance
  working in the UI.
- The Reference Engagement B **core2** record selects between two options that are
  both `none` impact, so the rule does not trigger. Its `forcing_perspective`
  (`EVOLUTION`) and `forcing_rationale` are recorded voluntarily to explain a
  client-directed deviation on diff size rather than consumer impact. Keep it —
  it shows the fields are useful beyond the mandatory case — but do not use it
  as the validation demo.
- Both SSIS target states declare `engine: none` and `coverage: none`. This is the
  single strongest differentiation point in the catalog — verify it renders
  prominently in the UI.
