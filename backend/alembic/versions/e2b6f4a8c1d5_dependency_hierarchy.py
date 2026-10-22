"""dependency hierarchy

Revision ID: e2b6f4a8c1d5
Revises: d7a3c1e9b4f2
Create Date: 2026-10-22

hierarchy_nodes / hierarchy_edges: each repository's dependency graph, written by the dependency-hierarchy step
(37-DEPENDENCY-HIERARCHY.md Part D) and replaced on each run. The repository page loads a node's children from them
when the node is expanded. Two new tables; nothing existing changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e2b6f4a8c1d5'
down_revision: Union[str, None] = 'd7a3c1e9b4f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'hierarchy_nodes',
        sa.Column('repository_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('repositories.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('node_id', sa.Text(), primary_key=True),
        sa.Column('node_type', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('is_root', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='SET NULL'), nullable=True),
        sa.Column('detail', postgresql.JSONB(), nullable=False),
        sa.Column('step_execution_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("node_type IN ('project', 'package', 'assembly')", name='ck_hierarchy_nodes_type'),
        sa.CheckConstraint("status IN ('checked', 'not_checked')", name='ck_hierarchy_nodes_status'),
    )
    op.create_index('ix_hierarchy_nodes_name', 'hierarchy_nodes', ['repository_id', sa.text('lower(name)')])
    op.create_table(
        'hierarchy_edges',
        sa.Column('repository_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('repositories.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('from_node', sa.Text(), primary_key=True),
        sa.Column('to_node', sa.Text(), primary_key=True),
        sa.Column('kind', sa.Text(), primary_key=True),
        sa.Column('resolution', sa.Text(), nullable=False),
        sa.Column('closes_cycle', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('detail', postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("kind IN ('project_reference', 'package_reference', 'central_package_version', 'packages_config', "
                           "'assembly_reference', 'package_dependency')", name='ck_hierarchy_edges_kind'),
    )
    op.create_index('ix_hierarchy_edges_to', 'hierarchy_edges', ['repository_id', 'to_node'])


def downgrade() -> None:
    op.drop_index('ix_hierarchy_edges_to', table_name='hierarchy_edges')
    op.drop_table('hierarchy_edges')
    op.drop_index('ix_hierarchy_nodes_name', table_name='hierarchy_nodes')
    op.drop_table('hierarchy_nodes')
