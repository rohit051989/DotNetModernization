"""The package step of a conversion's prepare, fast (36-COPILOT-ENHANCED-CONVERSION Part N): a conversion plan's
deterministic units applied in batches in one working copy, each batch built and tested once.

    batch first   every deterministic unit applied together, then one build and one test run. Green: one commit,
                  listing every change, and the branch fast-forwards to it.
    by halves     red: the working copy is reset with git to the branch's tip, and the units are split in two,
                  each half settled the same way, until each failing unit is alone. What passes is committed; each
                  failing unit is recorded with its error, and what depends on it is blocked.
    flaky tests   a test that passed at the baseline and fails is rerun once, alone. Passing then, it is flaky: listed
                  in the step's report, never a failure, never silent. Failing again, it is a regression.

It is the unit loop of app.conversion.runner (34-CONVERSION-ARCHITECTURE Part E) with the same approaches,
pre-checks, allowed paths, post-checks, baseline and failure policy by dependency, and the same evidence; only
the grouping differs. One scratch worktree serves the whole step, baseline included: build output is kept between
cycles, so each build after the first is incremental. An assisted unit is never applied (Part F): it stays planned,
left for the agent.
"""
import datetime
import json
import time
import uuid
from pathlib import Path

from app.conversion import dotnet, evidence, gitops
from app.conversion.approaches import APPROACHES
from app.conversion.runner import DONE, SATISFIED, Run, fingerprint
from app.engine import siblings
from app.engine.inputs import selfcontained

MESSAGE_END = "Made by a deterministic conversion, not an AI."


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def change_line(unit) -> list[str]:
    """One line per change a unit makes, for the batch commit's message: "- P a -> b (project)" for a version (the
    form the verifier reads back as a requested version), "- Remove P v (project)", or the unit's title."""
    t = unit.target
    if unit.approach_id == "package-upgrade-safe":
        return [f"- {b['package_id']} {b['from']} -> {b['to']} ({b['project']})" for b in t.get("bumps") or [t]]
    if unit.approach_id == "remove-package-reference":
        return [f"- Remove {t['package_id']} {t['version']} ({t['project']}): provided by {t['provided_by']}"]
    return [f"- {t.get('title')}"]


class Batch(Run):
    def __init__(self, db, plan, sibling_links: list[str] | None = None):
        super().__init__(db, plan, sibling_links)
        self.work = self.dir / "scratch" / "work"
        self.cycles = 0
        self.flaky: list[dict] = []

    # ---------- one build and test of the working copy ----------

    def cycle(self, label: str) -> tuple[list[dict], dict | None, str | None]:
        """(evidence, results, failure): the solution built and its unit tests run in the working copy; a test that
        passed at the baseline and fails now is rerun once, and counts as flaky when it passes."""
        self.cycles += 1
        out = self.evidence / f"cycle-{self.cycles:03d}-{label}"
        records, results, failure = self.build_and_test(self.work, out)
        if failure or not self.plan.baseline or not self.plan.baseline.get("passed"):
            return records, results, failure
        problems = []
        for project, base in self.plan.baseline["tests"].items():
            now = results.get(project)
            if now is None:
                problems.append(f"{project}: no results")
                continue
            if now.total < base["total"]:
                problems.append(f"{project}: {now.total} test(s), baseline {base['total']}")
            broken = sorted(set(base["passed_tests"]) - set(now.passed_tests))
            failing = [n for n in broken if n in now.failed_tests]
            gone = [n for n in broken if n not in now.failed_tests]
            if failing:
                passed, still = dotnet.rerun(self.work, project, failing, out / "rerun" / f"{Path(project).stem}.trx")
                self.flaky += [{"project": project, "test": n, "where": label} for n in passed]
                failing = still
            if failing or gone:
                lost = failing + gone
                problems.append(f"{project}: {len(lost)} test(s) passing at the baseline no longer pass: "
                                + ", ".join(lost[:10]) + (" ..." if len(lost) > 10 else ""))
        return records, results, ("unit tests: " + "; ".join(problems)) if problems else None

    # ---------- the baseline, in the working copy ----------

    def baseline(self) -> bool:
        if self.plan.baseline and self.plan.baseline.get("passed"):
            return True
        self.log(f"baseline: build {self.solution} and unit tests at {self.plan.legacy_commit[:10]}")
        self._reset(self.plan.legacy_commit)
        records, results, failure = self.cycle("baseline")
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

    # ---------- settling a group ----------

    def _reset(self, commit: str) -> None:
        """The working copy at `commit`, tracked and untracked changes discarded; build output (ignored) is kept."""
        gitops.git(self.work, "checkout", "--detach", "-q", "--force", commit)
        gitops.git(self.work, "reset", "--hard", "-q", commit)
        gitops.git(self.work, "clean", "-fdq")

    def _blocked_by(self, unit, by_sequence: dict) -> list[str]:
        return [f"unit {by_sequence[d['sequence']].sequence} ({by_sequence[d['sequence']].status})"
                for d in unit.depends_on if by_sequence[d["sequence"]].status in ("failed", "blocked", "stale")
                or (by_sequence[d["sequence"]].status == "planned" and by_sequence[d["sequence"]].automation_class != "deterministic")]

    def settle(self, group: list, by_sequence: dict) -> None:
        """Applies `group` together at the branch's tip; commits it when green, else settles each half."""
        tip = gitops.head(self.target)
        self._reset(tip)
        applied, allowed, notes = [], set(), {}
        for unit in group:
            if unit.status in DONE:
                continue
            waiting = self._blocked_by(unit, by_sequence)
            if waiting:
                unit.status, unit.status_reason = "blocked", f"waits on {', '.join(waiting)}"
                self.db.commit()
                self.log(f"{unit.sequence:>3} blocked: {unit.status_reason}")
                continue
            approach = APPROACHES[unit.approach_id]
            if approach.version != unit.approach_version:
                self.fail(unit, f"approach {approach.id} is {approach.version}, the plan was made with {unit.approach_version}", [], "stale")
                continue
            unit.execution_id, unit.started_at, unit.status_reason = unit.execution_id or uuid.uuid4(), unit.started_at or _now(), None
            pre = approach.pre_check(self.work, unit.target)
            if pre.outcome == "not_applicable":
                unit.status, unit.status_reason, unit.evidence, unit.finished_at = "not_applicable", pre.reason, [], _now()
                self.db.commit()
                self.log(f"{unit.sequence:>3} not applicable: {pre.reason}")
                continue
            if pre.outcome in ("stale", "refused"):
                self.fail(unit, pre.reason, [], "stale" if pre.outcome == "stale" else "failed")
                continue
            try:
                notes[unit.sequence] = approach.apply(self.work, unit.target)
                problems = approach.post_check(self.work, unit.target)
            except Exception as error:   # an approach failure: this unit alone fails; the group starts again
                self.fail(unit, f"{type(error).__name__}: {error}", [])
                return self.settle([u for u in group if u is not unit], by_sequence)
            if problems:
                self.fail(unit, "post-check: " + "; ".join(problems), [])
                return self.settle([u for u in group if u is not unit], by_sequence)
            applied.append(unit)
            allowed |= approach.allowed_paths(unit.target)
        if not applied:
            return
        label = f"units-{applied[0].sequence}-{applied[-1].sequence}" if len(applied) > 1 else f"unit-{applied[0].sequence}"
        diff = evidence.write(self.evidence / f"{label}.diff", gitops.diff(self.work))
        outside = sorted(set(gitops.changed_files(self.work)) - allowed)
        if outside:
            failure, records = f"changed files outside allowed_paths: {', '.join(outside)}", []
        else:
            records, _, failure = self.cycle(label)
        records = [evidence.record("diff", diff, self.dir, base=tip, changes=notes)] + records
        if failure is None:
            outside = sorted(set(gitops.changed_files(self.work)) - allowed)
            if outside:
                failure = f"build or tests changed tracked files: {', '.join(outside)}"
        if failure is None:
            message = (APPROACHES[applied[0].approach_id].message(applied[0].target) if len(applied) == 1 else
                       f"Package changes that need no code ({len(applied)})\n\n"
                       + "\n".join(line for u in applied for line in change_line(u))
                       + f"\nBuilt and tested together.\n{MESSAGE_END}")
            sha = gitops.commit(self.work, message, vocabulary=selfcontained.vocabulary(self.db))
            gitops.fast_forward(self.target, sha)
            for unit in applied:
                unit.status, unit.commit_sha, unit.evidence, unit.finished_at, unit.status_reason = (
                    "committed", sha, records, _now(), None)
            self.db.commit()
            self.log(f"committed {sha[:10]}: {len(applied)} unit(s) {', '.join(str(u.sequence) for u in applied)}")
            return
        if len(applied) == 1:
            self.fail(applied[0], failure, records)
            return
        self.log(f"red with {len(applied)} unit(s) ({failure[:160]}): by halves")
        half = len(applied) // 2
        self.settle(applied[:half], by_sequence)
        self.settle(applied[half:], by_sequence)

    # ---------- the step ----------

    def run(self) -> dict:
        started = time.monotonic()
        before = fingerprint(self.root)
        evidence.write(self.evidence / f"checkout-before-{_now():%Y%m%dT%H%M%S}.json", json.dumps(before, indent=2))
        gitops.ensure_branch_worktree(self.root, self.target, self.plan.branch, self.plan.legacy_commit)
        gitops.add_scratch(self.root, self.work, self.plan.legacy_commit)
        siblings.link(self.work, self.root, self.sibling_links)
        self.plan.status, self.plan.status_reason = "running", None
        self.db.commit()
        try:
            if self.baseline():
                from app import models

                units = (self.db.query(models.ConversionUnit).filter_by(plan_id=self.plan.id)
                         .order_by(models.ConversionUnit.sequence).all())
                by_sequence = {u.sequence: u for u in units}
                for unit in units:
                    if unit.status not in DONE and unit.automation_class != "deterministic":
                        unit.status, unit.status_reason = "planned", (
                            f"{unit.automation_class}: never applied by the deterministic runner (Part F); left for the agent")
                self.db.commit()
                self.settle([u for u in units if u.automation_class == "deterministic" and u.status not in DONE], by_sequence)
                counts = {}
                for u in units:
                    counts[u.status] = counts.get(u.status, 0) + 1
                summary = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
                self.plan.status = "completed" if all(u.status in SATISFIED for u in units) else "partial"
                self.plan.status_reason, self.plan.completed_at = summary, _now()
                self.db.commit()
                self.log(f"plan {self.plan.status}: {summary}; {self.cycles} build-and-test cycle(s)")
        finally:
            dotnet.shutdown_build_servers()
            gitops.remove(self.root, self.work)
            siblings.remove(self.work.parent, self.sibling_links)
            after = fingerprint(self.root)
            evidence.write(self.evidence / f"checkout-after-{_now():%Y%m%dT%H%M%S}.json", json.dumps(after, indent=2))
            if after != before:
                self.stop(f"the repository's checked-out working tree changed during the run: {before} -> {after}")
        return {"seconds": round(time.monotonic() - started), "cycles": self.cycles, "flaky": self.flaky}
