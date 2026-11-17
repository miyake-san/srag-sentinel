"""GraphRAG retrieval on a real SurrealDB, over the labelled headline corpus."""

from datetime import timedelta

import pytest
from helpers import kg_reader_connection, kg_writer_connection

from srag_sentinel.kg.build import build_kg
from srag_sentinel.kg.evaluation import recall_at_k
from srag_sentinel.kg.retrieve import GraphRetriever, Question
from srag_sentinel.kg.store import SurrealKgStore
from srag_sentinel.kg.summaries import RegionSummary, ensure_region_summary, summary_validators
from srag_sentinel.llm.fake import ScriptedModel
from srag_sentinel.llm.router.cascade import Router
from srag_sentinel.llm.router.policy import load_default_policy
from srag_sentinel.settings import Settings
from support_kg import NOW, FixedJudge, corpus_router, load_corpus, safe_article

pytestmark = pytest.mark.integration

# (scope, search terms, corpus ids a good answer must surface)
QUESTIONS: list[tuple[str, tuple[str, ...], set[str]]] = [
    ("SP", ("aumento", "casos", "srag"), {"k01"}),
    ("BR", ("vacina",), {"k03", "k07", "k14", "k21", "k29", "k30"}),
    ("RS", ("queda", "casos", "covid"), {"k02"}),
    ("RJ", ("uti", "internacao", "hospital"), {"k06"}),
    ("MG", ("obito",), {"k05"}),
    ("BR", ("surto",), {"k04", "k09", "k17", "k26"}),
    ("PE", ("vsr",), {"k04", "k11"}),
    ("BA", ("srag",), {"k09"}),
    ("SC", ("gripe", "vacina"), {"k14"}),
    ("DF", ("surto",), {"k17"}),
    ("PB", ("gripe",), {"k20"}),
    ("AL", ("vacina",), {"k21"}),
    ("SE", ("hospital", "uti"), {"k23"}),
    ("BR", ("obito", "covid"), {"k05", "k16", "k18"}),
    ("AM", ("casos",), {"k13"}),
]


async def populate(settings: Settings) -> dict[str, str]:
    """Build the graph from the whole corpus; return corpus id -> article id."""
    corpus = load_corpus()
    router = corpus_router(corpus)
    async with kg_writer_connection(settings) as db:
        await build_kg(
            [safe_article(item) for item in corpus],
            run_id="r",
            router=router,
            store=SurrealKgStore(db),
            now=NOW,
        )
    return {item["id"]: safe_article(item).article.id for item in corpus}


async def test_recall_at_12_meets_the_target_on_labelled_questions(settings: Settings) -> None:
    ids = await populate(settings)
    recalls = []
    async with kg_reader_connection(settings) as db:
        retriever = GraphRetriever(db)
        for scope, terms, relevant in QUESTIONS:
            pack = await retriever.retrieve(
                scope=scope, questions=[Question("q", terms)], top_k=12, now=NOW
            )
            returned = [item.article_id for item in pack.items if item.article_id]
            recalls.append(recall_at_k({ids[r] for r in relevant}, returned, 12))

    assert sum(recalls) / len(recalls) >= 0.8, recalls


async def test_every_item_has_provenance_a_path_and_a_source(settings: Settings) -> None:
    await populate(settings)
    async with kg_reader_connection(settings) as db:
        pack = await GraphRetriever(db).retrieve(
            scope="SP", questions=[Question("q", ("aumento", "casos"))], now=NOW
        )

    assert pack.items
    assert [item.evidence_id for item in pack.items] == [
        f"E{i}" for i in range(1, len(pack.items) + 1)
    ]
    for item in pack.items:
        assert item.provenance.produced_by
        assert item.provenance.run_id == "r"
        assert item.graph_path
        assert item.url and item.url.startswith("https://")
        assert item.provenance.source_domain == "saude.gov.br"
    assert any(item.graph_path.startswith("uf:SP") for item in pack.items)


async def test_the_scope_uf_outranks_distant_ufs(settings: Settings) -> None:
    await populate(settings)
    async with kg_reader_connection(settings) as db:
        pack = await GraphRetriever(db).retrieve(
            scope="SP", questions=[Question("q", ("casos",))], top_k=3, now=NOW
        )

    assert pack.items[0].graph_path.startswith("uf:SP")


async def test_neighbours_are_reached_through_the_graph_with_a_path(settings: Settings) -> None:
    await populate(settings)
    async with kg_reader_connection(settings) as db:
        pack = await GraphRetriever(db).retrieve(
            scope="SP", questions=[Question("q", ("gripe",))], top_k=12, max_hops=1, now=NOW
        )

    # k29 mentions SP and RJ; k12 (GO) is a neighbour-of-neighbour and must not appear at 1 hop
    paths = " ".join(item.graph_path for item in pack.items)
    assert "-adjacent_to-> uf:RJ" in paths or "uf:SP <-" in paths
    assert "uf:GO" not in paths


async def test_expired_nodes_are_not_retrieved(settings: Settings) -> None:
    await populate(settings)
    async with kg_reader_connection(settings) as db:
        pack = await GraphRetriever(db).retrieve(
            scope="SP",
            questions=[Question("q", ("casos",))],
            now=NOW + timedelta(days=45),
        )

    assert pack.items == ()


async def test_an_empty_graph_returns_an_empty_pack_not_an_error(settings: Settings) -> None:
    async with kg_reader_connection(settings) as db:
        pack = await GraphRetriever(db).retrieve(
            scope="SP", questions=[Question("q", ("casos",))], now=NOW
        )

    assert pack.items == ()


async def test_hostile_terms_cannot_alter_the_query(settings: Settings) -> None:
    await populate(settings)
    async with kg_reader_connection(settings) as db:
        pack = await GraphRetriever(db).retrieve(
            scope="SP",
            questions=[Question("q", ("x'; REMOVE TABLE claim; --",))],
            now=NOW,
        )
        remaining = await db.query("SELECT count() FROM claim GROUP ALL")

    assert pack.items is not None
    assert remaining and remaining[0]


async def test_a_verified_regional_summary_is_stored_and_retrieved(settings: Settings) -> None:
    await populate(settings)
    reply = RegionSummary(text="Há sinais de aumento de casos.", evidence_ids=("C1",))
    router = Router(
        load_default_policy(),
        models={"small": ScriptedModel([reply], model_name="fake:small")},  # type: ignore[dict-item]
        validators=summary_validators() | {"schema": lambda output, payload: ()},
        judge=FixedJudge(score=5),
    )
    async with kg_writer_connection(settings) as db:
        node = await ensure_region_summary(
            "SE", store=SurrealKgStore(db), router=router, run_id="r9", now=NOW
        )
    assert node is not None

    async with kg_reader_connection(settings) as db:
        pack = await GraphRetriever(db).retrieve(
            scope="SP", questions=[Question("q", ("casos",))], now=NOW
        )

    summaries = [item for item in pack.items if item.kind == "summary"]
    assert len(summaries) == 1
    assert "-in_region-> region:SE <-summarizes-" in summaries[0].graph_path
    assert summaries[0].provenance.judge == {
        "rubric": "region_summary@1",
        "score": 5,
        "passed": True,
    }
    assert summaries[0].url is None
