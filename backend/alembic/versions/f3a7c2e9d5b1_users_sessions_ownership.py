"""users, sessions, ownership, activity, versions, a heartbeat per machine

Revision ID: f3a7c2e9d5b1
Revises: e2b6f4a8c1d5
Create Date: 2026-10-27

Several developers, each running their own platform against one database (docs/VDI-SETUP.md, "Users and sign-in"):
- users and user_hosts: who may sign in, under which Windows account, from which machines; a password stored only as
  a salted scrypt hash (app.auth.passwords). user_sessions: the signed-in sessions, by a hash of their cookie.
- activity_records: who did what, from which machine. Every action that existed before sign-in is recorded once, as
  made "before sign-in": each repository's registration, each decision, each confirmation, each job.
- repositories.owner_user_id: the developer who registered it, who alone (with an admin) may act on it. Existing
  repositories have none until an admin assigns one. repositories.registered_host: the machine it was registered on.
- wf_job_executions.queued_by_host / queued_by_user_id: a backend runs only jobs queued on its own machine.
- version on decision_records, engagement_decisions and engagements, edit_version on catalog_items: an edit
  made from a stale copy is refused.
- platform_backends: one running backend per machine, replacing the one platform per schema of platform_heartbeat
  (left in place, unused, so nothing a client's schema holds is dropped).

Only adds; nothing existing is changed or removed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f3a7c2e9d5b1'
down_revision: Union[str, None] = 'e2b6f4a8c1d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BEFORE_SIGN_IN = 'before sign-in'


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('login', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('windows_account', sa.Text(), nullable=False),
        sa.Column('role', sa.Text(), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('admin', 'developer')", name='ck_users_role'),
    )
    op.create_index('uq_users_login', 'users', [sa.text('lower(login)')], unique=True)
    op.create_index('uq_users_windows_account', 'users', [sa.text('lower(windows_account)')], unique=True)
    op.create_table(
        'user_hosts',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('hostname', sa.Text(), primary_key=True),
    )
    op.create_index('uq_user_hosts_hostname', 'user_hosts', ['user_id', sa.text('lower(hostname)')], unique=True)
    op.create_table(
        'user_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('token_hash', sa.Text(), nullable=False, unique=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('hostname', sa.Text(), nullable=False),
        sa.Column('windows_account', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_user_sessions_user_id', 'user_sessions', ['user_id'])
    op.create_table(
        'activity_records',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('actor', sa.Text(), nullable=False),
        sa.Column('hostname', sa.Text(), nullable=True),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('subject_type', sa.Text(), nullable=True),
        sa.Column('subject_id', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
    )
    op.create_index('ix_activity_records_subject', 'activity_records', ['subject_type', 'subject_id'])
    op.create_index('ix_activity_records_at', 'activity_records', ['at'])
    op.create_table(
        'platform_backends',
        sa.Column('host', sa.Text(), primary_key=True),
        sa.Column('instance_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('os_user', sa.Text(), nullable=False),
        sa.Column('pid', sa.Integer(), nullable=False),
        sa.Column('platform_root', sa.Text(), nullable=False),
        sa.Column('api_port', sa.Integer(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('beat_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column('repositories', sa.Column('owner_user_id', postgresql.UUID(as_uuid=True),
                                            sa.ForeignKey('users.id', ondelete='SET NULL', name='fk_repositories_owner'), nullable=True))
    op.add_column('repositories', sa.Column('registered_host', sa.Text(), nullable=True))
    op.add_column('wf_job_executions', sa.Column('queued_by_host', sa.Text(), nullable=True))
    op.add_column('wf_job_executions', sa.Column('queued_by_user_id', postgresql.UUID(as_uuid=True),
                                                 sa.ForeignKey('users.id', ondelete='SET NULL', name='fk_wf_job_executions_queued_by'),
                                                 nullable=True))
    for table in ('decision_records', 'engagement_decisions', 'engagements'):
        op.add_column(table, sa.Column('version', sa.Integer(), nullable=False, server_default='1'))
    # catalog_items.version is the item's own semantic version (bumped when detection or scope changes); an edit of
    # any field bumps edit_version.
    op.add_column('catalog_items', sa.Column('edit_version', sa.Integer(), nullable=False, server_default='1'))

    # Every action from before sign-in existed, recorded once as such.
    op.execute(f"""
        INSERT INTO activity_records (at, actor, action, subject_type, subject_id, summary)
        SELECT coalesce(first_registered_at, created_at), '{BEFORE_SIGN_IN}', 'register_repository', 'repository', id::text, name
          FROM repositories
        UNION ALL
        SELECT created_at, '{BEFORE_SIGN_IN}', 'record_decision', 'decision', id::text, pattern_id FROM decision_records
        UNION ALL
        SELECT created_at, '{BEFORE_SIGN_IN}', 'record_item_decision', 'item_decision', id::text, item_id FROM engagement_decisions
        UNION ALL
        SELECT created_at, '{BEFORE_SIGN_IN}', 'confirm_matrix_entry', 'matrix_confirmation', id::text, entry_id
          FROM engagement_matrix_confirmations
        UNION ALL
        SELECT created_at, '{BEFORE_SIGN_IN}', 'queue_job', 'job_execution', id::text, triggered_by FROM wf_job_executions
    """)


def downgrade() -> None:
    op.drop_column('catalog_items', 'edit_version')
    for table in ('engagements', 'engagement_decisions', 'decision_records'):
        op.drop_column(table, 'version')
    op.drop_column('wf_job_executions', 'queued_by_user_id')
    op.drop_column('wf_job_executions', 'queued_by_host')
    op.drop_column('repositories', 'registered_host')
    op.drop_column('repositories', 'owner_user_id')
    op.drop_table('platform_backends')
    op.drop_index('ix_activity_records_at', table_name='activity_records')
    op.drop_index('ix_activity_records_subject', table_name='activity_records')
    op.drop_table('activity_records')
    op.drop_index('ix_user_sessions_user_id', table_name='user_sessions')
    op.drop_table('user_sessions')
    op.drop_index('uq_user_hosts_hostname', table_name='user_hosts')
    op.drop_table('user_hosts')
    op.drop_index('uq_users_windows_account', table_name='users')
    op.drop_index('uq_users_login', table_name='users')
    op.drop_table('users')
