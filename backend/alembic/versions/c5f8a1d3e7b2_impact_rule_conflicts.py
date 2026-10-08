"""impact_rule_conflicts: catalog rule conflicts across the estate

Revision ID: c5f8a1d3e7b2
Revises: b3e1c7a2d9f4
Create Date: 2026-10-08

33-IMPACT-ANALYSIS.md Part G, as implemented: conflicts are classified by the
rule pair that produces them across every repository in the engagement, not
per repository. dependency-and-context-map writes one row per rule-pair key
seen on more than one pair of work items, replaced per engagement at the end
of each estate run (app/impact/conflicts.py). Derived engagement data; no
catalog row is written.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c5f8a1d3e7b2'
down_revision: Union[str, None] = 'b3e1c7a2d9f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('impact_rule_conflicts',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('engagement_id', sa.Text(), nullable=False),
    sa.Column('rule_key', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('first', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('second', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('work_items', sa.Integer(), nullable=False),
    sa.Column('repositories', sa.Integer(), nullable=False),
    sa.Column('instances', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('step_execution_id', sa.UUID(), nullable=True),
    sa.CheckConstraint("kind IN ('delete_with_change', 'create_same_path')", name='ck_impact_rule_conflicts_kind'),
    sa.ForeignKeyConstraint(['engagement_id'], ['engagements.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('engagement_id', 'rule_key', name='uq_impact_rule_conflicts_key')
    )


def downgrade() -> None:
    op.drop_table('impact_rule_conflicts')
