"""Inclusive date windows used by the metrics."""

from datetime import date, timedelta
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator


class Window(BaseModel):
    """Inclusive ``[start, end]`` date interval."""

    model_config = ConfigDict(frozen=True)

    start: date
    end: date

    @model_validator(mode="after")
    def _end_not_before_start(self) -> Self:
        if self.end < self.start:
            raise ValueError("end must not be before start")
        return self

    @property
    def days(self) -> int:
        """Number of calendar days covered (inclusive)."""
        return (self.end - self.start).days + 1

    def contains(self, day: date) -> bool:
        """Return whether ``day`` lies inside the window."""
        return self.start <= day <= self.end


def window_pair(as_of: date, window_days: int) -> tuple[Window, Window]:
    """Return ``(previous, current)`` windows of ``window_days`` ending at ``as_of``.

    The current window is ``[as_of - window_days + 1, as_of]`` and the previous one is the
    adjacent, non-overlapping block of the same length right before it.
    """
    if window_days < 1:
        raise ValueError("window_days must be at least 1")
    current = Window(start=as_of - timedelta(days=window_days - 1), end=as_of)
    previous_end = current.start - timedelta(days=1)
    previous = Window(start=previous_end - timedelta(days=window_days - 1), end=previous_end)
    return previous, current
