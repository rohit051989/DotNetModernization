"""Where engine inputs and engine state live in a repository (36-COPILOT-ENHANCED-CONVERSION
Parts D and E). One definition, used by the generator that writes the inputs, the run record that
hashes them, and the verifier that excludes them from diff and impact comparison.

Locations are those GitHub Copilot upgrade reads, confirmed 2026-10-12 against
learn.microsoft.com/dotnet/core/porting/github-copilot-upgrade/customization (ms.date 2026-09-21)
and microsoft/upgrade-agent-plugins at 90bc71e0 (2026-10-09):

- `.github/skills/*.md`: repository skills, priority 2;
- `.github/upgrades/skills/*.md`: repository upgrade skills, priority 3. The current agent has no
  separate location for "custom upgrade instructions": it retrieves them through the same
  `get_instructions` call as skills, so one instruction per item and resolution is an upgrade skill;
- `.github/copilot-instructions.md`: global instructions, sent with every request;
- `.github/upgrades/{scenarioId}/`: the engine's own state (assessment.md, plan.md, tasks.md ...).

Platform files that the engine is not meant to read on its own — the assessment addendum, the
decision sheet and the inputs manifest — go under `.github/platform-inputs/`.

Claude Code's (Part Q; app.engine.inputs.claude says where each goes and why): `.claude/CLAUDE.md` or
`.claude/rules/conversion-instructions.md`, `.claude/skills/<work item>/SKILL.md`, `.claude/agents/*.md`,
`.claude/settings.json` or `.claude/settings.local.json`, and `.claude/conversion/`. The whole of `.claude/` is engine
state, excluded from comparison as `.github/upgrades/` is.
"""

COPILOT_INSTRUCTIONS = ".github/copilot-instructions.md"
SKILLS_DIR = ".github/skills"
UPGRADE_SKILLS_DIR = ".github/upgrades/skills"
PLATFORM_INPUTS_DIR = ".github/platform-inputs"
ENGINE_STATE_DIR = ".github/upgrades"

CLAUDE_DIR = ".claude"
CLAUDE_SKILLS_DIR = ".claude/skills"

# Every path the generator may write. A file under one of these is an input.
GENERATED_INPUT_PATHS = (COPILOT_INSTRUCTIONS, SKILLS_DIR + "/", UPGRADE_SKILLS_DIR + "/", PLATFORM_INPUTS_DIR + "/")
# Claude Code's: under .claude/, beside whatever of its own the repository keeps there.
CLAUDE_INPUT_PATHS = (CLAUDE_DIR + "/",)

# Where each engine's work items are: one file each (GitHub Copilot), one folder with a SKILL.md each (Claude Code).
WORK_ITEM_DIRS = (UPGRADE_SKILLS_DIR, CLAUDE_SKILLS_DIR)


def work_item_dirs(engine: str | None) -> tuple[str, ...]:
    """Where one engine's work items are (GitHub Copilot's, Claude Code's); both when the engine is not known."""
    from app.engine import engines

    return {engines.COPILOT: (UPGRADE_SKILLS_DIR,), engines.CLAUDE: (CLAUDE_SKILLS_DIR,)}.get(engine, WORK_ITEM_DIRS)

# Excluded from the verifier's diff, impact comparison and re-discovery: inputs and records, not
# conversion. The same list for every run of every arm, and for both engines.
EXCLUDED_FROM_COMPARISON = (ENGINE_STATE_DIR + "/", COPILOT_INSTRUCTIONS, SKILLS_DIR + "/", PLATFORM_INPUTS_DIR + "/",
                            CLAUDE_DIR + "/")


def is_work_item(path: str) -> bool:
    """A work item's file: `.github/upgrades/skills/<name>.md` or `.claude/skills/<name>/SKILL.md`."""
    path = path.replace("\\", "/")
    parts = path.split("/")
    if path.startswith(UPGRADE_SKILLS_DIR + "/"):
        return len(parts) == 4 and path.endswith(".md")
    return path.startswith(CLAUDE_SKILLS_DIR + "/") and len(parts) == 4 and parts[3] == "SKILL.md"


def work_item_name(path: str) -> str:
    """A work item's name from its file: `applying-x` for both engines' files."""
    parts = path.replace("\\", "/").split("/")
    return parts[-2] if parts[-1] == "SKILL.md" else parts[-1].rsplit(".", 1)[0]


def is_under(path: str, prefixes: tuple[str, ...]) -> bool:
    """True when the repository-relative `path` ("/" separated) is one of `prefixes`
    or lies under one ending in "/"."""
    path = path.replace("\\", "/")
    if path.startswith("./"):
        path = path[2:]
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in prefixes)
