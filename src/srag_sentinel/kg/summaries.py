"""Regional summaries (``kg.summarize_region``): small model + validators + judge, cached.

A summary only restates accepted claims of the region: every sentence cites claim labels, and no
number may appear that is not in the cited claims. The judge (policy: always) and fail-closed
exhaustion mean an unverifiable summary is simply not produced.
"""

import html
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from srag_sentinel.kg.models import SummaryNode
from srag_sentinel.kg.store import KgStore
from srag_sentinel.llm.prompts import Prompt, load_prompt
from srag_sentinel.llm.router.cascade import CallBudget, Router, TaskSpec
from srag_sentinel.llm.router.validators import Issue, Validator

TASK_ID = "kg.summarize_region"
SUMMARY_TTL_DAYS = 7
MAX_CLAIMS = 8
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


class RegionSummary(BaseModel):
    """Structured output of the summary task."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1, max_length=600)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=MAX_CLAIMS)


class SummaryInput(BaseModel):
    """Accepted claims of one region, labelled C1..Cn for citation."""

    model_config = ConfigDict(frozen=True)

    region: str
    claims: tuple[tuple[str, str], ...]  # (record id, text)

    @property
    def labelled(self) -> dict[str, str]:
        """Prompt label -> claim text."""
        return {f"C{index}": text for index, (_, text) in enumerate(self.claims, start=1)}

    def record_of(self, label: str) -> str:
        """Claim record id behind a prompt label."""
        return self.claims[int(label[1:]) - 1][0]


def _numbers(text: str) -> set[str]:
    return {match.replace(",", ".") for match in _NUMBER.findall(text)}


def citations_in_evidence(output: BaseModel, payload: Any) -> Sequence[Issue]:
    """Every cited label must exist in the input."""
    assert isinstance(output, RegionSummary) and isinstance(payload, SummaryInput)  # noqa: S101
    labels = payload.labelled
    unknown = [label for label in output.evidence_ids if label not in labels]
    return [Issue("unknown_citation", f"{label} is not an input claim") for label in unknown]


def no_new_numbers(output: BaseModel, payload: Any) -> Sequence[Issue]:
    """Numbers in the summary must come from the cited claims."""
    assert isinstance(output, RegionSummary) and isinstance(payload, SummaryInput)  # noqa: S101
    labels = payload.labelled
    allowed: set[str] = set()
    for label in output.evidence_ids:
        allowed |= _numbers(labels.get(label, ""))
    extra = _numbers(output.text) - allowed
    return [
        Issue("new_number", f"number {number} is not in the cited claims")
        for number in sorted(extra)
    ]


def summary_validators() -> Mapping[str, Validator]:
    """Validators for the summary task."""
    return {"citations_in_evidence": citations_in_evidence, "no_new_numbers": no_new_numbers}


def summary_prompt() -> Prompt:
    """The versioned system prompt."""
    return load_prompt("kg_summarize_region")


def _build_user(payload: SummaryInput, feedback: Sequence[str]) -> str:
    lines = "\n".join(f"[{label}] {html.escape(text)}" for label, text in payload.labelled.items())
    body = (
        f'<untrusted_claims region="{html.escape(payload.region)}">\n{lines}\n</untrusted_claims>'
    )
    if not feedback:
        return body
    notes = "\n".join(f"- {html.escape(item)}" for item in feedback)
    return f"{body}\n\nA tentativa anterior foi reprovada pelos seguintes motivos:\n{notes}"


def summary_task() -> TaskSpec[SummaryInput, RegionSummary]:
    """Everything the router needs to run the summary task."""
    return TaskSpec(
        task_id=TASK_ID,
        output_schema=RegionSummary,
        system_prompt=summary_prompt().text,
        build_user=_build_user,
        judge_source=lambda payload: "\n".join(f"[{k}] {v}" for k, v in payload.labelled.items()),
    )


async def ensure_region_summary(  # noqa: PLR0913 - dependency injection of the collaborators
    region: str,
    *,
    store: KgStore,
    router: Router,
    run_id: str,
    now: datetime,
    budget: CallBudget | None = None,
) -> SummaryNode | None:
    """Return a fresh cached summary or generate one; ``None`` when nothing can be verified."""
    cached = await store.fresh_summary(region, now)
    if cached is not None:
        return cached
    claims = await store.region_claims(region, now, MAX_CLAIMS)
    if not claims:
        return None
    payload = SummaryInput(region=region, claims=tuple(claims))
    outcome = await router.run(summary_task(), payload, budget=budget)
    if not outcome.accepted or outcome.output is None:
        return None
    node = SummaryNode(
        region=region,
        text=outcome.output.text,
        evidence_ids=tuple(payload.record_of(label) for label in outcome.output.evidence_ids),
        produced_by=f"{outcome.tier}/{outcome.model}/{summary_prompt().ref}",
        judge=(
            {
                "rubric": outcome.judge.rubric,
                "score": outcome.judge.score,
                "passed": outcome.judge.passed,
            }
            if outcome.judge
            else None
        ),
        run_id=run_id,
        created_at=now,
        valid_until=now + timedelta(days=SUMMARY_TTL_DAYS),
    )
    await store.write_summary(node)
    return node
