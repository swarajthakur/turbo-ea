"""Risk mitigation tasks: replace free-text mitigation with owned tasks + occurrences.

Adds two tables that turn the old single ``risks.mitigation`` text field into a
proper task-driven mitigation model:

* ``risk_mitigation_tasks`` — one row per mitigation activity attached to a risk.
  May be one-shot or recurring (every N days / weeks / months / years).
* ``risk_mitigation_task_occurrences`` — one row per scheduled instance of a task.
  One-shot tasks have exactly one occurrence; recurring tasks accumulate one row
  per completed / skipped / open cycle. Each occurrence snapshots both the
  originally-assigned owner and the owner at the moment of completion, so the
  audit trail answers "who signed off on the Jan 2024 review?" cleanly even
  after years of owner rotation.

Then drops the legacy ``risks.mitigation`` column outright (per the approved
plan — clean cut, no data migration).

Revision ID: 085
Revises: 084
Create Date: 2026-05-14
"""

from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "085"
down_revision: Union[str, None] = "084"
branch_labels: Union[str, tuple[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "risk_mitigation_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "risk_id",
            UUID(as_uuid=True),
            sa.ForeignKey("risks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "owner_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "recurrence_unit",
            sa.String(8),
            nullable=False,
            server_default="none",
        ),
        sa.Column(
            "recurrence_interval",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_risk_mitigation_tasks_risk_id",
        "risk_mitigation_tasks",
        ["risk_id"],
    )
    op.create_index(
        "ix_risk_mitigation_tasks_owner_id",
        "risk_mitigation_tasks",
        ["owner_id"],
    )
    op.create_index(
        "ix_risk_mitigation_tasks_active_risk",
        "risk_mitigation_tasks",
        ["is_active", "risk_id"],
    )

    op.create_table(
        "risk_mitigation_task_occurrences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("risk_mitigation_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "assigned_owner_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(8), nullable=False, server_default="open"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "completed_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "owner_at_completion",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("completion_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "task_id", "sequence", name="uq_risk_mitigation_task_occurrences_task_seq"
        ),
    )
    op.create_index(
        "ix_risk_mitigation_task_occurrences_task_id",
        "risk_mitigation_task_occurrences",
        ["task_id"],
    )
    op.create_index(
        "ix_risk_mitigation_task_occurrences_assigned_owner",
        "risk_mitigation_task_occurrences",
        ["assigned_owner_id"],
    )
    op.create_index(
        "ix_risk_mitigation_task_occurrences_status_due",
        "risk_mitigation_task_occurrences",
        ["status", "due_date"],
    )

    # Clean cut: drop the legacy free-text mitigation column. Any stored
    # text is discarded per the approved plan. Promotion of compliance
    # findings now spawns a one-shot mitigation task instead of writing
    # this column (see services/risk_service.py).
    op.drop_column("risks", "mitigation")


def downgrade() -> None:
    op.add_column(
        "risks",
        sa.Column("mitigation", sa.Text(), nullable=True),
    )

    op.drop_index(
        "ix_risk_mitigation_task_occurrences_status_due",
        table_name="risk_mitigation_task_occurrences",
    )
    op.drop_index(
        "ix_risk_mitigation_task_occurrences_assigned_owner",
        table_name="risk_mitigation_task_occurrences",
    )
    op.drop_index(
        "ix_risk_mitigation_task_occurrences_task_id",
        table_name="risk_mitigation_task_occurrences",
    )
    op.drop_table("risk_mitigation_task_occurrences")

    op.drop_index(
        "ix_risk_mitigation_tasks_active_risk",
        table_name="risk_mitigation_tasks",
    )
    op.drop_index(
        "ix_risk_mitigation_tasks_owner_id",
        table_name="risk_mitigation_tasks",
    )
    op.drop_index(
        "ix_risk_mitigation_tasks_risk_id",
        table_name="risk_mitigation_tasks",
    )
    op.drop_table("risk_mitigation_tasks")
