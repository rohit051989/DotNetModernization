# Suite optimization — handoff

Status: analysis only, nothing implemented. Written 2026-11-06 from a discussion about why
`scripts\run-suites.ps1` (no parameters, every suite) takes about 2 hours.

**Important caveat:** the cause of the 2 hours is NOT measured. Per-suite logs are deleted when a run passes, and
nothing was run during the discussion. Everything under "Suspected causes" is inferred from reading the code.
Measure first (Step 1) before changing anything.

## 1. What run-suites runs

`scripts\run-suites.ps1` asks `scripts\select_suites.py` which suites apply, then runs them in lanes.

- Default (no parameter) = every suite. `-Since <commit>` or `-Paths` = only the suites the change can affect.
  `-List` prints the selection and runs nothing.
- Suites: `backend` (unittest discover), `seed and registrations`, `reproduce`, `frontend tests` (vitest),
  `frontend type check` (tsc -b), `C# <project>` (4 test projects under `steps\step-003-fingerprinting`),
  `step <name>` Python tests (step-002 has about 44), `third_party code-modernization`.
- Parallelism: independent suites run together, up to `MaxParallel` (default = a quarter of logical processors,
  at least 1; this machine has 8, so 2). Suites in one lane run one after another: all C# projects share a lane
  (shared bin/obj), `seed` and `reproduce` share a lane.
- Wall time is therefore about the slowest lane, not the sum of suites.
- Backend suite = 691 tests, ~12.5k lines, 45+ modules, one `unittest discover` process on one core.
- `backend\tests\__init__.py` creates ONE scratch Postgres schema per run (alembic upgrade head, then
  `python -m app.seed`, then creates a test admin) and every test module shares it. Dropped at exit.
- 19 backend test modules spawn subprocesses / dotnet (engine, conversion, wcf probe, item detection, ingest,
  client install, ...).
- Count of C# tests: about 278.

## 2. Suspected causes (ranked, unmeasured)

1. Backend is a single serial process on 1 of 8 cores; it dominates wall time.
2. Heavy end-to-end modules inside it: `test_platform_scale`, `test_engine_*`, `test_conversion*`,
   `test_wcf_probe`, `test_repository_ingest`, `test_item_detection`.
3. The single shared test schema prevents running backend tests in parallel as-is.
4. C# projects run serially, each doing its own restore/build.
5. Default concurrency (2) is low for an 8-core machine.
6. Full run is the default; `-Since` is not the habitual workflow.
7. Windows Defender real-time scanning of `.venv`, `node_modules`, `bin\obj`, temp repos, `backend\runs`.

## 3. The 170-project repository question

Question raised: is generating a 170-project repository required, or can we generate 4-5 flavours instead?

What the docs say (`docs/37-DEPENDENCY-HIERARCHY.md` Part H, "Proof at scale"; `docs/01-ENVIRONMENT-SETUP.md`
"Running the tests"):
- `backend\tests\fixtures\synthetic_repository.py` writes 170 projects: 20 applications, 115 libraries in four
  layers with nested references and shared core libraries, 30 test projects, 5 non-code projects; legacy
  packages.config and HintPath/GAC/Framework references; central package management; one missing project
  reference; a local client feed of internal and external packages. It also writes `expected-graph.json`.
- Purpose: prove `dependency-hierarchy` and the Dependency graph tab at client-estate size. Measured 2026-10-22:
  171 nodes, 733 edges, depth 17, one shared library with 77 parents, step took 6 s, UI expand ~250 ms.
- Since release 7 it is generated per run into a scratch folder (not kept registered), so tests never touch a
  running platform's data. That was about isolation, not speed.
- NO document records a decision on why the number is 170. The size is a stand-in for a real estate.

Cost: `test_platform_scale` does ONE generate+register+scan in `setUpClass` shared by 4 tests; its docstring says
"about two minutes" (the setup doc says "a few minutes"). So it is a small share of 2 hours.

Assessment (inference, not from docs):
- Size matters only for the performance claims (time limit, depth 17, 77-parent node).
- It does not matter for correctness: "every step completes", "graph matches project files" and "every producing
  step writes the version it reports and registers" need variety, not size.
- Candidate flavours (the generator already has the features; add a size/flavour parameter, ~10-20 projects each):
  (a) SDK-style web + libraries, PackageReference; (b) legacy packages.config / HintPath / GAC;
  (c) central package management; (d) layered shared libraries with a missing ProjectReference;
  (e) multiple solutions sharing projects.
- Keep ONE 170-project run in a slow tier (pre-merge or nightly), not in the default loop.
- Before changing: the generator's `solutions` option is also used by the conversion-scope tests; `"171 project(s)"`
  is asserted in `test_platform_scale.py`; Part H of the doc quotes the 170 numbers. Check all three.

## 4. Recommended steps (in order)

1. **Measure.** Add a per-test/per-module timing report for the backend (print the 20 slowest), and an option to
   keep run-suites logs on success. Time every suite from `.\scripts\run-suites.ps1 -List` onward. Decide from data.
2. **Shard the backend suite** into 3-4 processes, each with its own schema (`mp_test_<ts>_<shard>` in
   `backend\tests\__init__.py`), split by measured duration, each shard a lane in run-suites. Expected backend wall
   time roughly divided by the shard count. Reproduce check and "never touch the platform's schema" must still hold.
3. **Raise default `MaxParallel`** to about cores/2. For C#: `dotnet build` once, then `dotnet test --no-build`
   (or separate `--artifacts-path` per project to allow parallel lanes).
4. **Tier the slow tests** (scale, wcf probe, conversion/engine end-to-end). Fast tier for the dev loop, full run
   before merge to master (CLAUDE.md rule 17 still met by the full run).
5. **Use `-Since origin/master` as the normal workflow**; document it.
6. **Cut Windows I/O cost:** ask IT to exclude `.venv`, `node_modules`, `backend\runs`, temp, `bin\obj` from
   real-time scanning.
7. **Cache fixtures:** migrate+seed template schema or dump/restore instead of alembic+seed per run/shard;
   flavour repos in place of the 170 one in the default tier.

## 5. Files that would change

- `scripts\run-suites.ps1`, `scripts\select_suites.py` (and `backend\tests\test_suite_selection.py` in step)
- `backend\tests\__init__.py` (per-shard schema)
- `backend\tests\fixtures\synthetic_repository.py`, `backend\tests\test_platform_scale.py` (flavours, slow tier)
- A short note in `docs\01-ENVIRONMENT-SETUP.md` "Running the tests".
- No new dependencies (CLAUDE.md "Tech stack" and rule 19).

## 6. How to verify when implemented

- `.\scripts\run-suites.ps1 -List`, then a timed full run; compare per-suite minutes before and after.
- The same 691 backend tests run sharded and unsharded with the same results.
- `python -m app.seed.reproduce` still reports 0 differences; no test touches the platform's own schema.
- Per rule 17 the full suite must still pass on master.

## 7. Open questions for the owner

- Is the 2-hour figure for a full run on a developer machine, a client VDI, or CI? (Defender and core count differ.)
- Are you willing to add a slow tier / nightly full run, given rule 17?
- Do client environments run run-suites too? If so, sharding must work on their database permissions (CREATE on
  the database is already required).
