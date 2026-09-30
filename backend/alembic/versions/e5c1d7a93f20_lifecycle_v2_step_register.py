"""lifecycle v2.0: 35-step register — rename, retire, soft-delete

Revision ID: e5c1d7a93f20
Revises: d8f3a15c72be
Create Date: 2026-09-29 10:00:00.000000

17-LIFECYCLE-STEPS.md v2.0 cuts the lifecycle from 51 steps to 35. Numbering
and display names are the seed's job (lifecycle_steps.yaml); this migration
does only what the seed cannot: retire registrations the new register no
longer contains, and move the slugs that changed meaning.

Two distinct mechanisms, mirroring CLAUDE.md rule 7:

- **Soft delete** (`deleted_at`/`deleted_by`, plus `superseded_by`) — the
  slug was *renamed*: the step lives on under a new step_name. Same
  insert-new -> repoint -> soft-delete-old sequence as the pattern-id rename
  in d5a7c3e91b04. The old row disappears from the step list but still
  resolves by name, so wf_step_executions history (which references step
  names, with no FK) stays linked to a real registration.
- **Deprecate** (`implementation_status = 'deprecated'`) — the step *left the
  lifecycle*: retired outright (moved into the catalog / approach UIs) or
  absorbed as a responsibility into a v2 step. Stays listed, shown as
  deprecated.

Both set lifecycle_step_no to NULL so a retired row never collides with a v2
number; the former number is kept in `retired_reason`.

wf_step_executions is deliberately NOT repointed: history records what ran,
under the name it ran as. Only `step_policies` (the one FK onto
wf_step_registrations) is repointed, since a policy is forward-looking.

The new rename targets are inserted here as bare stubs because
`step_policies` needs them to exist before it can be repointed; the seed
fills in their v2 descriptive fields.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5c1d7a93f20'
down_revision: Union[str, None] = 'd8f3a15c72be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SPEC = "17-LIFECYCLE-STEPS.md v2.0"

# New step_name -> (lifecycle_step_no, display_name, owner_code, viewpoint).
# Only the rename targets; every other v2 step is created by the seed.
_NEW_STEPS = {
    "item-detection": (6, "Catalog item detection & occurrence mapping", "P", "DEVELOPMENT"),
    "unclaimed-signal-report": (9, "Unclaimed signal report", "P", "DEVELOPMENT"),
    "dependency-and-context-map": (
        10, "Dependency graph, context map & external endpoint register", "P", "CONTEXT"
    ),
    "contract-snapshot": (14, "Contract snapshot", "P", "FUNCTIONAL"),
    "independent-verification": (
        20, "Independent build, test & scan verification", "P", "DEVELOPMENT"
    ),
}

# Renamed: (old step_name, old lifecycle_step_no, new step_name).
# api-contract-snapshot -> contract-snapshot is not in the spec's four-row
# slug table, but the v2 register names the step `contract-snapshot` and
# declares step_name values fixed, so it is handled the same way.
_RENAMES = [
    ("pattern-classification", 4, "item-detection"),
    ("pattern-discovery-clustering", 5, "unclaimed-signal-report"),
    ("pattern-validation", 6, "unclaimed-signal-report"),
    ("dependency-graph-construction", 7, "dependency-and-context-map"),
    ("api-contract-snapshot", 19, "contract-snapshot"),
    ("independent-build-test-verification", 31, "independent-verification"),
]

# Left the lifecycle: (step_name, old lifecycle_step_no, superseded_by, why).
# superseded_by is set only where the spec's old-to-new mapping names a
# single v2 step; "18 or 19" (depends on the item's scope) leaves it NULL.
_RETIRED = [
    ("impact-map-generation", 8, None, "the work list is the impact map"),
    ("inventory-dashboard-population", 11, None, "a read view over platform tables, not a step"),
    ("target-state-options-retrieval", 13, None, "target state governance moved to the catalog UI"),
    ("target-state-approval", 14, None, "target state governance moved to the catalog UI"),
    ("decision-record-capture", 15, None, "target state governance moved to the catalog UI"),
    ("accelerator-binding", 16, None, "moved to the conversion approach registry"),
    ("guardrail-playbook-generation", 21, None, "guardrails are conversion approach configuration"),
    ("engine-assessment", 23, None, "absorbed into steps 18/19 (conversion, by item scope)"),
    ("plan-validation", 24, "plan-approval-gate", "absorbed into step 17"),
    ("framework-retarget-package-upgrade", 25, None, "absorbed into steps 18/19 (conversion, by item scope)"),
    ("build-fix-loop", 26, None, "absorbed into steps 18/19 (conversion, by item scope)"),
    ("breaking-change-remediation", 27, None, "absorbed into steps 18/19 (conversion, by item scope)"),
    ("windows-to-linux-remediation", 28, "occurrence-scope-conversion", "absorbed into step 19"),
    ("configuration-externalization", 29, "occurrence-scope-conversion", "absorbed into step 19"),
    ("logging-health-endpoint-adaptation", 30, "occurrence-scope-conversion", "absorbed into step 19"),
    ("characterization-test-execution", 33, "independent-verification", "absorbed into step 20"),
    ("linux-compatibility-security-scan", 34, "independent-verification", "absorbed into step 20"),
    ("container-build-file-generation", 35, "application-scope-conversion", "absorbed into step 18"),
    ("ocp4-manifest-generation", 42, "application-scope-conversion", "absorbed into step 18"),
    ("cicd-pipeline-update", 45, "application-scope-conversion", "absorbed into step 18"),
]

_STUB_CONFIG = '{"exit_status": "NOT_IMPLEMENTED", "message": "Awaiting implementation by platform team"}'


def _exists(conn, step_name: str) -> bool:
    return conn.execute(
        sa.text("SELECT 1 FROM wf_step_registrations WHERE step_name = :s"), {"s": step_name}
    ).first() is not None


def _insert_stub(conn, step_name: str) -> None:
    step_no, display_name, owner_code, viewpoint = _NEW_STEPS[step_name]
    conn.execute(
        sa.text(
            """
            INSERT INTO wf_step_registrations (
                step_name, lifecycle_step_no, display_name, owner_code, version,
                adapter_type, adapter_config, consumes, produces,
                implementation_status, viewpoint
            ) VALUES (
                :step_name, :step_no, :display_name, :owner_code, '0.0.0',
                'stub', CAST(:config AS JSONB), '[]'::jsonb, '[]'::jsonb,
                'stub', :viewpoint
            )
            ON CONFLICT (step_name) DO NOTHING
            """
        ),
        {
            "step_name": step_name,
            "step_no": step_no,
            "display_name": display_name,
            "owner_code": owner_code,
            "viewpoint": viewpoint,
            "config": _STUB_CONFIG,
        },
    )


def _repoint_policies(conn, from_name: str, to_name: str) -> None:
    """Moves step_policies rows to the new name. Two old slugs merge into
    unclaimed-signal-report, so a row is only moved when the new name has no
    policy at that same scope yet — the partial unique indexes would reject
    a second one. A row that can't move stays on the old (still resolvable)
    registration rather than being dropped."""
    conn.execute(
        sa.text(
            """
            UPDATE step_policies p SET step_name = :to_name, updated_at = now()
            WHERE p.step_name = :from_name
              AND NOT EXISTS (
                SELECT 1 FROM step_policies q
                WHERE q.step_name = :to_name
                  AND q.engagement_id IS NOT DISTINCT FROM p.engagement_id
              )
            """
        ),
        {"from_name": from_name, "to_name": to_name},
    )


def upgrade() -> None:
    op.add_column("wf_step_registrations", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("wf_step_registrations", sa.Column("deleted_by", sa.Text(), nullable=True))
    op.add_column("wf_step_registrations", sa.Column("superseded_by", sa.Text(), nullable=True))
    op.add_column("wf_step_registrations", sa.Column("retired_reason", sa.Text(), nullable=True))

    conn = op.get_bind()

    # 1-3. Renames: insert-new, repoint, soft-delete-old.
    for old_name, old_no, new_name in _RENAMES:
        if not _exists(conn, old_name):
            # Fresh database — the seed registers the v2 names directly.
            continue
        _insert_stub(conn, new_name)
        _repoint_policies(conn, old_name, new_name)
        conn.execute(
            sa.text(
                """
                UPDATE wf_step_registrations
                SET deleted_at = now(), deleted_by = :deleted_by,
                    superseded_by = :new_name, retired_reason = :reason,
                    lifecycle_step_no = NULL, updated_at = now()
                WHERE step_name = :old_name
                """
            ),
            {
                "old_name": old_name,
                "new_name": new_name,
                "deleted_by": f"renamed to '{new_name}' (migration {revision})",
                "reason": f"Former step {old_no}; renamed to '{new_name}' in {SPEC}",
            },
        )

    # 4. Retirements: deprecate, keep listed. superseded_by may name a v2
    #    step the seed has not created yet — it is a plain text pointer, not
    #    an FK, precisely so the order doesn't matter.
    for step_name, old_no, superseded_by, why in _RETIRED:
        conn.execute(
            sa.text(
                """
                UPDATE wf_step_registrations
                SET implementation_status = 'deprecated', superseded_by = :superseded_by,
                    retired_reason = :reason, lifecycle_step_no = NULL, updated_at = now()
                WHERE step_name = :step_name
                """
            ),
            {
                "step_name": step_name,
                "superseded_by": superseded_by,
                "reason": f"Former step {old_no}; left the lifecycle in {SPEC}: {why}",
            },
        )

    # The C (Copilot engine) owner code is retired as a step owner. Kept in
    # the value list so deprecated rows keep their true historical owner,
    # but no live registration may carry it.
    op.create_check_constraint(
        "ck_wf_step_registrations_no_engine_owner",
        "wf_step_registrations",
        "owner_code <> 'C' OR implementation_status = 'deprecated'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_wf_step_registrations_no_engine_owner", "wf_step_registrations", type_="check")
    conn = op.get_bind()

    for step_name, old_no, _superseded_by, _why in _RETIRED:
        conn.execute(
            sa.text(
                "UPDATE wf_step_registrations SET implementation_status = 'stub', "
                "lifecycle_step_no = :old_no WHERE step_name = :step_name "
                "AND implementation_status = 'deprecated'"
            ),
            {"step_name": step_name, "old_no": old_no},
        )

    for old_name, old_no, new_name in _RENAMES:
        conn.execute(
            sa.text(
                "UPDATE wf_step_registrations SET deleted_at = NULL, deleted_by = NULL, "
                "lifecycle_step_no = :old_no WHERE step_name = :old_name"
            ),
            {"old_name": old_name, "old_no": old_no},
        )
        conn.execute(
            sa.text("UPDATE step_policies SET step_name = :old_name WHERE step_name = :new_name"),
            {"old_name": old_name, "new_name": new_name},
        )

    op.drop_column("wf_step_registrations", "retired_reason")
    op.drop_column("wf_step_registrations", "superseded_by")
    op.drop_column("wf_step_registrations", "deleted_by")
    op.drop_column("wf_step_registrations", "deleted_at")
    # The v2 rows the seed created are left in place: they may already have
    # executions, and a downgrade must not orphan history. Reseed from the
    # v1 lifecycle_steps.yaml to restore v1 numbering on shared slugs.
