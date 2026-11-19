"""The conversion engines (36-COPILOT-ENHANCED-CONVERSION Part Q): GitHub Copilot and Claude Code, behind one boundary.

One content model, two renderers (app.engine.inputs.render): the work items, decisions, assessment addendum, scope,
build and test commands and the rules are produced once, and each engine gets them in its own files. Only an engine's
mechanics differ: where it reads instructions, how it is started, how its guardrails are enforced.

Which engine a conversion uses: the repository's own choice (`repositories.conversion_engine`, set by its owner), else
its engagement's default (`engagements.default_engine`, set at creation, editable by admins). Every engagement that
existed before Claude Code was added keeps GitHub Copilot, and a conversion record without an engine was prepared for
GitHub Copilot.
"""

COPILOT = "github-copilot"
CLAUDE = "claude-code"
DEFAULT = COPILOT
ENGINES = (COPILOT, CLAUDE)
NAMES = {COPILOT: "GitHub Copilot", CLAUDE: "Claude Code"}


def name(engine: str | None) -> str:
    """The engine as people name it: "GitHub Copilot" or "Claude Code"."""
    return NAMES[engine or DEFAULT]


def check(engine: str) -> str:
    """The engine, or ValueError naming the ones there are."""
    if engine not in ENGINES:
        raise ValueError(f"unknown conversion engine '{engine}': one of {', '.join(ENGINES)}")
    return engine


def of_record(record: dict | None) -> str:
    """The engine a conversion was prepared for: a record from before engines were recorded is GitHub Copilot's."""
    return (record or {}).get("engine") or COPILOT


def of_repository(db, repository) -> str:
    """The engine a new conversion of this repository uses: its owner's choice, else its engagement's default."""
    from app import models

    if getattr(repository, "conversion_engine", None):
        return repository.conversion_engine
    engagement = db.get(models.Engagement, repository.engagement_id)
    return (getattr(engagement, "default_engine", None) if engagement is not None else None) or DEFAULT


def source(db, repository) -> str:
    """Where the repository's engine comes from: "repository" (its owner chose it) or "engagement" (the default)."""
    return "repository" if getattr(repository, "conversion_engine", None) else "engagement"
