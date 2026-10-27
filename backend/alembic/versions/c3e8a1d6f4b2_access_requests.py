"""access requests: people ask for access from their own platform's sign-in page, admins decide

- access_requests: one person's request, from the sign-in page of their own platform, with the Windows account and
  machine it runs on (never typed). kind 'access': someone not registered, with their name and a chosen password
  (stored only as its salted hash); 'machine': a registered user asking to add the machine they are on. pending until
  an admin approves or rejects it, with an optional reason. At most one pending request per Windows account.

Only adds; nothing existing is changed or removed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c3e8a1d6f4b2'
down_revision: Union[str, None] = 'b7d2e4f1a9c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'access_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('windows_account', sa.Text(), nullable=False),
        sa.Column('hostname', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('login', sa.Text(), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('status', sa.Text(), nullable=False, server_default='pending'),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decided_by_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.CheckConstraint("kind IN ('access', 'machine')", name='ck_access_requests_kind'),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name='ck_access_requests_status'),
    )
    op.create_index('uq_access_requests_pending', 'access_requests', [sa.text('lower(windows_account)')], unique=True,
                    postgresql_where=sa.text("status = 'pending'"))
    op.create_index('ix_access_requests_account', 'access_requests', [sa.text('lower(windows_account)'), 'requested_at'])


def downgrade() -> None:
    op.drop_index('ix_access_requests_account', table_name='access_requests')
    op.drop_index('uq_access_requests_pending', table_name='access_requests')
    op.drop_table('access_requests')
