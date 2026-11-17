"""Task validators registered with the router for the report's own LLM tasks."""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from srag_sentinel.agent.schemas import NewsPlan
from srag_sentinel.guardrails.news import injection_rule
from srag_sentinel.kg.summaries import summary_validators
from srag_sentinel.kg.validators import kg_validators
from srag_sentinel.llm.router.validators import BUILTIN_VALIDATORS, Issue, Validator
from srag_sentinel.news.models import NewsQuery

MAX_QUERIES = 3


def query_charset(output: BaseModel, payload: Any) -> Sequence[Issue]:
    """Every proposed query must be a valid, operator-free news query."""
    assert isinstance(output, NewsPlan)  # noqa: S101 - registered for this task only
    issues = []
    for index, text in enumerate(output.queries):
        try:
            NewsQuery(text=text)
        except ValidationError:
            issues.append(Issue("bad_query", f"query {index} is not a valid plain-text query"))
        if injection_rule(text):
            issues.append(Issue("suspicious_query", f"query {index} looks like an instruction"))
    return issues


def max_queries(output: BaseModel, payload: Any) -> Sequence[Issue]:
    """At most three queries per report."""
    assert isinstance(output, NewsPlan)  # noqa: S101 - registered for this task only
    if len(output.queries) > MAX_QUERIES:
        return (Issue("too_many_queries", f"at most {MAX_QUERIES} queries are allowed"),)
    return ()


def report_validators() -> Mapping[str, Validator]:
    """Validator registry for the tasks the report graph runs through the router."""
    return {
        **BUILTIN_VALIDATORS,
        "query_charset": query_charset,
        "max_queries": max_queries,
        **kg_validators(),
        **summary_validators(),
    }
