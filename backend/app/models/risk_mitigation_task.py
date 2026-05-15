"""Mitigation tasks attached to risks.

Each :class:`RiskMitigationTask` is a planned mitigation activity owned
by a single user — either one-shot or recurring (e.g. "Review access
rights every 6 months"). Each task accumulates one or more
:class:`RiskMitigationTaskOccurrence` rows, one per scheduled instance.

Per-occurrence owner snapshots (both ``assigned_owner_id`` at creation
and ``owner_at_completion`` at completion) preserve the audit trail when
ownership rotates across years — recurring control reviews can answer
"who signed off on the Jan 2024 review?" cleanly.

Recurrence is completion-driven: when an occurrence is marked done or
skipped, the next occurrence is created with ``due_date`` shifted by the
task's recurrence rule (calendar-correct via ``dateutil.relativedelta``).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class RiskMitigationTask(Base, UUIDMixin, TimestampMixin):
    """A single mitigation activity attached to a risk."""

    __tablename__ = "risk_mitigation_tasks"

    # Unique constraint is declared in ``__table_args__`` below with an
    # explicit name so ``Base.metadata.create_all()`` produces the same
    # constraint identifier the Alembic migration uses, letting the
    # Migration Rollback CI job round-trip ``downgrade -1`` cleanly.
    reference: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("risks.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # "none" | "days" | "weeks" | "months" | "years". When "none", the
    # task is one-shot and is_active flips to False once its single
    # occurrence is completed or skipped.
    recurrence_unit: Mapped[str] = mapped_column(String(8), nullable=False, default="none")
    recurrence_interval: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # See note on ``Survey`` relationships: ``lazy="raise"`` keeps the
    # N+1 protection and surfaces forgotten eager-loads loudly at
    # runtime instead of intermittently returning ``None`` under
    # pytest-xdist parallel sessions.
    occurrences = relationship(
        "RiskMitigationTaskOccurrence",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    __table_args__ = (
        UniqueConstraint("reference", name="uq_risk_mitigation_tasks_reference"),
        Index("ix_risk_mitigation_tasks_risk_id", "risk_id"),
        Index("ix_risk_mitigation_tasks_owner_id", "owner_id"),
        Index("ix_risk_mitigation_tasks_active_risk", "is_active", "risk_id"),
    )


class RiskMitigationTaskOccurrence(Base, UUIDMixin):
    """A single scheduled instance of a :class:`RiskMitigationTask`."""

    __tablename__ = "risk_mitigation_task_occurrences"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("risk_mitigation_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Monotonic counter per task, starts at 1. Unique with task_id.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    # Snapshot of task.owner_id at the moment this occurrence was opened.
    # Frozen once the occurrence completes (the audit trail of who was
    # nominally responsible for this cycle).
    assigned_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # "open" | "done" | "skipped". Terminal once not "open".
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="open")

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Snapshot of task.owner_id at the moment of completion — may differ
    # from assigned_owner_id when the owner changed mid-cycle.
    owner_at_completion: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    completion_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    task = relationship("RiskMitigationTask", back_populates="occurrences", lazy="raise")

    __table_args__ = (
        UniqueConstraint(
            "task_id", "sequence", name="uq_risk_mitigation_task_occurrences_task_seq"
        ),
        Index("ix_risk_mitigation_task_occurrences_task_id", "task_id"),
        Index("ix_risk_mitigation_task_occurrences_assigned_owner", "assigned_owner_id"),
        Index("ix_risk_mitigation_task_occurrences_status_due", "status", "due_date"),
    )
