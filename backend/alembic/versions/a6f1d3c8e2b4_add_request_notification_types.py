"""Add request lifecycle notification settings.

Revision ID: a6f1d3c8e2b4
Revises: 9e5b7c3a1d42
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a6f1d3c8e2b4"
down_revision: str | Sequence[str] | None = "9e5b7c3a1d42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_COLUMNS = (
    "admin_new_delete_request",
    "admin_new_protection_request",
    "admin_request_cancelled",
    "admin_delete_execution_failed",
    "delete_request_execution_succeeded",
    "delete_request_execution_failed",
)


def upgrade() -> None:
    with op.batch_alter_table("notification_settings") as batch_op:
        for column in _COLUMNS:
            batch_op.add_column(
                sa.Column(
                    column, sa.Boolean(), nullable=False, server_default=sa.false()
                )
            )

    # Preserve existing subscriptions to new-request admin events only.
    op.execute(
        """
        UPDATE notification_settings
        SET admin_new_delete_request = admin_message,
            admin_new_protection_request = admin_message
        WHERE admin_message = 1
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("notification_settings") as batch_op:
        for column in reversed(_COLUMNS):
            batch_op.drop_column(column)
