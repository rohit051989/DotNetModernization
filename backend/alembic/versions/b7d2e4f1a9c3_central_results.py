"""central results: what every view shows, in the database, for developers on other machines

Several developers run their own platform against one database (docs/VDI-SETUP.md, "More than one person"). A
repository's owner scans it on their own machine; everyone else sees its results from here, without that machine's
files (app.results):
- result_contents: one result artifact's JSON, once per checksum, compressed (lz4 where the server has it). `head` is
  its top-level fields other than lists: summaries and counts, which the Overview and each view's header read
  without opening the lists.
- result_artifacts: which artifact of which repository (or engagement, for the estate) each content belongs to.
  The newest RESULTS_KEEP of each kind are kept per repository and per engagement; older ones are pruned.
- conversion_results: a repository's conversions as its owner's machine last saw them, with each one's runbook and
  VERIFICATION.md, for everyone else's Conversion tab.

Only adds; nothing existing is changed or removed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b7d2e4f1a9c3'
down_revision: Union[str, None] = 'f3a7c2e9d5b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'result_contents',
        sa.Column('checksum', sa.Text(), primary_key=True),
        sa.Column('content', postgresql.JSONB(), nullable=False),
        sa.Column('head', postgresql.JSONB(), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('stored_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    # lz4 decompresses faster than the default pglz; a server built without it keeps pglz.
    lz4 = op.get_bind().execute(sa.text(
        "select 'lz4' = any(enumvals) from pg_settings where name = 'default_toast_compression'")).scalar()
    if lz4:
        op.execute("alter table result_contents alter column content set compression lz4")
    op.create_table(
        'result_artifacts',
        sa.Column('artifact_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('wf_artifacts.id', ondelete='CASCADE'),
                  primary_key=True),
        sa.Column('checksum', sa.Text(), sa.ForeignKey('result_contents.checksum'), nullable=False),
        sa.Column('artifact_type', sa.Text(), nullable=False),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('engagement_id', sa.Text(), nullable=True),
        sa.Column('job_execution_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('stored_by_host', sa.Text(), nullable=True),
        sa.Column('stored_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_result_artifacts_repository', 'result_artifacts', ['repository_id', 'artifact_type', 'created_at'])
    op.create_index('ix_result_artifacts_engagement', 'result_artifacts', ['engagement_id', 'artifact_type', 'created_at'])
    op.create_index('ix_result_artifacts_checksum', 'result_artifacts', ['checksum'])
    op.create_table(
        'conversion_results',
        sa.Column('repository_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('repositories.id', ondelete='CASCADE'),
                  primary_key=True),
        sa.Column('conversions', postgresql.JSONB(), nullable=False),
        sa.Column('last_prepare', postgresql.JSONB(), nullable=True),
        sa.Column('published_host', sa.Text(), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )


def downgrade() -> None:
    op.drop_table('conversion_results')
    op.drop_index('ix_result_artifacts_checksum', table_name='result_artifacts')
    op.drop_index('ix_result_artifacts_engagement', table_name='result_artifacts')
    op.drop_index('ix_result_artifacts_repository', table_name='result_artifacts')
    op.drop_table('result_artifacts')
    op.drop_table('result_contents')
