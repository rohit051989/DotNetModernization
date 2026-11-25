"""Claude Code's rendering of the conversion inputs (36-COPILOT-ENHANCED-CONVERSION Part Q).

The content is GitHub Copilot's, produced once by app.engine.inputs.render: the work items, the decisions, the
assessment addendum, the scope, the build and test commands and the rules. Only the engine's mechanics differ, and they
are one table, `MECHANICS`: where the work items are, where the platform's inputs are, where notes go. The parity test
(tests/test_engine_inputs.py, EngineParity) maps a Claude Code file back through the same table and compares it with
GitHub Copilot's.

Where Claude Code reads (code.claude.com/docs/en/memory, /skills, /settings, /permissions; checked 2026-11-19):

| Output | Where | Why there |
|---|---|---|
| The instructions: the plan, the rules, the scope | `.claude/CLAUDE.md`; `.claude/rules/conversion-instructions.md` when the repository has its own `.claude/CLAUDE.md` | Both load at start. A repository's own `CLAUDE.md` at its root loads too, and is kept. |
| One skill per work item | `.claude/skills/<name>/SKILL.md` | A project skill: its description is always in context, its body loads when used. |
| The three helpers adapted from the code-modernization plugin | `.claude/agents/<name>.md` | The plugin is a Claude Code plugin, and these were its subagents: Claude Code gets them in that form, under their own names. |
| The guardrails | `.claude/settings.json`; `.claude/settings.local.json` when the repository has its own | Enforced by Claude Code, not only stated: no `git push`, no history rewriting, no edit inside an excluded project. Read only from the folder Claude Code starts in. |
| Addendum, decision sheet, inputs manifest | `.claude/conversion/` | Read on the instructions' say-so. |

No file the repository already has is ever written: a location it already uses moves to the alternative above, and
when both are taken preparation is refused (InputsCollide). Claude Code has no upgrade tool and no stages: its
instructions give the plan itself, the work items in order, each built and tested with the conversion's solution and
committed on its own, naming it.
"""
import json
import re
from pathlib import Path

from app.engine.inputs import render as rendering

INSTRUCTIONS = ".claude/CLAUDE.md"
INSTRUCTIONS_ALTERNATIVE = ".claude/rules/conversion-instructions.md"
SKILLS_DIR = ".claude/skills"
AGENTS_DIR = ".claude/agents"
SETTINGS = ".claude/settings.json"
SETTINGS_ALTERNATIVE = ".claude/settings.local.json"
INPUTS_DIR = ".claude/conversion"
MANIFEST = f"{INPUTS_DIR}/inputs-manifest.json"

# The adapted plugin skills, as the plugin's own subagents: (their template, the upstream agent's name, its tools as
# upstream gives them).
GUIDES = {
    "analyzing-version-deltas": ("version-delta-analyst", "Read, Glob, Grep, Bash"),
    "reviewing-converted-code": ("architecture-critic", "Read, Glob, Grep, Bash"),
    "writing-characterization-tests": ("test-engineer", "Read, Write, Edit, Glob, Grep, Bash"),
}

# The engine mechanics in the shared content: (GitHub Copilot's text, Claude Code's text). Applied in this order to
# render; applied the other way round to compare (`neutral`). Nothing else differs.
MECHANICS = (
    ("`.github/upgrades/skills/`", "`.claude/skills/`"),
    (".github/platform-inputs/", f"{INPUTS_DIR}/"),
    ("custom upgrade instruction under", "skill under"),
    ("Record each one in the task's\n  progress notes", "Record each one in the\n  work item's commit message"),
    ("the task's notes", "the work item's commit message"),
    ("the upgrade tool's own assessment", "a general assessment of the upgrade"),
    ("The answers to give at the upgrade tool's upgrade-options stage, and the approach for each change.",
     "The answers to the upgrade's options, and the approach for each change."),
    ("skill `writing-characterization-tests`", "subagent `test-engineer`"),
    ("global instructions for GitHub Copilot upgrade;", "project instructions for Claude Code;"),
)

# Git commands that push or rewrite history, denied in Claude Code's settings. "Bash(x *)" also matches the bare
# command. A rule matches the command as Claude Code writes it: it is a guardrail, not a security boundary, and the
# verifier judges the branch whatever happened.
DENIED_COMMANDS = (
    "git push *", "git rebase *", "git reset --hard *", "git reset --keep *", "git commit --amend *",
    "git commit * --amend *", "git filter-branch *", "git filter-repo *", "git update-ref *", "git reflog expire *",
    "git replace *", "git branch -D *", "git branch -f *", "git branch --force *", "git branch -m *", "git branch -M *",
    "git checkout -b *", "git checkout -B *", "git switch -c *", "git switch -C *", "git worktree *",
)


class InputsCollide(ValueError):
    """The repository already has a file where Claude Code's inputs would go, and its alternative too."""


def to_claude(text: str) -> str:
    for copilot, claude in MECHANICS:
        text = text.replace(copilot, claude)
    return text


def neutral(text: str) -> str:
    """Claude Code's text with its mechanics put back as GitHub Copilot's: for comparing the two renderings."""
    for copilot, claude in reversed(MECHANICS):
        text = text.replace(claude, copilot)
    return text


def _free(model: dict, *candidates: str) -> str:
    existing = {f.lower() for f in model.get("files") or []}
    for path in candidates:
        if path.lower() not in existing:
            return path
    raise InputsCollide(f"the repository already has {' and '.join(candidates)}: Claude Code's inputs never replace a file "
                        "the repository has. Rename one of them in the repository, then prepare again")


def instructions_path(model: dict) -> str:
    return _free(model, INSTRUCTIONS, INSTRUCTIONS_ALTERNATIVE)


def settings_path(model: dict) -> str:
    return _free(model, SETTINGS, SETTINGS_ALTERNATIVE)


def own_claude_md(model: dict) -> list[str]:
    """The repository's own instruction files Claude Code also loads at its root: kept, never changed."""
    existing = {f.lower(): f for f in model.get("files") or []}
    return [existing[p.lower()] for p in ("CLAUDE.md", "CLAUDE.local.md", INSTRUCTIONS) if p.lower() in existing]


def skill_path(name: str) -> str:
    return f"{SKILLS_DIR}/{name}/SKILL.md"


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end >= 0:
            return text[end + 5:].lstrip("\n")
    return text


def _one_line(text: str, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


def work_item(model: dict, item: dict, copilot_text: str) -> str:
    """One work item as a Claude Code skill: its own frontmatter, then GitHub Copilot's instruction body."""
    res = item["resolution"]
    name = rendering.skill_name(res["id"])
    description = _one_line(f"{item['name']}: {res['name']}. A work item of this repository's upgrade to "
                            f"{model['engagement']['target_framework']} and OpenShift readiness: what to change, where, "
                            "and when it is done. Use it when applying this work item.")
    head = ["---", f"name: {name}", f"description: {json.dumps(description, ensure_ascii=False)}", "---", ""]
    return "\n".join(head) + to_claude(_strip_frontmatter(copilot_text))


def guide(template_name: str, copilot_text: str) -> str:
    """A plugin skill as the plugin's own subagent: the upstream agent's name and tools, the adapted body."""
    agent, tools = GUIDES[template_name]
    frontmatter = copilot_text.split("\n---\n", 1)[0]
    m = re.search(r"^description: >\n((?:  .*\n?)+)", frontmatter + "\n", re.MULTILINE)
    description = _one_line(m.group(1) if m else agent)
    body = _strip_frontmatter(copilot_text)
    body = body.replace("GitHub Copilot upgrade skill", "Claude Code subagent (the plugin's own form)")
    body = body.replace("This skill analyses", "This subagent analyses")
    for other, (name, _) in GUIDES.items():
        body = body.replace(f"`{other}`", f"`{name}`")
    head = ["---", f"name: {agent}", f"description: {json.dumps(description, ensure_ascii=False)}", f"tools: {tools}", "---", ""]
    return "\n".join(head) + to_claude(body)


def _escape(path: str) -> str:
    """A repository path as a literal in a gitignore-style permission pattern."""
    return re.sub(r"([\[\]*?!\\])", r"\\\1", path)


def excluded_edit_rules(model: dict) -> list[str]:
    """Edit denials for the projects outside the scope: each project's folder, relative to the folder Claude Code starts
    in (the worktree). A folder that also holds a kept project, or the repository's root, cannot be denied whole: then
    only the excluded project's own file is."""
    scope = model.get("scope") or {}
    kept = [p["path"] for p in model.get("projects") or []]          # the model holds only the kept projects
    rules = []
    for project in scope.get("excluded") or []:
        path = project["path"]
        folder = path.rsplit("/", 1)[0] if "/" in path else ""
        holds_kept = any(k.startswith(folder + "/") for k in kept) if folder else True
        if folder and not holds_kept:
            rules.append(f"Edit(/{_escape(folder)}/**)")
        else:
            rules.append(f"Edit(/{_escape(path)})")
    return sorted(set(rules), key=str.lower)


def settings(model: dict) -> str:
    deny = [f"Bash({c})" for c in DENIED_COMMANDS] + excluded_edit_rules(model)
    return json.dumps({"permissions": {"deny": deny}}, indent=2) + "\n"


def instructions(model: dict, items: list[dict], copilot_instructions: str) -> str:
    """Claude Code's instructions: the plan (Claude Code has no upgrade tool to make one), then GitHub Copilot's rules,
    build and test section and scope, through the mechanics table."""
    commands = rendering.commands(model)
    own = own_claude_md(model)
    built = f"`{commands['build']}`"
    tested = f"`{commands['test']}`"
    out = ["# Instructions for this conversion", "",
           rendering.generated_note(model), "",
           "These rules apply to every step of this upgrade of the solution: the plan below, each work item and the "
           "final checks. They are this project's rules for the upgrade and override any general habit."]
    if own:
        out += ["", "This repository's own " + " and ".join(f"`{f}`" for f in own) + " also "
                + ("applies" if len(own) == 1 else "apply") + ", unchanged. Where it and these instructions disagree, these "
                "instructions win for this conversion."]
    out += ["", "## How to run this conversion", "",
            "There is no separate upgrade tool: this is the plan. Work through these work items in this order, one at a "
            f"time. Each one is a skill under `{SKILLS_DIR}/`: read it in full before changing anything. The order is by "
            "phase, and within a phase each project's referenced projects first, so every step builds on the ones "
            "before it.", ""]
    steps: list[list[dict]] = []            # changes that run as one unit share a step (render.work_items)
    for entry in items:
        if entry.get("together_with") and steps:
            steps[-1].append(entry)
        else:
            steps.append([entry])
    for number, step in enumerate(steps, 1):
        phase = f" (phase {step[0]['phase']}, {rendering.PHASES[step[0]['phase']].lower()})" if step[0].get("phase") else ""
        if len(step) == 1:
            out.append(f"{number}. `{step[0]['name']}`: {step[0]['title']}{phase}")
        else:
            out.append(f"{number}. " + " and ".join(f"`{e['name']}`" for e in step) + ", in one task and one commit: "
                       + "; ".join(e["title"] for e in step) + phase)
    if not items:
        out.append("There is no work item: nothing in this repository needs a change the instructions describe.")
    if rendering.design_items(model):
        # The rule itself is in the shared rules below; the plan only puts it first.
        out += ["", "Before the first one, and before changing any code, ask the developer the questions \"Design "
                "questions before converting\" below describes, in one round, and record the answers."]
    out += ["", "For each work item, in order:", "",
            "1. Apply it as its skill says, at the places it lists, and only there.",
            f"2. Build with {built} and test with {tested}. Both must succeed, and every test that passed before must "
            "still pass. Fix what the work item broke before going on.",
            "3. Commit only that work item's changes, on the current branch, with a message that starts with its name: "
            "`<name>: <what changed>`. Record in the message any place left unchanged and why, and any surprise.",
            *(["", "A step that names more than one work item is one task: apply them all, then build and test, and "
                   "commit them once, with a message that starts with the first one's name."]
              if any(len(step) > 1 for step in steps) else []),
            "",
            f"Before the first one, read `{INPUTS_DIR}/assessment-addendum.md` (facts about this code a general assessment "
            f"misses) and `{INPUTS_DIR}/decision-sheet.md` (the approach chosen for each change). The subagents "
            f"`version-delta-analyst`, `test-engineer` and `architecture-critic` in `{AGENTS_DIR}/` help: run "
            "`architecture-critic` over the whole change before reporting done.", ""]
    rules = copilot_instructions.split("\n## ", 1)[1]
    out.append(to_claude("## " + rules).rstrip("\n"))
    return "\n".join(out) + "\n"


def render(model: dict, copilot_files: dict[str, str], items: list[dict]) -> dict[str, str]:
    """{path: text} for Claude Code, from GitHub Copilot's rendering of the same model (render.render): its work items,
    addendum, decision sheet and instructions, through the mechanics table. `items`: render.work_items(model)."""
    from app.engine import paths

    files: dict[str, str] = {}
    by_name = {}
    for entry in items:
        copilot_path = f"{paths.UPGRADE_SKILLS_DIR}/{entry['name']}.md"
        files[skill_path(entry["name"])] = work_item(model, entry["item"], copilot_files[copilot_path])
        by_name[entry["name"]] = entry
    for template, (agent, _) in GUIDES.items():
        files[f"{AGENTS_DIR}/{agent}.md"] = guide(template, copilot_files[f"{paths.SKILLS_DIR}/{template}.md"])
    files[instructions_path(model)] = instructions(model, items, copilot_files[paths.COPILOT_INSTRUCTIONS])
    files[settings_path(model)] = settings(model)
    files[f"{INPUTS_DIR}/assessment-addendum.md"] = to_claude(copilot_files[f"{paths.PLATFORM_INPUTS_DIR}/assessment-addendum.md"])
    files[f"{INPUTS_DIR}/decision-sheet.md"] = to_claude(copilot_files[f"{paths.PLATFORM_INPUTS_DIR}/decision-sheet.md"])
    return {k: v for k, v in sorted(files.items())}


def context_hazards(folder: Path, home: Path | None = None) -> list[str]:
    """Instruction files Claude Code would also read from a folder above `folder` (a conversion's worktree): every
    CLAUDE.md and CLAUDE.local.md up to the drive's root, and every .claude folder (its rules and skills) except the
    user's own in their home folder, which is Claude Code's user configuration and loads wherever it starts."""
    homes = {Path.home().resolve()} | ({home.resolve()} if home else set())
    found = []
    for parent in folder.resolve().parents:
        for name in ("CLAUDE.md", "CLAUDE.local.md"):
            if (parent / name).is_file():
                found.append(str(parent / name))
        if (parent / ".claude").is_dir() and parent not in homes:
            found.append(str(parent / ".claude"))
    return found
