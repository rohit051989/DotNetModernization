"""One conversion at a time (36-COPILOT-ENHANCED-CONVERSION Part N): prepare a branch for an engine, then verify it.

    python -m app.engine.convert prepare --engagement test-client-a --repository accountsapi-net10
        [--baseline e89bc6a] [--goal "..."] [--sibling-link EnterprisePackages]
        [--canary-file F --canary-find X --canary-replace Y --canary-why W]
    python -m app.engine.convert verify --engagement test-client-a --repository accountsapi-net10 --branch conversion/1
        [--base e89bc6a] [--label L] [--refresh-baseline]

`prepare` makes the next conversion of a repository: a branch `conversion/<n>` from its baseline, in a worktree at
`<RUNS_DIR>/<engagement>/<repository>/conversions/<n>/wt`. It generates the engine inputs into it and commits them as
the platform, then writes `RUNBOOK.md` and `conversion.json` beside the worktree. It records the platform commit it
ran at and pins nothing. There are no arms or generations. When the latest conversion has not been run (its branch is
still the baseline plus the inputs commit, and its worktree is clean), preparing again refreshes it in place.
Otherwise preparing again makes the next one. So fixing an instruction and preparing again needs nothing more.

A conversion's baseline, goal, sibling links and canaries default to the previous conversion's, so they are given
once per repository.

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
from app.engine.inputs import MANIFEST, generate
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
        "- Edit files with your file-editing tools, not through terminal commands.",
        "- Keep every terminal command on a single line.",
        "- Work on the current branch and do not create another branch. Commit after each change, with a message "
        "naming the change.",
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


def _write_record(record: dict) -> None:
    path = Path(record["folder"]) / RECORD
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def unrun(worktree: Path, base: str) -> bool:
    """True when nothing has happened in the conversion's worktree since it was prepared: it is clean, and its branch
    is the baseline, or the baseline plus the platform's inputs commit."""
    if not worktree.exists() or gitops.git(worktree, "status", "--porcelain").strip():
        return False
    head = gitops.head(worktree)
    if head == base:
        return True
    parents = gitops.git(worktree, "rev-list", "--parents", "-n", "1", "HEAD").split()
    return parents[1:] == [base] and gitops.git(worktree, "log", "-1", "--format=%s").strip() == INPUTS_COMMIT


def _repository(db, engagement_id: str, slug: str) -> models.Repository:
    return (db.query(models.Repository).filter_by(engagement_id=engagement_id, slug=slug)
            .filter(models.Repository.deleted_at.is_(None)).one())


def _commit_inputs(db, engagement_id: str, slug: str, worktree: Path) -> None:
    from app.engine import paths
    from app.engine.inputs import selfcontained

    generate(db, engagement_id, slug, worktree)
    gitops.platform_commit(worktree, INPUTS_COMMIT, vocabulary=selfcontained.vocabulary(db),
                           paths=[p.rstrip("/") for p in paths.GENERATED_INPUT_PATHS if (worktree / p.rstrip("/")).exists()])


def _inputs_current(db, engagement_id: str, slug: str, worktree: Path) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        fresh = generate(db, engagement_id, slug, Path(tmp))[MANIFEST]
    shown = gitops.git(worktree, "show", f"HEAD:{MANIFEST}", check=False)
    return bool(shown.strip()) and fresh.strip() == shown.strip()


# ---------------------------------------------------------------- prepare

def prepare(db, engagement_id: str, slug: str, *, baseline: str | None = None, goal: str | None = None,
            sibling_links: list[str] | None = None, canaries: list[dict] | None = None) -> dict:
    repository = _repository(db, engagement_id, slug)
    engagement = db.get(models.Engagement, engagement_id)
    root = Path(repository.local_path)
    latest = (records(engagement_id, slug) or [None])[-1]
    base = gitops.git(root, "rev-parse", baseline or (latest or {}).get("baseline") or "HEAD").strip()
    goal = goal or (latest or {}).get("goal") or DEFAULT_GOAL
    sibling_links = sibling_links if sibling_links is not None else (latest or {}).get("siblingLinks") or []
    canaries = canaries if canaries is not None else (latest or {}).get("canaries") or []

    refresh = latest is not None and latest["baseline"] == base and unrun(Path(latest["worktree"]), base)
    number = latest["number"] if refresh else (latest["number"] + 1 if latest else 1)
    folder = conversions_dir(engagement_id, slug) / str(number)
    worktree = folder / "wt"
    branch = f"conversion/{number}"
    if worktree.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"{worktree} would be inside the registered checkout")

    if refresh:
        if not _inputs_current(db, engagement_id, slug, worktree):
            # Not run, so nothing is lost: back to the baseline, then the inputs as they are now.
            gitops.git(worktree, "reset", "--hard", "-q", base)
            _commit_inputs(db, engagement_id, slug, worktree)
        action = "refreshed"
    else:
        if folder.exists():
            raise RuntimeError(f"{folder} exists without a conversion record: resolve it by hand")
        if gitops.git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).strip():
            raise RuntimeError(f"branch {branch} exists without its conversion record: resolve it by hand")
        gitops.ensure_branch_worktree(root, worktree, branch, base)
        _commit_inputs(db, engagement_id, slug, worktree)
        action = "prepared"
    siblings.link(worktree, root, sibling_links)

    solutions = sorted(p.name for p in worktree.glob("*.sln"))
    record = {
        "number": number, "engagement": engagement_id, "repository": slug, "baseline": base, "branch": branch,
        "folder": str(folder), "worktree": str(worktree), "runbook": str(folder / "RUNBOOK.md"),
        "head": gitops.head(worktree), "platform": instrument.platform_state(),
        "preparedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "goal": goal, "solution": solutions[0] if solutions else None, "siblingLinks": sibling_links,
        "canaries": canaries, "targetFramework": engagement.target_framework,
    }
    _write_record(record)
    Path(record["runbook"]).write_text(render_runbook(record), encoding="utf-8", newline="\n")
    return {**record, "action": action}


def verify_command(record: dict, branch: str | None = None, base: str | None = None) -> str:
    return (f"python -m app.engine.convert verify --engagement {record['engagement']} --repository {record['repository']} "
            f"--branch {branch or record['branch']}" + (f" --base {base[:8]}" if base else ""))


def render_runbook(record: dict) -> str:
    template = string.Template(RUNBOOK_TEMPLATE.read_text(encoding="utf-8"))
    return template.substitute(
        repository=record["repository"], branch=record["branch"], worktree=record["worktree"],
        solution=record["solution"] or "<solution>.sln", base=record["baseline"][:8],
        platform=record["platform"]["commit"][:12] + (" (with uncommitted changes)" if record["platform"]["dirty"] else ""),
        opening=opening_message(record["goal"], record["solution"]),
        target=framework_name(record["targetFramework"]), stuck_minutes=STUCK_MINUTES,
        verify_command=verify_command(record),
        prepare_command=f"python -m app.engine.convert prepare --engagement {record['engagement']} "
                        f"--repository {record['repository']}")


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
              "package_targets_from_inputs": True}
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
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.command == "prepare":
            canary = [args.canary_file, args.canary_find, args.canary_replace, args.canary_why]
            if any(canary) and not all(canary):
                parser.error("a canary needs all four: --canary-file, --canary-find, --canary-replace, --canary-why")
            canaries = ([{"file": canary[0], "find": canary[1], "replace": canary[2], "why": canary[3]}]
                        if all(canary) else None)
            r = prepare(db, args.engagement, args.repository, baseline=args.baseline, goal=args.goal,
                        sibling_links=args.sibling_links, canaries=canaries)
            print(f"{r['action']} {args.repository} {r['branch']} at {r['head'][:8]} (baseline {r['baseline'][:8]})")
            print(f"worktree: {r['worktree']}")
            print(f"runbook:  {r['runbook']}")
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
