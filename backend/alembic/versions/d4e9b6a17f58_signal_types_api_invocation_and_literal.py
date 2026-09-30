"""signal types: API_INVOCATION and LITERAL

Revision ID: d4e9b6a17f58
Revises: c3a8f5d20e71
Create Date: 2026-09-30 10:00:00.000000

21-STEP-003-FINGERPRINTING.md Part D "Signal types": two types added to the
step 3 contract with application-fingerprint@1.2.0, so API-usage and literal
findings (DateTime.Now, Encoding.Default, Windows path literals) can be
registered. Widens the signal_type CHECK on both tables that carry it.

Additive. The downgrade refuses (via the restored CHECK) if any row already
uses a new type, rather than silently dropping data.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4e9b6a17f58'
down_revision: Union[str, None] = 'c3a8f5d20e71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = (
    "'ATTRIBUTE', 'BASE_CLASS', 'FILE_PRESENCE', 'INVOCATION', 'CONFIG_ELEMENT', "
    "'PACKAGE', 'ASSEMBLY', 'NAMESPACE', 'ROUTE', 'ENTRY_POINT'"
)
_NEW = _OLD + ", 'API_INVOCATION', 'LITERAL'"

# (table, column, constraint name)
_CONSTRAINTS = [
    ("fingerprint_signals", "signal_type", "ck_fingerprint_signals_type"),
    ("signal_registry_entries", "type", "ck_signal_registry_entries_type"),
]


def _replace(values: str) -> None:
    for table, column, name in _CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"{column} IN ({values})")


def upgrade() -> None:
    _replace(_NEW)


def downgrade() -> None:
    _replace(_OLD)
