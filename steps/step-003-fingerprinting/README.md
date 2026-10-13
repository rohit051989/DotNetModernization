# `application-fingerprinting` — Application Fingerprinting

Lifecycle step `application-fingerprinting`. See `docs/21-APPLICATION-FINGERPRINTING.md` and
`docs/25-STANDARDS-AND-VIEWPOINTS.md` Part A3.

Standalone by design: invoked by the platform's `process` adapter, but this
directory has no dependency on `backend/app` — it is a separate deliverable
that happens to live in the same repository. Written in C# because it does
real Roslyn syntax analysis (`Microsoft.CodeAnalysis`) and MSBuild-adjacent
project parsing, unlike `solution-discovery`'s lightweight Python XML parsing.

## Solution layout

This solution also builds **`entry-point-inventory`**
(`docs/29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md` Part B) — see the section at the end.
The steps share libraries, never a contract: each has its own exe,
registration, artifact and tables.

| Project | What it holds | Used by |
|---|---|---|
| `Fingerprinting.Domain` | Artifact records, `DeterministicJson` (sorted keys, LF line endings) | both |
| `Fingerprinting.Analysis` | `FileSystemWalk`, `SourceFileScanner` (generated-code exclusion, file cap, Roslyn syntax parse), `RoslynNameHelpers` | both |
| `Fingerprinting.StepHost` | `StepBootstrap` (MSBuildLocator first, stdout guard, invariant culture), `StepEnvelopeRunner`, the StepContext/StepResult envelope, artifact URIs and checksums, the schema gate, `solution-discovery`'s inventory model, `PlatformDatabase` | both |
| `Fingerprinting.Extractors` / `Fingerprinting.Cli` | `application-fingerprinting`'s extractors and exe | `application-fingerprinting` |
| `Fingerprinting.EntryPoints` / `Fingerprinting.EntryPoints.Cli` | `entry-point-inventory`'s detectors, route composition and exe | `entry-point-inventory` |
| `Fingerprinting.Impact` / `Fingerprinting.Impact.Cli` | `impact-analysis`'s code index, impact-rule engine, rollup and exe (`docs/33-IMPACT-ANALYSIS.md`) | `impact-analysis` |

## Build

```powershell
dotnet publish src/Fingerprinting.Cli -c Release -o publish
dotnet publish src/Fingerprinting.EntryPoints.Cli -c Release -o publish/entry-point-inventory
dotnet publish src/Fingerprinting.Impact.Cli -c Release -o publish/impact-analysis
dotnet publish src/Fingerprinting.Dependencies.Cli -c Release -o publish/dependency-assessment
```

`publish/Fingerprinting.Cli.exe` is what `wf_step_registrations.adapter_config`
points at. Rebuild and republish after any change under `src/` — the engine
runs the published exe, not `dotnet run`.

## Run standalone

Reads a repository directly and `solution-discovery`'s `solution-project-inventory.json`,
skipping the database and the `StepContext`/`StepResult` envelope entirely —
useful for iterating on an extractor without the engine:

```powershell
.\publish\Fingerprinting.Cli.exe --repo <repository-root> --inventory <solution-project-inventory.json> --out <output-dir>
```

## Run via the process adapter

The normal path: a `StepContext` JSON object (see `docs/11-STEP-CONTRACT.md`)
on stdin, a `StepResult` JSON object on stdout, nothing else on stdout.
Requires `inputs.solution-project-inventory` and a `database_url` — unlike
`solution-discovery`, `application-fingerprinting` has no other source for the repository's `local_path` or for
project ids, so `database_url` is not optional here.

## Outputs

Two declared artifacts per run, both written to `output_dir`:

- `application-fingerprint.json` (`application-fingerprint@1.1.0`) — the
  native artifact. Every downstream step (classification, and anything built
  on top of it) reads this one; it stays primary. Every signal carries
  `evidenceKind` (`FILE`, `FOLDER`, or `NONE`, from the signal registry) —
  what `sourcePath` names. Never treat a `FOLDER` signal's `sourcePath` (e.g.
  `SERVICES_FOLDER`'s `src/ApplicationCore/Services`) as an openable file.
- `application-fingerprint.sarif` (`fingerprint-sarif@2.1.0`) — the same
  evidence re-projected into [SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html),
  the OASIS-standard static analysis interchange format. Additive: nothing
  reads it today, it exists so the evidence opens in any SARIF-aware viewer
  or tool without bespoke tooling. Signal registry entries become
  `tool.driver.rules`, one `run` per project, each signal a `result` at
  `level: "none"` (an observation, not a defect), evidence spans become
  region locations — only for `evidenceKind: FILE` signals; a `FOLDER`
  signal gets no `locations` at all (its path goes in `properties.folderPath`
  instead), since a SARIF `physicalLocation` means somewhere within a file a
  viewer can navigate to, and a directory isn't one. Every location carries
  `uriBaseId: "REPOROOT"`. Validated against the published SARIF 2.1.0 JSON
  schema before write — a validation failure fails the step, same as the
  native artifact's own schema gate.
- `application-fingerprint.local.sarif` — **not** a declared output, not
  checksummed, gitignored. Byte-identical to the registered SARIF file except
  `run.originalUriBaseIds.REPOROOT.uri` is filled in with this machine's real
  repository path (the registered file leaves it absent, so no absolute path
  enters the checksum). Rebuilt every run purely so a SARIF viewer on this
  machine — e.g. VS Code's SARIF Viewer extension — can resolve source
  locations; open the repository as the workspace root and open this file.

Both declared artifacts are byte-identical across reruns of unchanged input —
no timestamps, no absolute paths, alphabetical keys throughout
(`Fingerprinting.Domain.DeterministicJson`). The local sibling is not held to
that guarantee — it deliberately embeds this machine's path.

**Contributing an extractor?** If it wraps a Roslyn analyzer (or any other
tool that already speaks SARIF), consider having it hand back a SARIF
fragment directly instead of translating into the native `Signal` shape —
Roslyn analyzers emit SARIF natively, and that's the actual reason this step
adopted the format rather than inventing another proprietary one. Ask before
doing this for a first extractor; the fragment still needs to fold into the
per-project native artifact so `pattern-classification` keeps working
unchanged.

## Tests

```powershell
dotnet test tests/Fingerprinting.Tests
```

## `entry-point-inventory`

What can call each application: HTTP controller actions and minimal APIs
(with composed routes), WCF operations, ASMX web methods, gRPC and SignalR
methods, message consumers, hosted services, scheduled jobs, console mains
and WebForms pages. Syntax only, like `application-fingerprinting`; everything below 1.0
confidence says why. Entirely deterministic — no model is called.

Capability manifest: `schemas/entry-point-capabilities-1.0.0.json` — every kind
detected and every pattern not covered, stamped into each artifact. Add a kind
there and in `EntryPointKinds` together; a test fails otherwise.

`authDeclared` reports authentication declared in source and config only; gateway,
proxy and header-based authentication are invisible to it, so `none_declared` is
a review prompt, not a finding.

Registration: `registration/entry-point-inventory.json`, posted to
`POST /api/workflow/steps`. Artifact `entry-point-inventory@2.0.0`, schema
`schemas/entry-point-inventory-2.0.0.schema.json`, validated before every
write. Tables `entry_points` and `entry_point_scans`, replaced per repository.

**Inputs.** Both `consumes` entries are required, and
`phase0-repository-discovery` (v7) wires them. They are the only input path:
a step invoked without them fails rather than looking elsewhere.

Run standalone (no database; project ids come from the fingerprint, which
makes the output byte-identical to an engine run):

```powershell
.\publish\entry-point-inventory\EntryPointInventory.Cli.exe --repo <repository-root> --inventory <solution-project-inventory.json> --fingerprint <application-fingerprint.json> --out <output-dir>
```

`--fingerprint` is optional; without it projects are skipped by `solution-discovery`'s
out-of-scope rule instead of `application-fingerprinting`'s verdict.

