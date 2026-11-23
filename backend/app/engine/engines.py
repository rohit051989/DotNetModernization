"""The conversion engines (36-COPILOT-ENHANCED-CONVERSION Part Q): GitHub Copilot and Claude Code, behind one boundary.

One content model, two renderers (app.engine.inputs.render): the work items, decisions, assessment addendum, scope,
build and test commands and the rules are produced once, and each engine gets them in its own files. Only an engine's
mechanics differ: where it reads instructions, how it is started, how its guardrails are enforced.

Every conversion is prepared for both (2026-11-23): which one does the work depends on what is installed on the
machine of the person running it, so there is no choice to make in advance. The Conversion tab shows either engine's
inputs and runbook, and Verify records which assistant did the conversion. The columns that held a choice
(`engagements.default_engine`, `repositories.conversion_engine`) are kept, unused: their migration was applied.

A conversion record from before (one engine, `engine`) was prepared for that engine only, GitHub Copilot when it names
none; the other engine's inputs come with its next preparation.
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
    """The one engine a record from before both engines was prepared for (GitHub Copilot when it names none)."""
    return (record or {}).get("engine") or COPILOT


def of_conversion(record: dict | None) -> dict[str, dict]:
    """{engine: {prepared, usable, unsafe, notPrepared, ...}} for both engines. A record from before both engines has
    only its one engine prepared; the other is not prepared, and says why."""
    record = record or {}
    if record.get("engines"):
        return {e: {"prepared": False, "usable": False, **(record["engines"].get(e) or {})} for e in ENGINES}
    only = of_record(record)
    return {e: ({"prepared": True, "usable": True} if e == only else
                {"prepared": False, "usable": False,
                 "notPrepared": f"prepared before every conversion got both engines' inputs, for {name(only)} only: "
                                "they are added when it is prepared again"})
            for e in ENGINES}


def ran_with(record: dict | None) -> str | None:
    """The assistant that did the conversion, as Verify recorded it; None before it was verified."""
    return ((record or {}).get("assistant") or {}).get("engine")
