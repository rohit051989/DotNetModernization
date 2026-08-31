# Step 3 — Application Fingerprinting

Lifecycle step 3. See `docs/21-STEP-003-FINGERPRINTING.md` and
`docs/25-STANDARDS-AND-VIEWPOINTS.md` Part A3.

Standalone by design: invoked by the platform's `process` adapter, but this
directory has no dependency on `backend/app` — it is a separate deliverable
that happens to live in the same repository. Written in C# because it does
real Roslyn syntax analysis (`Microsoft.CodeAnalysis`) and MSBuild-adjacent
project parsing, unlike step 2's lightweight Python XML parsing.

## Build

```powershell
dotnet publish src/Fingerprinting.Cli -c Release -o publish
```

`publish/Fingerprinting.Cli.exe` is what `wf_step_registrations.adapter_config`
points at. Rebuild and republish after any change under `src/` — the engine
runs the published exe, not `dotnet run`.

## Run standalone

Reads a repository directly and step 2's `solution-project-inventory.json`,
skipping the database and the `StepContext`/`StepResult` envelope entirely —
useful for iterating on an extractor without the engine:

```powershell
.\publish\Fingerprinting.Cli.exe --repo <repository-root> --inventory <solution-project-inventory.json> --out <output-dir>
```

## Run via the process adapter

The normal path: a `StepContext` JSON object (see `docs/11-STEP-CONTRACT.md`)
on stdin, a `StepResult` JSON object on stdout, nothing else on stdout.
Requires `inputs.solution-project-inventory` and a `database_url` — unlike
step 2, step 3 has no other source for the repository's `local_path` or for
project ids, so `database_url` is not optional here.

## Outputs

Two declared artifacts per run, both written to `output_dir`:

- `application-fingerprint.json` (`application-fingerprint@1.0.0`) — the
  native artifact. Every downstream step (classification, and anything built
  on top of it) reads this one; it stays primary.
- `application-fingerprint.sarif` (`fingerprint-sarif@2.1.0`) — the same
  evidence re-projected into [SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html),
  the OASIS-standard static analysis interchange format. Additive: nothing
  reads it today, it exists so the evidence opens in any SARIF-aware viewer
  or tool without bespoke tooling. Signal registry entries become
  `tool.driver.rules`, one `run` per project, each signal a `result` at
  `level: "none"` (an observation, not a defect), evidence spans become
  region locations. Validated against the published SARIF 2.1.0 JSON schema
  before write — a validation failure fails the step, same as the native
  artifact's own schema gate.

Both are byte-identical across reruns of unchanged input — no timestamps, no
absolute paths, alphabetical keys throughout (`Fingerprinting.Domain.DeterministicJson`).

**Contributing an extractor?** If it wraps a Roslyn analyzer (or any other
tool that already speaks SARIF), consider having it hand back a SARIF
fragment directly instead of translating into the native `Signal` shape —
Roslyn analyzers emit SARIF natively, and that's the actual reason this step
adopted the format rather than inventing another proprietary one. Ask before
doing this for a first extractor; the fragment still needs to fold into the
per-project native artifact so pattern classification (step 4) keeps working
unchanged.

## Tests

```powershell
dotnet test tests/Fingerprinting.Tests
```
