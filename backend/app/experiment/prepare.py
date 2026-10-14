"""Prepare one Copilot experiment (36-COPILOT-ENHANCED-CONVERSION Part F). Nothing here runs an engine.

    python -m app.experiment.prepare --config <RUNS_DIR>\\<engagement>\\experiments\\<name>\\experiment.yaml

For every run of every Copilot arm: a branch `experiment/v<generation>/arm{a}-run{n}` from the baseline commit, in its
own worktree under `<RUNS_DIR>/<engagement>/<repository>/experiment-v<generation>/`. The registered checkout is never
touched. Arm 2's branches get the generated inputs (app.engine.inputs) as one commit by the platform's identity; arm
1's stay at the baseline. Then the operator runbook, RUNBOOK.md beside the configuration, rendered by this module:
every step is worded identically for both arms except where arm 2 uses its enhancement — its inputs, the assessment
addendum and the decision sheet's answers at the upgrade-options stage. Arm 1 accepts the engine's own
recommendations there. The commit strategy, one commit per task, is the same in both: it is measurement.

Safe to run again, and never changes an existing worktree: an arm 1 branch must still be at the baseline, an arm 2
branch must still be the baseline plus its inputs commit with the same inputs. Inputs that changed need a new
generation (`generation:` in experiment.yaml), which makes new branches and worktrees beside the old ones.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import yaml

from app import models
from app.conversion import gitops, planner
from app.engine import paths, siblings
from app.engine.inputs import MANIFEST, generate
from app.engine.inputs.collect import collect
from app.experiment import instrument
from app.engine.inputs.render import upgrade_options, without_guidance

# Self-contained like every platform commit (gitops.platform_commit): no platform document or vocabulary.
INPUTS_COMMIT = "Add generated upgrade inputs for GitHub Copilot (do not edit)"
DEFAULT_GOAL = "Upgrade this solution to .NET 10 and make the application ready to run on OpenShift."


def generation(config: dict) -> int:
    return int(config.get("generation") or 1)


def copilot_runs(config: dict) -> list[dict]:
    """Every Copilot run, interleaved arm by arm (arm1-run1, arm2-run1, arm1-run2, ...) so that time of day and
    service changes fall on both arms alike. `label` names the run's verification folder within its repository;
    `run_label` names its engine run record, unique across the engagement."""
    g = generation(config)
    arms = [a for a in config["arms"] if "ref" not in a]
    most = max(a["runs"] for a in arms)
    out = []
    for n in range(1, most + 1):
        for a in arms:
            if n > a["runs"]:
                continue
            run = f"arm{a['arm']}-run{n}"
            label = run if g == 1 else f"v{g}-{run}"
            out.append({"arm": a["arm"], "run": n, "enhancement": a["enhancement"], "name": a["name"], "label": label,
                        "run_label": f"{config.get('repository', '')}-{label}",
                        "branch": f"experiment/{run}" if g == 1 else f"experiment/v{g}/{run}",
                        "folder": "experiment" if g == 1 else f"experiment-v{g}", "worktree_name": run})
    return out


def _commit_inputs(db, config: dict, worktree: Path) -> None:
    from app.engine.inputs import selfcontained

    generate(db, config["engagement"], config["repository"], worktree)
    gitops.platform_commit(worktree, INPUTS_COMMIT, vocabulary=selfcontained.vocabulary(db),
                           paths=[p.rstrip("/") for p in paths.GENERATED_INPUT_PATHS if (worktree / p.rstrip("/")).exists()])


def _arm2(db, config: dict, r: dict, worktree: Path, base: str, created: bool) -> None:
    # A worktree still exactly the baseline, nothing changed in it, is a preparation that stopped before its inputs
    # were committed (the secret check refused them): finishing it changes no run.
    unfinished = gitops.head(worktree) == base and not gitops.git(worktree, "status", "--porcelain").strip()
    if created or unfinished:
        _commit_inputs(db, config, worktree)
        return
    parents = gitops.git(worktree, "rev-list", "--parents", "-n", "1", "HEAD").split()
    if parents[1:] != [base] or gitops.git(worktree, "log", "-1", "--format=%s").strip() != INPUTS_COMMIT:
        raise RuntimeError(f"{r['branch']} is not the baseline plus the platform's inputs commit: it has been run")
    with tempfile.TemporaryDirectory() as tmp:
        fresh = generate(db, config["engagement"], config["repository"], Path(tmp))[MANIFEST]
    if fresh.strip() != gitops.git(worktree, "show", f"HEAD:{MANIFEST}").strip():
        raise RuntimeError(f"{r['branch']}'s inputs are out of date. Existing worktrees are never changed: "
                           f"set generation: {generation(config) + 1} in experiment.yaml for new branches and worktrees")


def prepare(db, config: dict) -> dict:
    # The instrument is pinned: the platform must be clean and at the commit experiment.yaml names.
    if not config.get("platform_commit"):
        raise RuntimeError("experiment.yaml records no platform_commit: create it again with python -m app.experiment.create")
    instrument.require_clean(config["platform_commit"])
    repository = (db.query(models.Repository).filter_by(engagement_id=config["engagement"], slug=config["repository"])
                  .filter(models.Repository.deleted_at.is_(None)).one())
    root = Path(repository.local_path)
    base = gitops.git(root, "rev-parse", config["baseline_commit"]).strip()
    runs = copilot_runs(config)
    manifests = set()
    for r in runs:
        worktree = planner.RUNS / config["engagement"] / config["repository"] / r["folder"] / r["worktree_name"]
        if worktree.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"{worktree} would be inside the registered checkout")
        exists = gitops.git(root, "rev-parse", "--verify", "--quiet", r["branch"], check=False).strip()
        if exists and not worktree.exists():
            raise RuntimeError(f"branch {r['branch']} exists without its worktree {worktree}: resolve by hand")
        created = not worktree.exists()
        gitops.ensure_branch_worktree(root, worktree, r["branch"], base)
        siblings.link(worktree, root, config.get("sibling_links") or [])
        if r["enhancement"]:
            _arm2(db, config, r, worktree, base, created)
            manifests.add(gitops.git(worktree, "rev-parse", f"HEAD:{MANIFEST}").strip())
        elif gitops.head(worktree) != base:
            raise RuntimeError(f"{r['branch']} has moved from the baseline {base[:8]}: it has been run already")
        r.update(worktree=str(worktree), head=gitops.head(worktree))
    if len(manifests) > 1:
        raise RuntimeError("arm 2's runs were given different inputs")
    sln = sorted(root.glob("*.sln"))
    return {"config": config, "runs": runs, "base": base, "solution": sln[0].name if sln else "<solution>.sln",
            **_from_inputs(collect(db, repository))}


def _from_inputs(model: dict) -> dict:
    """What the runbook takes from the inputs' model: the upgrade-options answers, and the detected changes without
    engine-facing guidance (listed for the operator, never in the branch)."""
    return {"options": upgrade_options(model), "missing": without_guidance(model)}


def inspect(db, config: dict) -> dict:
    """What prepare would return, read without changing anything: no branch, worktree, junction or commit is made.
    Every worktree must already exist. For --render-only."""
    repository = (db.query(models.Repository).filter_by(engagement_id=config["engagement"], slug=config["repository"])
                  .filter(models.Repository.deleted_at.is_(None)).one())
    root = Path(repository.local_path)
    base = gitops.git(root, "rev-parse", config["baseline_commit"]).strip()
    runs = copilot_runs(config)
    for r in runs:
        worktree = planner.RUNS / config["engagement"] / config["repository"] / r["folder"] / r["worktree_name"]
        if not worktree.exists():
            raise RuntimeError(f"{worktree} does not exist: run prepare without --render-only")
        r.update(worktree=str(worktree), head=gitops.head(worktree))
    sln = sorted(root.glob("*.sln"))
    return {"config": config, "runs": runs, "base": base, "solution": sln[0].name if sln else "<solution>.sln",
            **_from_inputs(collect(db, repository))}


# ---------------------------------------------------------------- the runbook

# The opening message carries everything the engine needs (36-COPILOT-ENHANCED-CONVERSION Part M): the pilot showed
# the assessment, options and planning stages may never appear (a goal with no framework change skips them).
# OPENING_RULES are identical in both arms; arm 2 adds ENHANCEMENT_MESSAGE.
OPENING_RULES = ("Edit files with your file-editing tools, not through terminal commands. Keep every terminal command on a "
                 "single line. Work on the current branch and do not create another branch. Commit after each change, with "
                 "a message naming the change.")
ENHANCEMENT_MESSAGE = ("Use the custom upgrade instructions in .github/upgrades/skills and the skills in .github/skills, and "
                       "follow .github/copilot-instructions.md. Read .github/platform-inputs/assessment-addendum.md and "
                       ".github/platform-inputs/decision-sheet.md, and follow them.")
ARM1_OPTIONS = "Use your recommended options."
STUCK_MINUTES = 5


def opening_message(goal: str, enhancement: bool) -> str:
    """The message that starts a run, word for word: the goal, the rules both arms share, and for arm 2 its inputs."""
    return " ".join([goal.strip(), OPENING_RULES] + ([ENHANCEMENT_MESSAGE] if enhancement else []))


def _common(stop: dict) -> list[str]:
    return [
        "## Once, before the first run", "",
        "1. **Tools.** Visual Studio 2026 (or 2022 17.14.17 or later) with the **.NET desktop development** workload and its",
        "   optional components **GitHub Copilot** and **GitHub Copilot app modernization**. Turn off Visual Studio's",
        "   automatic updates until the last run is done: every run uses the same versions. Record them from",
        "   Help > About Microsoft Visual Studio (the Visual Studio version, and the GitHub Copilot and app modernization",
        "   component versions).",
        "2. **The model.** One model for every run, the one named in `experiment.yaml` (`engine.model`).",
        "   If it is not set there, stop: the model is a decision, not the operator's choice on the day.",
        "3. **No other customization.** Both arms must see the same Copilot configuration:",
        "   - `%UserProfile%\\.copilot\\skills\\` does not exist or is empty;",
        "   - Tools > Options > GitHub > Copilot: **custom instructions from .github/copilot-instructions.md are enabled**",
        "     (arm 1's branches have no such file; arm 2's do) and no other instruction file or prompt file is configured;",
        "   - no Copilot memory or saved preference carries over from an earlier session (start each run in a new chat thread).",
        "4. **The platform's database is reachable**, as `backend\\.env` configures it. The platform backend does not need to run.",
        "5. **Engine allowlist.** `python -m app.engine.allowlist show --engagement <engagement>` lists `github-copilot` under",
        "   the company's organisation. If not, stop: setting it is the engagement's decision.", "",
        "## Every run", "",
        "The table above gives each run's `<run>` (its record label), `<label>` (its verification label), `<branch>` and",
        "`<worktree>`. Commands run in PowerShell from the platform repository:", "",
        "```powershell", "cd backend; .venv\\Scripts\\Activate.ps1", "```", "",
        "### 1. Check the signed-in account — STOP if it is not the company account", "",
        "In Visual Studio: File > Account Settings. The GitHub account signed in, and the Copilot subscription shown by the",
        "Copilot status icon (top right), must be the **company-managed account**, with Copilot provided by the **company's",
        "organisation**. If it is a personal account, a personal subscription, or any organisation other than the company's,",
        "**stop here**. Do not run the engine. Do not sign in again on the operator's behalf: the person running it signs in",
        "with their own company account in their own tool.", "",
        "Note exactly as Visual Studio shows them: the account name, the organisation, the model selected in the Copilot",
        "chat model picker, and the GitHub Copilot app modernization version.", "",
        "### 2. Record the start — STOP if the platform refuses", "",
        "Use the `runs start` command below. It refuses unless the engagement's engine allowlist admits GitHub Copilot under",
        "the organisation you entered. If it prints `STOP.`, stop. It also records a hash of every input file in the worktree",
        "and of this runbook.", "",
        "### 3. Open the run's worktree", "",
        "Open `<worktree>\\<solution>` in Visual Studio — the worktree, never the registered checkout. Confirm the Git",
        "branch shown is `<branch>`. Open a **new** Copilot chat thread and select the model from step 1. Start a timer.", "",
        "### 4. Start", "",
        "Right-click the solution in Solution Explorer > **Modernize**. Send the opening message for the run's arm, exactly",
        "as written in **Opening messages** above: everything the engine needs is in it. Do not add to it.", "",
        "### 5. Answer the pre-initialization questions — the same in both arms", "",
        "| If it asks | Reply |", "|---|---|",
        "| Target framework | `.NET 10` |",
        "| Branch, Git strategy, commits | `Work on the current branch and do not create another branch. Commit after each change.` |",
        "| Automatic or guided flow | `Guided.` |",
        "| Whether to continue an existing upgrade or start fresh | stop: the worktree is not clean; report it |", "",
        "One commit per change is how the verifier attributes each change; it is the same for both arms.", "",
        "### 6. If the assessment, options and planning stages appear", "",
        "The run does not depend on them: a goal with no framework change may skip them entirely. If they appear, as they",
        "may for a framework upgrade:", "",
        "- **Assessment**: let it finish. Do not edit `assessment.md`.",
        f"- **Upgrade options**: **ARM 1** replies `{ARM1_OPTIONS}` to the options the agent presents, whatever they are.",
        "  **ARM 2 ONLY** answers each option with the decision sheet's answer, in the table above (also in",
        f"  `.github/platform-inputs/decision-sheet.md`); for an option not in that table, reply `{ARM1_OPTIONS}` and record",
        "  it (step 9).",
        "- **Planning and execution**: when it offers planning, send `Proceed to planning.` When `plan.md` is written, send",
        "  `Proceed to execution.` Do not edit `plan.md`, `tasks.md` or any task file.", "",
        "### 7. While it works — the same in both arms", "",
        "When the agent asks a question:", "",
        "| It asks | Reply |", "|---|---|",
        "| To choose between options | `Continue with your recommended option.` |",
        "| For a credential, a secret, a sign-in, an installation or a change outside the repository | `No. Continue without it.` |",
        "| For a value it does not have (host name, time zone, path) | `Do not invent it. Read it from configuration by name and continue.` |",
        "| Whether to continue after a pause | `Continue.` |", "",
        f"**Protocol: a stuck terminal.** If a terminal shows `>>` (PowerShell waiting for the rest of a command), or a command",
        f"has run {STUCK_MINUTES} minutes with no output, press **Ctrl+C** in that terminal. This is part of the protocol, the same in",
        "both arms: record it with the `runs protocol` command below, never as an intervention.", "",
        "### 8. When to stop", "",
        "Stop the run, and do not resume it, when the first of these happens:", "",
        "- the agent reports the work complete;",
        f"- {stop['max_elapsed_minutes']} minutes have passed since step 3;",
        f"- the agent has attempted one change {stop['max_attempts_on_one_task']} times without completing it;",
        "- the agent asks for a credential or a machine change a second time;",
        "- the agent works outside `<worktree>`, or on a branch other than `<branch>`.", "",
        "Then send `Commit all remaining changes on the current branch.` and wait until it has.", "",
        "### 9. Record interventions as they happen", "",
        "Every message you send that is not worded in this runbook, every manual edit and every option not in the decision",
        "sheet: use the `runs intervene` command below. A protocol step (step 7) is not an intervention.", "",
        "### 10. Finish the record", "",
        "Save the chat transcript (copy the whole Copilot chat thread into `<worktree>-transcript.md`, beside the worktree).",
        "It is a record of the run, never evidence. Note the elapsed time and the premium requests the run used (the",
        "Copilot usage figure before step 4 and after step 8). Then use the `runs finish` command below.", "",
        "### 11. Verify", "",
        "Use the `verifier` command below. It is independent of the engine; nothing it reported counts.", "",
    ]



def render_runbook(prepared: dict, config_path: Path) -> str:
    c, runs, base = prepared["config"], prepared["runs"], prepared["base"]
    eng, slug = c["engagement"], c["repository"]
    folder = config_path.parent
    goal = c.get("goal") or DEFAULT_GOAL
    out = [f"# Operator runbook — {c.get('title', slug)}", "",
           "> Generated by `python -m app.experiment.prepare` from `experiment.yaml` beside this file. Do not edit: change",
           "> the configuration and run it again. Spec: `docs/36-COPILOT-ENHANCED-CONVERSION.md` Part F.", "",
           f"Subject `{slug}` from baseline `{base[:8]}`, engagement `{eng}`, generation {generation(c)}. "
           f"Solution `{prepared['solution']}`.", "",
           f"Platform commit `{c['platform_commit']}`: the instrument every run is verified with. Verify each run at "
           "this commit; the report flags a run verified at any other.", ""]
    if c.get("sequence_note"):
        out += [c["sequence_note"].strip(), ""]
    out += ["The arms differ in one thing, the platform's enhancement. **Every step is worded identically for both arms,",
            "except the lines marked ARM 1 and ARM 2 ONLY**: arm 2 gets its inputs, the assessment addendum and the decision",
            "sheet's answers; arm 1 takes the engine's own recommendations. Read each message exactly as written; do not add",
            "to it, rephrase it or explain it. Anything you type that is not in this runbook is an *intervention* and is",
            "recorded. The experiment runs interactively; a person drives the engine. Nothing here asks for, stores or types",
            "a credential.", "",
            f"`<goal>`: **{goal}**", "",
            "## Runs, in this order", "",
            "Interleaved so time of day and service changes fall on both arms alike.", "",
            "| # | `<run>` | `<label>` | Arm | `<branch>` | `<worktree>` |", "|---|---|---|---|---|---|"]
    for i, r in enumerate(runs, 1):
        out.append(f"| {i} | `{r['run_label']}` | `{r['label']}` | {r['arm']} — {r['name']} | `{r['branch']}` | `{r['worktree']}` |")
    arm3 = next((a for a in c["arms"] if "ref" in a), None)
    if arm3:
        out += ["", f"Arm 3 — {arm3['name']}: the existing branch `{arm3['ref']}`. Not run by a person; verified only "
                f"(CALIBRATION.md). It covers the {arm3['scope']}, not OpenShift readiness, and is compared on that dimension alone."]
    missing = prepared.get("missing") or []
    out += ["", "## Changes without engine-facing guidance", ""]
    if missing:
        out += ["Arm 2's inputs carry no conversion guidance for these. Where the approach has none, its places are listed "
                "in the decision sheet to leave unchanged; where only the change's own explanation is missing, the "
                "instruction carries the approach's steps alone.", "",
                "| Item | Resolution | Missing |", "|---|---|---|"]
        out += [f"| `{m['item']}` | `{m['resolution'] or '-'}` | {m['missing']} guidance |" for m in missing]
    else:
        out.append("None: every detected change has engine-facing guidance.")
    out += ["", "## Opening messages", "",
            "Step 4 sends one of these, word for word. Both arms share every sentence but the last; arm 2 adds its inputs.", "",
            "**ARM 1**:", "", "```text", opening_message(goal, enhancement=False), "```", "",
            "**ARM 2**:", "", "```text", opening_message(goal, enhancement=True), "```"]
    out += ["", "**ARM 2 ONLY** — answers at the upgrade-options stage, if it appears (the decision sheet):", "",
            "| Option | Answer | Status |", "|---|---|---|"]
    for o in prepared["options"]:
        out.append(f"| {o['question']} | `{o['answer']}` | {'presumptive' if o['presumptive'] else 'decided'} |")
    plan = c.get("baseline_plan")
    config_arg = str(config_path)
    out += ["", "Commands (replace `<run>`, `<label>`, `<worktree>`, `<branch>` from the table):", "", "```powershell",
            f"python -m app.engine.runs start --engagement {eng} --repository {slug} --label <run> --worktree <worktree> "
            f"--base {base[:8]} --provider {c['engine']['provider']} --organisation <organisation> --identity <account> "
            f"--model \"<model>\" --engine-version \"<app modernization version>\" --host \"<Visual Studio version>\" "
            f"--runbook \"{folder / 'RUNBOOK.md'}\"",
            f"python -m app.engine.runs intervene --engagement {eng} --label <run> --stage <assessment|options|planning|execution> --what \"<what and why>\"",
            f"python -m app.engine.runs protocol --engagement {eng} --label <run> --action ctrl-c --why \"<'>>' prompt, or {STUCK_MINUTES} minutes with no output>\"",
            f"python -m app.engine.runs finish --engagement {eng} --label <run> --outcome <completed|stopped|abandoned> "
            "--elapsed-minutes <n> --premium-requests <n> --transcript <worktree>-transcript.md --notes \"<which stop rule ended it>\"",
            f"python -m app.engine.verifier --engagement {eng} --repository {slug} --base {base[:8]} --ref <branch> --label <label> "
            f"--config \"{config_arg}\"" + (f" --baseline-plan {plan}" if plan else ""),
            "```", "",
            "After the last run:", "", "```powershell", f"python -m app.experiment.report --config \"{config_arg}\"", "```", ""]
    out += _common(c["stop"])
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(prog="python -m app.experiment.prepare", description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", required=True, type=Path, help="the experiment's experiment.yaml")
    parser.add_argument("--render-only", action="store_true",
                        help="write RUNBOOK.md from the existing worktrees, changing nothing else")
    parser.add_argument("--out", type=Path, help="write RUNBOOK.md into this folder instead (with --render-only)")
    args = parser.parse_args(argv)
    if args.out and not args.render_only:
        parser.error("--out needs --render-only: preparing changes worktrees, rendering does not")
    config_path = args.config.resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    db = SessionLocal()
    try:
        prepared = inspect(db, config) if args.render_only else prepare(db, config)
    finally:
        db.close()
    runbook = (args.out.resolve() if args.out else config_path.parent) / "RUNBOOK.md"
    runbook.parent.mkdir(parents=True, exist_ok=True)
    runbook.write_text(render_runbook(prepared, config_path), encoding="utf-8", newline="\n")
    for r in prepared["runs"]:
        print(f"{config['repository']} {r['label']}: {r['branch']} at {r['head'][:8]} in {r['worktree']}")
    print(f"runbook: {runbook}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
