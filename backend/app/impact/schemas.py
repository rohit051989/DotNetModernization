"""Response shapes for the repository page's Impact section —
33-IMPACT-ANALYSIS.md Part J."""

from typing import Literal

from pydantic import BaseModel, Field

Action = Literal["update", "rewrite", "delete", "create", "review"]
ACTIONS: tuple[str, ...] = ("rewrite", "update", "delete", "create", "review")
# The actions that change an existing file. Create and review are counted
# apart and never added to them.
CHANGES: tuple[str, ...] = ("rewrite", "update", "delete")

PENDING_NOTE = "Impact is analysed for the default resolution and the chosen one. Other resolutions are not analysed."


class ActionCountsOut(BaseModel):
    rewrite: int = 0
    update: int = 0
    delete: int = 0
    create: int = 0
    review: int = 0


class RollupWorkItemOut(BaseModel):
    item_id: str
    item_name: str
    project_path: str
    resolution_id: str
    resolution_name: str
    action: Action
    source: Literal["structural", "client"]
    rule_ids: list[str] = Field(description="The rules that put this work item on the file.")


class ConflictOut(BaseModel):
    """A work-item conflict: one pair of work items, for a person to decide."""
    file_key: str
    kind: Literal["delete_with_change", "create_same_path"]
    first: RollupWorkItemOut
    second: RollupWorkItemOut


class RuleSideOut(BaseModel):
    item_id: str
    item_name: str
    resolution_id: str
    resolution_name: str
    rule_ids: list[str]
    action: Action


class RuleConflictOut(BaseModel):
    """A catalog rule conflict as this repository sees it: a rule pair that
    produces conflicts on more than one pair of work items across the estate,
    fixed once in the rules. `instances` are this repository's."""
    rule_key: str
    kind: Literal["delete_with_change", "create_same_path"]
    first: RuleSideOut
    second: RuleSideOut
    work_items: int = Field(description="Distinct work items affected across the estate.")
    repositories: int = Field(description="Repositories in the engagement where the rule pair conflicts.")
    classified_by: Literal["estate", "repository"] = Field(
        description="estate: from the last estate run. repository: recurs within this repository, and the estate run has not seen it yet.")
    instances: list[ConflictOut]


class EstateInstanceOut(BaseModel):
    repository_id: str
    repository_slug: str | None
    file_key: str
    first_project_path: str
    second_project_path: str


class EstateRuleConflictOut(BaseModel):
    """A catalog rule conflict across one engagement's estate."""
    rule_key: str
    kind: Literal["delete_with_change", "create_same_path"]
    first: RuleSideOut
    second: RuleSideOut
    work_items: int
    repositories: int
    computed_at: str
    instances: list[EstateInstanceOut]


class EngagementRuleConflictsOut(BaseModel):
    engagement_id: str
    rule_conflicts: list[EstateRuleConflictOut]
    note: str


class EngagementCountOut(BaseModel):
    engagement_id: str
    client_name: str
    work_items: int
    repositories: int


class MasterRuleConflictOut(BaseModel):
    """One rule pair, across every engagement whose estate shows it as a
    catalog rule conflict: for catalog authors to fix once."""
    rule_key: str
    kind: Literal["delete_with_change", "create_same_path"]
    first: RuleSideOut
    second: RuleSideOut
    work_items: int
    repositories: int
    engagements: list[EngagementCountOut]


class FileRollupOut(BaseModel):
    file_key: str = Field(description="The file's path, or 'create:' and a proposed path.")
    work_items: list[RollupWorkItemOut]
    hotspot: bool
    conflicts: int
    includes_client: bool


class ResolutionSummaryOut(BaseModel):
    resolution_id: str
    name: str
    roles: list[str]
    effective: bool
    rules_source: Literal["explicit", "default"]
    counts: ActionCountsOut
    changed: int = Field(description="Existing files updated, rewritten or deleted (structural). The headline.")
    created: int = Field(description="New files (structural).")
    to_review: int = Field(description="Files a person should check (structural). Never added to changed.")
    client_changed: int
    client_review: int
    confirmed: int
    possible: int
    known_limits: list[str]
    stale: bool
    stale_reason: str | None


class WorkItemSummaryOut(BaseModel):
    item_id: str
    item_name: str
    project_path: str
    effective_resolution_id: str
    stale: bool
    resolutions: list[ResolutionSummaryOut]
    possible_only: bool = Field(default=False, description="Found only on possible evidence (item-detection): counted "
                                                           "apart, as the work list does.")


class ImpactTotalsOut(BaseModel):
    """Under effective resolutions, files in this repository, structural and
    client. Every figure reconciles: `changes` = by_action rewrite + update +
    delete, one per file per work item, across `files_changed` distinct files;
    `creates` = by_action create, at `new_files` distinct paths; `review_marks`
    = by_action review. `files_to_review` counts files with review marks and
    no change, so it never overlaps `files_changed`."""
    work_items: int
    changes: int
    files_changed: int
    by_action: ActionCountsOut
    creates: int
    new_files: int
    review_marks: int
    files_to_review: int
    client_changes: int = Field(description="Of `changes`, those labelled client.")
    hotspots: int
    conflicts: int = Field(description="Conflict instances, file by file: rule conflicts' instances plus work-item conflicts.")
    rule_conflicts: int = Field(description="Distinct catalog rule pairs producing conflicts on more than one pair of work items.")
    rule_conflict_work_items: int
    work_item_conflicts: int
    stale_work_items: int
    possible_work_items: int = Field(default=0, description="Of `work_items`, those found only on possible evidence: "
                                                            "the work list's \"plus N possible\".")


class RepositoryImpactOut(BaseModel):
    totals: ImpactTotalsOut
    hotspots: list[FileRollupOut]
    rule_conflicts: list[RuleConflictOut]
    work_item_conflicts: list[ConflictOut]
    work_items: list[WorkItemSummaryOut]
    files: list[FileRollupOut]
    client_impact_note: str


class ImpactEntryOut(BaseModel):
    file_repository_slug: str | None = Field(description="Set when the file is in another repository (a client).")
    file_path: str | None
    proposed_path: str | None
    description: str | None
    action: Action
    certainty: Literal["confirmed", "possible"]
    source: Literal["structural", "client"]
    reasons: list[dict]
    traversal_paths: list[str]
    details: list[str] = Field(description="What happens within the file: the config element an update edits, the types it loses.")


class ResolutionImpactOut(ResolutionSummaryOut):
    entries: list[ImpactEntryOut]


class PendingResolutionOut(BaseModel):
    resolution_id: str
    name: str


class WorkItemImpactOut(BaseModel):
    item_id: str
    item_name: str
    project_path: str
    effective_resolution_id: str
    resolutions: list[ResolutionImpactOut]
    pending: list[PendingResolutionOut]
    pending_note: str
