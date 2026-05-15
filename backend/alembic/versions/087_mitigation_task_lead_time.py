"""Lead-time gated recurrence for risk mitigation tasks.

Solves the "open six months early, get drowned in Todo noise" problem from
iteration 1 of the task-driven mitigation feature. Recurring control reviews
("Re-attest cross-border transfer documentation every year") used to land
in the owner's Todo list the moment the previous cycle closed — twelve
months of visible obligation drowning out the things that actually need
attention this week.

Two columns are added:

* ``risk_mitigation_tasks.lead_time_days`` — how many days **before** the
  occurrence's ``due_date`` the cycle should be promoted from the new
  ``scheduled`` status to ``open`` (at which point a system Todo + a
  ``task_assigned`` notification fire). The first occurrence is created
  ``scheduled`` if today is outside the lead window, ``open`` otherwise;
  same for every subsequent cycle created by the completion-driven roll
  forward.
* ``risk_mitigation_task_occurrences.activated_at`` — timestamp captured
  the moment a scheduled occurrence flipped to open, so the audit trail
  can answer "did the daily promotion job actually fire on time?". Stays
  NULL for occurrences that were never gated (i.e. opened directly).

Backfill is conservative: existing **recurring** tasks get a smart
default lead-time derived from the unit, while existing **one-shot**
tasks stay at 0 (gating is meaningless when there is no roll-forward).
Existing open occurrences are left as-is — they were always open, not
promoted from scheduled, so synthesising an ``activated_at`` would be
misleading.

Revision ID: 087
Revises: 086
Create Date: 2026-05-15
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "087"
down_revision: Union[str, None] = "086"
branch_labels: Union[str, tuple[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # 1. Add lead_time_days. Server default 0 so the column add is safe
    #    on a non-empty table; the smart per-unit default is applied via
    #    the backfill UPDATE below so existing recurring tasks inherit
    #    a sensible window instead of "promote on the due date itself".
    op.add_column(
        "risk_mitigation_tasks",
        sa.Column(
            "lead_time_days",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # 2. Backfill smart defaults for existing recurring tasks. Numbers
    #    mirror app/services/risk_mitigation_task_service.default_lead_time_days
    #    — daily: 1, weekly: 2, monthly: 7, yearly: 14. One-shot tasks
    #    keep the column default (0). The (interval × unit-in-days) / 2
    #    cap prevents the lead from overlapping the previous cycle when
    #    the interval is short (e.g. every 2 weeks → cap at 7, default 2
    #    fits comfortably).
    op.execute(
        """
        UPDATE risk_mitigation_tasks
        SET lead_time_days = CASE recurrence_unit
            WHEN 'days'   THEN LEAST(1,  GREATEST(0, (recurrence_interval     ) / 2))
            WHEN 'weeks'  THEN LEAST(2,  GREATEST(1, (recurrence_interval * 7 ) / 2))
            WHEN 'months' THEN LEAST(7,  GREATEST(1, (recurrence_interval * 30) / 2))
            WHEN 'years'  THEN LEAST(14, GREATEST(1, (recurrence_interval *365) / 2))
            ELSE 0
        END
        WHERE recurrence_unit <> 'none'
        """
    )

    # 3. Add activated_at — nullable timestamp, set by the promotion
    #    pathway when a scheduled occurrence flips to open. Pre-feature
    #    open occurrences stay NULL on purpose: they were never gated.
    op.add_column(
        "risk_mitigation_task_occurrences",
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 4. Widen the status column from String(8) to String(16) so the new
    #    "scheduled" literal (9 chars) fits. The previous values
    #    ("open" / "done" / "skipped") all stay inside the 8-char window,
    #    so no data migration is needed.
    op.alter_column(
        "risk_mitigation_task_occurrences",
        "status",
        existing_type=sa.String(length=8),
        type_=sa.String(length=16),
        existing_nullable=False,
        existing_server_default="open",
    )


def downgrade() -> None:
    # Best-effort narrow-back. If any rows are in "scheduled" state when
    # the downgrade runs, this alter would fail — convert them to "open"
    # first to keep the downgrade idempotent against partially-rolled-out
    # data.
    op.execute(
        "UPDATE risk_mitigation_task_occurrences SET status = 'open' WHERE status = 'scheduled'"
    )
    op.alter_column(
        "risk_mitigation_task_occurrences",
        "status",
        existing_type=sa.String(length=16),
        type_=sa.String(length=8),
        existing_nullable=False,
        existing_server_default="open",
    )
    op.drop_column("risk_mitigation_task_occurrences", "activated_at")
    op.drop_column("risk_mitigation_tasks", "lead_time_days")
