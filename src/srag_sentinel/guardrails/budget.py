"""G4: per-run budget (model calls per tier, news queries, articles, wall-clock deadline)."""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from srag_sentinel.guardrails.verdict import GuardrailVerdict
from srag_sentinel.llm.router.cascade import CallBudget


class BudgetLimits(BaseModel):
    """Configured caps for one report run."""

    model_config = ConfigDict(frozen=True)

    max_large_calls: int = Field(default=3, ge=1)
    max_small_calls: int = Field(default=40, ge=0)
    max_news_queries: int = Field(default=3, ge=1)
    max_articles: int = Field(default=8, ge=1)
    timeout_seconds: float = Field(default=90.0, gt=0)


@dataclass
class RunBudget:
    """Mutable counters for one run. Exceeding a cap yields a blocking G4 verdict."""

    limits: BudgetLimits = field(default_factory=BudgetLimits)
    clock: Callable[[], float] = time.monotonic
    news_queries: int = 0
    verdicts: list[GuardrailVerdict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._started = self.clock()
        self.model_calls = CallBudget(
            {"large": self.limits.max_large_calls, "small": self.limits.max_small_calls}
        )

    def try_news_query(self) -> bool:
        """Reserve one news query; record a verdict and return False when the cap is hit."""
        if self.news_queries >= self.limits.max_news_queries:
            self._block("G4.news_queries", used=self.news_queries)
            return False
        self.news_queries += 1
        return True

    def cap_articles[T](self, articles: Sequence[T]) -> list[T]:
        """Keep at most ``max_articles`` items, recording a verdict when something is dropped."""
        if len(articles) > self.limits.max_articles:
            self.verdicts.append(
                GuardrailVerdict(
                    "G4",
                    "G4.articles",
                    "sanitize",
                    {
                        "kept": self.limits.max_articles,
                        "dropped": len(articles) - self.limits.max_articles,
                    },
                )
            )
        return list(articles[: self.limits.max_articles])

    def time_left(self) -> float:
        """Seconds remaining before the run deadline (never negative)."""
        return max(0.0, self.limits.timeout_seconds - (self.clock() - self._started))

    def deadline_exceeded(self) -> bool:
        """Whether the deadline passed; records a blocking verdict the first time."""
        if self.time_left() > 0:
            return False
        if not any(v.rule_id == "G4.deadline" for v in self.verdicts):
            self._block("G4.deadline", timeout_seconds=self.limits.timeout_seconds)
        return True

    def _block(self, rule_id: str, **details: str | int | float) -> None:
        self.verdicts.append(GuardrailVerdict("G4", rule_id, "block", dict(details)))
