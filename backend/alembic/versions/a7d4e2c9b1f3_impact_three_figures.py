"""impact: three figures and file-level actions

Revision ID: a7d4e2c9b1f3
Revises: fb29977e6d01
Create Date: 2026-10-08

impact-analysis 2.0.0 (33-STEP-009-IMPACT-ANALYSIS.md):
- impact_summaries: `files` counted review as touched, so a resolution that
  only asks for review looked as big as one that changes everything. It is
  replaced by three figures never added together: `changed` (update,
  rewrite, delete), `created`, `to_review`; `client_files` by
  `client_changed` and `client_review`. Backfilled from `counts` and the
  client rows, so existing summaries read correctly until the next scan.
- work_item_impacts.details: what happens within a file (the config element
  an update edits, the types a file loses when it is not deleted whole).

Step 9's own derived rows only; no catalog row is written.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a7d4e2c9b1f3'
down_revision: Union[str, None] = 'fb29977e6d01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CLIENT_COUNT = """(SELECT count(*) FROM work_item_impacts w WHERE w.source = 'client' AND w.action {op} 'review'
    AND w.repository_id = s.repository_id AND w.item_id = s.item_id
    AND w.project_path = s.project_path AND w.resolution_id = s.resolution_id)"""


def upgrade() -> None:
    op.add_column('work_item_impacts', sa.Column('details', postgresql.JSONB(astext_type=sa.Text()),
                                                 server_default=sa.text("'[]'::jsonb"), nullable=False))
    for name in ('changed', 'created', 'to_review', 'client_changed', 'client_review'):
        op.add_column('impact_summaries', sa.Column(name, sa.Integer(), server_default='0', nullable=False))
    op.execute("""
        UPDATE impact_summaries SET
            changed = COALESCE((counts->>'update')::int, 0) + COALESCE((counts->>'rewrite')::int, 0)
                      + COALESCE((counts->>'delete')::int, 0),
            created = COALESCE((counts->>'create')::int, 0),
            to_review = COALESCE((counts->>'review')::int, 0)
    """)
    op.execute(f"UPDATE impact_summaries s SET client_changed = {_CLIENT_COUNT.format(op='<>')}, "
               f"client_review = {_CLIENT_COUNT.format(op='=')}")
    # Structural counts have no server default: step 9 always writes them.
    for name in ('changed', 'created', 'to_review'):
        op.alter_column('impact_summaries', name, server_default=None)
    op.drop_column('impact_summaries', 'files')
    op.drop_column('impact_summaries', 'client_files')


def downgrade() -> None:
    op.add_column('impact_summaries', sa.Column('client_files', sa.Integer(), server_default='0', nullable=False))
    op.add_column('impact_summaries', sa.Column('files', sa.Integer(), server_default='0', nullable=False))
    op.execute("UPDATE impact_summaries SET files = changed + to_review, client_files = client_changed + client_review")
    op.alter_column('impact_summaries', 'files', server_default=None)
    for name in ('client_review', 'client_changed', 'to_review', 'created', 'changed'):
        op.drop_column('impact_summaries', name)
    op.drop_column('work_item_impacts', 'details')
