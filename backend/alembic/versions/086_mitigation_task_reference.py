"""Add human-readable reference to risk mitigation tasks.

Adds a ``T-NNNNNN`` reference column to ``risk_mitigation_tasks`` so the
UI can display a stable, monospaced ID next to each task (paralleling
the existing ``R-NNNNNN`` pattern on ``risks``). Format is zero-padded
to a minimum of 6 digits — it auto-widens past T-999999 because the
column is ``String(16)``, exactly matching the risk reference column.

The column lands non-null + unique after a one-shot backfill that
numbers existing tasks by ``created_at`` ascending.

Revision ID: 086
Revises: 085
Create Date: 2026-05-15
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "086"
down_revision: Union[str, None] = "085"
branch_labels: Union[str, tuple[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # 1. Add column as nullable so we can backfill before flipping it.
    op.add_column(
        "risk_mitigation_tasks",
        sa.Column("reference", sa.String(16), nullable=True),
    )

    # 2. Backfill: number existing rows by created_at ascending. Uses a
    #    correlated subquery with row_number() so a single statement
    #    handles arbitrary row counts deterministically. format() emits
    #    "T-NNNNNN" with a minimum width of 6 (auto-widens past 999999
    #    because we'll never use FM in to_char).
    op.execute(
        """
        UPDATE risk_mitigation_tasks AS t
        SET reference = 'T-' || lpad(sub.rn::text, 6, '0')
        FROM (
            SELECT id, row_number() OVER (ORDER BY created_at ASC, id ASC) AS rn
            FROM risk_mitigation_tasks
        ) AS sub
        WHERE t.id = sub.id
        """
    )

    # 3. Constraints: non-null + unique. Done after backfill so existing
    #    rows don't fail the NOT NULL check.
    op.alter_column("risk_mitigation_tasks", "reference", nullable=False)
    op.create_unique_constraint(
        "uq_risk_mitigation_tasks_reference",
        "risk_mitigation_tasks",
        ["reference"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_risk_mitigation_tasks_reference",
        "risk_mitigation_tasks",
        type_="unique",
    )
    op.drop_column("risk_mitigation_tasks", "reference")
