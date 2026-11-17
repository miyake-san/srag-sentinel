import pytest

from srag_sentinel.agent.report import ReportDraft
from support_report import (
    AS_OF,
    HOSTILE_TITLE,
    make_article,
    make_draft,
    make_metrics,
    make_narrative,
    make_series,
)

__all__ = [
    "AS_OF",
    "HOSTILE_TITLE",
    "make_article",
    "make_draft",
    "make_metrics",
    "make_narrative",
    "make_series",
]


@pytest.fixture
def draft() -> ReportDraft:
    return make_draft(narrative=make_narrative(), articles=(make_article(),))
