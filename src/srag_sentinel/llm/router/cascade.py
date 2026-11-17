"""Cascade router (ADR 0018): small -> large, validators first, judge only when warranted.

Every accepted output passed all validators. A hard validator error is never overridden by the
judge, and tiers that are not configured are skipped (everything then runs on ``large``).
"""

import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel

from srag_sentinel.llm.ports import ModelError, StructuredModel
from srag_sentinel.llm.router.events import Detail, EventKind, EventSink, NullSink, RouterEvent
from srag_sentinel.llm.router.judge import Judge
from srag_sentinel.llm.router.policy import OnExhausted, RouterPolicy, TaskPolicy, Tier
from srag_sentinel.llm.router.validators import Issue, Validator


class RouterConfigError(RuntimeError):
    """The router cannot run a task as configured (missing tier, validator or judge)."""


@dataclass(frozen=True)
class TaskSpec[P, O: BaseModel]:
    """Everything the router needs to run one kind of task."""

    task_id: str
    output_schema: type[O]
    system_prompt: str
    build_user: Callable[[P, Sequence[str]], str]
    judge_source: Callable[[P], str] | None = None


@dataclass(frozen=True)
class JudgeInfo:
    """The accepted attempt's judgement, kept as provenance (``None`` when no judge ran)."""

    rubric: str
    score: int
    passed: bool


@dataclass(frozen=True)
class TaskOutcome[O: BaseModel]:
    """Result of running a task through the cascade."""

    accepted: bool
    output: O | None
    tier: str | None
    attempts: int
    feedback: tuple[str, ...] = ()
    on_exhausted: OnExhausted | None = None
    model: str | None = None
    judge: JudgeInfo | None = None


@dataclass
class CallBudget:
    """Caps the number of model calls per tier for one run (guardrail G4)."""

    limits: Mapping[str, int]
    used: dict[str, int] = field(default_factory=dict)

    def try_consume(self, tier: str) -> bool:
        """Reserve one call on ``tier``; return False when the cap is reached."""
        used = self.used.get(tier, 0)
        if used >= self.limits.get(tier, used + 1):
            return False
        self.used[tier] = used + 1
        return True


@dataclass(frozen=True)
class _Step[P, O: BaseModel]:
    """One attempt: the task, its input and where in the cascade we are."""

    task: TaskSpec[P, O]
    payload: P
    policy: TaskPolicy
    checks: list[tuple[str, Validator]]
    tier: Tier
    attempt: int

    def event(self, kind: EventKind, details: dict[str, Detail]) -> RouterEvent:
        """Build an event stamped with this step's task, tier and attempt."""
        return RouterEvent(kind, self.task.task_id, self.tier, self.attempt, details)


@dataclass(frozen=True)
class _Attempt[O: BaseModel]:
    output: O | None
    accepted: bool
    feedback: tuple[str, ...]
    judge: JudgeInfo | None = None


class Router:
    """Runs tasks through the policy's tiers with validation and optional judging."""

    def __init__(  # noqa: PLR0913 - dependency injection of collaborators
        self,
        policy: RouterPolicy,
        *,
        models: Mapping[Tier, StructuredModel],
        validators: Mapping[str, Validator],
        judge: Judge | None = None,
        sink: EventSink | None = None,
        sampler: Callable[[], float] = random.random,
    ) -> None:
        self._policy = policy
        self._models = models
        self._validators = validators
        self._judge = judge
        self._sink: EventSink = sink or NullSink()
        self._sampler = sampler

    async def run[P, O: BaseModel](
        self, task: TaskSpec[P, O], payload: P, *, budget: CallBudget | None = None
    ) -> TaskOutcome[O]:
        """Run ``task`` on the cheapest tier that produces a verified output."""
        policy = self._policy.for_task(task.task_id)
        checks = self._resolve_validators(policy)
        tiers = [tier for tier in policy.tiers if tier in self._models]
        if not tiers:
            raise RouterConfigError(f"{task.task_id}: none of {policy.tiers} is configured")
        if policy.judge != "never" and self._judge is None:
            raise RouterConfigError(f"{task.task_id}: policy needs a judge but none is configured")

        feedback: tuple[str, ...] = ()
        attempts = 0
        for tier in tiers:
            for attempt_in_tier in range(1, policy.max_attempts_per_tier + 1):
                if budget is not None and not budget.try_consume(tier):
                    return self._exhausted(task, policy, attempts, feedback, reason="budget")
                attempts += 1
                step = _Step(task, payload, policy, checks, tier, attempts)
                reason = (
                    "retry" if attempt_in_tier > 1 else "escalation" if feedback else "first_choice"
                )
                self._sink.emit(step.event("router_decision", {"reason": reason}))
                result = await self._attempt(step, feedback)
                if result.accepted:
                    self._sink.emit(step.event("task_accepted", {}))
                    return TaskOutcome(
                        True,
                        result.output,
                        tier,
                        attempts,
                        model=self._models[tier].name,
                        judge=result.judge,
                    )
                feedback = result.feedback
        return self._exhausted(task, policy, attempts, feedback, reason="tiers_exhausted")

    # -- internals ---------------------------------------------------------------------

    def _resolve_validators(self, policy: TaskPolicy) -> list[tuple[str, Validator]]:
        missing = [name for name in policy.validators if name not in self._validators]
        if missing:
            raise RouterConfigError(f"unknown validators: {', '.join(missing)}")
        return [(name, self._validators[name]) for name in policy.validators]

    async def _attempt[P, O: BaseModel](
        self, step: _Step[P, O], feedback: Sequence[str]
    ) -> _Attempt[O]:
        task = step.task
        try:
            output = await self._models[step.tier].invoke_structured(
                task.output_schema,
                system=task.system_prompt,
                user=task.build_user(step.payload, feedback),
            )
        except ModelError as error:
            self._sink.emit(step.event("validation", {"model_error": True}))
            return _Attempt(None, False, (f"model_error: {error}",))

        issues = [issue for _, check in step.checks for issue in check(output, step.payload)]
        errors = [issue for issue in issues if issue.severity == "error"]
        warnings = [issue for issue in issues if issue.severity == "warning"]
        self._sink.emit(
            step.event("validation", {"errors": len(errors), "warnings": len(warnings)})
        )
        if errors:
            return _Attempt(output, False, tuple(f"{i.code}: {i.message}" for i in errors))
        if not self._needs_judge(step.policy, has_warnings=bool(warnings)):
            return _Attempt(output, True, ())
        return await self._judged(step, output, issues)

    def _needs_judge(self, policy: TaskPolicy, *, has_warnings: bool) -> bool:
        if policy.judge == "always":
            return True
        if policy.judge == "on_warning":
            return has_warnings
        probability = policy.sample_probability
        return probability is not None and self._sampler() < probability

    async def _judged[P, O: BaseModel](
        self, step: _Step[P, O], output: O, issues: Sequence[Issue]
    ) -> _Attempt[O]:
        rubric = step.policy.judge_rubric
        assert self._judge is not None and rubric is not None  # noqa: S101 - checked in run()
        task = step.task
        source = (
            task.judge_source(step.payload)
            if task.judge_source
            else task.build_user(step.payload, ())
        )
        verdict = await self._judge.evaluate(
            rubric=rubric, source=source, output=output, issues=issues
        )
        passed = verdict.passed and verdict.score >= step.policy.judge_min_score
        self._sink.emit(
            step.event(
                "judge_verdict", {"rubric": rubric, "score": verdict.score, "passed": passed}
            )
        )
        if passed:
            return _Attempt(output, True, (), JudgeInfo(rubric, verdict.score, True))
        reasons = verdict.reasons or [f"judge score {verdict.score}"]
        return _Attempt(output, False, tuple(f"judge: {reason}" for reason in reasons))

    def _exhausted[P, O: BaseModel](
        self,
        task: TaskSpec[P, O],
        policy: TaskPolicy,
        attempts: int,
        feedback: Sequence[str],
        *,
        reason: str,
    ) -> TaskOutcome[O]:
        self._sink.emit(
            RouterEvent(
                "task_exhausted",
                task.task_id,
                None,
                attempts,
                {"reason": reason, "action": policy.on_exhausted},
            )
        )
        return TaskOutcome(False, None, None, attempts, tuple(feedback), policy.on_exhausted)
