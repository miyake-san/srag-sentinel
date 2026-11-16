"""Routing policy: a validated, declarative task -> tiers table."""

import re
from importlib.resources import files
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Tier = Literal["small", "large"]
OnExhausted = Literal["drop_item", "low_confidence", "template_fallback", "fail_closed"]

PINNED_LARGE_TASK = "report.synthesize"
_SAMPLE = re.compile(r"^sample:(0(\.\d+)?|1(\.0+)?)$")
_JUDGE_MODES = ("always", "never", "on_warning")


class PolicyError(ValueError):
    """The routing policy file is invalid."""


class TaskPolicy(BaseModel):
    """How one task is routed, verified and judged."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tiers: list[Tier] = Field(min_length=1)
    validators: list[str] = Field(default_factory=list)
    judge: str = "never"
    judge_rubric: str | None = None
    judge_min_score: int = Field(default=4, ge=1, le=5)
    max_attempts_per_tier: int = Field(default=1, ge=1, le=3)
    on_exhausted: OnExhausted

    @field_validator("judge")
    @classmethod
    def _known_judge_mode(cls, value: str) -> str:
        if value not in _JUDGE_MODES and not _SAMPLE.fullmatch(value):
            raise ValueError(f"judge must be one of {_JUDGE_MODES} or 'sample:<0..1>'")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if len(set(self.tiers)) != len(self.tiers):
            raise ValueError("tiers must not repeat")
        if self.judge != "never" and not self.judge_rubric:
            raise ValueError("a judged task needs a judge_rubric")
        return self

    @property
    def sample_probability(self) -> float | None:
        """Probability for ``sample:<p>`` judging, else None."""
        return float(self.judge.split(":", 1)[1]) if self.judge.startswith("sample:") else None


class RouterPolicy(BaseModel):
    """All task policies."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tasks: dict[str, TaskPolicy]

    @model_validator(mode="after")
    def _synthesis_stays_on_large(self) -> Self:
        pinned = self.tasks.get(PINNED_LARGE_TASK)
        if pinned is not None and pinned.tiers != ["large"]:
            raise ValueError(f"{PINNED_LARGE_TASK} must run on the large tier only")
        return self

    def for_task(self, task_id: str) -> TaskPolicy:
        """Return the policy of ``task_id`` or fail fast for an unknown task."""
        try:
            return self.tasks[task_id]
        except KeyError:
            raise PolicyError(f"no routing policy for task {task_id!r}") from None


def parse_policy(text: str) -> RouterPolicy:
    """Parse and validate a YAML policy document."""
    try:
        return RouterPolicy.model_validate(yaml.safe_load(text))
    except (yaml.YAMLError, ValueError) as error:
        raise PolicyError(f"invalid routing policy: {error}") from error


def load_default_policy() -> RouterPolicy:
    """Load the policy shipped with the package."""
    text = files("srag_sentinel.llm.router").joinpath("policy.yaml").read_text(encoding="utf-8")
    return parse_policy(text)
