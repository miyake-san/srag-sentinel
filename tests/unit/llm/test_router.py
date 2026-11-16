from collections.abc import Sequence

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

from srag_sentinel.llm.fake import ScriptedModel
from srag_sentinel.llm.ports import ModelError
from srag_sentinel.llm.router.cascade import CallBudget, Router, RouterConfigError, TaskSpec
from srag_sentinel.llm.router.events import ListSink
from srag_sentinel.llm.router.judge import Verdict
from srag_sentinel.llm.router.policy import (
    PolicyError,
    RouterPolicy,
    load_default_policy,
    parse_policy,
)
from srag_sentinel.llm.router.validators import Issue, max_items


class Items(BaseModel):
    values: list[str]


def policy(judge: str = "never", tiers: str = "[small, large]", extra: str = "") -> RouterPolicy:
    rubric = "judge_rubric: r@1" if judge != "never" else ""
    return parse_policy(
        f"""
tasks:
  t.task:
    tiers: {tiers}
    validators: [limit]
    judge: {judge}
    {rubric}
    on_exhausted: drop_item
    {extra}
"""
    )


def task() -> TaskSpec[str, Items]:
    return TaskSpec(
        task_id="t.task",
        output_schema=Items,
        system_prompt="sys",
        build_user=lambda text, feedback: f"{text}|{'/'.join(feedback)}",
    )


class ScriptedJudge:
    def __init__(self, *verdicts: Verdict) -> None:
        self._verdicts = list(verdicts)
        self.calls: list[tuple[str, Sequence[Issue]]] = []

    async def evaluate(
        self, *, rubric: str, source: str, output: BaseModel, issues: Sequence[Issue]
    ) -> Verdict:
        self.calls.append((rubric, issues))
        return self._verdicts.pop(0)


GOOD = Items(values=["a"])
TOO_MANY = Items(values=["a", "b", "c"])
VALIDATORS = {"limit": max_items("values", 2)}


def router(  # noqa: PLR0913 - test helper with many optional collaborators
    *,
    policy_: RouterPolicy | None = None,
    small: ScriptedModel | None = None,
    large: ScriptedModel | None = None,
    judge: ScriptedJudge | None = None,
    sink: ListSink | None = None,
    sampler: float = 0.5,
) -> Router:
    models = {}
    if small is not None:
        models["small"] = small
    if large is not None:
        models["large"] = large
    return Router(
        policy_ or policy(),
        models=models,  # type: ignore[arg-type]
        validators=VALIDATORS,
        judge=judge,
        sink=sink,
        sampler=lambda: sampler,
    )


async def test_small_tier_result_is_accepted_when_validators_pass() -> None:
    small, large = ScriptedModel([GOOD]), ScriptedModel([GOOD])
    sink = ListSink()

    outcome = await router(small=small, large=large, sink=sink).run(task(), "x")

    assert (outcome.accepted, outcome.tier, outcome.attempts) == (True, "small", 1)
    assert large.calls == []  # never paid for the large model
    assert sink.kinds() == ["router_decision", "validation", "task_accepted"]


async def test_validator_error_escalates_to_large_with_feedback() -> None:
    small, large = ScriptedModel([TOO_MANY]), ScriptedModel([GOOD])
    sink = ListSink()

    outcome = await router(small=small, large=large, sink=sink).run(task(), "x")

    assert (outcome.accepted, outcome.tier, outcome.attempts) == (True, "large", 2)
    assert "too_many_items" in large.calls[0].user  # the large tier saw the reason
    reasons = [e.details["reason"] for e in sink.events if e.kind == "router_decision"]
    assert reasons == ["first_choice", "escalation"]


async def test_model_error_counts_as_a_failed_attempt_and_escalates() -> None:
    small, large = ScriptedModel([ModelError("bad json")]), ScriptedModel([GOOD])

    outcome = await router(small=small, large=large).run(task(), "x")

    assert (outcome.tier, outcome.attempts) == ("large", 2)
    assert "model_error" in large.calls[0].user


async def test_exhausted_cascade_applies_the_policy_action_and_returns_no_output() -> None:
    small, large = ScriptedModel([TOO_MANY]), ScriptedModel([TOO_MANY])
    sink = ListSink()

    outcome = await router(small=small, large=large, sink=sink).run(task(), "x")

    assert (outcome.accepted, outcome.output, outcome.on_exhausted) == (False, None, "drop_item")
    assert sink.kinds()[-1] == "task_exhausted"


async def test_without_a_small_tier_everything_runs_on_large() -> None:
    large = ScriptedModel([GOOD])

    outcome = await router(large=large).run(task(), "x")

    assert (outcome.accepted, outcome.tier) == (True, "large")


async def test_no_configured_tier_is_a_configuration_error() -> None:
    with pytest.raises(RouterConfigError, match="configured"):
        await router(policy_=policy(tiers="[small]"), large=ScriptedModel([GOOD])).run(task(), "x")


async def test_unknown_task_and_unknown_validator_fail_fast() -> None:
    unknown = TaskSpec("nope", Items, "s", lambda p, f: p)
    with pytest.raises(PolicyError, match="no routing policy"):
        await router(large=ScriptedModel([GOOD])).run(unknown, "x")

    bad = parse_policy(
        "tasks:\n  t.task:\n    tiers: [large]\n    validators: [ghost]\n"
        "    on_exhausted: drop_item\n"
    )
    with pytest.raises(RouterConfigError, match="ghost"):
        await router(policy_=bad, large=ScriptedModel([GOOD])).run(task(), "x")


async def test_a_judged_policy_without_a_judge_is_a_configuration_error() -> None:
    with pytest.raises(RouterConfigError, match="judge"):
        await router(policy_=policy(judge="always"), large=ScriptedModel([GOOD])).run(task(), "x")


async def test_always_judge_accepts_a_passing_verdict() -> None:
    judge = ScriptedJudge(Verdict(score=5, passed=True))
    sink = ListSink()

    outcome = await router(
        policy_=policy("always"), small=ScriptedModel([GOOD]), judge=judge, sink=sink
    ).run(task(), "x")

    assert (outcome.accepted, outcome.tier) == (True, "small")
    assert "judge_verdict" in sink.kinds()
    assert judge.calls[0][0] == "r@1"


async def test_failing_verdict_escalates_with_the_judges_reasons() -> None:
    judge = ScriptedJudge(
        Verdict(score=2, passed=False, reasons=["entity is wrong"]), Verdict(score=5, passed=True)
    )
    small, large = ScriptedModel([GOOD]), ScriptedModel([GOOD])

    outcome = await router(policy_=policy("always"), small=small, large=large, judge=judge).run(
        task(), "x"
    )

    assert (outcome.tier, outcome.attempts) == ("large", 2)
    assert "entity is wrong" in large.calls[0].user


async def test_low_score_fails_even_if_the_judge_says_passed() -> None:
    judge = ScriptedJudge(Verdict(score=3, passed=True), Verdict(score=5, passed=True))

    outcome = await router(
        policy_=policy("always"),
        small=ScriptedModel([GOOD]),
        large=ScriptedModel([GOOD]),
        judge=judge,
    ).run(task(), "x")

    assert outcome.tier == "large"  # min score is 4


async def test_the_judge_cannot_rescue_a_hard_validator_error() -> None:
    judge = ScriptedJudge(Verdict(score=5, passed=True))
    small, large = ScriptedModel([TOO_MANY]), ScriptedModel([TOO_MANY])

    outcome = await router(policy_=policy("always"), small=small, large=large, judge=judge).run(
        task(), "x"
    )

    assert not outcome.accepted
    assert judge.calls == []  # never even consulted


async def test_on_warning_judges_only_ambiguous_outputs() -> None:
    def warn(output: BaseModel, payload: object) -> Sequence[Issue]:
        return (Issue("vague", "unclear entity", "warning"),) if payload == "ambiguous" else ()

    judge = ScriptedJudge(Verdict(score=5, passed=True))
    custom = Router(
        policy("on_warning"),
        models={"small": ScriptedModel([GOOD, GOOD])},  # type: ignore[dict-item]
        validators={**VALIDATORS, "limit": warn},
        judge=judge,
    )

    await custom.run(task(), "clear")
    assert judge.calls == []
    await custom.run(task(), "ambiguous")
    assert len(judge.calls) == 1


@pytest.mark.parametrize(("draw", "expect_calls"), [(0.05, 1), (0.5, 0)])
async def test_sample_judging_follows_the_probability(draw: float, expect_calls: int) -> None:
    judge = ScriptedJudge(Verdict(score=5, passed=True))

    await router(
        policy_=policy("sample:0.1"), small=ScriptedModel([GOOD]), judge=judge, sampler=draw
    ).run(task(), "x")

    assert len(judge.calls) == expect_calls


async def test_retry_within_a_tier_uses_the_attempt_limit() -> None:
    small = ScriptedModel([ModelError("schema"), GOOD])
    config = policy(tiers="[small]", extra="max_attempts_per_tier: 2")

    outcome = await router(policy_=config, small=small).run(task(), "x")

    assert (outcome.accepted, outcome.attempts) == (True, 2)


async def test_budget_caps_calls_per_tier() -> None:
    small, large = ScriptedModel([TOO_MANY]), ScriptedModel([GOOD])
    sink = ListSink()

    outcome = await router(small=small, large=large, sink=sink).run(
        task(), "x", budget=CallBudget({"small": 1, "large": 0})
    )

    assert not outcome.accepted
    assert large.calls == []
    assert sink.events[-1].details["reason"] == "budget"


def test_synthesis_is_pinned_to_the_large_tier() -> None:
    with pytest.raises(PolicyError, match="large tier only"):
        parse_policy(
            "tasks:\n  report.synthesize:\n    tiers: [small, large]\n"
            "    on_exhausted: fail_closed\n"
        )


@pytest.mark.parametrize(
    "bad",
    [
        "tasks:\n  t:\n    tiers: [large]\n    judge: sometimes\n    on_exhausted: drop_item\n",
        # judged task without a rubric
        "tasks:\n  t:\n    tiers: [large]\n    judge: always\n    on_exhausted: drop_item\n",
        "tasks:\n  t:\n    tiers: [large, large]\n    on_exhausted: drop_item\n",
        "tasks:\n  t:\n    tiers: []\n    on_exhausted: drop_item\n",
        "tasks:\n  t:\n    tiers: [medium]\n    on_exhausted: drop_item\n",
        "tasks:\n  t:\n    tiers: [large]\n    on_exhausted: shrug\n",
        "tasks:\n  t:\n    tiers: [large]\n    on_exhausted: drop_item\n    surprise: 1\n",
        "not: [valid",
    ],
)
def test_invalid_policies_are_rejected(bad: str) -> None:
    with pytest.raises(PolicyError):
        parse_policy(bad)


def test_the_shipped_policy_loads_and_keeps_synthesis_on_large() -> None:
    shipped = load_default_policy()

    assert shipped.for_task("report.synthesize").tiers == ["large"]
    assert shipped.for_task("kg.extract_claims").tiers == ["small", "large"]


@given(st.lists(st.sampled_from(["a", "b", "c", "d"]), min_size=0, max_size=4))
async def test_an_accepted_output_always_passed_every_validator(values: list[str]) -> None:
    candidate = Items(values=values)

    outcome = await router(small=ScriptedModel([candidate]), large=ScriptedModel([candidate])).run(
        task(), "x"
    )

    if outcome.accepted:
        assert outcome.output is not None
        assert len(outcome.output.values) <= 2
    else:
        assert outcome.output is None
