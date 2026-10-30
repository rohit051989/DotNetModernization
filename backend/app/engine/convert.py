"""One conversion at a time (36-COPILOT-ENHANCED-CONVERSION Part N): prepare a branch for an engine, then verify it.

    python -m app.engine.convert prepare --engagement test-client-a --repository accountsapi-net10
        [--baseline e89bc6a] [--goal "..."] [--sibling-link EnterprisePackages]
        [--canary-file F --canary-find X --canary-replace Y --canary-why W]
    python -m app.engine.convert verify --engagement test-client-a --repository accountsapi-net10 --branch conversion/1
        [--base e89bc6a] [--label L] [--refresh-baseline]
    python -m app.engine.convert approve-removal --engagement test-client-a --repository accountsapi-net10
        --branch conversion/2 --test <test name or test file> [--test ...] --reason "..." --by "<person>"

`prepare` makes the next conversion of a repository: a branch `conversion/<n>` from its baseline, in a worktree at
`<RUNS_DIR>/<engagement>/<repository>/conversions/<n>/wt`. First the platform applies the package changes that need no
code: safe upgrades (each also fixing the vulnerability its package carries) and removals of packages the target
framework provides. It uses the conversion unit loop (app.conversion.runner): one commit each on the conversion
branch, every one building and passing the baseline's tests. A change that does not go green is not committed, and is
reported. Then it generates the engine inputs, less what those commits did, commits them as the platform, and writes
`RUNBOOK.md` and `conversion.json` beside the worktree. The agent is left what needs code: breaking upgrades, a
retired package's successor, and any package change that did not go green. It records the platform commit it ran at
and pins nothing. There are no arms or generations. When the latest conversion has not been run (every commit on its
branch is the platform's, and its worktree is clean), preparing again refreshes it in place. Its package commits are
kept when the planned package changes are the same, and made again otherwise. Otherwise preparing again makes the
next one. So fixing an instruction and preparing again needs nothing more.

A conversion's baseline, goal, sibling links and canaries default to the previous conversion's, so they are given
once per repository.

Before anything is changed, every package version the inputs ask for (an upgrade's, a vulnerability's fix, a retired
package's successor) is checked against the package lookups: none may carry a known advisory, and the lookups must be
less than a day old. Otherwise prepare refuses and says to run discovery again.

`verify` runs the verifier (app.engine.verifier) on a branch against its baseline. It needs no experiment
configuration. The baseline, sibling links and canaries come from the branch's conversion record, or from the
repository's latest one for any other branch (then `--base` is required). Package lookups are answered live, and a
package upgrade is judged against the version the branch's inputs asked for when the conversion was prepared, not
today's newest release (app.engine.verifier.packages).
"""
import argparse
import datetime
import json
import string
import sys
import tempfile
from pathlib import Path

from app import models
from app.conversion import gitops, planner
from app.engine import siblings
from app.engine.inputs import generate
from app.experiment import instrument

INPUTS_COMMIT = "Add generated upgrade inputs for GitHub Copilot (do not edit)"
DEFAULT_GOAL = "Upgrade this solution to .NET 10 and make the application ready to run on OpenShift."
RUNBOOK_TEMPLATE = Path(__file__).resolve().parent / "templates" / "conversion-runbook.md"
RECORD = "conversion.json"
STUCK_MINUTES = 5
MAX_ROUNDS = 3


# ---------------------------------------------------------------- the opening message

def opening_message(goal: str, solution: str | None) -> str:
    """Everything the agent needs, in the first message: the goal, how to work, the inputs, and what done means."""
    build = f"Build the solution ({solution})" if solution else "Build the solution"
    return "\n".join([
        goal.strip(),
        "",
        "How to work:",
        "- Every instruction names, by path, the existing files it concerns. Open those files by their paths; do not "
        "search for them, and never create a file the instructions say already exists.",
        "- Edit files with your file-editing tools, not through terminal commands.",
        "- Never suppress a warning or an error to make a check pass: no -nowarn, NoWarn, #pragma warning disable, "
        "lowered warning level or skipped analyzer.",
        "- Keep every terminal command on a single line.",
        "- Work on the current branch and do not create another branch.",
        "- Keep every test, and the code it uses, unless an instruction says a decision chose otherwise; keep every "
        "existing deployment and build mechanism, adding beside it.",
        "- Use the custom upgrade instructions in .github/upgrades/skills and the skills in .github/skills, and follow "
        ".github/copilot-instructions.md. Read .github/platform-inputs/assessment-addendum.md and "
        ".github/platform-inputs/decision-sheet.md, and follow them.",
        "",
        "You are done only when all of these hold. Before you report done:",
        f"1. {build} with 0 errors.",
        "2. Run all tests. Every test must pass. Do not weaken, skip or delete any test. If a test file must change "
        "(a renamed namespace, for instance), keep the change minimal and list each change with its reason.",
        "3. Confirm that every JSON and XML configuration file in the repository still parses.",
        "4. Start the application without blocking the terminal, wait until it reports that it is listening or until "
        "it fails, then stop it. If it fails only because a secret, a vault or an external service is unavailable on "
        "this machine, report that, and do not change code to work around it.",
        f"If any of these fails, fix it and run all four again, at most {MAX_ROUNDS} times; then report what still "
        "fails.",
        "Every result you report must be from the final state of the code. If you change anything after a check, "
        "run all four checks again, and report only the results of that last run.",
        "Report each result with the command you ran and a summary of its output.",
    ])


def framework_name(tfm: str) -> str:
    """`net10.0` as the agent names it: `.NET 10`."""
    if tfm.startswith("net") and tfm[3:4].isdigit():
        major, _, minor = tfm[3:].partition(".")
        return f".NET {major}" + (f".{minor}" if minor and minor != "0" else "")
    return tfm


# ---------------------------------------------------------------- conversion records

def conversions_dir(engagement_id: str, slug: str) -> Path:
    return planner.RUNS / engagement_id / slug / "conversions"


def records(engagement_id: str, slug: str) -> list[dict]:
    """Every conversion record of a repository, oldest first."""
    home = conversions_dir(engagement_id, slug)
    found = [json.loads(f.read_text(encoding="utf-8")) for f in home.glob(f"*/{RECORD}")] if home.exists() else []
    return sorted(found, key=lambda r: r["number"])


def record(engagement_id: str, slug: str, number: int) -> dict | None:
    """Conversion `number`'s record, or None."""
    path = conversions_dir(engagement_id, slug) / str(number) / RECORD
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def commits_beyond_inputs(rec: dict) -> int:
    """How many commits the conversion's branch has beyond what prepare left (its inputs commit): the engine's work.
    A conversion counts as run once there is one (Part N)."""
    worktree = Path(rec["worktree"])
    if not worktree.exists():
        return 0
    return int(gitops.git(worktree, "rev-list", "--count", f"{rec['head']}..HEAD", check=False).strip() or 0)


def uncommitted(rec: dict) -> list[str]:
    worktree = Path(rec["worktree"])
    return gitops.changed_files(worktree) if worktree.exists() else []


def verification_of(rec: dict) -> dict | None:
    """The verification of this conversion's branch (label conversion-<n>), when one was made."""
    path = planner.RUNS / rec["engagement"] / rec["repository"] / "verification" / rec["branch"].replace("/", "-") / "verification.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def status(rec: dict) -> dict:
    """prepared (nothing beyond its inputs), run (commits beyond them) or verified (a verification of the branch's
    current head exists), with what each is read from."""
    beyond = commits_beyond_inputs(rec)
    worktree = Path(rec["worktree"])
    head = gitops.head(worktree) if worktree.exists() else None
    v = verification_of(rec)
    verified = bool(v and head and v.get("tip") == head)
    return {"state": "verified" if verified else ("run" if beyond else "prepared"), "head": head,
            "commitsBeyondInputs": beyond, "uncommitted": uncommitted(rec), "verification": v,
            "verificationIsCurrent": verified}


def verify_refusal(rec: dict) -> str | None:
    """Why this conversion cannot be verified now, or None: its worktree has uncommitted changes, or its branch has
    nothing beyond its inputs."""
    worktree = Path(rec["worktree"])
    if not worktree.exists():
        return f"the worktree {worktree} does not exist"
    changed = uncommitted(rec)
    if changed:
        return (f"the worktree has {len(changed)} uncommitted change(s) ({', '.join(changed[:3])}"
                + (" ..." if len(changed) > 3 else "") + "): commit them on the branch first")
    if not commits_beyond_inputs(rec):
        # The verifier's fixed rules make "nothing converted" a failed check, so the verdict is known without a run.
        return (f"NOT PROVEN, nothing converted: {rec['branch']} has nothing beyond its inputs, so the conversion "
                "has not been run. Run it, commit on the branch, then verify")
    return None


def _write_record(record: dict) -> None:
    path = Path(record["folder"]) / RECORD
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def unrun(worktree: Path, base: str) -> bool:
    """True when nothing has happened in the conversion's worktree since it was prepared: it is clean, and every commit
    on its branch after the baseline is the platform's (its package commits and its inputs commit)."""
    from app.engine.verifier.packages import PLATFORM_EMAIL

    if not worktree.exists() or gitops.git(worktree, "status", "--porcelain").strip():
        return False
    if gitops.git(worktree, "merge-base", base, "HEAD", check=False).strip() != base:
        return False
    authors = gitops.git(worktree, "log", "--format=%ae", f"{base}..HEAD").split()
    return all(a.lower() == PLATFORM_EMAIL for a in authors)


def _repository(db, engagement_id: str, slug: str) -> models.Repository:
    return (db.query(models.Repository).filter_by(engagement_id=engagement_id, slug=slug)
            .filter(models.Repository.deleted_at.is_(None)).one())


def _commit_inputs(db, engagement_id: str, slug: str, worktree: Path, applied: list[dict]) -> list[dict]:
    """Generates and commits the inputs. Returns [{file, references}]: each input that names a secret value by its
    file, key and line instead of quoting it (app.engine.inputs.secrets)."""
    from app.engine import paths
    from app.engine.inputs import selfcontained

    warnings: list[dict] = []
    generate(db, engagement_id, slug, worktree, applied=applied, warnings=warnings)
    gitops.platform_commit(worktree, INPUTS_COMMIT, vocabulary=selfcontained.vocabulary(db),
                           paths=[p.rstrip("/") for p in paths.GENERATED_INPUT_PATHS if (worktree / p.rstrip("/")).exists()])
    return warnings


# ---------------------------------------------------------------- the package changes the platform applies

# Settled on the branch (app.conversion.runner.SATISFIED): committed, or found already done.
SATISFIED = ("committed", "not_applicable")


def plan_packages(db, engagement_id: str, slug: str, base: str, branch: str, worktree: Path):
    """A conversion plan (app.conversion.planner) on the conversion's own branch and worktree. Its deterministic units
    are the package changes that need no code; its breaking upgrades stay assisted and are left for the agent."""
    plan = planner.create(db, engagement_id, slug, [])
    plan.legacy_commit, plan.branch, plan.worktree_path = base, branch, str(worktree)
    db.commit()
    units = db.query(models.ConversionUnit).filter_by(plan_id=plan.id).order_by(models.ConversionUnit.sequence).all()
    return plan, units


def unit_targets(units) -> list[dict]:
    """[{project, package, asked}] for every version the plan's deterministic units would set."""
    out = []
    for u in units:
        if u.automation_class != "deterministic" or u.approach_id != "package-upgrade-safe":
            continue
        for b in u.target.get("bumps") or [u.target]:
            out.append({"project": b["project"], "package": b["package_id"], "asked": b["to"]})
    return out


def applied_changes(units) -> list[dict]:
    """[{item, project, package, to}] for every unit settled on the branch: what the inputs leave out."""
    out = []
    for u in units:
        if u.status not in SATISFIED:
            continue
        if u.approach_id == "package-upgrade-safe":
            out += [{"item": "package-upgrade-safe", "project": b["project"], "package": b["package_id"], "to": b["to"]}
                    for b in u.target.get("bumps") or [u.target]]
        elif u.approach_id == "remove-package-reference":
            out.append({"item": "package-provided-by-framework", "project": u.target["project"],
                        "package": u.target["package_id"], "to": None})
        elif u.approach_id == "retarget-tfm":
            out.append({"item": "target-framework-retarget", "project": "*", "package": "", "to": u.target["to"]})
        elif u.target.get("delta_id"):
            out.append({"item": "framework-delta", "project": u.target["file"], "package": u.target["delta_id"], "to": None})
    return out


def _unit_record(u) -> dict:
    return {"sequence": u.sequence, "title": u.target.get("title"), "approach": u.approach_id,
            "automation": u.automation_class, "status": u.status, "reason": u.status_reason, "commit": u.commit_sha}


def run_packages(db, plan, sibling_links: list[str]) -> tuple[list, dict]:
    """(the plan's units, settled; the step's report: seconds, build-and-test cycles, flaky tests): the batch unit
    loop (app.conversion.batch), all of a group at once, by halves when red."""
    from app.conversion import batch

    step = batch.Batch(db, plan, sibling_links).run()
    units = db.query(models.ConversionUnit).filter_by(plan_id=plan.id).order_by(models.ConversionUnit.sequence).all()
    return units, step


# ---------------------------------------------------------------- advisories

LOOKUP_TTL = datetime.timedelta(hours=24)       # dependency-assessment's lookup_cache_ttl_hours


class AdvisoryFound(RuntimeError):
    pass


def check_advisories(db, files: dict[str, str] | None = None, now: datetime.datetime | None = None,
                     targets: list[dict] | None = None, check_age: bool = True) -> list[dict]:
    """Every package version the generated instructions (`files`) and the package commits (`targets`) ask for,
    checked against the package lookups: [{project, package, asked, advisories, fetchedAt}]. Refuses (AdvisoryFound)
    when one has a known advisory, is unknown to the lookups, or was answered by lookups older than a day: "today's
    advisories" must be today's."""
    from sqlalchemy import text

    from app.engine.inputs import render

    now = now or datetime.datetime.now(datetime.timezone.utc)
    checked, problems, stale = [], [], []
    for t in (targets or []) + render.package_targets(files or {}):
        rows = db.execute(text("SELECT metadata, fetched_at FROM package_lookup_cache WHERE package_id = :p"),
                          {"p": t["package"].lower()}).all()
        answers = [(m.get(t["asked"]) or {}, fetched) for m, fetched in rows if (m or {}).get(t["asked"])]
        entry = {**{k: t[k] for k in ("project", "package", "asked")},
                 "advisories": sorted({v["advisoryUrl"] for meta, _ in answers for v in meta.get("vulnerabilities") or []}),
                 "fetchedAt": min((f for _, f in answers), default=None)}
        checked.append(entry)
        where = f"{t['package']} {t['asked']} ({t['project']})"
        if not answers:
            problems.append(f"{where}: no package lookup knows this version")
        elif entry["advisories"]:
            problems.append(f"{where}: known advisories {', '.join(entry['advisories'])}")
        elif check_age and now - entry["fetchedAt"] > LOOKUP_TTL:
            stale.append(f"{where}: looked up {entry['fetchedAt']:%Y-%m-%d %H:%M} UTC, more than a day ago")
    if stale and not problems:
        # Part N: old lookups are refreshed, never refused. The caller runs discovery, which answers them again and
        # ends by preparing the conversion.
        raise LookupsStale(f"{len(stale)} package lookup(s) older than a day; the first: {stale[0]}")
    if problems:
        raise AdvisoryFound("the inputs ask for package versions that cannot be confirmed free of known advisories "
                            "today. Run discovery again (python -m app.repositories.cli discover) so the lookups are "
                            "fresh, then prepare again:\n  " + "\n  ".join(problems))
    return checked


# ---------------------------------------------------------------- prepare

class LookupsStale(RuntimeError):
    """The package lookups are older than their limit: discovery answers them again before prepare runs."""


def prepare(db, engagement_id: str, slug: str, *, baseline: str | None = None, goal: str | None = None,
            sibling_links: list[str] | None = None, canaries: list[dict] | None = None, when_run: str = "new",
            lookups_from_discovery: bool = False) -> dict:
    """Prepares the repository's conversion. `when_run`:
    - "keep" (a rescan): refreshes an unrun latest conversion in place; leaves one that has been run (its branch has
      commits beyond its inputs) and prepares nothing — a person starts the next conversion from the UI;
    - "new" (the command line): refreshes an unrun latest conversion, else starts the next one;
    - "next" (the UI's "Start the next conversion"): always a new conversion; no existing one is changed.

    The conversion starts from the commit discovery scanned (`repository.ingest_commit_sha`), so its package step,
    instructions and runbook are about the code that was analysed — never from an earlier conversion's baseline.
    `baseline` overrides it (the command line's --baseline). Refreshing an unrun conversion moves it onto that commit.
    `lookups_from_discovery`: the discovery run this prepare ends has just answered the package lookups, so their age
    is not checked again; otherwise lookups older than their limit raise LookupsStale."""
    repository = _repository(db, engagement_id, slug)
    engagement = db.get(models.Engagement, engagement_id)
    root = Path(repository.local_path)
    latest = (records(engagement_id, slug) or [None])[-1]
    base = gitops.git(root, "rev-parse", baseline or repository.ingest_commit_sha or "HEAD").strip()
    goal = goal or (latest or {}).get("goal") or DEFAULT_GOAL
    if sibling_links is None:
        sibling_links = (latest or {}).get("siblingLinks") if latest and latest.get("siblingLinks") is not None else siblings.detect(root)
    canaries = canaries if canaries is not None else (latest or {}).get("canaries") or []

    latest_unrun = latest is not None and unrun(Path(latest["worktree"]), latest["baseline"])
    refresh = latest_unrun and when_run != "next"
    if latest is not None and not latest_unrun and when_run == "keep":
        return {**latest, "action": "kept",
                "reason": f"conversion {latest['number']} has been run: a rescan does not start another (start the next "
                          "conversion from the UI)"}
    number = latest["number"] if refresh else (latest["number"] + 1 if latest else 1)
    folder = conversions_dir(engagement_id, slug) / str(number)
    worktree = folder / "wt"
    branch = f"conversion/{number}"
    if worktree.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"{worktree} would be inside the registered checkout")

    if not refresh:
        if folder.exists():
            raise RuntimeError(f"{folder} exists without a conversion record: resolve it by hand")
        if gitops.git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).strip():
            raise RuntimeError(f"branch {branch} exists without its conversion record: resolve it by hand")

    # The package step's plan. A repository the planner cannot plan (no unit test project, two target frameworks)
    # gets no package step: its package changes go to the agent as instructions, and the reason is recorded.
    try:
        plan, units = plan_packages(db, engagement_id, slug, base, branch, worktree)
        not_planned = None
    except (LookupError, ValueError) as error:
        db.rollback()
        plan, units, not_planned = None, [], f"no package step: {error}"

    # Nothing is changed unless no version the package commits or the inputs would ask for has a known advisory
    # today. The inputs are generated aside first, whole: a superset of what they will ask for.
    with tempfile.TemporaryDirectory() as tmp:
        fresh = generate(db, engagement_id, slug, Path(tmp))
    checked = check_advisories(db, fresh, targets=unit_targets(units), check_age=not lookups_from_discovery)

    planned = [u.target.get("title") for u in units]
    reuse = bool(refresh and latest["baseline"] == base and latest.get("packagesHead")
                 and latest.get("plannedPackageChanges") == planned)
    if reuse and plan is not None:
        # The package commits on the branch stand, so this plan is not run: the record keeps the plan that made them.
        db.query(models.ConversionUnit).filter_by(plan_id=plan.id).delete()
        db.delete(plan)
        db.commit()
    if refresh:
        # Not run, so nothing is lost: back to the package commits when the same changes are planned on the same
        # commit, else to the new baseline (the commit discovery scanned), and everything again.
        gitops.git(worktree, "reset", "--hard", "-q", latest["packagesHead"] if reuse else base)
        action = "refreshed"
    else:
        gitops.ensure_branch_worktree(root, worktree, branch, base)
        action = "prepared"
    siblings.link(worktree, root, sibling_links)
    if reuse:
        changes, applied, step = latest["packageChanges"], latest["applied"], latest.get("packageStep") or {}
    elif plan is None:
        changes, applied, step = [], [], {"seconds": 0, "cycles": 0, "flaky": [], "skipped": not_planned}
    else:
        units, step = run_packages(db, plan, sibling_links)
        changes, applied = [_unit_record(u) for u in units], applied_changes(units)
    packages_head = gitops.head(worktree)
    secret_references = _commit_inputs(db, engagement_id, slug, worktree, applied)

    solutions = sorted(p.name for p in worktree.glob("*.sln"))
    record = {
        "number": number, "engagement": engagement_id, "repository": slug, "baseline": base, "branch": branch,
        # Where the baseline came from: the commit discovery scanned, or the command line's --baseline.
        "baselineFrom": "the --baseline given" if baseline else "the commit discovery scanned"
                        if repository.ingest_commit_sha else "the checkout's HEAD",
        "scannedAt": repository.last_scanned_at.isoformat(timespec="seconds") if repository.last_scanned_at else None,
        # The package step's plan whose units this record reports (a refresh that reuses the commits keeps its plan).
        "planId": (latest.get("planId") if reuse else str(plan.id) if plan is not None else None),
        "folder": str(folder), "worktree": str(worktree), "runbook": str(folder / "RUNBOOK.md"),
        "head": gitops.head(worktree), "platform": instrument.platform_state(),
        "preparedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "goal": goal, "solution": solutions[0] if solutions else None, "siblingLinks": sibling_links,
        "canaries": canaries, "targetFramework": engagement.target_framework,
        # Every package version the package commits and the inputs ask for, confirmed free of known advisories.
        "packageVersionsChecked": [{**c, "fetchedAt": c["fetchedAt"].isoformat() if c["fetchedAt"] else None}
                                   for c in checked],
        # The package changes the platform applied before the agent: each unit, committed or why not.
        "plannedPackageChanges": planned, "packageChanges": changes, "applied": applied, "packagesHead": packages_head,
        # How long the package step took, its build-and-test cycles, and the tests that failed once and passed on
        # their rerun: flaky, reported, never a failure. `skipped`: why no package change was applied.
        "packageStep": step,
        "leftForAgent": left_for_agent(db, engagement_id, slug, applied, changes),
        # The inputs that name a secret value by its file, key and line instead of quoting it: a warning, never a
        # failure (app.engine.inputs.secrets).
        "secretReferences": secret_references,
    }
    _write_record(record)
    Path(record["runbook"]).write_text(render_runbook(record), encoding="utf-8", newline="\n")
    return {**record, "action": action}


def left_for_agent(db, engagement_id: str, slug: str, applied: list[dict], changes: list[dict]) -> dict:
    """What the agent's inputs still ask for: each item with its resolution and places (a package item's values),
    the package changes that did not go green, and the assisted ones (breaking upgrades)."""
    from app.engine.inputs import model_for, secrets

    model, repository = model_for(db, engagement_id, slug, applied)
    model = secrets.redact(model, Path(repository.local_path))     # a secret is named by where it is, never quoted
    return {"items": [{"item": i["id"], "resolution": (i["resolution"] or {}).get("id"), "places": len(i["occurrences"]),
                       "values": [o.get("value") for o in i["occurrences"]] if i["id"].startswith("package-") else []}
                      for i in model["items"]],
            "packageChangesNotGreen": [c for c in changes if c["automation"] == "deterministic"
                                       and c["status"] not in SATISFIED],
            "assisted": [c for c in changes if c["automation"] != "deterministic"]}


def verify_command(record: dict, branch: str | None = None, base: str | None = None) -> str:
    return (f"python -m app.engine.convert verify --engagement {record['engagement']} --repository {record['repository']} "
            f"--branch {branch or record['branch']}" + (f" --base {base[:8]}" if base else ""))


def render_runbook(record: dict) -> str:
    template = string.Template(RUNBOOK_TEMPLATE.read_text(encoding="utf-8"))
    return template.substitute(
        repository=record["repository"], branch=record["branch"], worktree=record["worktree"],
        solution=record["solution"] or "<solution>.sln", base=record["baseline"][:8],
        platform=instrument.describe(record["platform"]),
        opening=opening_message(record["goal"], record["solution"]),
        target=framework_name(record["targetFramework"]), stuck_minutes=STUCK_MINUTES,
        verify_command=verify_command(record),
        prepare_command=f"python -m app.engine.convert prepare --engagement {record['engagement']} "
                        f"--repository {record['repository']}")


# ---------------------------------------------------------------- approved test removals

def approvals_path(engagement_id: str, slug: str) -> Path:
    return planner.RUNS / engagement_id / slug / "approvals.json"


def approvals_for(engagement_id: str, slug: str, branch: str) -> list[dict]:
    path = approvals_path(engagement_id, slug)
    return (json.loads(path.read_text(encoding="utf-8")).get(branch) or []) if path.exists() else []


def approve_removal(engagement_id: str, slug: str, branch: str, tests: list[str], reason: str, by: str) -> list[dict]:
    """A person approves the removal of tests (a test's name, or a test file's path) from a branch, with a reason
    (Part N). The verifier records each approval and does not count the removal against the verdict; an unapproved
    removal still fails it. Engagement data, under RUNS_DIR."""
    if not reason.strip() or not by.strip():
        raise ValueError("an approval needs a reason and the name of the person approving")
    path = approvals_path(engagement_id, slug)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    kept = [a for a in data.get(branch, []) if a["test"] not in tests]
    data[branch] = kept + [{"test": t, "reason": reason.strip(), "approvedBy": by.strip(), "at": at} for t in tests]
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return data[branch]


# ---------------------------------------------------------------- verify

def verify(db, engagement_id: str, slug: str, branch: str, *, base: str | None = None, label: str | None = None,
           refresh_baseline: bool = False) -> dict:
    from app.engine import verifier

    known = records(engagement_id, slug)
    own = next((r for r in reversed(known) if r["branch"] == branch), None)
    facts = own or (known[-1] if known else {})
    base = base or (own or {}).get("baseline")
    if not base:
        raise RuntimeError(f"{branch} is not a prepared conversion of {slug}: give its baseline with --base")
    # The repository's facts, as the verifier's configuration: no experiment, no frozen package lookups.
    config = {"sibling_links": facts.get("siblingLinks") or [], "canaries": facts.get("canaries") or [],
              # Package upgrades against the versions the branch's inputs asked for, not today's newest release.
              "package_targets_from_inputs": True,
              # Removed tests a person approved, with a reason: recorded, not counted (approve_removal).
              "approved_test_removals": approvals_for(engagement_id, slug, branch)}
    return verifier.verify(db, engagement_id=engagement_id, slug=slug, base=base, ref=branch,
                           label=label or branch.replace("/", "-"), config=config, refresh_baseline=refresh_baseline)


# ---------------------------------------------------------------- the command line

def main(argv: list[str] | None = None) -> int:
    from app.db import SessionLocal
    from app.engine import verifier

    parser = argparse.ArgumentParser(prog="python -m app.engine.convert", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="a branch and worktree from the baseline, with the inputs and RUNBOOK.md")
    p.add_argument("--engagement", required=True)
    p.add_argument("--repository", required=True, help="repository slug")
    p.add_argument("--baseline", help="the commit to convert (default: the previous conversion's, else the checkout's HEAD)")
    p.add_argument("--goal", help="the first line of the opening message (default: the previous conversion's)")
    p.add_argument("--sibling-link", action="append", dest="sibling_links",
                   help="a folder beside the checkout the repository reaches by relative path (repeatable)")
    p.add_argument("--canary-file")
    p.add_argument("--canary-find")
    p.add_argument("--canary-replace")
    p.add_argument("--canary-why")
    v = sub.add_parser("verify", help="the verifier on a branch against its baseline")
    v.add_argument("--engagement", required=True)
    v.add_argument("--repository", required=True, help="repository slug")
    v.add_argument("--branch", required=True)
    v.add_argument("--base", help="the baseline commit (default: the conversion record's)")
    v.add_argument("--label", help="names the verification folder (default: the branch, '/' as '-')")
    v.add_argument("--refresh-baseline", action="store_true", help="re-run discovery on the base commit")
    a = sub.add_parser("approve-removal", help="approve, with a reason, the removal of tests from a branch")
    a.add_argument("--engagement", required=True)
    a.add_argument("--repository", required=True, help="repository slug")
    a.add_argument("--branch", required=True)
    a.add_argument("--test", action="append", required=True, dest="tests", help="a test's name or a test file (repeatable)")
    a.add_argument("--reason", required=True)
    a.add_argument("--by", required=True, help="the person approving")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.command == "prepare":
            canary = [args.canary_file, args.canary_find, args.canary_replace, args.canary_why]
            if any(canary) and not all(canary):
                parser.error("a canary needs all four: --canary-file, --canary-find, --canary-replace, --canary-why")
            canaries = ([{"file": canary[0], "find": canary[1], "replace": canary[2], "why": canary[3]}]
                        if all(canary) else None)
            options = dict(baseline=args.baseline, goal=args.goal, sibling_links=args.sibling_links, canaries=canaries)
            try:
                r = prepare(db, args.engagement, args.repository, **options)
            except LookupsStale as stale:
                # Part N: refreshed, never refused. Discovery answers the lookups again (its own prepare step off,
                # so these options are kept), then prepare runs on what it answered.
                from app.repositories import cli as repositories_cli

                print(f"{stale}: running discovery to refresh them")
                execution = repositories_cli.discover(db, _repository(db, args.engagement, args.repository),
                                                      prepare_conversion=False)
                if execution.batch_status != "COMPLETED":
                    raise SystemExit(f"discovery ended {execution.batch_status}: nothing prepared")
                r = prepare(db, args.engagement, args.repository, lookups_from_discovery=True, **options)
            print(f"{r['action']} {args.repository} {r['branch']} at {r['head'][:8]} (baseline {r['baseline'][:8]})")
            print(f"worktree: {r['worktree']}")
            print(f"runbook:  {r['runbook']}")
            for c in r["packageChanges"]:
                print(f"  package {c['sequence']:>3} {c['status']:<14} {(c['commit'] or '')[:8]:<8} {c['title']}"
                      + (f"  ({c['reason']})" if c["status"] not in SATISFIED and c["reason"] else ""))
            step = r.get("packageStep") or {}
            print(f"package step: {step.get('seconds', 0)} s, {step.get('cycles', 0)} build-and-test cycle(s)")
            for f in step.get("flaky") or []:
                print(f"  flaky: {f['test']} ({f['project']}) failed once in {f['where']} and passed on its rerun")
            left = r["leftForAgent"]
            print(f"left for the agent: {len(left['items'])} instruction item(s); "
                  f"{len(left['packageChangesNotGreen'])} package change(s) not green; {len(left['assisted'])} assisted")
            checked = r["packageVersionsChecked"]
            oldest = min((c["fetchedAt"] for c in checked if c["fetchedAt"]), default=None)
            print(f"package versions asked for: {len(checked)}, none with a known advisory"
                  + (f" (lookups from {oldest[:16]} UTC or later)" if oldest else ""))
        elif args.command == "approve-removal":
            for x in approve_removal(args.engagement, args.repository, args.branch, args.tests, args.reason, args.by):
                print(f"approved: {x['test']} ({x['reason']}; {x['approvedBy']}, {x['at']})")
        else:
            report = verify(db, args.engagement, args.repository, args.branch, base=args.base, label=args.label,
                            refresh_baseline=args.refresh_baseline)
            print(f"{report['label']}: {report['verdict']}")
            for reason in report["reasons"]:
                print(f"  - {reason}")
            print(f"  {verifier.RUNS / args.engagement / args.repository / 'verification' / report['label'] / 'VERIFICATION.md'}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
