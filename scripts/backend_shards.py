"""Runs the backend test suite split across several processes ("shards"): scripts\\run-suites.ps1 runs the backend lane
this way.

    python scripts\\backend_shards.py [--shards N] [--tier quick|full] [--modules tests.test_a tests.test_b ...]
                                      [--timings FILE] [--report N] [--log-dir DIR]

Each shard is its own Python process running some of the backend test modules with the standard library's unittest.
Each one imports backend\\tests first, which gives it a database schema and folders of its own (backend\\tests\\
__init__.py), so shards never share data. The modules are spread over the shards by how long each took last time
(backend\\tests\\durations.json), longest first, onto the shard with the least so far; a module not listed there
counts as the median.

--tier quick leaves out the tests marked slow (backend\\tests\\tiers.py); --tier full (the default) runs them all.
--timings FILE writes each module's and each test's duration (seconds) as JSON; --record also rewrites
backend\\tests\\durations.json from this run, when every module ran. --report N prints the N slowest modules and tests.

Exit code 0 only when every shard passed. At the end it prints how many tests ran in how many shards, how long it
took, and any failure, with the log of the shard it was in. Standard library only (CLAUDE.md rule 19).

    python scripts\\backend_shards.py --worker --out FILE MODULE ...    (one shard; run by the above)
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DURATIONS = BACKEND / "tests" / "durations.json"
DEFAULT_SHARDS = 6


def modules_of_suite() -> list[str]:
    """Every backend test module, as unittest discover -s tests -t . finds them: tests\\test*.py."""
    return sorted(f"tests.{p.stem}" for p in (BACKEND / "tests").glob("test*.py"))


def _durations_file() -> dict:
    try:
        return json.loads(DURATIONS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def known_durations() -> dict[str, float]:
    return {k: float(v) for k, v in (_durations_file().get("modules") or {}).items()}


def splittable() -> set[str]:
    """Modules whose tests each set up for themselves (setUp, no setUpClass or ordered tests): their tests may run in
    several shards (durations.json `split`)."""
    return set(_durations_file().get("split") or [])


def plan(modules: list[str], shards: int, durations: dict[str, float], split: set[str] | None = None) -> list[list[str]]:
    """Longest first, each onto the shard with the least time so far. A splittable module longer than a shard's share
    becomes parts, `module#k/n` (part k of n), each run in its own shard (worker: _part). Never more shards than units."""
    if not modules:
        return []
    default = statistics.median(durations.values()) if durations else 1.0
    cost = {m: durations.get(m, default) for m in modules}
    share = sum(cost.values()) / max(1, shards)
    units: dict[str, float] = {}
    for m in modules:
        parts = min(shards, int(-(-cost[m] // share))) if m in (split or set()) and share > 0 else 1
        if parts > 1:
            units.update({f"{m}#{k}/{parts}": cost[m] / parts for k in range(1, parts + 1)})
        else:
            units[m] = cost[m]
    count = max(1, min(shards, len(units)))
    bins: list[tuple[float, list[str]]] = [(0.0, []) for _ in range(count)]
    for u in sorted(units, key=lambda u: (-units[u], u)):
        i = min(range(count), key=lambda k: (bins[k][0], k))
        bins[i] = (bins[i][0] + units[u], bins[i][1] + [u])
    return [sorted(b[1]) for b in bins if b[1]]


def _part(tests: list, k: int, n: int) -> list:
    """Part k of n of a module's tests: longest first onto the lightest part, by durations.json's `tests` (a test not
    listed counts as the median), so every worker computes the same parts and each test runs in exactly one."""
    known = {t: float(s) for t, s in (_durations_file().get("tests") or {}).items()}
    ids = sorted(t.id() for t in tests)
    listed = [known[i] for i in ids if i in known]
    default = statistics.median(listed) if listed else 1.0
    loads = [0.0] * n
    owner = {}
    for i in sorted(ids, key=lambda i: (-known.get(i, default), i)):
        j = min(range(n), key=lambda x: (loads[x], x))
        loads[j] += known.get(i, default)
        owner[i] = j + 1
    return [t for t in sorted(tests, key=lambda t: t.id()) if owner[t.id()] == k]


# ---------------------------------------------------------------- one shard


def worker(out: Path, modules: list[str]) -> int:
    sys.path.insert(0, str(BACKEND))
    os.chdir(BACKEND)
    import unittest

    tests: dict[str, float] = {}
    module_times: dict[str, float] = {}

    class Timed(unittest.TextTestResult):
        def startTest(self, test):
            self._began = time.perf_counter()
            super().startTest(test)

        def stopTest(self, test):
            tests[test.id()] = round(time.perf_counter() - self._began, 3)
            super().stopTest(test)

    loader = unittest.TestLoader()
    result = Timed(unittest.runner._WritelnDecorator(sys.stderr), descriptions=True, verbosity=1)
    began = time.perf_counter()
    def flat(suite):
        for t in suite:
            if isinstance(t, unittest.TestSuite):
                yield from flat(t)
            else:
                yield t

    for unit in modules:
        module, _, part = unit.partition("#")
        start = time.perf_counter()
        try:
            suite = loader.loadTestsFromName(module)
            if part:
                k, n = (int(x) for x in part.split("/"))
                suite = unittest.TestSuite(_part(list(flat(suite)), k, n))
        except Exception as error:                          # a module that cannot be imported is a failure
            def cannot_import(error=error):
                raise error
            suite = unittest.TestSuite([unittest.FunctionTestCase(cannot_import, description=f"import {module}")])
        suite.run(result)
        module_times[module] = round(module_times.get(module, 0) + time.perf_counter() - start, 3)
    result.printErrors()
    taken = time.perf_counter() - began
    stream = result.stream
    stream.writeln(unittest.TextTestResult.separator2)
    stream.writeln(f"Ran {result.testsRun} tests in {taken:.3f}s")
    stream.writeln("")
    ok = result.wasSuccessful()
    details = [f"{name}={n}" for name, n in (("failures", len(result.failures)), ("errors", len(result.errors)),
                                             ("skipped", len(result.skipped))) if n]
    stream.writeln(("OK" if ok else "FAILED") + (f" ({', '.join(details)})" if details else ""))
    out.write_text(json.dumps({
        "schema": os.environ.get("PLATFORM_TEST_SCHEMA"),   # this shard's own, set by importing backend\tests
        "modules": module_times, "tests": tests, "ran": result.testsRun, "skipped": len(result.skipped),
        "failures": sorted(t.id() for t, _ in result.failures), "errors": sorted(t.id() for t, _ in result.errors),
        "unexpected_successes": len(result.unexpectedSuccesses),
    }, indent=1, sort_keys=True), encoding="utf-8")
    sys.stderr.flush()
    return 0 if ok else 1


# ---------------------------------------------------------------- the run


def run(shards: int, tier: str, modules: list[str], log_dir: Path) -> tuple[int, dict]:
    groups = plan(modules, shards, known_durations(), splittable())
    env = {k: v for k, v in os.environ.items() if k != "PLATFORM_TEST_SCHEMA"}   # each shard makes its own schema
    env["PLATFORM_TESTS_TIER"] = tier
    env["PYTHONUNBUFFERED"] = "1"
    print(f"Backend: {len(modules)} module(s) in {len(groups)} shard(s), tier {tier}.", flush=True)
    running = []
    for n, group in enumerate(groups, 1):
        out = log_dir / f"shard-{n}.json"
        log = log_dir / f"shard-{n}.log"
        handle = log.open("w", encoding="utf-8")
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", "--out", str(out), *group],
                                   cwd=BACKEND, env=env, stdout=handle, stderr=subprocess.STDOUT)
        running.append({"n": n, "process": process, "handle": handle, "out": out, "log": log, "modules": group,
                        "began": time.monotonic()})
    merged = {"modules": {}, "tests": {}, "ran": 0, "skipped": 0, "failures": [], "errors": []}
    failed = []
    for shard in running:
        code = shard["process"].wait()
        shard["handle"].close()
        minutes = (time.monotonic() - shard["began"]) / 60
        try:
            data = json.loads(shard["out"].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if data:
            merged["tests"].update(data["tests"])
            for module, seconds in data["modules"].items():        # a split module's parts add up
                merged["modules"][module] = round(merged["modules"].get(module, 0) + seconds, 3)
            for key in ("ran", "skipped"):
                merged[key] += data[key]
            merged["failures"] += data["failures"]
            merged["errors"] += data["errors"]
        state = "passed" if code == 0 else f"FAILED (exit {code})"
        ran = f"{data['ran']} tests" if data else "no result written"
        print(f"   shard {shard['n']}: {state}, {ran}, {minutes:.1f} min ({len(shard['modules'])} modules)", flush=True)
        if code != 0:
            failed.append(shard)
            tail = shard["log"].read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
            for line in tail:
                print(f"      {line}")
            print(f"      log: {shard['log']}")
    return (1 if failed else 0), merged


def record(data: dict) -> None:
    """Rewrites durations.json from a full run: every module's seconds, the splittable modules (kept as they were) and
    their tests' seconds, which a split module's parts are assigned by. Stable key order, so it diffs well."""
    split = sorted(splittable())
    tests = {t: round(s, 1) for t, s in sorted(data["tests"].items()) if t.rsplit(".", 2)[0] in split}
    DURATIONS.write_text(json.dumps({"modules": {m: round(s, 1) for m, s in sorted(data["modules"].items())},
                                     "split": split, "tests": tests}, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def report(data: dict, count: int, lane_seconds: float | None = None) -> None:
    total = lane_seconds or sum(data["modules"].values()) or 1.0
    print(f"\nSlowest {count} modules (share of {total / 60:.1f} min):")
    for m, s in sorted(data["modules"].items(), key=lambda kv: -kv[1])[:count]:
        print(f"  {s / 60:6.1f} min  {100 * s / total:5.1f}%  {m}")
    print(f"\nSlowest {count} tests (share of {total / 60:.1f} min):")
    for t, s in sorted(data["tests"].items(), key=lambda kv: -kv[1])[:count]:
        print(f"  {s / 60:6.1f} min  {100 * s / total:5.1f}%  {t}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts\\backend_shards.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--shards", type=int, default=DEFAULT_SHARDS)
    parser.add_argument("--tier", choices=("quick", "full"), default="full")
    parser.add_argument("--modules", nargs="*", help="these backend test modules only (default: every one)")
    parser.add_argument("--timings", help="write each module's and test's duration here (JSON)")
    parser.add_argument("--record", action="store_true", help="rewrite backend\\tests\\durations.json from this run")
    parser.add_argument("--report", type=int, default=0, help="print the N slowest modules and tests")
    parser.add_argument("--log-dir", help="where each shard's log goes (default: a new temporary folder)")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--out", help=argparse.SUPPRESS)
    parser.add_argument("names", nargs="*", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        return worker(Path(args.out), args.names)

    every = modules_of_suite()
    modules = args.modules or every
    log_dir = Path(args.log_dir) if args.log_dir else Path(tempfile.mkdtemp(prefix="mp-backend-shards-"))
    log_dir.mkdir(parents=True, exist_ok=True)
    began = time.monotonic()
    code, data = run(args.shards, args.tier, modules, log_dir)
    seconds = time.monotonic() - began
    if args.timings:
        Path(args.timings).write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    shard_count = len(plan(modules, args.shards, known_durations(), splittable()))
    if args.record and sorted(modules) == every and args.tier == "full":
        record(data)
    if args.report:
        report(data, args.report)
    problems = data["failures"] + data["errors"]
    print(f"\nRan {data['ran']} tests ({data['skipped']} skipped) in {shard_count} "
          f"shard(s), {seconds / 60:.1f} min: {'OK' if code == 0 and not problems else 'FAILED'}")
    for name in problems[:30]:
        print(f"  failed: {name}")
    if code != 0 or problems:
        print(f"Shard logs: {log_dir}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
