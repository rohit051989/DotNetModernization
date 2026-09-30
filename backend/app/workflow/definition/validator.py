"""The 10 static validation rules from 12-JOB-DEFINITION-FORMAT.md. Reports
ALL errors in one pass, in the documented shape:

    {"code": ..., "step": ..., "detail": ..., "affected_steps": [...]}

Rule 2 (consumes satisfied by an upstream produces or an external input, with
a compatible semver range) is the contract-change tripwire — the whole point
of validating at job-definition load time per 10-ENGINE-CONCEPTS.md.

Rule 9 (every non-optional consumes entry actually wired through the flow
node's `inputs` mapping) is a distinct check from rule 2: rule 2 asks
"could this be satisfied by something upstream?"; rule 9 asks "is it actually
plumbed through?" A consumes entry can be satisfiable (rule 2 passes) and
still never resolved at runtime because nobody wrote the `inputs:` entry —
this is exactly what happened with step 3; see
22-STEP-SEQUENCING-AND-POLICY.md Part A.
"""

import importlib
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app import models
from app.workflow import semver
from app.workflow.definition.model import (
    DecisionNode,
    ExternalInputSpec,
    FlowNode,
    JobDefinitionFile,
    SplitNode,
    StepNode,
    WhenAll,
    WhenAny,
    WhenCondition,
    WhenLeaf,
    WhenNot,
)
from app.workflow.definition.references import Reference, extract_references


@dataclass
class ValidationErrorItem:
    code: str
    detail: str
    step: str | None = None
    affected_steps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "step": self.step,
            "detail": self.detail,
            "affected_steps": self.affected_steps,
        }


@dataclass
class FlowOccurrence:
    step_name: str
    node: StepNode
    ancestors: frozenset[str]  # step names guaranteed to have completed before this one


def _flatten_flow(
    nodes: list[FlowNode], ancestors: frozenset[str] = frozenset()
) -> list[FlowOccurrence]:
    """Walks the (nested) flow into a flat list of step occurrences, each
    carrying the set of step names positionally guaranteed to run before it.

    Split branches run in parallel from the same starting ancestor set, and
    their combined step names become ancestors for whatever follows the
    split. Decision outcomes are mutually exclusive at runtime — only one
    branch executes — so outcome/default steps are NOT added to the ancestor
    set for anything after the decision; a later step cannot assume any
    particular outcome ran.
    """
    occurrences: list[FlowOccurrence] = []
    current_ancestors = ancestors

    for node in nodes:
        if isinstance(node, StepNode):
            occurrences.append(
                FlowOccurrence(step_name=node.step, node=node, ancestors=current_ancestors)
            )
            current_ancestors = current_ancestors | {node.step}

        elif isinstance(node, SplitNode):
            branch_step_names: set[str] = set()
            for branch in node.branches:
                branch_occurrences = _flatten_flow(branch, current_ancestors)
                occurrences.extend(branch_occurrences)
                branch_step_names.update(occ.step_name for occ in branch_occurrences)
            current_ancestors = current_ancestors | branch_step_names

        elif isinstance(node, DecisionNode):
            for outcome_nodes in node.outcomes.values():
                occurrences.extend(_flatten_flow(outcome_nodes, current_ancestors))
            if node.default:
                occurrences.extend(_flatten_flow(node.default, current_ancestors))

    return occurrences


def _all_decision_nodes(nodes: list[FlowNode]) -> list[DecisionNode]:
    decisions: list[DecisionNode] = []
    for node in nodes:
        if isinstance(node, DecisionNode):
            decisions.append(node)
            for outcome_nodes in node.outcomes.values():
                decisions.extend(_all_decision_nodes(outcome_nodes))
            if node.default:
                decisions.extend(_all_decision_nodes(node.default))
        elif isinstance(node, SplitNode):
            for branch in node.branches:
                decisions.extend(_all_decision_nodes(branch))
    return decisions


def _resolve_callable(entrypoint: str) -> None:
    """Raises if `module.path:function` does not import and resolve."""
    if ":" not in entrypoint:
        raise ValueError(f"'{entrypoint}' must be 'module.path:function'")
    module_name, func_name = entrypoint.split(":", 1)
    module = importlib.import_module(module_name)
    if not hasattr(module, func_name):
        raise ValueError(f"'{module_name}' has no attribute '{func_name}'")


def _producers_of(
    artifact_type: str, ancestors: frozenset[str], registrations: dict[str, models.WfStepRegistration]
) -> list[str]:
    """Ancestor step names that produce `artifact_type`, regardless of
    whether their produced version actually satisfies anything."""
    return sorted(
        name
        for name in ancestors
        if name in registrations
        for produced in registrations[name].produces
        if produced["artifact_type"] == artifact_type
    )


def _produced_versions(
    step_name: str, artifact_type: str, registrations: dict[str, models.WfStepRegistration]
) -> list[str]:
    reg = registrations.get(step_name)
    if reg is None:
        return []
    return [p["artifact_version"] for p in reg.produces if p["artifact_type"] == artifact_type]


def _check_consumes_satisfied(
    artifact_type: str,
    version_range: str,
    ancestors: frozenset[str],
    registrations: dict[str, models.WfStepRegistration],
    external_inputs: list[ExternalInputSpec],
) -> tuple[bool, list[str]]:
    producers = _producers_of(artifact_type, ancestors, registrations)
    satisfied = any(
        semver.satisfies(version, version_range)
        for name in producers
        for version in _produced_versions(name, artifact_type, registrations)
    )
    if not satisfied:
        satisfied = any(
            ext.artifact_type == artifact_type and semver.ranges_overlap(ext.version_range, version_range)
            for ext in external_inputs
        )
    return satisfied, producers


def _unsatisfied_detail(
    artifact_type: str,
    version_range: str,
    producers: list[str],
    registrations: dict[str, models.WfStepRegistration],
) -> str:
    if not producers:
        return (
            f"consumes {artifact_type} {version_range} but no upstream step or "
            "external input produces it"
        )
    if len(producers) == 1:
        name = producers[0]
        versions = ", ".join(_produced_versions(name, artifact_type, registrations))
        return (
            f"consumes {artifact_type} {version_range} but the only upstream producer, "
            f"{name}, produces {versions}"
        )
    described = "; ".join(
        f"{name} produces {', '.join(_produced_versions(name, artifact_type, registrations))}"
        for name in producers
    )
    return f"consumes {artifact_type} {version_range} but no upstream producer satisfies it ({described})"


def _wired_artifact_types(
    step_name: str,
    all_references: list[Reference],
    external_inputs_by_name: dict[str, ExternalInputSpec],
) -> set[str]:
    """Every artifact_type that `step_name`'s `inputs` mapping actually wires,
    derived from what each `${...}` reference resolves to — not the
    mapping's logical keys, which are free-form labels the step's own code
    chooses (12-JOB-DEFINITION-FORMAT.md's own minimal example wires
    `repositories: "${steps.repository-ingest.outputs.repository-inventory}"`,
    where the key does not match the artifact type at all)."""
    types: set[str] = set()
    for ref in all_references:
        if ref.step_name != step_name or ref.field != "inputs":
            continue
        if ref.kind == "steps" and len(ref.parts) == 4 and ref.parts[2] == "outputs":
            types.add(ref.parts[3])
        elif ref.kind == "artifacts" and len(ref.parts) == 2:
            types.add(ref.parts[1])
        elif ref.kind == "external" and len(ref.parts) == 2:
            ext = external_inputs_by_name.get(ref.parts[1])
            if ext is not None:
                types.add(ext.artifact_type)
    return types


def _when_leaves(condition: WhenCondition) -> list[WhenLeaf]:
    """Every `WhenLeaf` anywhere in a (possibly nested) `when:` tree —
    22-STEP-SEQUENCING-AND-POLICY.md Part B."""
    if isinstance(condition, WhenAll):
        return [leaf for c in condition.all for leaf in _when_leaves(c)]
    if isinstance(condition, WhenAny):
        return [leaf for c in condition.any for leaf in _when_leaves(c)]
    if isinstance(condition, WhenNot):
        return _when_leaves(condition.not_condition)
    return [condition]


def _detect_cycle(occurrences: list[FlowOccurrence], edges: set[tuple[str, str]]) -> list[str] | None:
    """Kahn's algorithm over (upstream, downstream) edges built from
    consumes/produces satisfaction and explicit steps.* references. Edges by
    construction only ever point from an ancestor to a descendant, so a cycle
    should be structurally impossible in this nested-list flow format — this
    is a defensive backstop for rule 3, not expected to ever fire."""
    node_names = {occ.step_name for occ in occurrences}
    in_degree = {name: 0 for name in node_names}
    adjacency: dict[str, list[str]] = {name: [] for name in node_names}
    for upstream, downstream in edges:
        if upstream in node_names and downstream in node_names and upstream != downstream:
            adjacency[upstream].append(downstream)
            in_degree[downstream] += 1

    queue = [name for name in node_names if in_degree[name] == 0]
    visited = 0
    while queue:
        name = queue.pop()
        visited += 1
        for downstream in adjacency[name]:
            in_degree[downstream] -= 1
            if in_degree[downstream] == 0:
                queue.append(downstream)

    if visited == len(node_names):
        return None
    return sorted(name for name in node_names if in_degree[name] > 0)


def validate_job_definition(
    db: Session, definition: JobDefinitionFile, *, exclude_definition_id: uuid.UUID | None = None
) -> list[ValidationErrorItem]:
    """`exclude_definition_id` is for re-validating an already-stored
    definition in place (registration.py's `revalidate_active_definitions_for_step`)
    — without it, rule 7 would always find the row being re-checked and
    report it as a duplicate of itself. Leave it unset when validating a new,
    not-yet-stored submission (the normal /validate and store paths), where
    any existing row with the same job_name + version is a genuine
    duplicate."""
    errors: list[ValidationErrorItem] = []

    occurrences = _flatten_flow(definition.flow)
    occurrence_by_step = {occ.step_name: occ for occ in occurrences}  # last occurrence wins
    step_names = {occ.step_name for occ in occurrences}

    registrations: dict[str, models.WfStepRegistration] = {
        row.step_name: row
        for row in db.query(models.WfStepRegistration).filter(
            models.WfStepRegistration.step_name.in_(step_names)
        )
    }

    # Rule 1 — every referenced step exists in wf_step_registrations.
    for occ in occurrences:
        if occ.step_name not in registrations:
            errors.append(
                ValidationErrorItem(
                    code="STEP_NOT_REGISTERED",
                    step=occ.step_name,
                    detail=f"step '{occ.step_name}' is not registered",
                )
            )
            continue
        # A renamed (soft-deleted) or retired (deprecated) step still
        # resolves for history, but a definition may not bind to it.
        reg = registrations[occ.step_name]
        if reg.deleted_at is not None or reg.implementation_status == "deprecated":
            successor = f"; use '{reg.superseded_by}'" if reg.superseded_by else ""
            errors.append(
                ValidationErrorItem(
                    code="STEP_RETIRED",
                    step=occ.step_name,
                    detail=f"step '{occ.step_name}' has left the lifecycle{successor}",
                )
            )

    # Rule 2 — every consumes entry is satisfied. THE CONTRACT TRIPWIRE.
    edges: set[tuple[str, str]] = set()
    for occ in occurrences:
        reg = registrations.get(occ.step_name)
        if reg is None:
            continue
        for consumed in reg.consumes:
            artifact_type = consumed["artifact_type"]
            version_range = consumed["version_range"]
            satisfied, producers = _check_consumes_satisfied(
                artifact_type, version_range, occ.ancestors, registrations, definition.external_inputs
            )
            for producer in producers:
                edges.add((producer, occ.step_name))
            if not satisfied and not consumed.get("optional", False):
                errors.append(
                    ValidationErrorItem(
                        code="UNSATISFIED_INPUT",
                        step=occ.step_name,
                        detail=_unsatisfied_detail(artifact_type, version_range, producers, registrations),
                        affected_steps=producers,
                    )
                )

    # Rule 4 material also feeds rule 3's edge set (explicit steps.* references).
    all_references: list[Reference] = []
    for occ in occurrences:
        all_references.extend(extract_references(occ.step_name, "inputs", occ.node.inputs))
        all_references.extend(extract_references(occ.step_name, "config", occ.node.config))

    for ref in all_references:
        if ref.kind == "steps" and len(ref.parts) == 4 and ref.parts[2] == "outputs":
            edges.add((ref.parts[1], ref.step_name))

    # Rule 3 — no cycles.
    cycle = _detect_cycle(occurrences, edges)
    if cycle is not None:
        errors.append(
            ValidationErrorItem(
                code="CYCLE_DETECTED",
                detail=f"a dependency cycle involves: {', '.join(cycle)}",
                affected_steps=cycle,
            )
        )

    # Rule 4 — every ${...} reference resolves. Rule 8 (undeclared parameter)
    # is a specific case of this, reported under its own code.
    declared_param_names = {p.name for p in definition.parameters}
    declared_external_names = {e.logical_name for e in definition.external_inputs}
    for ref in all_references:
        if ref.kind == "params":
            name = ref.parts[1] if len(ref.parts) > 1 else ""
            if name not in declared_param_names:
                errors.append(
                    ValidationErrorItem(
                        code="UNDECLARED_PARAMETER",
                        step=ref.step_name,
                        detail=f"'${{{ref.raw}}}' references an undeclared parameter",
                    )
                )
            continue

        if ref.kind == "external":
            name = ref.parts[1] if len(ref.parts) > 1 else ""
            if name not in declared_external_names:
                errors.append(
                    ValidationErrorItem(
                        code="UNRESOLVED_REFERENCE",
                        step=ref.step_name,
                        detail=f"'${{{ref.raw}}}' references an undeclared external input",
                    )
                )
            continue

        if ref.kind == "steps":
            if len(ref.parts) != 4 or ref.parts[2] != "outputs":
                errors.append(
                    ValidationErrorItem(
                        code="UNRESOLVED_REFERENCE",
                        step=ref.step_name,
                        detail=(
                            f"'${{{ref.raw}}}' is not a valid steps reference "
                            "(expected steps.<step>.outputs.<type>)"
                        ),
                    )
                )
                continue
            upstream_step, artifact_type = ref.parts[1], ref.parts[3]
            occ = occurrence_by_step.get(ref.step_name)
            if occ is None or upstream_step not in occ.ancestors:
                errors.append(
                    ValidationErrorItem(
                        code="UNRESOLVED_REFERENCE",
                        step=ref.step_name,
                        detail=(
                            f"'${{{ref.raw}}}' references step '{upstream_step}', which is not "
                            f"an upstream step of '{ref.step_name}'"
                        ),
                    )
                )
                continue
            if not _produced_versions(upstream_step, artifact_type, registrations):
                errors.append(
                    ValidationErrorItem(
                        code="UNRESOLVED_REFERENCE",
                        step=ref.step_name,
                        detail=(
                            f"'${{{ref.raw}}}' references output '{artifact_type}', which "
                            f"'{upstream_step}' does not produce"
                        ),
                    )
                )
            continue

        if ref.kind == "artifacts":
            artifact_type = ref.parts[1] if len(ref.parts) > 1 else ""
            occ = occurrence_by_step.get(ref.step_name)
            ancestors = occ.ancestors if occ else frozenset()
            if not _producers_of(artifact_type, ancestors, registrations):
                errors.append(
                    ValidationErrorItem(
                        code="UNRESOLVED_REFERENCE",
                        step=ref.step_name,
                        detail=f"'${{{ref.raw}}}' does not match any upstream produced artifact type",
                    )
                )
            continue

        errors.append(
            ValidationErrorItem(
                code="UNRESOLVED_REFERENCE",
                step=ref.step_name,
                detail=f"'${{{ref.raw}}}' has an unrecognised reference kind '{ref.kind}'",
            )
        )

    # Rule 5 — decider outcomes are exhaustive (a `default` branch is the only
    # way to guarantee that, since a decider's return value isn't enumerable).
    for decision in _all_decision_nodes(definition.flow):
        if not decision.default:
            errors.append(
                ValidationErrorItem(
                    code="NON_EXHAUSTIVE_OUTCOMES",
                    step=decision.decision,
                    detail=f"decision '{decision.decision}' has no default outcome",
                )
            )

    # Rule 6 — partitioned steps declare an importable partitioner.
    for occ in occurrences:
        if occ.node.partition is None:
            continue
        try:
            _resolve_callable(occ.node.partition.partitioner)
        except Exception as exc:
            errors.append(
                ValidationErrorItem(
                    code="PARTITIONER_NOT_IMPORTABLE",
                    step=occ.step_name,
                    detail=f"partitioner '{occ.node.partition.partitioner}' is not importable: {exc}",
                )
            )

    # Rule 7 — job_name + version is unique.
    existing_query = db.query(models.WfJobDefinition).filter_by(
        job_name=definition.job_name, version=definition.version
    )
    if exclude_definition_id is not None:
        existing_query = existing_query.filter(models.WfJobDefinition.id != exclude_definition_id)
    existing = existing_query.first()
    if existing is not None:
        errors.append(
            ValidationErrorItem(
                code="DUPLICATE_JOB_VERSION",
                detail=f"'{definition.job_name}' version {definition.version} is already stored",
            )
        )

    # Rule 9 — every non-optional consumes entry is actually wired through
    # the flow node's inputs mapping, not merely satisfiable somewhere
    # upstream (rule 2). This is the gap rule 2 alone cannot see: a consumes
    # entry with no corresponding inputs entry passes rule 2 fine and then
    # fails at runtime with "input was not resolved" — see
    # 22-STEP-SEQUENCING-AND-POLICY.md Part A.
    external_inputs_by_name = {e.logical_name: e for e in definition.external_inputs}
    for occ in occurrences:
        reg = registrations.get(occ.step_name)
        if reg is None:
            continue
        wired_types = _wired_artifact_types(occ.step_name, all_references, external_inputs_by_name)
        for consumed in reg.consumes:
            if consumed.get("optional", False):
                continue
            artifact_type = consumed["artifact_type"]
            if artifact_type in wired_types:
                continue
            producers = _producers_of(artifact_type, occ.ancestors, registrations)
            errors.append(
                ValidationErrorItem(
                    code="UNWIRED_INPUT",
                    step=occ.step_name,
                    detail=(
                        f"requires {artifact_type} {consumed['version_range']} but the flow node "
                        "declares no inputs mapping for it. Add inputs: { "
                        f'{artifact_type}: "${{artifacts.{artifact_type}}}"'
                        " }"
                    ),
                    affected_steps=producers,
                )
            )

    # Rule 10 — when: leaf validation. 22-STEP-SEQUENCING-AND-POLICY.md Part
    # B: "A missing param fails validation at load time" and "step_status
    # referencing a step not earlier in the flow fails validation." A
    # missing `context` key is deliberately NOT checked here — context keys
    # are runtime job-execution state, not statically knowable, and Part B's
    # missing-context behaviour (false under `exists`, fail otherwise) is a
    # runtime concern, not a load-time one.
    for occ in occurrences:
        if occ.node.when is None:
            continue
        for leaf in _when_leaves(occ.node.when):
            if leaf.param is not None and leaf.param not in declared_param_names:
                errors.append(
                    ValidationErrorItem(
                        code="UNDECLARED_PARAMETER",
                        step=occ.step_name,
                        detail=f"when: references undeclared parameter '{leaf.param}'",
                    )
                )
            elif leaf.step_status is not None and leaf.step_status not in occ.ancestors:
                errors.append(
                    ValidationErrorItem(
                        code="INVALID_STEP_STATUS_REFERENCE",
                        step=occ.step_name,
                        detail=(
                            f"when: references step_status of '{leaf.step_status}', which is not "
                            f"an upstream step of '{occ.step_name}'"
                        ),
                    )
                )

    return errors
