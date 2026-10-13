"""Prepare the Copilot experiment (36-COPILOT-ENHANCED-CONVERSION Part F). Nothing here runs an engine.

    python -m app.experiment.prepare --config ..\\experiments\\copilot-eshoponweb\\experiment.yaml

For every run of every Copilot arm: a branch `experiment/arm{a}-run{n}` from the baseline commit, in its own
worktree under `runs/<engagement>/<repository>/experiment/`. The registered checkout is never touched. Arm 2's
branches get the generated inputs (app.engine.inputs) as one commit by the platform's identity; arm 1's stay
at the baseline. Then the operator runbook is written beside the configuration, `RUNBOOK.md`, from one
template, so every step is worded identically for both arms except where arm 2 references its inputs.

Safe to run again: an existing branch is checked, never recreated or moved.
"""
import argparse
import sys
from pathlib import Path

import yaml

from app import models
from app.conversion import gitops, planner
from app.engine import paths
from app.engine.inputs import generate
from app.engine.inputs.render import upgrade_options

INPUTS_COMMIT = "Platform inputs for GitHub Copilot upgrade (generated, 36-COPILOT-ENHANCED-CONVERSION Part D)"


def copilot_runs(config: dict) -> list[dict]:
    """Every Copilot run, interleaved arm by arm (arm1-run1, arm2-run1, arm1-run2, ...) so that time of day and
    service changes fall on both arms alike."""
    arms = [a for a in config["arms"] if "ref" not in a]
    most = max(a["runs"] for a in arms)
    out = []
    for n in range(1, most + 1):
        for a in arms:
            if n <= a["runs"]:
                out.append({"arm": a["arm"], "run": n, "enhancement": a["enhancement"], "name": a["name"],
                            "label": f"arm{a['arm']}-run{n}", "branch": f"experiment/arm{a['arm']}-run{n}"})
    return out


def prepare(db, config: dict, config_path: Path) -> list[dict]:
    repository = (db.query(models.Repository).filter_by(engagement_id=config["engagement"], slug=config["repository"])
                  .filter(models.Repository.deleted_at.is_(None)).one())
    root = Path(repository.local_path)
    base = gitops.git(root, "rev-parse", config["baseline_commit"]).strip()
    home = planner.RUNS / config["engagement"] / config["repository"] / "experiment"
    runs = copilot_runs(config)
    manifests = set()
    for r in runs:
        worktree = home / r["label"]
        if worktree.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"{worktree} would be inside the registered checkout")
        exists = gitops.git(root, "rev-parse", "--verify", "--quiet", r["branch"], check=False).strip()
        if exists and not worktree.exists():
            raise RuntimeError(f"branch {r['branch']} exists without its worktree {worktree}: resolve by hand")
        gitops.ensure_branch_worktree(root, worktree, r["branch"], base)
        if r["enhancement"]:
            if gitops.head(worktree) == base:
                generate(db, config["engagement"], config["repository"], worktree)
                gitops.git(worktree, "add", "--", *[p.rstrip("/") for p in paths.GENERATED_INPUT_PATHS
                                                    if (worktree / p.rstrip("/")).exists()])
                gitops.git(worktree, *gitops.PLATFORM_IDENTITY, "commit", "--no-verify", "-q", "-m", INPUTS_COMMIT)
            parents = gitops.git(worktree, "rev-list", "--parents", "-n", "1", "HEAD").split()
            if parents[1:] != [base] or gitops.git(worktree, "log", "-1", "--format=%s").strip() != INPUTS_COMMIT:
                raise RuntimeError(f"{r['branch']} is not the baseline plus the platform's inputs commit")
            manifests.add(gitops.git(worktree, "rev-parse", f"HEAD:{paths.PLATFORM_INPUTS_DIR}/inputs-manifest.json").strip())
        elif gitops.head(worktree) != base:
            raise RuntimeError(f"{r['branch']} has moved from the baseline {base[:8]}: it has been run already")
        r.update(worktree=str(worktree), head=gitops.head(worktree))
    if len(manifests) > 1:
        raise RuntimeError("arm 2's runs were given different inputs: regenerate them together")

    from app.engine.inputs.collect import collect
    options = upgrade_options(collect(db, repository))
    runbook = config_path.parent / "RUNBOOK.md"
    runbook.write_text(render_runbook(config, runs, options, base, repository), encoding="utf-8", newline="\n")
    return runs


# ---------------------------------------------------------------- the runbook

START_MESSAGE = "Upgrade this solution to .NET 10 and make the application ready to run on OpenShift."
ENHANCEMENT_MESSAGE = (" Use the custom upgrade instructions in .github/upgrades/skills and the skills in .github/skills,"
                       " and follow .github/copilot-instructions.md.")
ADDENDUM_MESSAGE = ("I added the platform's findings to assessment.md, under \"Platform assessment addendum\". "
                    "Take them into account in the upgrade options and the plan.")


def render_runbook(config: dict, runs: list[dict], options: list[dict], base: str, repository) -> str:
    eng, slug, stop = config["engagement"], config["repository"], config["stop"]
    folder = f"..\\experiments\\{Path(config['_dir']).name}"
    cfg = f"{folder}\\experiment.yaml"
    sln = sorted(Path(repository.local_path).glob("*.sln"))
    sln_name = sln[0].name if sln else "<solution>.sln"
    arm3 = next((a for a in config["arms"] if "ref" in a), None)
    out = [
        "# Operator runbook — Copilot-enhanced conversion, first experiment", "",
        "> Generated by `python -m app.experiment.prepare` from `experiment.yaml`. Do not edit: change the configuration",
        "> or the generator and run it again. Spec: `docs/36-COPILOT-ENHANCED-CONVERSION.md` Part F.", "",
        f"Subject: `{slug}` from baseline `{base[:8]}`, to .NET 10 and OpenShift readiness, engagement `{eng}`.", "",
        "The arms differ in one thing. **Every step below is worded identically for both arms, except the lines marked",
        "ARM 2 ONLY**, which reference arm 2's inputs. Read each message exactly as written; do not add to it, rephrase it",
        "or explain it. Anything you type that is not in this runbook is an *intervention* and is recorded.", "",
        "The experiment runs interactively; a person drives the engine. Nothing here asks for, stores or types a credential.",
        "", "## Runs, in this order", "",
        "Interleaved so time of day and service changes fall on both arms alike.", "",
        "| # | Run | Arm | Branch | Worktree |", "|---|---|---|---|---|",
    ]
    for i, r in enumerate(runs, 1):
        out.append(f"| {i} | `{r['label']}` | {r['arm']} — {r['name']} | `{r['branch']}` | `{r['worktree']}` |")
    if arm3:
        out += ["", f"Arm 3 — {arm3['name']}: the existing branch `{arm3['ref']}`. Not run by a person; verified only. "
                f"It covers the {arm3['scope']}, not OpenShift readiness, and is compared on that dimension alone."]

    out += ["", "## Once, before the first run", "",
            "1. **Tools.** Visual Studio 2026 (or 2022 17.14.17 or later) with the **.NET desktop development** workload and its",
            "   optional components **GitHub Copilot** and **GitHub Copilot app modernization**. Turn off Visual Studio's",
            "   automatic updates until the last run is done: every run uses the same versions. Record them from",
            "   Help > About Microsoft Visual Studio (the Visual Studio version, and the GitHub Copilot and app modernization",
            "   component versions).",
            "2. **The model.** One model for every run, the one named in `experiment.yaml` (`engine.model`). If it is not",
            "   set there, stop: the model is a decision, not the operator's choice on the day.",
            "3. **No other customization.** Both arms must see the same Copilot configuration:",
            "   - `%UserProfile%\\.copilot\\skills\\` does not exist or is empty;",
            "   - Tools > Options > GitHub > Copilot: **custom instructions from .github/copilot-instructions.md are enabled**",
            "     (arm 1's branches have no such file; arm 2's do) and no other instruction file or prompt file is configured;",
            "   - no Copilot memory or saved preference carries over from an earlier session (start each run in a new chat thread).",
            "4. **The platform's database is reachable**, as `backend\\.env` configures it. The platform backend does not need to run.",
            "", "## Every run", "",
            "Replace `<run>`, `<branch>` and `<worktree>` with the row from the table. Commands run in PowerShell:", "",
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
            "```powershell",
            f"python -m app.engine.runs start --engagement {eng} --repository {slug} --label <run> --worktree <worktree> "
            f"--base {base[:8]} --provider {config['engine']['provider']} --organisation <organisation> --identity <account> "
            f"--model \"<model>\" --engine-version \"<app modernization version>\" --host \"<Visual Studio version>\" "
            f"--runbook {folder}\\RUNBOOK.md",
            "```", "",
            "It refuses unless the engagement's engine allowlist admits GitHub Copilot under the organisation you entered.",
            "If it prints `STOP.`, stop. It also records a hash of every input file in the worktree and of this runbook.", "",
            "### 3. Open the run's worktree", "",
            f"Open `<worktree>\\{sln_name}` in Visual Studio — the worktree, never the registered checkout. Confirm the Git",
            "branch shown is `<branch>`. Open a **new** Copilot chat thread and select the model from step 1. Start a timer.", "",
            "### 4. Start the upgrade", "",
            "Right-click the solution in Solution Explorer > **Modernize**. Send this message:", "",
            f"> {START_MESSAGE}", "",
            "**ARM 2 ONLY**, the same message with one sentence added:", "",
            f"> {START_MESSAGE}{ENHANCEMENT_MESSAGE}", "",
            "### 5. Answer the pre-initialization questions", "",
            "| If it asks | Reply |", "|---|---|",
            "| Target framework | `.NET 10` |",
            "| Branch, Git strategy, commits | `Work on the current branch <branch>. Do not create another branch. Commit after each task.` |",
            "| Automatic or guided flow | `Guided.` |",
            "| Whether to continue an existing upgrade or start fresh | stop: the worktree is not clean; report it |", "",
            "### 6. After the assessment", "",
            "When the agent says the assessment is done and `.github/upgrades/<scenario>/assessment.md` exists:", "",
            "**ARM 2 ONLY**: merge the platform's addendum, then send the message below it.", "",
            "```powershell", "python -m app.engine.inputs merge-addendum --worktree <worktree>", "```", "",
            f"> {ADDENDUM_MESSAGE}", "",
            "Both arms: do not edit `assessment.md` in any other way.", "",
            "### 7. Answer the upgrade options", "",
            "The same answers for both arms (the decision sheet). For each option the agent presents, reply with the answer",
            "in this table; for an option not in the table, reply `Use your recommended default.` and record it (step 10).", "",
            "| Option | Answer | Status |", "|---|---|---|",
        ]
    for o in options:
        out.append(f"| {o['question']} | `{o['answer']}` | {'presumptive' if o['presumptive'] else 'decided'} |")
    out += ["", "### 8. Planning and execution", "",
            "When it offers planning, send `Proceed to planning.` When `plan.md` is written, send `Proceed to execution.`",
            "Do not edit `plan.md`, `tasks.md` or any task file.", "",
            "During execution, when the agent asks a question:", "",
            "| It asks | Reply |", "|---|---|",
            "| To choose between options | `Continue with your recommended option.` |",
            "| For a credential, a secret, a sign-in, an installation or a change outside the repository | `No. Continue without it.` |",
            "| Whether to continue after a pause | `Continue.` |", "",
            "### 9. When to stop", "",
            "Stop the run, and do not resume it, when the first of these happens:", "",
            "- the agent reports the upgrade complete (`tasks.md` shows every task done);",
            f"- {stop['max_elapsed_minutes']} minutes have passed since step 3;",
            f"- the agent has attempted one task {stop['max_attempts_on_one_task']} times without completing it;",
            "- the agent asks for a credential or a machine change a second time;",
            "- the agent works outside `<worktree>`, or on a branch other than `<branch>`.", "",
            "Then send `Commit all remaining changes on the current branch.` and wait until it has.", "",
            "### 10. Record interventions as they happen", "",
            "Every message you send that is not worded in this runbook, every manual edit and every option not in step 7:", "",
            "```powershell",
            f"python -m app.engine.runs intervene --engagement {eng} --label <run> --stage <assessment|options|planning|execution> --what \"<what you did and why>\"",
            "```", "",
            "### 11. Finish the record", "",
            "Save the chat transcript (copy the whole Copilot chat thread into `<worktree>-transcript.md`, beside the worktree).",
            "It is a record of the run, never evidence. Note the elapsed time and the premium requests the run used (the",
            "Copilot usage figure before step 4 and after step 9).", "",
            "```powershell",
            f"python -m app.engine.runs finish --engagement {eng} --label <run> --outcome <completed|stopped|abandoned> "
            "--elapsed-minutes <n> --premium-requests <n> --transcript <worktree>-transcript.md --notes \"<which stop rule ended it>\"",
            "```", "",
            "### 12. Verify", "",
            "Independent of the engine; nothing it reported counts.", "",
            "```powershell",
            f"python -m app.engine.verifier --engagement {eng} --repository {slug} --base {base[:8]} --ref <branch> --label <run> "
            f"--config {cfg} --baseline-plan {config['baseline_plan']}",
            "```", "",
            "## After the last run", "",
            "```powershell",
            f"python -m app.experiment.report --config {cfg}",
            "```", "",
            "One comparison across every run, the scorecard per run and arm 3's limitation stated. PROVEN is evidence, not",
            "approval: a named person signs.", ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(prog="python -m app.experiment.prepare", description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    config["_dir"] = str(args.config.resolve().parent)
    db = SessionLocal()
    try:
        runs = prepare(db, config, args.config.resolve())
    finally:
        db.close()
    for r in runs:
        print(f"{r['label']}: {r['branch']} at {r['head'][:8]} in {r['worktree']}")
    print(f"runbook: {args.config.resolve().parent / 'RUNBOOK.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
