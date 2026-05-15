"""Pydantic schemas for risk mitigation tasks + per-occurrence history."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

RecurrenceUnitLiteral = Literal["none", "days", "weeks", "months", "years"]
OccurrenceStatusLiteral = Literal["scheduled", "open", "done", "skipped"]

# Upper bound mirrors the column's headroom — 365 × 10 years gives admins
# room to schedule decade-out reviews without overflow, while preventing
# nonsense like "open this task 100,000 days early".
MAX_LEAD_TIME_DAYS = 3650


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


class MitigationTaskCreate(BaseModel):
    """Payload for ``POST /risks/{risk_id}/mitigation-tasks``.

    ``lead_time_days`` is optional on create — when omitted the service
    layer picks a smart default per ``recurrence_unit`` (1 / 2 / 7 / 14
    for daily / weekly / monthly / yearly, capped at half the cycle so
    the lead window never overlaps the previous occurrence). One-shot
    tasks default to 0 because there is no roll-forward to gate.
    """

    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    owner_id: str | None = None
    due_date: date | None = None
    recurrence_unit: RecurrenceUnitLiteral = "none"
    recurrence_interval: int = Field(default=1, ge=1, le=365)
    lead_time_days: int | None = Field(default=None, ge=0, le=MAX_LEAD_TIME_DAYS)


class MitigationTaskUpdate(BaseModel):
    """Partial update for ``PATCH /mitigation-tasks/{task_id}``.

    ``owner_id`` changes propagate to the **current open occurrence** (its
    ``assigned_owner_id``) so the Todo + notification flow reflects the
    new assignee immediately. Past completed occurrences keep their
    historical owner snapshots and are not modified.

    Recurrence changes apply to **future** occurrences only — the current
    open occurrence keeps its scheduled ``due_date``. Lead-time changes
    take effect on future cycles too, but the API re-evaluates any
    currently-scheduled cycle against the new window so shortening the
    lead time can promote a cycle immediately instead of waiting for the
    next daily promotion run.
    """

    title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    owner_id: str | None = None
    due_date: date | None = None
    recurrence_unit: RecurrenceUnitLiteral | None = None
    recurrence_interval: int | None = Field(default=None, ge=1, le=365)
    lead_time_days: int | None = Field(default=None, ge=0, le=MAX_LEAD_TIME_DAYS)
    is_active: bool | None = None


class OccurrenceCompleteRequest(BaseModel):
    """Optional notes when marking an occurrence done or skipped."""

    notes: str | None = None


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


class MitigationTaskOccurrenceOut(BaseModel):
    id: str
    task_id: str
    sequence: int

    assigned_owner_id: str | None = None
    assigned_owner_name: str | None = None
    due_date: date | None = None

    status: OccurrenceStatusLiteral

    # Set when a scheduled cycle was promoted to open (by the daily loop
    # or via manual "Activate now"). NULL on cycles that were never
    # gated, including everything created before the feature shipped.
    activated_at: datetime | None = None

    completed_at: datetime | None = None
    completed_by: str | None = None
    completed_by_name: str | None = None
    owner_at_completion: str | None = None
    owner_at_completion_name: str | None = None
    completion_notes: str | None = None

    created_at: datetime | None = None
    updated_at: datetime | None = None


class MitigationTaskOut(BaseModel):
    id: str
    reference: str
    risk_id: str

    title: str
    description: str | None = None

    owner_id: str | None = None
    owner_name: str | None = None

    recurrence_unit: RecurrenceUnitLiteral
    recurrence_interval: int
    lead_time_days: int
    is_active: bool

    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Eagerly include the full occurrence history so the UI can render
    # the audit list in one round-trip. Volume is small (a handful per
    # task) so this stays cheap.
    occurrences: list[MitigationTaskOccurrenceOut] = Field(default_factory=list)
