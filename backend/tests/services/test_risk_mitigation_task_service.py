"""Unit tests for the pure helpers in ``risk_mitigation_task_service``.

DB-touching lifecycle paths are exercised by the API integration tests in
``tests/api/test_risk_mitigation_tasks.py``. Here we cover the
calendar-correct recurrence math and recurrence-rule edge cases.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.risk_mitigation_task_service import (
    OCCURRENCE_STATUSES,
    RECURRENCE_UNITS,
    _add_months,
    compute_next_due,
    default_lead_time_days,
    is_within_lead_window,
)

# ---------------------------------------------------------------------------
# Calendar month math — Jan 31 + 1 month MUST land on Feb 28/29, not Mar 3
# ---------------------------------------------------------------------------


def test_add_months_simple_addition_within_year():
    assert _add_months(date(2026, 3, 15), 2) == date(2026, 5, 15)


def test_add_months_crosses_year_boundary():
    assert _add_months(date(2026, 11, 5), 3) == date(2027, 2, 5)


def test_add_months_clamps_to_last_day_of_short_month():
    # Jan 31 + 1 month → Feb 28 in a common year, Feb 29 in a leap year.
    assert _add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert _add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)


def test_add_months_clamps_31_to_30_day_month():
    assert _add_months(date(2026, 3, 31), 1) == date(2026, 4, 30)


def test_add_months_handles_year_jumps():
    assert _add_months(date(2026, 5, 14), 24) == date(2028, 5, 14)


# ---------------------------------------------------------------------------
# compute_next_due — dispatches across units
# ---------------------------------------------------------------------------


def test_compute_next_due_for_one_shot_returns_none():
    assert compute_next_due(date(2026, 5, 14), "none", 1) is None


def test_compute_next_due_for_days():
    assert compute_next_due(date(2026, 5, 14), "days", 1) == date(2026, 5, 15)
    assert compute_next_due(date(2026, 5, 14), "days", 30) == date(2026, 6, 13)


def test_compute_next_due_for_weeks():
    # 2 weeks = 14 days; spans a month boundary.
    assert compute_next_due(date(2026, 5, 14), "weeks", 2) == date(2026, 5, 28)
    assert compute_next_due(date(2026, 5, 28), "weeks", 1) == date(2026, 6, 4)


def test_compute_next_due_for_months():
    # The 6-month review use case from the user.
    assert compute_next_due(date(2026, 1, 15), "months", 6) == date(2026, 7, 15)


def test_compute_next_due_for_months_clamps_day():
    assert compute_next_due(date(2026, 1, 31), "months", 1) == date(2026, 2, 28)


def test_compute_next_due_for_years():
    assert compute_next_due(date(2026, 5, 14), "years", 1) == date(2027, 5, 14)
    # Leap-day rollover: Feb 29, 2024 + 1 year → Feb 28, 2025 (clamped).
    assert compute_next_due(date(2024, 2, 29), "years", 1) == date(2025, 2, 28)


def test_compute_next_due_rejects_unknown_unit():
    assert compute_next_due(date(2026, 5, 14), "fortnights", 1) is None


def test_compute_next_due_rejects_zero_interval():
    assert compute_next_due(date(2026, 5, 14), "days", 0) is None
    assert compute_next_due(date(2026, 5, 14), "months", 0) is None


# ---------------------------------------------------------------------------
# Vocabulary exports
# ---------------------------------------------------------------------------


def test_recurrence_units_include_none_and_all_intervals():
    assert RECURRENCE_UNITS == ("none", "days", "weeks", "months", "years")


def test_occurrence_statuses_include_scheduled_and_three_lifecycle_states():
    # "scheduled" is the lead-time gated pre-state; "open" is the live
    # workable state; "done" / "skipped" are the immutable terminals.
    assert OCCURRENCE_STATUSES == ("scheduled", "open", "done", "skipped")


# ---------------------------------------------------------------------------
# Guard against accidentally introducing fractional/negative intervals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unit,interval",
    [
        ("days", -1),
        ("weeks", -2),
        ("months", -3),
        ("years", 0),
    ],
)
def test_compute_next_due_rejects_non_positive_intervals(unit: str, interval: int):
    assert compute_next_due(date(2026, 5, 14), unit, interval) is None


# ---------------------------------------------------------------------------
# default_lead_time_days — per-unit defaults capped at half the cycle
# ---------------------------------------------------------------------------


def test_default_lead_time_is_zero_for_one_shot_tasks():
    # One-shot tasks have no roll-forward to gate, so the lead time is
    # meaningless and defaults to 0.
    assert default_lead_time_days("none", 1) == 0


def test_default_lead_time_for_canonical_recurring_units():
    # The canonical per-unit defaults: 1 / 2 / 7 / 14 days for daily /
    # weekly / monthly / yearly tasks at interval=1. These are picked so
    # the assignee gets a useful reminder window without sitting on an
    # open Todo for the bulk of the cycle.
    assert default_lead_time_days("days", 30) == 1
    assert default_lead_time_days("weeks", 4) == 2
    assert default_lead_time_days("months", 6) == 7
    assert default_lead_time_days("years", 1) == 14


def test_default_lead_time_caps_at_half_the_cycle():
    # Daily (every 1 day) caps the lead at floor(1 / 2) = 0 so the lead
    # window never overlaps the previous cycle.
    assert default_lead_time_days("days", 1) == 0
    # Every 2 days → cap = 1, default = 1 → result 1.
    assert default_lead_time_days("days", 2) == 1
    # Every 1 week → cap = floor(7 / 2) = 3, default = 2 → result 2.
    assert default_lead_time_days("weeks", 1) == 2


def test_default_lead_time_uses_per_unit_default_for_long_intervals():
    # Yearly tasks always default to 14 days regardless of interval — the
    # cap (interval × 365 / 2) is always far higher than the per-unit
    # baseline, so the baseline always wins.
    assert default_lead_time_days("years", 5) == 14
    # Monthly tasks at interval 6 cap at (6 × 30 / 2) = 90, default 7 wins.
    assert default_lead_time_days("months", 6) == 7


def test_default_lead_time_rejects_unknown_unit_returns_zero():
    assert default_lead_time_days("fortnights", 1) == 0
    assert default_lead_time_days("", 1) == 0


# ---------------------------------------------------------------------------
# is_within_lead_window — boundary cases
# ---------------------------------------------------------------------------


def test_within_lead_window_exact_boundary_is_inside():
    # today == due_date - lead_time_days is the first day in the window.
    assert is_within_lead_window(date(2026, 6, 1), 7, date(2026, 5, 25)) is True


def test_within_lead_window_one_day_before_boundary_is_outside():
    assert is_within_lead_window(date(2026, 6, 1), 7, date(2026, 5, 24)) is False


def test_within_lead_window_after_due_date_is_inside():
    # Once the due date has passed, the cycle is well within the window
    # (the assignee is now overdue but still owns the task).
    assert is_within_lead_window(date(2026, 6, 1), 7, date(2026, 6, 30)) is True


def test_within_lead_window_zero_lead_means_open_only_on_due_date():
    # lead = 0 collapses the window to the due date itself — relevant
    # for one-shot tasks created far ahead of time.
    assert is_within_lead_window(date(2026, 6, 1), 0, date(2026, 5, 31)) is False
    assert is_within_lead_window(date(2026, 6, 1), 0, date(2026, 6, 1)) is True


def test_within_lead_window_null_due_date_is_always_inside():
    # NULL due_date == "no deadline" — the cycle should always be live.
    assert is_within_lead_window(None, 14, date(2026, 5, 14)) is True


def test_within_lead_window_clamps_negative_lead_to_zero():
    # Negative lead would be a programmer error — clamped to 0 so the
    # window doesn't accidentally invert.
    assert is_within_lead_window(date(2026, 6, 1), -10, date(2026, 5, 31)) is False
    assert is_within_lead_window(date(2026, 6, 1), -10, date(2026, 6, 1)) is True


# ---------------------------------------------------------------------------
# Task reference format — width auto-extends past T-999999
# ---------------------------------------------------------------------------


def test_task_reference_format_pads_to_six_digits():
    # The format spec is min-width, not max. These three should all
    # produce the canonical reference string the next_task_reference
    # helper emits.
    assert f"T-{1:06d}" == "T-000001"
    assert f"T-{42:06d}" == "T-000042"
    assert f"T-{999999:06d}" == "T-999999"


def test_task_reference_format_widens_beyond_six_digits():
    # Past 999999 the format auto-widens. The column is String(16), and
    # "T-" eats 2 chars, leaving 14 digits of headroom (~10^14 tasks).
    # This is the canonical answer to "what happens after T-999999?" —
    # nothing breaks, the reference is just one char wider per decade.
    assert f"T-{1_000_000:06d}" == "T-1000000"
    assert f"T-{12_345_678:06d}" == "T-12345678"
    # Confirm a 14-digit reference still fits in the 16-char column.
    assert len(f"T-{99_999_999_999_999:06d}") == 16
