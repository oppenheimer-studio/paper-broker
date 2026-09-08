from datetime import date

from paper_broker.application.catchup import pending_sessions


def test_first_run_uses_seed():
    cal = [date(2026, 9, d) for d in range(1, 11)]
    pending = pending_sessions(last_success=None, expected=date(2026, 9, 10), calendar=cal, seed_sessions=3)
    assert pending == [date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10)]


def test_catchup_yesterday_and_today():
    cal = [date(2026, 9, d) for d in range(1, 11)]
    pending = pending_sessions(
        last_success=date(2026, 9, 8), expected=date(2026, 9, 10), calendar=cal, seed_sessions=14
    )
    assert pending == [date(2026, 9, 9), date(2026, 9, 10)]


def test_same_day_rerun_still_lists_expected():
    cal = [date(2026, 9, d) for d in range(1, 11)]
    pending = pending_sessions(
        last_success=date(2026, 9, 10), expected=date(2026, 9, 10), calendar=cal, seed_sessions=14
    )
    assert pending == [date(2026, 9, 10)]


def test_no_expected():
    assert pending_sessions(last_success=None, expected=None, calendar=[], seed_sessions=14) == []
