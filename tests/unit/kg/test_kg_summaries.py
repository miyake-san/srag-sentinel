from datetime import timedelta

import pytest

from srag_sentinel.kg.build import build_kg
from srag_sentinel.kg.lexicon import expand_terms
from srag_sentinel.kg.rank import Candidate, recency, select_top
from srag_sentinel.kg.store import MemoryKgStore
from srag_sentinel.kg.summaries import (
    RegionSummary,
    SummaryInput,
    citations_in_evidence,
    ensure_region_summary,
    no_new_numbers,
    summary_validators,
)
from srag_sentinel.llm.fake import ScriptedModel
from srag_sentinel.llm.router.cascade import Router
from srag_sentinel.llm.router.policy import load_default_policy
from support_kg import NOW, FixedJudge, corpus_router, load_corpus, safe_article


async def store_with_southeast_claims() -> MemoryKgStore:
    corpus = [item for item in load_corpus() if item["id"] in {"k01", "k05", "k06"}]
    router = corpus_router(corpus)
    store = MemoryKgStore()
    await build_kg(
        [safe_article(i) for i in corpus], run_id="r", router=router, store=store, now=NOW
    )
    return store


def summary_router(*replies: object, judge: FixedJudge | None = None) -> Router:
    models = {
        "small": ScriptedModel(list(replies), model_name="fake:small"),  # type: ignore[arg-type]
        "large": ScriptedModel(list(replies), model_name="fake:large"),  # type: ignore[arg-type]
    }
    return Router(
        load_default_policy(),
        models=models,  # type: ignore[arg-type]
        validators=summary_validators() | {"schema": lambda output, payload: ()},
        judge=judge or FixedJudge(),
    )


def payload() -> SummaryInput:
    return SummaryInput(
        region="SE", claims=(("c1", "Casos sobem em SP, 12 casos"), ("c2", "UTI lotada"))
    )


def test_citations_must_exist_in_the_input() -> None:
    good = RegionSummary(text="x", evidence_ids=("C1", "C2"))
    bad = RegionSummary(text="x", evidence_ids=("C1", "C9"))

    assert citations_in_evidence(good, payload()) == []
    assert [i.code for i in citations_in_evidence(bad, payload())] == ["unknown_citation"]


def test_numbers_must_come_from_the_cited_claims() -> None:
    cited = RegionSummary(text="Foram 12 casos.", evidence_ids=("C1",))
    invented = RegionSummary(text="Foram 99 casos.", evidence_ids=("C1",))
    other_claim = RegionSummary(text="Foram 12 casos.", evidence_ids=("C2",))

    assert no_new_numbers(cited, payload()) == []
    assert [i.code for i in no_new_numbers(invented, payload())] == ["new_number"]
    assert no_new_numbers(other_claim, payload())  # 12 is in C1, which is not cited here


async def test_a_verified_summary_is_written_with_provenance_and_cached() -> None:
    store = await store_with_southeast_claims()
    reply = RegionSummary(
        text="Há sinais de aumento de casos e pressão hospitalar.", evidence_ids=("C1", "C2")
    )
    router = summary_router(reply)

    first = await ensure_region_summary("SE", store=store, router=router, run_id="r2", now=NOW)
    second = await ensure_region_summary("SE", store=store, router=router, run_id="r3", now=NOW)

    assert first is not None and first.run_id == "r2"
    assert first.produced_by.startswith("small/fake:small/kg.summarize_region@")
    assert first.judge == {"rubric": "region_summary@1", "score": 5, "passed": True}
    assert second is first  # served from the cache: no second model call was available anyway


async def test_an_expired_summary_is_regenerated() -> None:
    store = await store_with_southeast_claims()
    reply = RegionSummary(text="Há sinais de aumento de casos.", evidence_ids=("C1",))
    router = summary_router(reply, reply)

    await ensure_region_summary("SE", store=store, router=router, run_id="r2", now=NOW)
    later = NOW + timedelta(days=8)
    # claims live 30 days, so they are still there; the 7-day summary is not
    again = await ensure_region_summary("SE", store=store, router=router, run_id="r3", now=later)

    assert again is not None and again.run_id == "r3"


async def test_an_unverifiable_summary_is_not_produced() -> None:
    store = await store_with_southeast_claims()
    lie = RegionSummary(text="Foram 5000 casos.", evidence_ids=("C1",))
    router = summary_router(lie, lie)

    result = await ensure_region_summary("SE", store=store, router=router, run_id="r", now=NOW)

    assert result is None and store.summaries == {}


async def test_a_judge_rejection_blocks_the_summary() -> None:
    store = await store_with_southeast_claims()
    reply = RegionSummary(text="Há sinais de aumento de casos.", evidence_ids=("C1",))
    router = summary_router(reply, reply, judge=FixedJudge(score=2, passed=False))

    result = await ensure_region_summary("SE", store=store, router=router, run_id="r", now=NOW)

    assert result is None


async def test_no_claims_means_no_summary_and_no_model_call() -> None:
    models = {"small": ScriptedModel([], model_name="fake:small")}
    router = Router(
        load_default_policy(),
        models=models,
        validators=summary_validators(),
        judge=FixedJudge(),
    )

    result = await ensure_region_summary(
        "N", store=MemoryKgStore(), router=router, run_id="r", now=NOW
    )

    assert result is None and models["small"].calls == []


def candidate(**overrides: object) -> Candidate:
    base: dict[str, object] = {
        "kind": "claim",
        "record_id": "c1",
        "text": "t",
        "graph_path": "p",
        "article_id": "a1",
        "confidence": 0.8,
        "trust": 1.0,
        "created_at": NOW,
        "relevance": 1.0,
        "hops": 0,
        "produced_by": "x",
        "judge": None,
        "source_domain": None,
        "run_id": None,
        "url": None,
        "published_at": None,
    }
    return Candidate(**{**base, **overrides})  # type: ignore[arg-type]


def test_ranking_prefers_relevant_confident_recent_near_items() -> None:
    near = candidate(record_id="near", article_id="a1")
    far = candidate(record_id="far", article_id="a2", hops=2)
    old = candidate(record_id="old", article_id="a3", created_at=NOW - timedelta(days=60))
    weak = candidate(record_id="weak", article_id="a4", confidence=0.2)

    order = [c.record_id for c, _ in select_top([weak, old, far, near], NOW, 4)]

    assert order[0] == "near" and order[-1] in {"weak", "old"}


def test_only_the_best_item_per_article_is_kept() -> None:
    claim = candidate(record_id="c1", article_id="a1", confidence=0.9)
    article = candidate(kind="article", record_id="a1", article_id="a1", confidence=0.5)

    chosen = select_top([article, claim], NOW, 5)

    assert [c.record_id for c, _ in chosen] == ["c1"]


def test_select_top_respects_the_cut_off() -> None:
    items = [candidate(record_id=f"c{i}", article_id=f"a{i}") for i in range(10)]

    assert len(select_top(items, NOW, 3)) == 3


def test_recency_decays_and_has_a_floor() -> None:
    assert recency(NOW, NOW) == pytest.approx(1.0)
    assert recency(NOW - timedelta(days=14), NOW) == pytest.approx(0.5)
    assert recency(NOW - timedelta(days=365), NOW) == 0.2
    assert recency(None, NOW) == 0.2


def test_lexicon_expands_known_concepts_and_is_bounded() -> None:
    terms = expand_terms(["vacina", "xyz"])

    assert "vacinação" in terms and "xyz" in terms
    assert len(expand_terms(["aumento", "queda", "uti", "obito"], limit=5)) == 5
