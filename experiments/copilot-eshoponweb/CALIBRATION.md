# Verifier calibration — eShopOnWeb, 2026-10-12

The verifier (`python -m app.engine.verifier`, version 1.0.0, vendored plugin at `f359d43`) run before any Copilot
arm, on two known branches. Full output: `backend\runs\test-client-a\eshoponweb\verification\<label>\VERIFICATION.md`
(local, not committed). Both runs used the same baseline re-discovery snapshot of `4da8212` and the T1 measured
baseline (plan `90bc71e0`, 44 of 44, TRX kept and its sha256 checked). The registered checkout's fingerprint was
unchanged across both.

## Baseline `4da8212` (label `calibration-baseline`) — must read as nothing converted

**NOT PROVEN.**

- Something converted: **fail** — the branch changes nothing outside engine state and generated inputs: nothing was converted
- Deltas covered: gap — 4 of 6 Behavioral-silent delta(s) have no test that names their site: D-002 (no test names
  CustomAuthStateProvider); D-003 (no test names Logout); D-004 (no test names UserController); D-006 (no test names Index)
- Re-discovery: gap — 0 of 33 work items resolved, 33 remaining, 0 introduced; 10 projects not on net10.0

Passing: clean re-run (built, 44 tests executed), measured baseline (44 results parsed from the result files),
baseline diff (44 of 44), tests kept (0 of 50 test files changed), canary (`BasketRemoveEmptyItems` failed when
`Basket.RemoveEmptyItems` was broken). Equivalence not applicable: no cases. Impact: 0 changed, 31 of 31 predicted
files untouched.

## Arm 3, the T1 round-two branch `conversion/90bc71e0` (label `arm3`)

**PARTLY PROVEN.** Arm 3 covers the version upgrade only, not OpenShift readiness.

- Deltas covered: gap — the same 4 of 6 Behavioral-silent sites named by no test (unchanged from the baseline:
  arm 3 adds no tests)
- Re-discovery: gap — 10 of 33 work items resolved, 23 remaining, 0 introduced; every project on net10.0

Passing: something converted (3 files, +26 -22, 19 commits), clean re-run (44 executed), measured baseline, baseline
diff (44 of 44 on net10.0), tests kept (0 of 50 changed), canary (caught by `BasketRemoveEmptyItems`). Equivalence
not applicable.

Resolved: `package-upgrade-safe` in 7 projects, `package-vulnerable` in 2, `package-replacement-required` in
Infrastructure. Remaining include the three assisted groups T1 left for T1b (MSTest, Swashbuckle,
Ardalis.Specification as `package-upgrade-breaking`), and every OpenShift item (expected: out of arm 3's scope).

## What calibration found

1. **The verdict rules separate the two cases.** Nothing converted fails outright; a real but partial conversion
   with green tests caps at PARTLY on its remaining work items.
2. **Impact analysis misses central package management.** On arm 3, `Directory.Packages.props` and `global.json`
   changed but were not predicted, and every package item's predicted `.csproj` was untouched: eShopOnWeb
   declares versions centrally, and the package impact rules point at the project file. The comparison reports
   it; nothing is judged. A fix belongs in the catalog's impact rules (`package-upgrade-*`, `traverse:
   project_file`), not in the verifier.
3. **Four DateTime.Now sites have no test that names them**, on every branch. The deltas check will cap every arm
   at PARTLY unless the arm adds characterization tests — which arm 2's `writing-characterization-tests` skill
   asks for and arm 1 is not told to do. That is a real difference between the arms, not noise.
