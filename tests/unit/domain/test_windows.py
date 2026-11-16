from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from srag_sentinel.domain.windows import Window, window_pair


def test_window_pair_for_30_days_is_contiguous_and_inclusive() -> None:
    previous, current = window_pair(date(2026, 11, 15), 30)

    assert current == Window(start=date(2026, 10, 17), end=date(2026, 11, 15))
    assert previous == Window(start=date(2026, 9, 17), end=date(2026, 10, 16))
    assert current.days == 30
    assert previous.days == 30


def test_window_contains_is_inclusive_on_both_ends() -> None:
    window = Window(start=date(2026, 1, 1), end=date(2026, 1, 3))

    assert window.contains(date(2026, 1, 1))
    assert window.contains(date(2026, 1, 3))
    assert not window.contains(date(2025, 12, 31))
    assert not window.contains(date(2026, 1, 4))


def test_window_rejects_end_before_start() -> None:
    with pytest.raises(ValueError, match="end"):
        Window(start=date(2026, 1, 2), end=date(2026, 1, 1))


@pytest.mark.parametrize("days", [0, -1])
def test_window_pair_rejects_non_positive_length(days: int) -> None:
    with pytest.raises(ValueError, match="window_days"):
        window_pair(date(2026, 11, 15), days)


@given(
    as_of=st.dates(min_value=date(2019, 1, 1), max_value=date(2030, 12, 31)),
    days=st.integers(min_value=1, max_value=90),
)
def test_windows_are_disjoint_adjacent_and_of_requested_length(as_of: date, days: int) -> None:
    previous, current = window_pair(as_of, days)

    assert current.end == as_of
    assert current.days == previous.days == days
    assert (current.start - previous.end).days == 1
