"""projects.project_sdk: the SDK a project file declares

Revision ID: f1c7a3e9d2b5
Revises: e5b8d2f4a9c6
Create Date: 2026-10-03 16:00:00.000000

Written by step 2 (solution-project-inventory 2.1.0): `Microsoft.NET.Sdk.Web`,
`Microsoft.NET.Sdk.BlazorWebAssembly`, ..., or 'none' for a legacy MSBuild
project. Item detection's `projectSdk` metadata field reads it; step 3's
project_fingerprints.project_sdk awaits MSBuild evaluation and is never set.
Null until the next rescan.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f1c7a3e9d2b5'
down_revision: Union[str, None] = 'e5b8d2f4a9c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("project_sdk", sa.Text()))


def downgrade() -> None:
    op.drop_column("projects", "project_sdk")
