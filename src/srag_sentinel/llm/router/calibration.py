"""Judge calibration: agreement with labelled items (accuracy, Cohen's kappa, false accepts).

A judge that approves what a human rejected is the costly failure, so false accepts are
reported on their own and not only through kappa.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from srag_sentinel.llm.router.judge import Judge

TARGET_KAPPA = 0.6


@dataclass(frozen=True)
class LabelledItem:
    """A candidate with the human decision about it (``True`` = should be accepted)."""

    item_id: str
    source: str
    output: BaseModel
    human_pass: bool


@dataclass(frozen=True)
class Agreement:
    """How well the judge agrees with the labels."""

    total: int
    accuracy: float
    kappa: float
    false_accepts: int
    false_rejects: int

    @property
    def meets_target(self) -> bool:
        """Kappa at or above the target and no false accept."""
        return self.kappa >= TARGET_KAPPA and self.false_accepts == 0


def cohen_kappa(human: Sequence[bool], judge: Sequence[bool]) -> float:
    """Cohen's kappa for two binary raters (1.0 when both always agree and are constant)."""
    if len(human) != len(judge) or not human:
        raise ValueError("ratings must be non-empty and of equal length")
    total = len(human)
    observed = sum(a == b for a, b in zip(human, judge, strict=True)) / total
    p_human = sum(human) / total
    p_judge = sum(judge) / total
    expected = p_human * p_judge + (1 - p_human) * (1 - p_judge)
    if expected == 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)


async def measure_agreement(
    judge: Judge, rubric: str, items: Sequence[LabelledItem], *, min_score: int = 4
) -> Agreement:
    """Run ``judge`` on every labelled item and compare its decision with the human one."""
    human = [item.human_pass for item in items]
    decisions = []
    for item in items:
        verdict = await judge.evaluate(
            rubric=rubric, source=item.source, output=item.output, issues=()
        )
        decisions.append(verdict.passed and verdict.score >= min_score)
    return Agreement(
        total=len(items),
        accuracy=sum(a == b for a, b in zip(human, decisions, strict=True)) / len(items),
        kappa=cohen_kappa(human, decisions),
        false_accepts=sum(d and not h for h, d in zip(human, decisions, strict=True)),
        false_rejects=sum(h and not d for h, d in zip(human, decisions, strict=True)),
    )
