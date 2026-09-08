from __future__ import annotations

from datetime import date, timedelta


def pending_sessions(
    *,
    last_success: date | None,
    expected: date | None,
    calendar: list[date],
    seed_sessions: int,
) -> list[date]:
    """Sessions the daily job must cover. Inclusive of `expected`. Empty if nothing to do.

    First run: last `seed_sessions` calendar days up to expected.
    Catch-up: every calendar session after last_success through expected.
    Same-day re-run: still returns [expected] so the job can fill gaps (idempotent skips).
    """
    if expected is None:
        return []
    sessions = [d for d in calendar if d <= expected]
    if not sessions:
        return []
    if last_success is None:
        return sessions[-seed_sessions:]
    after = [d for d in sessions if d > last_success]
    if after:
        return after
    if last_success == expected:
        return [expected]
    return []


def next_day(d: date) -> date:
    return d + timedelta(days=1)
