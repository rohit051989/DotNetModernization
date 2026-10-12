"""engagement target WCF client version

Revision ID: a7c2e9f4d816
Revises: f3a9c6e1b245
Create Date: 2026-10-12 16:30:00.000000

The WCF client package version an engagement targets (System.ServiceModel.*,
e.g. 8.1.2). The SOAP backend compatibility report flags a matrix entry whose
probe evidence covers an older WCF client than this
(29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md C11). Null: the WCF client version
the matrices record for the engagement's target framework.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7c2e9f4d816'
down_revision: Union[str, None] = 'f3a9c6e1b245'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('engagements', sa.Column('target_wcf_client_version', sa.Text(), nullable=True))
    op.create_check_constraint('ck_engagements_target_wcf_client_version', 'engagements',
                               "target_wcf_client_version IS NULL OR target_wcf_client_version ~ '^[0-9]+(\\.[0-9]+){1,3}(-[0-9A-Za-z.-]+)?$'")


def downgrade() -> None:
    op.drop_constraint('ck_engagements_target_wcf_client_version', 'engagements', type_='check')
    op.drop_column('engagements', 'target_wcf_client_version')
