"""engagement probe evidence and matrix confirmations

Revision ID: b4d8f1a3c925
Revises: a7c2e9f4d816
Create Date: 2026-10-12 18:00:00.000000

29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md C10, the probe evidence boundary:
the WCF client matrices ship with the platform and hold platform knowledge
only. A probe run in a client's environment, and a confirmation made on its
evidence, are that client's data: they live here, with the engagement, and
the SOAP report applies them on top of the shipped matrix.

The database itself refuses a confirmation of an entry its decision does not
name, and one with no evidence; at most one live confirmation per entry.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b4d8f1a3c925'
down_revision: Union[str, None] = 'a7c2e9f4d816'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'engagement_probe_evidence',
        sa.Column('engagement_id', sa.Text(), sa.ForeignKey('engagements.id'), primary_key=True),
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('scenario', sa.Text(), nullable=False),
        sa.Column('where', sa.Text(), nullable=False),
        sa.Column('outcome', sa.Text(), nullable=False),
        sa.Column('error_type', sa.Text(), nullable=True),
        sa.Column('attribution', sa.Text(), nullable=True),
        sa.Column('control_of', sa.Text(), nullable=True),
        sa.Column('covers', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('matrix_entries', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('sha256', sa.Text(), nullable=False),
        sa.Column('probed_on', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("outcome IN ('passed', 'failed', 'error')", name='ck_engagement_probe_evidence_outcome'),
    )
    op.create_index('ix_engagement_probe_evidence_engagement_id', 'engagement_probe_evidence', ['engagement_id'])

    op.create_table(
        'engagement_matrix_confirmations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('engagement_id', sa.Text(), sa.ForeignKey('engagements.id'), nullable=False),
        sa.Column('matrix_kind', sa.Text(), nullable=False),
        sa.Column('entry_id', sa.Text(), nullable=False),
        sa.Column('decision_id', sa.Text(), nullable=False),
        sa.Column('decided_by', sa.Text(), nullable=False),
        sa.Column('decided_on', sa.Date(), nullable=False),
        sa.Column('instruction', sa.Text(), nullable=False),
        sa.Column('named_entries', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('evidence_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('reverted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reverted_by', sa.Text(), nullable=True),
        sa.Column('reverted_reason', sa.Text(), nullable=True),
        sa.CheckConstraint("matrix_kind IN ('support', 'platform')", name='ck_engagement_matrix_confirmations_kind'),
        sa.CheckConstraint("named_entries ? entry_id", name='ck_engagement_matrix_confirmations_named'),
        sa.CheckConstraint("jsonb_array_length(evidence_ids) > 0", name='ck_engagement_matrix_confirmations_evidence'),
    )
    op.create_index('uq_engagement_matrix_confirmations_active', 'engagement_matrix_confirmations',
                    ['engagement_id', 'matrix_kind', 'entry_id'], unique=True, postgresql_where=sa.text('reverted_at IS NULL'))


def downgrade() -> None:
    op.drop_index('uq_engagement_matrix_confirmations_active', table_name='engagement_matrix_confirmations')
    op.drop_table('engagement_matrix_confirmations')
    op.drop_index('ix_engagement_probe_evidence_engagement_id', table_name='engagement_probe_evidence')
    op.drop_table('engagement_probe_evidence')
