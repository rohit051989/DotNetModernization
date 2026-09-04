"""Thin wrapper around the Anthropic API for step 5's LLM-assisted pass
(23-STEP-005-PATTERN-DISCOVERY.md Part D, pass 2). Deliberately narrow —
two operations only, both returning plain data — so `llm_pass.py` never
touches the SDK directly and tests can inject a fake client with the same
two methods instead of hitting the network.

No API key configured -> `LlmClient.available` is False and pass 2 is
skipped with a diagnostic, not a hard failure: the LLM pass is a catch-net
layered on top of the always-on structural pass (pass 1), never something
step 5 needs in order to produce a result at all.
"""

from __future__ import annotations

import json
import os

DEFAULT_MODEL = "claude-sonnet-4-5"

_SUMMARY_SYSTEM_PROMPT = (
    "You summarize a .NET application's structural signals for a modernization discovery "
    "exercise. Describe application type, technology characteristics, hosting "
    "characteristics, and notable structural indicators in 3-5 sentences of plain prose. "
    "Do not name or suggest a specific modernization pattern or target state - that "
    "decision belongs to a later, human-reviewed step (step 6). You are helping a human "
    "understand what the application looks like, not deciding anything."
)

_JUDGMENT_SYSTEM_PROMPT = (
    "You judge whether a set of .NET applications, already flagged as structurally similar, "
    "represent the SAME underlying legacy pattern from a modernization point of view. You "
    "are not choosing a pattern name or a migration target - only which applications belong "
    'together. Respond with ONLY a JSON object of the exact shape '
    '{"groups": [["id1","id2"], ...], "rationale": "..."} and nothing else - no markdown '
    "fencing, no prose outside the JSON. Every project id you were given must appear in at "
    "most one group; omit an id entirely if it does not clearly belong with any other "
    "application in the set. A group must have 2 or more members - never emit a group of "
    "one, and never invent an id that was not given to you."
)


class LlmError(Exception):
    """Raised when a call succeeds at the transport level but the model's
    response cannot be used (bad JSON, missing fields, invalid group) even
    after this class's own light validation."""


class LlmClient:
    """`api_key=None` (the default) reads `ANTHROPIC_API_KEY` from the
    environment; leave it unset in a dev/test environment and `available`
    is simply False. The `anthropic` package is imported lazily, inside
    `__init__`, only when a key is actually present — so environments that
    never exercise pass 2 (this repo's own CI today) do not need it
    installed to run anything else in this step."""

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._model = model
        self._client = None
        if self._api_key:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self._api_key)

    @property
    def available(self) -> bool:
        return self._client is not None

    def _complete(self, system: str, user: str, *, max_tokens: int) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in response.content if getattr(block, "type", None) == "text")

    def summarize_application(self, project_id: str, signals: list[dict]) -> str:
        """`signals` — a list of `{name, category, type, value,
        occurrence_count}` dicts for one residue application
        (`persistence.load_signal_details`). Returns a short structured-
        prose summary, never a pattern decision."""
        user = f"Signals for application {project_id}:\n{json.dumps(signals, indent=2)}"
        return self._complete(_SUMMARY_SYSTEM_PROMPT, user, max_tokens=400).strip()

    def judge_group(self, summaries: dict[str, str]) -> dict:
        """`summaries` — `{project_id: summary_text}` for one weak-threshold
        component (2+ residue applications whose structural signatures
        overlapped enough at `threshold_weak` to be worth a semantic
        comparison). Returns `{"groups": [[project_id, ...], ...],
        "rationale": str}` — each sub-list of length 2+ is an affirmed
        same-underlying-pattern group; a project id in no sub-list falls
        back to `unclustered`. Never returns a pattern name or migration
        decision — grouping judgment only."""
        user = f"Application summaries:\n{json.dumps(summaries, indent=2)}"
        raw = self._complete(_JUDGMENT_SYSTEM_PROMPT, user, max_tokens=800)
        return _parse_group_judgment(raw, expected_ids=set(summaries))


def _parse_group_judgment(raw: str, *, expected_ids: set[str]) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LlmError(f"could not parse LLM judgment as JSON: {exc}") from exc

    groups = parsed.get("groups")
    if not isinstance(groups, list):
        raise LlmError("LLM judgment response is missing a 'groups' list")

    seen: set[str] = set()
    cleaned: list[list[str]] = []
    for group in groups:
        if not isinstance(group, list):
            continue
        # An id the model was never given, or already placed in an earlier
        # group in this same response, is dropped rather than trusted —
        # membership must trace back to what step 5 actually asked about.
        valid = [pid for pid in group if pid in expected_ids and pid not in seen]
        if len(valid) < 2:
            continue
        seen.update(valid)
        cleaned.append(valid)

    return {"groups": cleaned, "rationale": parsed.get("rationale", "")}
