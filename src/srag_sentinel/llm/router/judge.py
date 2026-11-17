"""The LLM judge (ADR 0018, docs/specs/08 §5): rubric-based, structured, never the only barrier.

The judge sees the source text and the candidate as escaped data, has no tools, and is told to
ignore instructions inside them. Its verdict is a signal: the router never lets it override a
hard validator error, and a judge that fails or misbehaves counts as a rejection (fail-closed).
"""

import html
from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from srag_sentinel.llm.ports import ModelError, StructuredModel
from srag_sentinel.llm.prompts import Prompt, load_prompt
from srag_sentinel.llm.router.validators import Issue

ISSUE_CODES = frozenset(
    {
        "unsupported_claim",
        "wrong_entity",
        "wrong_direction",
        "wrong_type",
        "invented_span",
        "new_number",
        "clinical_advice",
        "judge_unavailable",
        "other",
    }
)
MAX_REASON_CHARS = 200
MIN_PASSING_SCORE = 4  # the rubrics define 4 as "minor imprecision, same meaning"
UNAVAILABLE_REASON = "judge unavailable"


class Verdict(BaseModel):
    """Structured judgement of a candidate output against a rubric."""

    model_config = ConfigDict(frozen=True)

    score: int = Field(ge=1, le=5)
    passed: bool
    reasons: list[str] = Field(default_factory=list, max_length=3)
    issues: list[str] = Field(default_factory=list, description="codes from a closed list")


class Judge(Protocol):
    """Evaluates a candidate output; never sees tools and treats ``source`` as data."""

    async def evaluate(
        self,
        *,
        rubric: str,
        source: str,
        output: BaseModel,
        issues: Sequence[Issue],
    ) -> Verdict:
        """Return a verdict for ``output`` given the original ``source`` text."""
        ...


class RubricError(RuntimeError):
    """The requested rubric does not exist or is not the pinned version."""


def load_rubric(ref: str) -> Prompt:
    """Load ``<name>@<version>`` from ``prompts/judge`` and check the pinned version."""
    name, _, version = ref.partition("@")
    if not name.isidentifier() or not version.isdigit():
        raise RubricError(f"invalid rubric reference: {ref!r}")
    try:
        prompt = load_prompt(f"judge/{name}")
    except FileNotFoundError as error:
        raise RubricError(f"unknown rubric: {ref}") from error
    if prompt.version != int(version):
        raise RubricError(f"{ref}: the packaged rubric is version {prompt.version}")
    return prompt


def _clean(verdict: Verdict) -> Verdict:
    """Trim reasons and keep only issue codes from the closed list."""
    reasons = [reason.strip()[:MAX_REASON_CHARS] for reason in verdict.reasons if reason.strip()]
    codes = [code if code in ISSUE_CODES else "other" for code in verdict.issues]
    return Verdict(
        score=verdict.score,
        passed=verdict.passed and verdict.score >= MIN_PASSING_SCORE,
        reasons=reasons,
        issues=list(dict.fromkeys(codes)),
    )


def build_judge_user(source: str, output: BaseModel, issues: Sequence[Issue]) -> str:
    """The judge prompt body: every untrusted value is escaped so it cannot close a tag."""
    findings = "\n".join(f"- {issue.code}: {issue.message}" for issue in issues) or "(none)"
    return (
        f"<untrusted_source>\n{html.escape(source)}\n</untrusted_source>\n"
        f"<candidate_output>\n{html.escape(output.model_dump_json())}\n</candidate_output>\n"
        f"<validator_findings>\n{html.escape(findings)}\n</validator_findings>"
    )


class LlmJudge:
    """A :class:`Judge` backed by a structured-output model (the ``judge`` tier)."""

    def __init__(self, model: StructuredModel) -> None:
        self._model = model

    @property
    def model_name(self) -> str:
        """The judging model, recorded with each verdict."""
        return self._model.name

    async def evaluate(
        self,
        *,
        rubric: str,
        source: str,
        output: BaseModel,
        issues: Sequence[Issue],
    ) -> Verdict:
        """Judge ``output`` against ``rubric``; any failure is a rejection, never a pass."""
        prompt = load_rubric(rubric)
        try:
            verdict = await self._model.invoke_structured(
                Verdict, system=prompt.text, user=build_judge_user(source, output, issues)
            )
        except ModelError:
            return Verdict(
                score=1, passed=False, reasons=[UNAVAILABLE_REASON], issues=["judge_unavailable"]
            )
        return _clean(verdict)
