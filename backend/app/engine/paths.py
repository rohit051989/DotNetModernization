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
"""

COPILOT_INSTRUCTIONS = ".github/copilot-instructions.md"
SKILLS_DIR = ".github/skills"
UPGRADE_SKILLS_DIR = ".github/upgrades/skills"
PLATFORM_INPUTS_DIR = ".github/platform-inputs"
ENGINE_STATE_DIR = ".github/upgrades"

# Every path the generator may write. A file under one of these is an input.
GENERATED_INPUT_PATHS = (COPILOT_INSTRUCTIONS, SKILLS_DIR + "/", UPGRADE_SKILLS_DIR + "/", PLATFORM_INPUTS_DIR + "/")

# Excluded from the verifier's diff, impact comparison and re-discovery: inputs and records, not
# conversion. The same list for every run of every arm.
EXCLUDED_FROM_COMPARISON = (ENGINE_STATE_DIR + "/", COPILOT_INSTRUCTIONS, SKILLS_DIR + "/", PLATFORM_INPUTS_DIR + "/")


def is_under(path: str, prefixes: tuple[str, ...]) -> bool:
    """True when the repository-relative `path` ("/" separated) is one of `prefixes`
    or lies under one ending in "/"."""
    path = path.replace("\\", "/")
    if path.startswith("./"):
        path = path[2:]
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in prefixes)
