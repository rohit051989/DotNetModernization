"""The verifier (36-COPILOT-ENHANCED-CONVERSION Part E): one verdict per run, by fixed rules written into its
output, independent of the engine. Nothing an engine reported is evidence; only what this runs.

    python -m app.engine.verifier --engagement test-client-a --repository eshoponweb --base 4da8212
        --ref experiment/arm2-run1 --label arm2-run1 [--config <RUNS_DIR>/<engagement>/experiments/<name>/experiment.yaml]
        [--baseline-plan 90bc71e0] [--refresh-baseline]

Writes `runs/<engagement>/<repository>/verification/<label>/`: `verification.json`, `VERIFICATION.md` and
the evidence (build and test logs, TRX files, the diff, both re-discovery snapshots). The registered
checkout is never written; every build, test and scan runs in a scratch worktree, and a fingerprint of the
checkout taken before and after must match.

The checks, and what fails or caps the verdict:

| Check | Source | Fails (NOT PROVEN) | Caps (PARTLY PROVEN) |
|---|---|---|---|
| Something converted | Git | no change outside engine state and generated inputs | |
| Measured baseline | Plugin `baseline_diff` | | baseline counts not parsed from result files |
| Clean re-run | Platform | build fails; a test project fails to run; zero tests executed | |
| Baseline diff | Plugin `baseline_diff` | a regression, a new failure, a test that stopped running | |
| Tests kept | Plugin `uplift_checks` | | a removed test file, or more than 25% of test files changed |
| Deltas covered | Plugin `uplift_checks` | | a Behavioral-silent delta whose site no test names |
| Configuration files parse | Platform | a JSON or XML configuration file the conversion made unparseable | one that did not parse at the base commit either |
| Canary | Plugin method | a deliberate break that no test catches | no canary could be run |
| Equivalence | Plugin `compare` | | (no cases: not applicable) |
| Re-discovery | Platform | | a work item remains, is introduced or is not checked; a project not on the target framework |
| Impact comparison | Platform | reported, never judged | reported, never judged |

Engine state under `.github/upgrades/` and the generated inputs are excluded from the diff, the impact
comparison and re-discovery (app.engine.paths).

A work item with a place at the base commit in a configuration file that does not parse on the branch is **not
checked**, never resolved: discovery cannot see inside a file it cannot read, so the item's absence proves nothing
(Part N).
"""
import argparse
import datetime
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from app import models
from app.conversion import dotnet, gitops, planner
from app.conversion.runner import fingerprint
from app.engine import configfiles, paths, siblings
from app.engine.inputs.collect import SILENT_ITEMS
from app.engine.verifier import plugin, rediscovery
from app.experiment import instrument, lookups

VERIFIER_VERSION = "1.1.0"
RUNS = planner.RUNS          # the same runs folder as the conversion runner, whatever the working directory

RULES = [
    "NOT PROVEN when any check fails: nothing converted; the build fails; a test project fails to run or no test "
    "executes; a regression, a new failure or a baseline test that no longer runs; a JSON or XML configuration "
    "file that parsed at the base commit, or is new, and does not parse on the branch; a deliberate break (canary) "
    "that no test catches.",
    "Otherwise PARTLY PROVEN when any check has a gap: the baseline is not measured from result files; a test "
    "file was removed or more than 25% of test files changed; a Behavioral-silent delta's site is named by no "
    "test; a configuration file that did not parse at the base commit still does not; no canary could be run; an "
    "equivalence case is missing or differs without approval; a work item remains, was introduced or could not be "
    "checked; a project does not target the engagement's framework.",
    "A work item with a place in a configuration file that does not parse on the branch is not checked, never "
    "resolved: discovery cannot read inside that file.",
    "Otherwise PROVEN.",
    "The impact comparison and the diff size are reported, never judged.",
    "Engine state under .github/upgrades/ and the generated inputs are excluded from the diff, the impact "
    "comparison and re-discovery.",
    "PROVEN is evidence, not approval: a named person signs.",
]


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _check(cid: str, label: str, state: str, detail: str, **evidence) -> dict:
    return {"id": cid, "label": label, "state": state, "detail": detail, **({"evidence": evidence} if evidence else {})}


def verdict(checks: list[dict]) -> tuple[str, list[str]]:
    """The fixed rules: any fail is NOT PROVEN, else any gap is PARTLY PROVEN, else PROVEN. Returns the
    verdict and every reason (each failing, then each gapped check's detail)."""
    fails = [c for c in checks if c["state"] == "fail"]
    gaps = [c for c in checks if c["state"] == "gap"]
    reasons = [f"{c['label']}: {c['detail']}" for c in fails + gaps]
    if fails:
        return "NOT PROVEN", reasons
    if gaps:
        return "PARTLY PROVEN", reasons
    return "PROVEN", reasons


# ---------------------------------------------------------------- the diff

def diff(root: Path, base: str, tip: str) -> dict:
    status = gitops.git(root, "diff", "--name-status", "-M", base, tip)
    numstat = gitops.git(root, "diff", "--numstat", "-M", base, tip)
    files, excluded = [], []
    for line in status.splitlines():
        parts = line.split("\t")
        change, path = parts[0][0], parts[-1]
        entry = {"path": path, "change": change}
        if len(parts) == 3:
            entry["from"] = parts[1]
        (excluded if paths.is_under(path, paths.EXCLUDED_FROM_COMPARISON) else files).append(entry)
    added = deleted = 0
    for line in numstat.splitlines():
        a, d, path = line.split("\t", 2)
        path = path.split(" => ")[-1].rstrip("}") if "=>" in path else path
        if paths.is_under(path, paths.EXCLUDED_FROM_COMPARISON) or a == "-":
            continue
        added, deleted = added + int(a), deleted + int(d)
    commits = int(gitops.git(root, "rev-list", "--count", f"{base}..{tip}") or 0)
    return {"files": files, "excluded": excluded, "filesTouched": len(files), "linesAdded": added,
            "linesDeleted": deleted, "commits": commits}


# ---------------------------------------------------------------- impact comparison

def impact_comparison(predicted_model: dict, changed: list[dict]) -> dict:
    predicted, creates, review = {}, [], {}
    for item in predicted_model["items"]:
        for e in item["impact"]:
            if e["action"] == "create":
                creates.append({"path": e["proposed"], "item": item["id"]})
            elif e["action"] == "review":
                review.setdefault(e["file"], set()).add(item["id"])
            else:
                predicted.setdefault(e["file"], set()).add(item["id"])
    actual = {c["path"] for c in changed}
    unpredicted = []
    for c in sorted(changed, key=lambda c: c["path"]):
        path = c["path"]
        if path in predicted or path in review or c.get("from") in predicted:
            continue
        if c["change"] == "A" and any(cr["path"] and (path == cr["path"] or path.startswith(cr["path"].rstrip("/") + "/"))
                                      for cr in creates):
            continue
        unpredicted.append(path)
    untouched = sorted(p for p in predicted if p not in actual)
    created = [cr for cr in creates if cr["path"] and any(a == cr["path"] or a.startswith(cr["path"].rstrip("/") + "/") for a in actual)]
    return {
        "predictedFiles": len(predicted), "predictedCreates": len(creates), "predictedReview": len(review),
        "changedFiles": len(actual), "unpredicted": unpredicted, "predictedUntouched": untouched,
        "predictedUntouchedByItem": {p: sorted(predicted[p]) for p in untouched},
        "createsMade": len(created), "reviewTouched": sorted(p for p in review if p in actual),
    }


# ---------------------------------------------------------------- configuration files (Part N)

def config_check(base_unparseable: dict[str, str], tip_unparseable: dict[str, str], files_read: int) -> dict:
    """Fails for a file the conversion made unparseable: it parsed at the base commit, or is new. A file that did
    not parse at the base commit either is a gap: the conversion left it as it found it."""
    made = {p: w for p, w in tip_unparseable.items() if p not in base_unparseable}
    already = {p: w for p, w in tip_unparseable.items() if p in base_unparseable}
    named = lambda found: "; ".join(f"{p} ({w})" for p, w in sorted(found.items()))
    if made:
        detail = f"{len(made)} made unparseable by the conversion: {named(made)}"
        if already:
            detail += f"; {len(already)} did not parse at the base commit either: {named(already)}"
        return _check("config", "Configuration files parse", "fail", detail, unparseable=tip_unparseable)
    if already:
        return _check("config", "Configuration files parse", "gap",
                      f"{len(already)} did not parse at the base commit and still do not: {named(already)}",
                      unparseable=tip_unparseable)
    return _check("config", "Configuration files parse", "pass",
                  f"all {files_read} JSON and XML configuration file(s) parse")


def _place_file(place: str) -> str:
    """The file of a work item's place, "file:line" or "file"."""
    head, sep, tail = place.rpartition(":")
    return head if sep and tail.isdigit() else place


def split_not_checked(resolved: list[tuple[str, str]], before_items: dict, unparseable: set[str]) -> tuple[list, list]:
    """(resolved, not checked): a work item that is gone from the branch, but had a place in a file that does not
    parse there, is not checked — discovery could not read that file, so its absence proves nothing."""
    kept, not_checked = [], []
    for key in resolved:
        files = {_place_file(p) for p in before_items[key]["places"]}
        (not_checked if files & unparseable else kept).append(key)
    return kept, not_checked


# ---------------------------------------------------------------- the delta catalog the plugin reads

def delta_catalog(model: dict) -> str:
    """DELTA_CATALOG.md in the plugin's table form, from the baseline's discovery: the Behavioral-silent items
    with their sites, the framework deltas and the breaking package changes."""
    rows = ["| ID | Delta | Category | Sites |", "|---|---|---|---|"]
    n = 0
    for item in model["items"]:
        if item["id"] in SILENT_ITEMS:
            for occ in item["occurrences"]:
                for line in occ["lines"] or [None]:
                    n += 1
                    site = (occ["file"] or occ["project"]) + (f":{line['line']}" if line else "")
                    rows.append(f"| D-{n:03d} | {item['name']} | Behavioral-silent | {site} |")
        elif item["id"] == "package-upgrade-breaking":
            for occ in item["occurrences"]:
                n += 1
                rows.append(f"| D-{n:03d} | {(occ['value'] or item['name']).replace('|', '/')} | Dependency | {occ['file']} |")
    for d in model["deltas"]:
        for fix_file in d["sites"]:
            n += 1
            rows.append(f"| D-{n:03d} | {d['id']} | Project-system | {fix_file} |")
    return "# Delta catalog\n\nGenerated by the platform verifier from the baseline's discovery.\n\n" + "\n".join(rows) + "\n"


# ---------------------------------------------------------------- the baseline the plugin compares with

def _baseline_md(adir: Path, origin: str, executed: int, failed: int, skipped: int) -> Path:
    (adir / "BASELINE.md").write_text(
        "# Baseline\n\n"
        f"{origin}\n\n"
        "- **Recorded:** machine-readable per-test results in `baseline/`.\n\n"
        "| Totals | Count |\n|---|---|\n"
        f"| Executed | {executed} |\n| Passed | {executed - failed} |\n| Failed | {failed} |\n| Skipped | {skipped} |\n",
        encoding="utf-8")
    return adir / "BASELINE.md"


def measure_baseline(base_tree: Path, solution: str | None, projects: list[str], measured_dir: Path, base_sha: str) -> dict:
    """Builds the base commit and runs its unit tests, once per base commit: the measured baseline where no
    conversion plan recorded one. Cached in `measured_dir/measured.json` with its TRX files."""
    record = measured_dir / "measured.json"
    if record.exists():
        cached = json.loads(record.read_text(encoding="utf-8"))
        if cached.get("commit") == base_sha:
            return cached
    if measured_dir.exists():
        gitops._rmtree(measured_dir)
    if not solution or not projects:
        result = {"built": False, "buildExit": None, "projects": {}, "trx": [], "why": "no solution or no unit test project"}
    else:
        result = build_and_test(base_tree, solution, projects, measured_dir)
    result.update(commit=base_sha, at=_now(), solution=solution)
    measured_dir.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def measured_baseline(db, repository: models.Repository, base_sha: str, plan_prefix: str | None, workspace: Path,
                      measured: dict | None = None) -> tuple[Path, dict]:
    """BASELINE.md and its result files: a conversion plan's measured baseline at `base_sha` where one exists (the T1
    proof kept its TRX files), else the verifier's own measurement of the base commit. The typed table is written
    from the counts; baseline_diff then checks it against the result files, so a disagreement shows."""
    q = db.query(models.ConversionPlan).filter_by(repository_id=repository.id, legacy_commit=base_sha)
    plans = [p for p in q.order_by(models.ConversionPlan.created_at.desc()) if (p.baseline or {}).get("passed")
             and (plan_prefix is None or str(p.id).startswith(plan_prefix))]
    adir = workspace / "analysis" / repository.slug
    (adir / "baseline").mkdir(parents=True, exist_ok=True)
    if not plans and measured is not None and measured.get("trx"):
        for trx in measured["trx"]:
            shutil.copyfile(trx, adir / "baseline" / Path(trx).name)
        counts = measured["projects"].values()
        total = sum(p.get("total", 0) for p in counts)
        skipped = sum(p.get("skipped", 0) for p in counts)
        failed = sum(p.get("failed", 0) for p in counts)
        path = _baseline_md(adir, f"Measured at `{base_sha}` by the verifier on {measured['at'][:10]}: a clean build of "
                                  f"`{measured['solution']}` and its unit test projects.", total - skipped, failed, skipped)
        return path, {"plan": None, "measuredBy": "verifier", "at": measured["at"], "projects": sorted(measured["projects"]),
                      "total": total, "sources": [{"path": t} for t in measured["trx"]]}
    if not plans:
        why = (measured or {}).get("why") or ("the base commit did not build" if measured and not measured.get("built")
                                              else "no test ran at the base commit")
        (adir / "BASELINE.md").write_text(f"# Baseline\n\nNo measured baseline: {why}.\n", encoding="utf-8")
        return adir / "BASELINE.md", {"plan": None, "sources": [], "why": why, "total": 0, "projects": []}
    plan = plans[0]
    plan_dir = Path(plan.worktree_path).parent
    sources = []
    for e in plan.baseline["evidence"]:
        if e["kind"] != "test_results":
            continue
        src = plan_dir / e["path"]
        ok = src.exists() and hashlib.sha256(src.read_bytes()).hexdigest() == e["sha256"]
        if ok:
            shutil.copyfile(src, adir / "baseline" / src.name)
        sources.append({"path": str(src), "sha256": e["sha256"], "intact": ok, "project": e.get("project")})
    b = plan.baseline
    executed = b["total"] - sum(t["skipped"] for t in b["tests"].values())
    failed = sum(t["failed"] for t in b["tests"].values())
    skipped = sum(t["skipped"] for t in b["tests"].values())
    path = _baseline_md(adir, f"Measured at `{b['commit']}` by conversion plan `{str(plan.id)[:8]}` on {b['at'][:10]}.",
                        executed, failed, skipped)
    return path, {"plan": str(plan.id), "at": b["at"], "sources": sources,
                                  "projects": sorted(b["tests"]), "total": b["total"]}


# ---------------------------------------------------------------- build, tests and canary

def build_and_test(worktree: Path, solution: str, projects: list[str], out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    for leftover in ("bin", "obj"):                  # a fresh worktree has none; deleted again to be sure
        for d in worktree.rglob(leftover):
            if d.is_dir():
                gitops._rmtree(d)
    built = dotnet.build(worktree, solution)
    (out / "build.log").write_text(built.log, encoding="utf-8")
    result = {"built": built.ok, "buildExit": built.exit_code, "projects": {}, "trx": []}
    if not built.ok:
        return result
    for project in projects:
        name = Path(project).stem
        run, tests = dotnet.test(worktree, project, out / "tests" / f"{name}.trx")
        (out / "tests" / f"{name}.log").write_text(run.log, encoding="utf-8")
        result["projects"][project] = {"ran": tests is not None, "exit": run.exit_code,
                                       **(tests.as_dict() if tests else {"total": 0})}
        if tests is not None:
            result["trx"].append(str(out / "tests" / f"{name}.trx"))
    return result


def run_canary(worktree: Path, solution: str, projects: list[str], canary: dict, clean_failed: set[str], out: Path) -> dict:
    target = worktree / canary["file"]
    if not target.is_file():
        return {"ran": False, "why": f"{canary['file']} does not exist on this branch"}
    original = target.read_bytes()
    text = original.decode("utf-8-sig")
    if text.count(canary["find"]) != 1:
        return {"ran": False, "why": f"`{canary['find']}` does not occur exactly once in {canary['file']} on this branch"}
    try:
        target.write_bytes(original.replace(canary["find"].encode("utf-8"), canary["replace"].encode("utf-8"), 1))
        result = build_and_test(worktree, solution, projects, out)
    finally:
        target.write_bytes(original)
    if not result["built"]:
        return {"ran": False, "why": "the build with the canary in place failed", "change": canary["why"]}
    failed = set()
    for trx in result["trx"]:
        rep = plugin.baseline_diff.read_results([trx])
        failed |= {t for t, st in rep["tests"].items() if st in ("FAIL", "ERROR")}
    caught = sorted(failed - clean_failed)
    return {"ran": True, "change": canary["why"], "file": canary["file"], "testsFailed": len(caught), "tests": caught[:20],
            "trx": result["trx"]}


# ---------------------------------------------------------------- the run

def platform_state(db) -> dict:
    """What discovery's answer depends on besides the code: each discovery step's registered version and a digest of
    the committed catalog export. A cached baseline snapshot taken under another state is taken again."""
    from sqlalchemy import text

    steps = {name: version for name, version in db.execute(text(
        "SELECT step_name, version FROM wf_step_registrations WHERE deleted_at IS NULL ORDER BY step_name"))}
    digest = hashlib.sha256()
    for f in sorted((planner.CODE / "catalog" / "items").glob("*.yaml")):
        digest.update(f.name.encode() + b"\0" + f.read_bytes())
    return {"steps": steps, "catalog": digest.hexdigest()}


def _outside(checkout: Path, scratch: Path) -> None:
    """A scratch worktree is absolute and never inside the registered checkout, which is never written."""
    if not scratch.is_absolute():
        raise ValueError(f"scratch worktree {scratch} is not an absolute path")
    if scratch.resolve().is_relative_to(checkout.resolve()):
        raise ValueError(f"scratch worktree {scratch} would be inside the registered checkout {checkout}")


def verify(db, *, engagement_id: str, slug: str, base: str, ref: str, label: str, config: dict | None = None,
           baseline_plan: str | None = None, refresh_baseline: bool = False) -> dict:
    repository = (db.query(models.Repository).filter_by(engagement_id=engagement_id, slug=slug)
                  .filter(models.Repository.deleted_at.is_(None)).one())
    engagement = db.get(models.Engagement, engagement_id)
    root = Path(repository.local_path)
    base_sha = gitops.git(root, "rev-parse", base).strip()
    tip_sha = gitops.git(root, "rev-parse", ref).strip()
    home = RUNS / engagement_id / slug / "verification"
    out = home / label
    config = config or {}
    siblings_needed = config.get("sibling_links") or []
    if out.exists():
        siblings.remove(out, siblings_needed)
        gitops._rmtree(out)
    gitops.git(root, "worktree", "prune")       # a run that crashed leaves its worktree registered
    out.mkdir(parents=True)
    before = fingerprint(root)

    # The baseline's re-discovery, once per base commit and platform state: every run is compared with the same
    # snapshot, taken again when a step, the catalog or the input generator changes.
    base_dir = home / f"_baseline-{base_sha[:8]}"
    snapshot_file = base_dir / "rediscovery.json"
    # Short folder names: a worktree under runs/ must keep the repository's deepest path under 260 characters.
    base_tree = base_dir / "wt"
    _outside(root, base_tree)
    state = platform_state(db)
    # Part L: an experiment's package lookups come from its frozen snapshot, never a live feed.
    frozen_rows, frozen_sha = lookups.load(config) if lookups.recorded(config) else (None, None)
    answered = ({"source": "snapshot", "sha256": frozen_sha, "rows": len(frozen_rows)} if frozen_rows is not None
                else {"source": "live"})
    cached = json.loads(snapshot_file.read_text(encoding="utf-8")) if snapshot_file.exists() else None
    if (refresh_baseline or cached is None or cached.get("platform") != state or "isolation" not in cached
            or cached.get("packageLookups") != answered):
        gitops.add_scratch(root, base_tree, base_sha)
        siblings.link(base_tree, root, siblings_needed)
        snap = rediscovery.snapshot(engagement_id, base_tree, f"{slug} verifier baseline {base_sha[:8]}", base_dir / "scratch",
                                    frozen_rows)
        snap.update(commit=base_sha, at=_now(), platform=state, packageLookups=answered)
        snapshot_file.write_text(json.dumps(snap, indent=2, sort_keys=True, default=str), encoding="utf-8")
    base_snap = json.loads(snapshot_file.read_text(encoding="utf-8"))
    if not base_tree.exists():
        gitops.add_scratch(root, base_tree, base_sha)
    siblings.link(base_tree, root, siblings_needed)

    tip_tree = out / "wt"
    _outside(root, tip_tree)
    gitops.add_scratch(root, tip_tree, tip_sha)
    siblings.link(tip_tree, root, siblings_needed)
    for prefix in paths.EXCLUDED_FROM_COMPARISON:   # inputs and records, not conversion
        target = tip_tree / prefix.rstrip("/")
        if target.is_dir():
            gitops._rmtree(target)
        elif target.is_file():
            target.unlink()
    # Read before anything is built: whether every configuration file parses, on the branch and at the base commit.
    tip_unparseable = configfiles.unparseable(tip_tree)
    base_unparseable = configfiles.unparseable(base_tree, exclude=paths.EXCLUDED_FROM_COMPARISON)
    config_files_read = configfiles.counted(tip_tree)

    checks: list[dict] = []
    person: list[str] = []
    changes = diff(root, base_sha, tip_sha)
    (out / "diff.json").write_text(json.dumps(changes, indent=2), encoding="utf-8")
    if not changes["files"]:
        checks.append(_check("converted", "Something converted", "fail",
                             "the branch changes nothing outside engine state and generated inputs: nothing was converted"))
    else:
        checks.append(_check("converted", "Something converted", "pass",
                             f"{changes['filesTouched']} file(s) changed in {changes['commits']} commit(s), "
                             f"+{changes['linesAdded']} -{changes['linesDeleted']} lines"))

    # Measured baseline and the clean re-run.
    workspace = out / "workspace"
    measured = None
    if not baseline_plan:
        measured = measure_baseline(base_tree, base_snap["solution"], base_snap["unit_test_projects"], base_dir / "measured", base_sha)
    baseline_md, baseline_info = measured_baseline(db, repository, base_sha, baseline_plan, workspace, measured)
    projects = baseline_info.get("projects") or base_snap["unit_test_projects"]
    solution = base_snap["solution"]
    clean = build_and_test(tip_tree, solution, projects, out / "clean")
    total = sum(p.get("total", 0) for p in clean["projects"].values())
    not_run = [p for p, r in clean["projects"].items() if not r["ran"]]
    if not clean["built"]:
        checks.append(_check("clean", "Clean re-run", "fail", f"the build failed (exit {clean['buildExit']}); see clean/build.log"))
    elif not_run or total == 0:
        checks.append(_check("clean", "Clean re-run", "fail",
                             f"no test executed" if total == 0 else f"test project(s) did not run: {', '.join(not_run)}"))
    else:
        checks.append(_check("clean", "Clean re-run", "pass",
                             f"bin/obj absent, built {solution}, {total} test(s) executed in {len(projects)} project(s)"))

    base_report = None
    try:
        base_report = plugin.baseline_diff.run(str(baseline_md), clean["trx"]) if clean["trx"] else None
    except plugin.baseline_diff.InputError as err:
        checks.append(_check("baseline", "Measured baseline", "gap", f"the baseline could not be read: {err}"))
    if base_report is not None:
        assessment = base_report["baseline"]["assessment"]
        if assessment["kind"] == "measured" and not assessment["disagree"]:
            checks.append(_check("baseline", "Measured baseline", "pass",
                                 f"{assessment['measuredTests']} test result(s) parsed from the baseline's result files "
                                 + (f"(plan {baseline_info['plan'][:8]})" if baseline_info.get("plan")
                                    else "(measured by the verifier at the base commit)")))
        else:
            checks.append(_check("baseline", "Measured baseline", "gap",
                                 f"baseline is {assessment['kind']}" + (f", {assessment['disagree']} disagreement(s)" if assessment["disagree"] else "")))
        problems = []
        if base_report["regressionsCount"]:
            problems.append(f"{base_report['regressionsCount']} regression(s): " + ", ".join(r["id"] for r in base_report["regressions"][:5]))
        if base_report["newFailuresCount"]:
            problems.append(f"{base_report['newFailuresCount']} new failure(s): " + ", ".join(base_report["newFailures"][:5]))
        if base_report["missingCount"] or base_report["executedDrop"] or base_report["missingModulesCount"]:
            problems.append(f"{base_report['missingCount']} baseline test(s) no longer run" +
                            (f"; executed {base_report['executedDrop']['now']} of {base_report['executedDrop']['before']}" if base_report["executedDrop"] else ""))
        fresh = base_report["fresh"]["counts"]
        summary = f"{fresh['pass']} of {base_report['baseline']['counts']['executed'] if base_report['baseline']['counts'] else '?'} baseline tests pass now ({fresh['executed']} executed)"
        checks.append(_check("diff", "Baseline diff", "fail" if problems else "pass",
                             "; ".join(problems) if problems else summary))
        (out / "baseline-diff.json").write_text(json.dumps(base_report, indent=2, default=str), encoding="utf-8")
    elif clean["built"]:
        checks.append(_check("diff", "Baseline diff", "fail", "no result file from the clean re-run to compare"))

    # Tests kept and deltas covered: the plugin's own checks, in its own words.
    tc = plugin.uplift_checks.tests_changed(str(base_tree), str(tip_tree))
    kept = plugin.proof_pack.check_tests_kept(tc, person)
    checks.append(_check("kept", "Tests kept", kept["state"], kept["detail"]))
    catalog = delta_catalog(base_snap["model"])
    (workspace / "analysis" / slug / "DELTA_CATALOG.md").write_text(catalog, encoding="utf-8")
    if "| D-" not in catalog:
        # The plugin cannot tell an empty catalog from an unreadable one; the platform can: discovery found none.
        checks.append(_check("deltas", "Deltas covered", "pass",
                             "discovery found no Behavioral-silent delta, framework delta or breaking package change "
                             "in this repository at the base commit: nothing to cover"))
    else:
        dc = plugin.uplift_checks.delta_coverage(catalog, str(tip_tree))
        deltas = plugin.proof_pack.check_deltas(dc, person)
        checks.append(_check("deltas", "Deltas covered", deltas["state"], deltas["detail"]))

    checks.append(config_check(base_unparseable, tip_unparseable, config_files_read))

    # Canary: a deliberate break in the converted code must make a test fail.
    canaries = config.get("canaries") or []
    if not clean["built"] or not clean["trx"]:
        checks.append(_check("canary", "Canary", "gap", "not run: the clean re-run did not produce test results"))
    elif not canaries:
        checks.append(_check("canary", "Canary", "gap", "no canary is configured for this repository"))
    else:
        clean_failed = set()
        for trx in clean["trx"]:
            clean_failed |= {t for t, st in plugin.baseline_diff.read_results([trx])["tests"].items() if st in ("FAIL", "ERROR")}
        results = [run_canary(tip_tree, solution, projects, c, clean_failed, out / f"canary-{i + 1}") for i, c in enumerate(canaries)]
        (out / "canary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        silent = [r for r in results if r["ran"] and r["testsFailed"] == 0]
        shown = [r for r in results if r["ran"] and r["testsFailed"] > 0]
        if silent:
            checks.append(_check("canary", "Canary", "fail", f"a deliberate break that no test caught: {silent[0]['change']}"))
        elif shown:
            checks.append(_check("canary", "Canary", "pass", f"{shown[0]['change']}: {shown[0]['testsFailed']} test(s) failed "
                                 f"({', '.join(shown[0]['tests'][:3])})"))
        else:
            checks.append(_check("canary", "Canary", "gap", "not run: " + "; ".join(r["why"] for r in results)))

    # Equivalence: compare.py where cases exist.
    if config.get("equivalence_cases"):
        checks.append(_check("same", "Equivalence", "gap", "equivalence cases are configured but this verifier does not run them yet"))
    else:
        checks.append(_check("same", "Equivalence", "na", "no equivalence cases exist for this repository"))

    # Re-discovery on the branch, and the impact comparison against the baseline's prediction.
    tip_snap = rediscovery.snapshot(engagement_id, tip_tree, f"{slug} verifier {label}", out / "scratch", frozen_rows)
    (out / "rediscovery.json").write_text(json.dumps(tip_snap, indent=2, sort_keys=True, default=str), encoding="utf-8")
    before_items, after_items = rediscovery.work_items(base_snap["model"]), rediscovery.work_items(tip_snap["model"])
    resolved, not_checked = split_not_checked(sorted(k for k in before_items if k not in after_items), before_items,
                                              set(tip_unparseable))
    remaining = sorted(k for k in before_items if k in after_items)
    introduced = sorted(k for k in after_items if k not in before_items)
    target = engagement.target_framework
    off_target = sorted(p["path"] for p in tip_snap["model"]["projects"] if p["framework"] and p["framework"] != target)
    rd = {"before": len(before_items), "resolved": [list(k) for k in resolved], "remaining": [list(k) for k in remaining],
          "introduced": [list(k) for k in introduced], "notChecked": [list(k) for k in not_checked], "offTarget": off_target,
          "notCheckedPlaces": {f"{p} {i}": before_items[(p, i)]["places"][:10] for p, i in not_checked},
          "remainingPlaces": {f"{p} {i}": after_items[(p, i)]["places"][:10] for p, i in remaining},
          "introducedPlaces": {f"{p} {i}": after_items[(p, i)]["places"][:10] for p, i in introduced}}
    # Part M: a package at a version newer than the snapshot's answers is upgraded (its work item resolved), and is
    # listed apart, never as unresolved or unknown.
    rd["newerThanSnapshot"] = tip_snap.get("newerThanSnapshot") or []
    detail = (f"{len(resolved)} of {len(before_items)} work item(s) resolved, {len(remaining)} remaining, "
              f"{len(introduced)} introduced"
              + (f", {len(not_checked)} not checked (a place in a configuration file that does not parse)"
                 if not_checked else "")
              + f"; {len(off_target)} project(s) not on {target}"
              + (f"; {len(rd['newerThanSnapshot'])} package(s) newer than snapshot, counted as upgraded"
                 if rd["newerThanSnapshot"] else ""))
    checks.append(_check("rediscovery", "Re-discovery", "gap" if remaining or introduced or not_checked or off_target
                         else "pass", detail))
    impact = impact_comparison(base_snap["model"], changes["files"])
    checks.append(_check("impact", "Impact comparison", "info",
                         f"{len(impact['unpredicted'])} changed file(s) not predicted; "
                         f"{len(impact['predictedUntouched'])} of {impact['predictedFiles']} predicted file(s) untouched; "
                         f"{impact['createsMade']} of {impact['predictedCreates']} predicted new file(s) made"))

    after = fingerprint(root)
    checkout_untouched = before == after
    if not checkout_untouched:
        checks.append(_check("checkout", "Registered checkout untouched", "fail", "the registered checkout changed during verification"))
    gitops.remove(root, tip_tree)
    siblings.remove(out, siblings_needed)

    result_verdict, reasons = verdict(checks)
    report = {
        "verifier": {"version": VERIFIER_VERSION, "plugin": "third_party/code-modernization @ f359d43"},
        # The platform commit the verification ran at, and whether its tree was clean (app.experiment.instrument).
        "platform": instrument.platform_state(),
        # Where package lookups were answered from: the experiment's frozen snapshot (by sha256), or live feeds.
        "packageLookups": answered,
        "label": label, "repository": slug, "engagement": engagement_id, "base": base_sha, "ref": ref, "tip": tip_sha,
        "verifiedAt": _now(), "verdict": result_verdict, "reasons": reasons, "rules": RULES, "checks": checks,
        "forAPerson": person, "baseline": baseline_info, "baselineSnapshot": {"commit": base_snap["commit"], "at": base_snap["at"]},
        "cleanRun": clean, "diff": {k: v for k, v in changes.items() if k not in ("files", "excluded")},
        "excludedPaths": [e["path"] for e in changes["excluded"]], "rediscovery": rd, "impact": impact,
        "checkoutUntouched": checkout_untouched,
    }
    (out / "verification.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (out / "VERIFICATION.md").write_text(markdown(report), encoding="utf-8")
    return report


def _platform_line(state: dict | None) -> str:
    if not state:
        return "Platform commit: not recorded."
    return f"Platform commit `{state['commit'][:12]}`" + (" with uncommitted changes." if state.get("dirty") else ".")


def _lookups_line(answered: dict | None) -> str:
    if not answered or answered.get("source") != "snapshot":
        return "Package lookups: answered from live feeds."
    return f"Package lookups: answered from the frozen snapshot `{answered['sha256'][:12]}` ({answered['rows']} answers), offline."


def markdown(r: dict) -> str:
    out = [f"# Verification: {r['label']}", "",
           f"**Verdict: {r['verdict']}**", "",
           f"Repository `{r['repository']}`, base `{r['base'][:8]}`, `{r['ref']}` at `{r['tip'][:8]}`; verified {r['verifiedAt']} "
           f"by verifier {r['verifier']['version']} ({r['verifier']['plugin']}).", "",
           _platform_line(r.get("platform")), _lookups_line(r.get("packageLookups")), "", "## Reasons", ""]
    out += [f"- {x}" for x in r["reasons"]] or ["- None: every check passed."]
    out += ["", "## Checks", "", "| Check | State | Detail |", "|---|---|---|"]
    out += [f"| {c['label']} | {c['state']} | {c['detail'].replace('|', '/')} |" for c in r["checks"]]
    rd = r["rediscovery"]
    out += ["", "## Work items", "",
            f"Before: {rd['before']}. Resolved: {len(rd['resolved'])}. Remaining: {len(rd['remaining'])}. Introduced: {len(rd['introduced'])}."
            + (f" Not checked: {len(rd['notChecked'])}." if rd.get("notChecked") else ""), ""]
    for name, rows in (("Resolved", rd["resolved"]), ("Remaining", rd["remaining"]), ("Introduced", rd["introduced"]),
                       ("Not checked", rd.get("notChecked") or [])):
        if rows:
            out += [f"**{name}:** " + ", ".join(f"`{i}` ({p})" for p, i in rows), ""]
    if rd.get("notChecked"):
        out += ["Not checked: gone from the branch, but with a place in a configuration file that does not parse there. "
                "Discovery cannot read inside that file, so the item is never counted as resolved.", ""]
    if rd["offTarget"]:
        out += ["**Not on the target framework:** " + ", ".join(f"`{p}`" for p in rd["offTarget"]), ""]
    if rd.get("newerThanSnapshot"):
        out += ["**Newer than snapshot** (upgraded; the frozen lookups predate the release): "
                + ", ".join(f"`{n['package']} {n['version']}` ({n['project']}; snapshot recommended {n['snapshotRecommended']})"
                            for n in rd["newerThanSnapshot"]), ""]
    im = r["impact"]
    out += ["## Impact comparison", "",
            f"Predicted files {im['predictedFiles']}, predicted new files {im['predictedCreates']}, changed files {im['changedFiles']}.", ""]
    if im["unpredicted"]:
        out += ["Changed but not predicted:", ""] + [f"- `{p}`" for p in im["unpredicted"][:100]] + [""]
    if im["predictedUntouched"]:
        out += ["Predicted but untouched:", ""] + [f"- `{p}` ({', '.join(im['predictedUntouchedByItem'][p])})" for p in im["predictedUntouched"][:100]] + [""]
    d = r["diff"]
    out += ["## Diff", "", f"{d['filesTouched']} file(s), +{d['linesAdded']} -{d['linesDeleted']}, {d['commits']} commit(s). "
            f"Excluded as engine state or generated inputs: {len(r['excludedPaths'])} file(s).", ""]
    if r["forAPerson"]:
        out += ["## For a person", ""] + [f"- {x}" for x in r["forAPerson"]] + [""]
    out += ["## Rules", ""] + [f"{i + 1}. {x}" for i, x in enumerate(r["rules"])] + [""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(prog="python -m app.engine.verifier", description=__doc__.split("\n\n")[0])
    parser.add_argument("--engagement", required=True)
    parser.add_argument("--repository", required=True, help="repository slug")
    parser.add_argument("--base", required=True, help="the baseline commit")
    parser.add_argument("--ref", required=True, help="the branch or commit to verify")
    parser.add_argument("--label", required=True, help="names the output folder, e.g. arm2-run1")
    parser.add_argument("--config", type=Path, help="experiment configuration with canaries and equivalence cases")
    parser.add_argument("--baseline-plan", help="the conversion plan whose measured baseline to use (id prefix)")
    parser.add_argument("--refresh-baseline", action="store_true", help="re-run discovery on the base commit")
    args = parser.parse_args(argv)
    config = yaml.safe_load(args.config.read_text(encoding="utf-8")) if args.config else None
    db = SessionLocal()
    try:
        report = verify(db, engagement_id=args.engagement, slug=args.repository, base=args.base, ref=args.ref,
                        label=args.label, config=config, baseline_plan=args.baseline_plan,
                        refresh_baseline=args.refresh_baseline)
    finally:
        db.close()
    print(f"{report['label']}: {report['verdict']}")
    for reason in report["reasons"]:
        print(f"  - {reason}")
    print(f"  {RUNS / args.engagement / args.repository / 'verification' / args.label / 'VERIFICATION.md'}")
    return 0
