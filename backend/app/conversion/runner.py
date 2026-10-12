"""The unit loop — 34-CONVERSION-ARCHITECTURE.md Part E, for a plan's units in
`sequence`, after the baseline.

**Baseline first.** The solution is built and its unit tests run at the
legacy commit, in a scratch worktree. A build failure, or a test count of
zero, fails the baseline and nothing runs. Its test results — failures
included — are what every unit is held to.

**Each unit**, in its own scratch git worktree at the conversion branch's
tip (Part E):

    depends_on    a unit it needs that is not committed -> blocked, not applied
    pre-check     not_applicable -> recorded; stale or refused -> the unit fails
    apply         the approach's edit; the diff is kept as evidence (the dry run)
    allowed_paths a change to any other file fails the unit
    post-checks
    build         the solution
    unit tests    no test that passed at the baseline may fail or vanish
    commit        one commit, the approach's message; the branch fast-forwards to it

Any failure discards the scratch worktree: nothing red is ever committed, so
there is nothing to roll back.

**Failure policy: by dependency, not by phase.** A failed unit is recorded
`failed` with its reason; every unit that depends on it, transitively, is
recorded `blocked`, naming what it waits on; every other unit carries on. An
assisted unit (Part F) is never applied here — it stays `planned`, left for
T1b — and what depends on it is blocked too. The plan ends `completed` when
every unit is committed or not applicable, `partial` otherwise; it is
`stopped` only by what invalidates every unit (a failed baseline, a change to
the checked-out working tree). Nobody excludes a unit: the runner records,
and has no switch to skip one. A rerun retries every unit not committed or
not applicable.

**Layout in_place.** The conversion branch lives in its own worktree under
the platform's runs directory. The repository's checked-out working tree is
never written: the runner fingerprints it (HEAD, git status with ignored
files, every file's path, size and modification time) before and after,
keeps both as evidence, and stops the plan if they differ.

    python -m app.conversion.runner --plan <plan-id>
"""

import argparse
import datetime
import hashlib
import json
import os
import uuid
from pathlib import Path

from app import models
from app.conversion import dotnet, evidence, gitops
from app.conversion.approaches import APPROACHES
from app.db import SessionLocal

# Settled: never run again. `excluded` is the first proof's history (models.UNIT_STATUS).
DONE = ("committed", "not_applicable", "excluded")
# What a dependent may build on.
SATISFIED = ("committed", "not_applicable")


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def fingerprint(root: Path) -> dict:
    """HEAD, git status with ignored files, and a hash over every file's path,
    size and modification time (.git excluded)."""
    status = gitops.git(root, "status", "--porcelain=v1", "--ignored")
    digest, files = hashlib.sha256(), 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for name in sorted(filenames):
            p = Path(dirpath) / name
            st = p.stat()
            digest.update(f"{p.relative_to(root).as_posix()}|{st.st_size}|{st.st_mtime_ns}\n".encode())
            files += 1
    return {"head": gitops.head(root), "branch": gitops.git(root, "symbolic-ref", "--short", "HEAD", check=False).strip(),
            "status_sha256": hashlib.sha256(status.encode()).hexdigest(), "files": files, "files_sha256": digest.hexdigest()}


class Run:
    def __init__(self, db, plan: models.ConversionPlan):
        self.db = db
        self.plan = plan
        self.repository = db.get(models.Repository, plan.repository_id)
        self.root = Path(self.repository.local_path)
        self.target = Path(plan.worktree_path)
        self.dir = self.target.parent
        self.evidence = self.dir / "evidence"
        self.solution = plan.ordering["solution"]
        self.unit_tests = plan.ordering["unit_test_projects"]

    def log(self, message: str) -> None:
        print(f"{_now():%H:%M:%S} {message}", flush=True)

    # ---------- build and test ----------

    def build_and_test(self, worktree: Path, out: Path) -> tuple[list[dict], dict | None, str | None]:
        """(evidence records, test results by project, failure reason)."""
        records = []
        built = dotnet.build(worktree, self.solution)
        log = evidence.write(out / "build.log", built.log)
        records.append(evidence.record("build_log", log, self.dir, ok=built.ok, exit_code=built.exit_code))
        if not built.ok:
            return records, None, f"build of {self.solution} failed (exit {built.exit_code})"
        results = {}
        for project in self.unit_tests:
            name = Path(project).stem
            run, tests = dotnet.test(worktree, project, out / "tests" / f"{name}.trx")
            console = evidence.write(out / "tests" / f"{name}.log", run.log)
            records.append(evidence.record("test_log", console, self.dir, project=project, exit_code=run.exit_code))
            if tests is None:
                return records, None, f"{project}: no test results were written (exit {run.exit_code})"
            records.append(evidence.record("test_results", out / "tests" / f"{name}.trx", self.dir, project=project,
                                           **tests.as_dict()))
            results[project] = tests
        return records, results, None

    # ---------- baseline ----------

    def baseline(self) -> bool:
        if self.plan.baseline and self.plan.baseline.get("passed"):
            return True
        self.log(f"baseline: build {self.solution} and unit tests at {self.plan.legacy_commit[:10]}")
        scratch = self.dir / "scratch" / "baseline"
        gitops.add_scratch(self.root, scratch, self.plan.legacy_commit)
        try:
            records, results, failure = self.build_and_test(scratch, self.evidence / "000-baseline")
        finally:
            dotnet.shutdown_build_servers()
            gitops.remove(self.root, scratch)
        total = sum(r.total for r in (results or {}).values())
        if failure is None and total == 0:
            failure = "the unit tests ran no test: a baseline of zero tests proves nothing"
        self.plan.baseline = {
            "passed": failure is None, "failure": failure, "commit": self.plan.legacy_commit, "evidence": records,
            "tests": {p: {**r.as_dict(), "passed_tests": r.passed_tests} for p, r in (results or {}).items()},
            "total": total, "at": _now().isoformat(),
        }
        if failure:
            self.stop(f"baseline failed: {failure}")
        self.db.commit()
        self.log(f"baseline: {'passed' if failure is None else 'FAILED'}; {total} unit test(s)")
        return failure is None

    def regressions(self, results: dict) -> list[str]:
        problems = []
        for project, base in self.plan.baseline["tests"].items():
            now = results.get(project)
            if now is None:
                problems.append(f"{project}: no results")
                continue
            if now.total < base["total"]:
                problems.append(f"{project}: {now.total} test(s), baseline {base['total']}")
            broken = sorted(set(base["passed_tests"]) - set(now.passed_tests))
            if broken:
                problems.append(f"{project}: {len(broken)} test(s) passing at the baseline no longer pass: "
                                + ", ".join(broken[:10]) + (" ..." if len(broken) > 10 else ""))
        return problems

    # ---------- units ----------

    def stop(self, reason: str) -> None:
        self.plan.status, self.plan.status_reason = "stopped", reason
        self.db.commit()
        self.log(f"plan stopped: {reason}")

    def fail(self, unit, reason: str, records: list[dict], status: str = "failed") -> None:
        unit.status, unit.status_reason, unit.evidence, unit.finished_at = status, reason, records, _now()
        self.db.commit()
        self.log(f"{unit.sequence:>3} {status}: {reason}")

    @staticmethod
    def blockers(unit, by_sequence: dict) -> list[str]:
        """What this unit waits on: each unit it depends on that is not committed or not applicable."""
        waiting = []
        for edge in unit.depends_on:
            other = by_sequence[edge["sequence"]]
            if other.status in SATISFIED:
                continue
            assisted = other.status == "planned" and other.automation_class != "deterministic"
            waiting.append(f"unit {other.sequence} ({'assisted, left for T1b' if assisted else other.status})")
        return waiting

    def unit(self, unit: models.ConversionUnit) -> bool:
        approach = APPROACHES[unit.approach_id]
        if approach.version != unit.approach_version:
            self.fail(unit, f"approach {approach.id} is {approach.version}, the plan was made with {unit.approach_version}", [], "stale")
            return False
        unit.execution_id, unit.started_at, unit.status_reason = uuid.uuid4(), _now(), None
        out = self.evidence / f"{unit.sequence:03d}-{unit.approach_id}"
        pre = approach.pre_check(self.target, unit.target)
        if pre.outcome == "not_applicable":
            unit.status, unit.status_reason, unit.evidence, unit.finished_at = "not_applicable", pre.reason, [], _now()
            self.db.commit()
            self.log(f"{unit.sequence:>3} not applicable: {pre.reason}")
            return True
        if pre.outcome in ("stale", "refused"):
            self.fail(unit, pre.reason, [], "stale" if pre.outcome == "stale" else "failed")
            return False

        scratch = self.dir / "scratch" / f"{unit.sequence:03d}"
        tip = gitops.head(self.target)
        gitops.add_scratch(self.root, scratch, tip)
        records: list[dict] = []
        try:
            changes = approach.apply(scratch, unit.target)
            diff = evidence.write(out / "dry-run.diff", gitops.diff(scratch))
            records.append(evidence.record("diff", diff, self.dir, base=tip, changes=changes))
            unit.status = "applied"
            changed = gitops.changed_files(scratch)
            outside = sorted(set(changed) - approach.allowed_paths(unit.target))
            if outside:
                self.fail(unit, f"changed files outside allowed_paths: {', '.join(outside)}", records)
                return False
            if not changed:
                self.fail(unit, "the approach changed nothing, though its pre-check said it applies", records)
                return False
            problems = approach.post_check(scratch, unit.target)
            if problems:
                self.fail(unit, "post-check: " + "; ".join(problems), records)
                return False
            built, results, failure = self.build_and_test(scratch, out)
            records.extend(built)
            if failure:
                self.fail(unit, failure, records)
                return False
            regressions = self.regressions(results)
            if regressions:
                self.fail(unit, "unit tests: " + "; ".join(regressions), records)
                return False
            unit.status = "verified"
            outside = sorted(set(gitops.changed_files(scratch)) - approach.allowed_paths(unit.target))
            if outside:
                self.fail(unit, f"build or tests changed tracked files: {', '.join(outside)}", records)
                return False
            sha = gitops.commit(scratch, approach.message(unit.target))
            gitops.fast_forward(self.target, sha)
            result = evidence.write(out / "result.json", json.dumps(
                {"unit_id": unit.unit_id, "sequence": unit.sequence, "commit": sha, "evidence": records}, indent=2))
            records.append(evidence.record("result", result, self.dir, commit=sha))
            unit.status, unit.commit_sha, unit.evidence, unit.finished_at, unit.status_reason = "committed", sha, records, _now(), None
            self.db.commit()
            totals = {Path(p).stem: f"{r.passed}/{r.total}" for p, r in results.items()}
            self.log(f"{unit.sequence:>3} committed {sha[:10]}  tests {totals}")
            return True
        except Exception as error:   # an approach or git failure: discard, never commit
            self.fail(unit, f"{type(error).__name__}: {error}", records)
            return False
        finally:
            dotnet.shutdown_build_servers()
            gitops.remove(self.root, scratch)

    def run(self) -> None:
        before = fingerprint(self.root)
        evidence.write(self.evidence / f"checkout-before-{_now():%Y%m%dT%H%M%S}.json", json.dumps(before, indent=2))
        gitops.ensure_branch_worktree(self.root, self.target, self.plan.branch, self.plan.legacy_commit)
        self.plan.status, self.plan.status_reason = "running", None
        self.db.commit()
        try:
            if self.baseline():
                units = (self.db.query(models.ConversionUnit).filter_by(plan_id=self.plan.id)
                         .order_by(models.ConversionUnit.sequence).all())
                by_sequence = {u.sequence: u for u in units}
                pending = [u for u in units if u.status not in DONE]
                if pending:
                    self.log(f"running {len(pending)} of {len(units)} unit(s), from unit {pending[0].sequence}")
                for unit in pending:
                    waiting = self.blockers(unit, by_sequence)
                    if waiting:
                        unit.status, unit.status_reason = "blocked", f"waits on {', '.join(waiting)}"
                        self.db.commit()
                        self.log(f"{unit.sequence:>3} blocked: {unit.status_reason}")
                    elif unit.automation_class != "deterministic":
                        unit.status, unit.status_reason = "planned", (
                            f"{unit.automation_class}: never applied by the deterministic runner (Part F); left for T1b")
                        self.db.commit()
                        self.log(f"{unit.sequence:>3} left for T1b: {unit.automation_class}")
                    else:
                        self.unit(unit)
                counts = {}
                for u in units:
                    counts[u.status] = counts.get(u.status, 0) + 1
                summary = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
                self.plan.status = "completed" if all(u.status in SATISFIED for u in units) else "partial"
                self.plan.status_reason, self.plan.completed_at = summary, _now()
                self.db.commit()
                self.log(f"plan {self.plan.status}: {summary}")
        finally:
            after = fingerprint(self.root)
            evidence.write(self.evidence / f"checkout-after-{_now():%Y%m%dT%H%M%S}.json", json.dumps(after, indent=2))
            if after != before:
                self.stop(f"the repository's checked-out working tree changed during the run: {before} -> {after}")
            else:
                self.log(f"checkout unchanged: HEAD {after['head'][:10]}, {after['files']} files, {after['files_sha256'][:12]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a conversion plan's units (34-CONVERSION-ARCHITECTURE.md Part E).")
    parser.add_argument("--plan", required=True)
    args = parser.parse_args()
    db = SessionLocal()
    try:
        Run(db, db.get(models.ConversionPlan, uuid.UUID(args.plan))).run()
    finally:
        db.close()


if __name__ == "__main__":
    main()
