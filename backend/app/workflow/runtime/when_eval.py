"""Evaluates `when:` conditions — 22-STEP-SEQUENCING-AND-POLICY.md Part B.

Pure and side-effect free: no database access. The caller resolves the three
data sources ahead of time (job parameters, job execution context, and the
exit statuses recorded so far in this execution) and passes them in.
"""

import re
from typing import Any

from app.workflow.definition.model import WhenAll, WhenAny, WhenCondition, WhenLeaf, WhenNot

_MISSING = object()


class WhenEvaluationError(Exception):
    """A `when:` condition could not be evaluated — a missing value under a
    comparison operator, or a type mismatch. The caller must treat this as a
    step FAILURE, never a silent skip: "a typo'd context key must never
    silently skip a verification step. Fail loud." (Part B)."""


def _leaf_value(leaf: WhenLeaf, *, params: dict, job_context: dict, step_statuses: dict[str, str]) -> Any:
    if leaf.param is not None:
        return params.get(leaf.param, _MISSING)
    if leaf.context is not None:
        return job_context.get(leaf.context, _MISSING)
    return step_statuses.get(leaf.step_status, _MISSING)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _evaluate_leaf(leaf: WhenLeaf, *, params: dict, job_context: dict, step_statuses: dict[str, str]) -> bool:
    value = _leaf_value(leaf, params=params, job_context=job_context, step_statuses=step_statuses)
    op, operand = leaf.operator
    where = f"{leaf.source_kind}.{leaf.source_name}"

    if op == "exists":
        present = value is not _MISSING and value is not None
        return present if operand else not present

    # Missing context evaluates false only under `exists` (above). Any other
    # operator on a missing value fails the step rather than skipping it —
    # a typo must be loud, not indistinguishable from a deliberate skip.
    if value is _MISSING:
        raise WhenEvaluationError(
            f"'{where}' has no value and operator '{op}' is not 'exists' — "
            "failing rather than silently skipping"
        )

    if op == "eq":
        return value == operand
    if op == "ne":
        return value != operand
    if op in ("lt", "lte", "gt", "gte"):
        if not _is_number(value) or not _is_number(operand):
            raise WhenEvaluationError(
                f"'{where}': cannot compare {value!r} {op} {operand!r} — type mismatch"
            )
        return {
            "lt": value < operand,
            "lte": value <= operand,
            "gt": value > operand,
            "gte": value >= operand,
        }[op]
    if op == "in":
        return value in operand
    if op == "not_in":
        return value not in operand
    if op == "matches":
        if not isinstance(value, str):
            raise WhenEvaluationError(
                f"'{where}': 'matches' requires a string value, got {type(value).__name__} — type mismatch"
            )
        return re.fullmatch(operand, value) is not None

    raise AssertionError(f"unreachable — WhenLeaf validates operator identity, got '{op}'")


def evaluate_when(
    condition: WhenCondition, *, params: dict, job_context: dict, step_statuses: dict[str, str]
) -> bool:
    """Raises `WhenEvaluationError` for a leaf that cannot be evaluated — the
    caller must treat that as a step FAILURE, not a skip. `all`/`any` use
    Python's native short-circuiting, so a later leaf that would raise is
    never reached once the combinator's outcome is already determined —
    consistent with ordinary boolean AND/OR evaluation."""
    if isinstance(condition, WhenAll):
        return all(
            evaluate_when(c, params=params, job_context=job_context, step_statuses=step_statuses)
            for c in condition.all
        )
    if isinstance(condition, WhenAny):
        return any(
            evaluate_when(c, params=params, job_context=job_context, step_statuses=step_statuses)
            for c in condition.any
        )
    if isinstance(condition, WhenNot):
        return not evaluate_when(
            condition.not_condition, params=params, job_context=job_context, step_statuses=step_statuses
        )
    return _evaluate_leaf(condition, params=params, job_context=job_context, step_statuses=step_statuses)


def describe_when(condition: WhenCondition) -> str:
    """A compact, literal rendering for exit_message/diagnostics — not the
    polished prose the future job-definition viewer wants
    (22-STEP-SEQUENCING-AND-POLICY.md Part E), just enough to say what was
    checked without a database round-trip."""
    if isinstance(condition, WhenAll):
        return "all(" + ", ".join(describe_when(c) for c in condition.all) + ")"
    if isinstance(condition, WhenAny):
        return "any(" + ", ".join(describe_when(c) for c in condition.any) + ")"
    if isinstance(condition, WhenNot):
        return f"not({describe_when(condition.not_condition)})"
    return condition.describe()


_PROSE_SYMBOLS = {
    "eq": "=",
    "ne": "≠",
    "lt": "<",
    "lte": "≤",
    "gt": ">",
    "gte": "≥",
    "in": "in",
    "not_in": "not in",
    "matches": "matches",
}


def _format_operand(operand: Any) -> str:
    if isinstance(operand, list):
        return ", ".join(str(item) for item in operand)
    return str(operand)


def _render_leaf_prose(leaf: WhenLeaf) -> str:
    op, operand = leaf.operator
    name = leaf.source_name
    if op == "exists":
        return f"{name} is set" if operand else f"{name} is not set"
    symbol = _PROSE_SYMBOLS.get(op, op)
    return f"{name} {symbol} {_format_operand(operand)}"


def _render_prose(condition: WhenCondition) -> str:
    if isinstance(condition, WhenAll):
        return " and ".join(_render_prose(c) for c in condition.all)
    if isinstance(condition, WhenAny):
        return " or ".join(_render_prose(c) for c in condition.any)
    if isinstance(condition, WhenNot):
        return f"not ({_render_prose(condition.not_condition)})"
    return _render_leaf_prose(condition)


def render_when_prose(condition: WhenCondition) -> str:
    """Readable prose for the job definition viewer —
    22-STEP-SEQUENCING-AND-POLICY.md Part E: e.g. "Runs when
    test_coverage_percent < 60 and engagement_id ≠ reference-engagement-b".
    Not used for evaluation or for exit_message (see describe_when) — display
    only."""
    return f"Runs when {_render_prose(condition)}"
